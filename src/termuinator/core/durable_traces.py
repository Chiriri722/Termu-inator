"""Durable project-scoped storage for closed redacted action traces."""

from __future__ import annotations

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
from typing import Callable, Iterator

from ..contracts import ErrorCode, PageRevision, RiskClass, TraceRecord, to_wire
from ..errors import TermuinatorError


_FORMAT = "termuinator-trace-record-v1"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TRACE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{7,127}$")
_MAX_RECORD_BYTES = 64 * 1024
_RECORD_FIELDS = frozenset(
    {
        "trace_id",
        "step_id",
        "action_kind",
        "risk",
        "page_revision",
        "permission",
        "verification_passed",
        "started_at",
        "duration_ms",
        "diagnostics_id",
    }
)


@dataclass(frozen=True)
class _DiskTrace:
    record: TraceRecord
    stored_at: datetime


class DurableTraceRecorder:
    """Persist append-only trace records under one owner/project digest."""

    def __init__(
        self,
        *,
        root: Path,
        owner_project_digest: str,
        authorize_session: Callable[[str], bool],
        retention_seconds: int,
        quota_bytes: int,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise ValueError("trace root must be an absolute Path")
        if not _DIGEST.fullmatch(owner_project_digest):
            raise ValueError("owner_project_digest must be a lowercase SHA-256")
        if not callable(authorize_session):
            raise ValueError("authorize_session must be callable")
        if not 1 <= retention_seconds <= 31 * 86_400:
            raise ValueError("trace retention_seconds is out of bounds")
        if (
            isinstance(quota_bytes, bool)
            or not isinstance(quota_bytes, int)
            or quota_bytes < 1
        ):
            raise ValueError("trace quota_bytes must be positive")
        self.owner_project_digest = owner_project_digest
        self._root = root
        self._authorize_session = authorize_session
        self._retention_seconds = retention_seconds
        self._quota_bytes = quota_bytes
        self._now = now or (lambda: datetime.now(timezone.utc))

    def append(self, *, session_id: str, record: TraceRecord) -> None:
        self._authorize(session_id)
        if not isinstance(record, TraceRecord):
            raise TypeError("trace recorder accepts only TraceRecord values")
        stored_at = self._current_time()
        payload = self._encode(_DiskTrace(record=record, stored_at=stored_at))
        if len(payload) > self._quota_bytes:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Trace record exceeds the project trace quota",
            )

        with self._locked_directory() as directory:
            self._remove_expired(directory, stored_at)
            path = self._path(directory, record.trace_id)
            existing = self._read_record(path, missing_ok=True)
            if existing is not None:
                if existing.record == record:
                    return
                raise self._corrupt("Trace identifier conflicts with another record")
            self._atomic_write(path, payload)
            self._evict_to_quota(directory, exclude_trace_id=record.trace_id)

    def list_page(
        self,
        *,
        session_id: str,
        limit: int,
    ) -> tuple[tuple[TraceRecord, ...], bool]:
        self._authorize(session_id)
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1_000
        ):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "trace list limit must be between 1 and 1000",
            )
        with self._locked_directory() as directory:
            self._remove_expired(directory, self._current_time())
            entries = self._all_entries(directory)
            selected = entries[-limit:]
            return tuple(item.record for _path, item in selected), len(entries) > limit

    def get(self, *, session_id: str, trace_id: str) -> TraceRecord:
        self._authorize(session_id)
        if not isinstance(trace_id, str) or not _TRACE_ID.fullmatch(trace_id):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "trace_id is invalid",
            )
        with self._locked_directory() as directory:
            self._remove_expired(directory, self._current_time())
            entry = self._read_record(
                self._path(directory, trace_id),
                missing_ok=True,
            )
            if entry is None:
                raise TermuinatorError(
                    ErrorCode.TARGET_NOT_FOUND,
                    "Trace record was not found or has expired",
                    details={"trace_id": trace_id},
                )
            return entry.record

    def _authorize(self, session_id: str) -> None:
        if not isinstance(session_id, str) or not self._authorize_session(session_id):
            raise TermuinatorError(
                ErrorCode.OWNERSHIP_DENIED,
                "The active session does not own this trace namespace",
            )

    @contextmanager
    def _locked_directory(self) -> Iterator[Path]:
        directory = self._ensure_directory()
        lock_path = directory / ".trace.lock"
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise self._corrupt("Trace lock path is unsafe") from exc
        try:
            self._require_private_regular(descriptor, "Trace lock")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                raise TermuinatorError(
                    ErrorCode.SESSION_BUSY,
                    "Another process is updating project traces",
                ) from exc
            try:
                yield directory
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def _ensure_directory(self) -> Path:
        if self._root.is_symlink() or not self._root.is_dir():
            raise self._corrupt("Trace root must be a real directory")
        parent = self._root / "traces"
        directory = parent / self.owner_project_digest
        for item in (parent, directory):
            try:
                if item.is_symlink():
                    raise self._corrupt("Trace directories cannot be symbolic links")
                item.mkdir(mode=0o700, exist_ok=True)
                metadata = item.lstat()
            except TermuinatorError:
                raise
            except OSError as exc:
                raise self._corrupt("Trace directory path is unsafe") from exc
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise self._corrupt("Trace directories must use mode 0700")
        return directory

    @staticmethod
    def _path(directory: Path, trace_id: str) -> Path:
        if not _TRACE_ID.fullmatch(trace_id):
            raise ValueError("internal trace identifier is invalid")
        return directory / f"{trace_id}.json"

    def _all_entries(self, directory: Path) -> list[tuple[Path, _DiskTrace]]:
        entries: list[tuple[Path, _DiskTrace]] = []
        try:
            children = tuple(directory.iterdir())
        except OSError as exc:
            raise self._corrupt("Trace directory cannot be listed") from exc
        for path in children:
            if path.name == ".trace.lock":
                continue
            if path.name.startswith(".") and path.name.endswith(".tmp"):
                self._remove_private_file(path, "Trace temporary file")
                continue
            if path.suffix != ".json" or not _TRACE_ID.fullmatch(path.stem):
                raise self._corrupt("Trace directory contains an unexpected entry")
            entry = self._read_record(path, missing_ok=False)
            if entry is None:
                raise self._corrupt("Trace record disappeared during listing")
            if entry.record.trace_id != path.stem:
                raise self._corrupt("Trace filename and record identifier differ")
            entries.append((path, entry))
        entries.sort(key=lambda item: (item[1].stored_at, item[1].record.trace_id))
        return entries

    def _remove_expired(self, directory: Path, now: datetime) -> None:
        changed = False
        for path, entry in self._all_entries(directory):
            if now >= entry.stored_at + timedelta(seconds=self._retention_seconds):
                self._remove_private_file(path, "Expired trace record")
                changed = True
        if changed:
            self._fsync_directory(directory)

    def _evict_to_quota(self, directory: Path, *, exclude_trace_id: str) -> None:
        entries = self._all_entries(directory)
        sizes: dict[Path, int] = {}
        total = 0
        for path, _entry in entries:
            try:
                size = path.lstat().st_size
            except OSError as exc:
                raise self._corrupt("Trace record size cannot be inspected") from exc
            sizes[path] = size
            total += size
        changed = False
        for path, entry in entries:
            if total <= self._quota_bytes:
                break
            if entry.record.trace_id == exclude_trace_id:
                continue
            self._remove_private_file(path, "Evicted trace record")
            total -= sizes[path]
            changed = True
        if total > self._quota_bytes:
            raise self._corrupt("Trace quota could not retain the new record")
        if changed:
            self._fsync_directory(directory)

    def _read_record(self, path: Path, *, missing_ok: bool) -> _DiskTrace | None:
        flags = os.O_RDONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise self._corrupt("Trace record is missing")
        except OSError as exc:
            raise self._corrupt("Trace record path is unsafe") from exc
        try:
            self._require_private_regular(descriptor, "Trace record")
            metadata = os.fstat(descriptor)
            if not 1 <= metadata.st_size <= _MAX_RECORD_BYTES:
                raise self._corrupt("Trace record size is invalid")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                raw = stream.read(_MAX_RECORD_BYTES + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        try:
            payload = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=self._closed_object,
                parse_constant=self._reject_constant,
            )
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise self._corrupt("Trace record JSON is invalid") from exc
        if not isinstance(payload, dict) or set(payload) != {
            "format",
            "record",
            "record_sha256",
            "stored_at",
        }:
            raise self._corrupt("Trace record envelope is invalid")
        if payload["format"] != _FORMAT:
            raise self._corrupt("Trace record format is unsupported")
        record_payload = payload["record"]
        if not isinstance(record_payload, dict) or set(record_payload) != _RECORD_FIELDS:
            raise self._corrupt("Trace record fields are invalid")
        expected_digest = self._record_digest(record_payload)
        if not isinstance(payload["record_sha256"], str) or not secrets.compare_digest(
            payload["record_sha256"], expected_digest
        ):
            raise self._corrupt("Trace record digest verification failed")
        try:
            stored_at = datetime.fromisoformat(
                str(payload["stored_at"]).replace("Z", "+00:00")
            )
            if stored_at.tzinfo is None:
                raise ValueError("stored_at must include timezone")
            diagnostics_id = record_payload["diagnostics_id"]
            if diagnostics_id is not None and not isinstance(diagnostics_id, str):
                raise ValueError("diagnostics_id is invalid")
            record = TraceRecord(
                trace_id=self._required_string(record_payload, "trace_id"),
                step_id=self._required_string(record_payload, "step_id"),
                action_kind=self._required_string(record_payload, "action_kind"),
                risk=RiskClass(record_payload["risk"]),
                page_revision=PageRevision.parse(
                    self._required_string(record_payload, "page_revision")
                ),
                permission=self._required_string(record_payload, "permission"),
                verification_passed=record_payload["verification_passed"],
                started_at=self._required_string(record_payload, "started_at"),
                duration_ms=record_payload["duration_ms"],
                diagnostics_id=diagnostics_id,
            )
        except (TypeError, ValueError) as exc:
            raise self._corrupt("Trace record values are invalid") from exc
        return _DiskTrace(record=record, stored_at=stored_at)

    def _encode(self, entry: _DiskTrace) -> bytes:
        record = to_wire(entry.record)
        if not isinstance(record, dict):
            raise AssertionError("TraceRecord must serialize to an object")
        payload = {
            "format": _FORMAT,
            "record": record,
            "record_sha256": self._record_digest(record),
            "stored_at": entry.stored_at.isoformat(),
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    @staticmethod
    def _record_digest(record: dict[str, object]) -> str:
        canonical = json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(
            b"termuinator-trace-record-v1\x00" + canonical
        ).hexdigest()

    def _atomic_write(self, path: Path, payload: bytes) -> None:
        temporary = path.parent / f".{path.stem}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = -1
        try:
            descriptor = os.open(temporary, flags, 0o600)
            self._require_private_regular(descriptor, "Trace temporary file")
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            self._fsync_directory(path.parent)
        except OSError as exc:
            raise self._corrupt("Trace record could not be published atomically") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _remove_private_file(self, path: Path, label: str) -> None:
        flags = os.O_RDONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise self._corrupt(f"{label} path is unsafe") from exc
        try:
            self._require_private_regular(descriptor, label)
        finally:
            os.close(descriptor)
        try:
            path.unlink()
        except OSError as exc:
            raise self._corrupt(f"{label} could not be removed") from exc

    @staticmethod
    def _require_private_regular(descriptor: int, label: str) -> None:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise TermuinatorError(
                ErrorCode.INTERNAL_ERROR,
                f"{label} must be a private regular file",
            )

    def _current_time(self) -> datetime:
        value = self._now()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("trace clock must return a timezone-aware datetime")
        return value

    @staticmethod
    def _required_string(payload: dict[str, object], name: str) -> str:
        value = payload[name]
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
        return value

    @staticmethod
    def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    @staticmethod
    def _reject_constant(value: str) -> object:
        raise ValueError(f"non-finite JSON value is invalid: {value}")

    @staticmethod
    def _corrupt(message: str) -> TermuinatorError:
        return TermuinatorError(ErrorCode.INTERNAL_ERROR, message)


__all__ = ["DurableTraceRecorder"]
