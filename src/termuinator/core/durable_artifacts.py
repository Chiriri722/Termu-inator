"""Private content-addressed artifact storage for remote chunk retrieval."""

from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any, Callable, Iterator, Mapping

from ..contracts import Artifact, ArtifactChunk, ErrorCode
from ..errors import TermuinatorError


_FORMAT = "termuinator-artifact-metadata-v1"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_URI = re.compile(r"^artifact://sha256/([0-9a-f]{64})$")
_MAX_METADATA_BYTES = 64 * 1024


@dataclass(frozen=True)
class _DiskArtifact:
    metadata: Artifact
    last_accessed_at: datetime


class DurableArtifactStore:
    """Store verified bytes in an owner/project namespace, never by URI alone."""

    def __init__(
        self,
        *,
        root: Path,
        owner_project_digest: str,
        authorize_session: Callable[[str], bool],
        retention_seconds: int,
        quota_bytes: int,
        max_chunk_bytes: int,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise ValueError("artifact root must be an absolute Path")
        if not _DIGEST.fullmatch(owner_project_digest):
            raise ValueError("owner_project_digest must be a lowercase SHA-256")
        if not callable(authorize_session):
            raise ValueError("authorize_session must be callable")
        if not 1 <= retention_seconds <= 31 * 86_400:
            raise ValueError("retention_seconds is out of bounds")
        if quota_bytes < 1:
            raise ValueError("quota_bytes must be positive")
        if not 1 <= max_chunk_bytes <= 512 * 1024:
            raise ValueError("max_chunk_bytes must be between 1 and 512 KiB")
        self.owner_project_digest = owner_project_digest
        self._root = root
        self._authorize_session = authorize_session
        self._retention_seconds = retention_seconds
        self._quota_bytes = quota_bytes
        self._max_chunk_bytes = max_chunk_bytes
        self._now = now or (lambda: datetime.now(timezone.utc))

    def put(self, *, session_id: str, data: bytes, mime_type: str) -> Artifact:
        self._authorize(session_id)
        if not isinstance(data, bytes):
            raise TypeError("artifact data must be bytes")
        if not isinstance(mime_type, str) or not 1 <= len(mime_type) <= 255:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "artifact mime_type must contain 1 to 255 characters",
            )
        if len(data) > self._quota_bytes:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "artifact exceeds the project quota",
            )

        digest = hashlib.sha256(data).hexdigest()
        with self._locked_directory() as directory:
            now = self._current_time()
            self._remove_expired(directory, now)
            data_path, metadata_path = self._paths(directory, digest)
            existing = self._read_metadata(metadata_path, missing_ok=True)
            if existing is not None:
                self._read_verified_data(data_path, existing.metadata)
            elif data_path.exists() or data_path.is_symlink():
                self._verify_orphan(data_path, digest, len(data))

            metadata = Artifact(
                uri=f"artifact://sha256/{digest}",
                sha256=digest,
                size_bytes=len(data),
                mime_type=mime_type,
                created_at=now.isoformat(),
                expires_at=(
                    now + timedelta(seconds=self._retention_seconds)
                ).isoformat(),
            )
            self._atomic_write(data_path, data)
            self._write_metadata(
                metadata_path,
                _DiskArtifact(metadata=metadata, last_accessed_at=now),
            )
            self._evict_to_quota(directory, exclude_digest=digest)
            return metadata

    def read(
        self,
        *,
        session_id: str,
        uri: str,
        offset: int,
        limit: int,
    ) -> ArtifactChunk:
        self._authorize(session_id)
        digest = self._parse_uri(uri)
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or offset < 0
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= self._max_chunk_bytes
        ):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "artifact offset or limit is out of bounds",
            )

        with self._locked_directory() as directory:
            now = self._current_time()
            self._remove_expired(directory, now)
            data_path, metadata_path = self._paths(directory, digest)
            entry = self._read_metadata(metadata_path, missing_ok=True)
            if entry is None:
                raise TermuinatorError(
                    ErrorCode.ARTIFACT_NOT_FOUND,
                    "Artifact was not found or has expired",
                )
            data = self._read_verified_data(data_path, entry.metadata)
            if offset > len(data):
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "artifact offset exceeds its size",
                )
            raw = data[offset : offset + limit]
            next_offset = offset + len(raw)
            self._write_metadata(
                metadata_path,
                _DiskArtifact(metadata=entry.metadata, last_accessed_at=now),
            )
            return ArtifactChunk(
                uri=uri,
                offset=offset,
                next_offset=next_offset,
                eof=next_offset >= len(data),
                data_base64=base64.b64encode(raw).decode("ascii"),
            )

    def _authorize(self, session_id: str) -> None:
        if not isinstance(session_id, str) or not self._authorize_session(session_id):
            raise TermuinatorError(
                ErrorCode.OWNERSHIP_DENIED,
                "The active session does not own this artifact namespace",
            )

    @contextmanager
    def _locked_directory(self) -> Iterator[Path]:
        directory = self._ensure_directory()
        lock_path = directory / ".artifact.lock"
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise self._corrupt("Artifact lock path is unsafe") from exc
        try:
            self._require_private_regular(fd, "Artifact lock")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                raise TermuinatorError(
                    ErrorCode.SESSION_BUSY,
                    "Another process is updating project artifacts",
                ) from exc
            try:
                yield directory
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _ensure_directory(self) -> Path:
        if self._root.is_symlink() or not self._root.is_dir():
            raise self._corrupt("Artifact root must be a real directory")
        parent = self._root / "artifacts"
        directory = parent / self.owner_project_digest
        for item in (parent, directory):
            try:
                if item.is_symlink():
                    raise self._corrupt(
                        "Artifact directories cannot be symbolic links"
                    )
                item.mkdir(mode=0o700, exist_ok=True)
                info = item.lstat()
            except TermuinatorError:
                raise
            except OSError as exc:
                raise self._corrupt("Artifact directory path is unsafe") from exc
            if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
                raise self._corrupt("Artifact directories must use mode 0700")
        return directory

    @staticmethod
    def _paths(directory: Path, digest: str) -> tuple[Path, Path]:
        if not _DIGEST.fullmatch(digest):
            raise ValueError("internal artifact digest is invalid")
        return directory / f"{digest}.bin", directory / f"{digest}.json"

    def _read_metadata(
        self,
        path: Path,
        *,
        missing_ok: bool,
    ) -> _DiskArtifact | None:
        raw = self._read_private_file(
            path,
            maximum=_MAX_METADATA_BYTES,
            missing_ok=missing_ok,
            label="Artifact metadata",
        )
        if raw is None:
            return None
        try:
            payload = json.loads(
                raw.decode("utf-8"),
                parse_constant=self._reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise self._corrupt("Artifact metadata is invalid JSON") from exc
        if not isinstance(payload, Mapping) or set(payload) != {
            "format",
            "owner_project_digest",
            "artifact",
            "last_accessed_at",
        }:
            raise self._corrupt("Artifact metadata fields are invalid")
        if (
            payload["format"] != _FORMAT
            or payload["owner_project_digest"] != self.owner_project_digest
        ):
            raise self._corrupt("Artifact metadata namespace is invalid")
        artifact_value = payload["artifact"]
        if not isinstance(artifact_value, Mapping) or set(artifact_value) != {
            "uri",
            "sha256",
            "size_bytes",
            "mime_type",
            "created_at",
            "expires_at",
        }:
            raise self._corrupt("Stored artifact fields are invalid")
        try:
            artifact = Artifact(**artifact_value)
            last_accessed = self._parse_time(
                payload["last_accessed_at"],
                "last_accessed_at",
            )
        except (TypeError, ValueError) as exc:
            raise self._corrupt("Stored artifact violates its contract") from exc
        if artifact.size_bytes > self._quota_bytes:
            raise self._corrupt("Stored artifact exceeds the project quota")
        if path.name != f"{artifact.sha256}.json":
            raise self._corrupt("Artifact metadata filename does not match its digest")
        return _DiskArtifact(artifact, last_accessed)

    def _write_metadata(self, path: Path, entry: _DiskArtifact) -> None:
        payload = {
            "format": _FORMAT,
            "owner_project_digest": self.owner_project_digest,
            "artifact": {
                "uri": entry.metadata.uri,
                "sha256": entry.metadata.sha256,
                "size_bytes": entry.metadata.size_bytes,
                "mime_type": entry.metadata.mime_type,
                "created_at": entry.metadata.created_at,
                "expires_at": entry.metadata.expires_at,
            },
            "last_accessed_at": entry.last_accessed_at.isoformat(),
        }
        encoded = (
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        self._atomic_write(path, encoded)

    def _read_verified_data(self, path: Path, artifact: Artifact) -> bytes:
        data = self._read_private_file(
            path,
            maximum=self._quota_bytes,
            missing_ok=False,
            label="Artifact data",
        )
        if data is None:
            raise self._corrupt("Artifact data disappeared")
        if len(data) != artifact.size_bytes:
            raise self._corrupt("Artifact data size does not match metadata")
        if not secrets.compare_digest(hashlib.sha256(data).hexdigest(), artifact.sha256):
            raise self._corrupt("Artifact data digest does not match metadata")
        return data

    def _verify_orphan(self, path: Path, digest: str, size: int) -> None:
        data = self._read_private_file(
            path,
            maximum=self._quota_bytes,
            missing_ok=False,
            label="Orphan artifact data",
        )
        if data is None or len(data) != size:
            raise self._corrupt("Orphan artifact data is inconsistent")
        if not secrets.compare_digest(hashlib.sha256(data).hexdigest(), digest):
            raise self._corrupt("Orphan artifact digest is inconsistent")

    def _read_private_file(
        self,
        path: Path,
        *,
        maximum: int,
        missing_ok: bool,
        label: str,
    ) -> bytes | None:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise self._corrupt(f"{label} was not found")
        except OSError as exc:
            raise self._corrupt(f"{label} path is unsafe") from exc
        try:
            self._require_private_regular(fd, label)
            size = os.fstat(fd).st_size
            if not 0 <= size <= maximum:
                raise self._corrupt(f"{label} size is invalid")
            chunks: list[bytes] = []
            remaining = size
            while remaining:
                chunk = os.read(fd, min(65_536, remaining))
                if not chunk:
                    raise self._corrupt(f"{label} was truncated")
                chunks.append(chunk)
                remaining -= len(chunk)
            return b"".join(chunks)
        finally:
            os.close(fd)

    def _atomic_write(self, path: Path, data: bytes) -> None:
        try:
            existing = path.lstat()
        except FileNotFoundError:
            existing = None
        if existing is not None and (
            not stat.S_ISREG(existing.st_mode)
            or stat.S_IMODE(existing.st_mode) != 0o600
        ):
            raise self._corrupt("Artifact publication path is unsafe")
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(12)}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd: int | None = None
        try:
            fd = os.open(temporary, flags, 0o600)
            self._require_private_regular(fd, "Temporary artifact")
            written = 0
            while written < len(data):
                count = os.write(fd, data[written:])
                if count <= 0:
                    raise OSError("short artifact write")
                written += count
            os.fsync(fd)
            os.close(fd)
            fd = None
            os.replace(temporary, path)
            directory_fd = os.open(
                path.parent,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0),
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except TermuinatorError:
            raise
        except OSError as exc:
            raise self._corrupt("Artifact publication failed") from exc
        finally:
            if fd is not None:
                os.close(fd)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _entries(self, directory: Path) -> list[_DiskArtifact]:
        entries: list[_DiskArtifact] = []
        try:
            paths = tuple(directory.iterdir())
        except OSError as exc:
            raise self._corrupt("Artifact directory cannot be enumerated") from exc
        for path in paths:
            match = re.fullmatch(r"([0-9a-f]{64})\.json", path.name)
            if match is None:
                continue
            entry = self._read_metadata(path, missing_ok=False)
            if entry is None:
                raise self._corrupt("Artifact metadata disappeared")
            entries.append(entry)
        return entries

    def _remove_expired(self, directory: Path, now: datetime) -> None:
        for entry in self._entries(directory):
            expires = self._parse_time(entry.metadata.expires_at, "expires_at")
            if expires <= now:
                self._delete_entry(directory, entry.metadata.sha256)

    def _evict_to_quota(self, directory: Path, *, exclude_digest: str) -> None:
        while True:
            entries = self._entries(directory)
            total = sum(entry.metadata.size_bytes for entry in entries)
            if total <= self._quota_bytes:
                return
            candidates = [
                entry
                for entry in entries
                if entry.metadata.sha256 != exclude_digest
            ]
            if not candidates:
                raise self._corrupt("Artifact quota cannot be satisfied")
            victim = min(
                candidates,
                key=lambda item: (
                    item.last_accessed_at,
                    item.metadata.created_at,
                    item.metadata.sha256,
                ),
            )
            self._delete_entry(directory, victim.metadata.sha256)

    def _delete_entry(self, directory: Path, digest: str) -> None:
        data_path, metadata_path = self._paths(directory, digest)
        for path in (data_path, metadata_path):
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                raise self._corrupt("Artifact cleanup path is unsafe")
            try:
                path.unlink()
            except OSError as exc:
                raise self._corrupt("Artifact cleanup failed") from exc

    @staticmethod
    def _parse_uri(uri: str) -> str:
        match = _URI.fullmatch(uri) if isinstance(uri, str) else None
        if match is None:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "artifact URI must be content-addressed",
            )
        return match.group(1)

    def _current_time(self) -> datetime:
        value = self._now()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("artifact clock must return a timezone-aware datetime")
        return value

    @staticmethod
    def _parse_time(value: Any, label: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise ValueError(f"{label} is not an ISO date-time") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{label} must include a timezone")
        return parsed

    @staticmethod
    def _require_private_regular(fd: int, label: str) -> None:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise TermuinatorError(
                ErrorCode.INTERNAL_ERROR,
                f"{label} must be a private mode 0600 regular file",
            )

    @staticmethod
    def _reject_json_constant(value: str) -> None:
        raise ValueError(f"invalid JSON numeric constant: {value}")

    @staticmethod
    def _corrupt(message: str) -> TermuinatorError:
        return TermuinatorError(ErrorCode.INTERNAL_ERROR, message)


__all__ = ["DurableArtifactStore"]
