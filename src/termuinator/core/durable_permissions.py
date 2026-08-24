"""Private crash-safe storage for origin permission decisions."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import threading
from typing import Callable, Iterator, Mapping, Any

from ..contracts import ErrorCode, PermissionDecision, PermissionPolicy
from ..errors import TermuinatorError
from .permissions import canonical_origin


_FORMAT = "termuinator-permissions-v1"
_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_DECISIONS = 1024


class DurablePermissionEngine:
    """Persist block/allow while keeping session grants process-local."""

    def __init__(
        self,
        *,
        root: Path,
        owner_scope: str,
        project_id: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise ValueError("permission root must be an absolute Path")
        self._validate_scope(owner_scope, "owner_scope")
        self._validate_scope(project_id, "project_id")
        self._root = root
        self._project_id = project_id
        self._now = now or (lambda: datetime.now(timezone.utc))
        scope = (
            b"termuinator-permission-owner-v1\x00"
            + owner_scope.encode("utf-8")
            + b"\x00"
            + project_id.encode("utf-8")
        )
        self._scope_digest = hashlib.sha256(scope).hexdigest()
        self._session: dict[tuple[str, str], PermissionDecision] = {}
        self._session_lock = threading.RLock()

    def evaluate(self, *, url: str, session_id: str) -> PermissionPolicy:
        self._validate_session_id(session_id)
        origin = canonical_origin(url)
        persistent = self._load_persistent()
        decision = persistent.get(origin)
        if decision is not None and not self._expired(decision):
            return decision.policy
        with self._session_lock:
            session = self._session.get((session_id, origin))
        return session.policy if session is not None else PermissionPolicy.ASK

    def record(
        self,
        *,
        origin: str,
        policy: PermissionPolicy,
        session_id: str | None = None,
    ) -> PermissionDecision:
        normalized = canonical_origin(origin)
        if not isinstance(policy, PermissionPolicy) or policy is PermissionPolicy.ASK:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "ask is derived and cannot be recorded",
            )
        now = self._current_time().isoformat()
        if policy is PermissionPolicy.SESSION_ALLOW:
            self._validate_session_id(session_id)
            decision = PermissionDecision(
                project_id=self._project_id,
                origin=normalized,
                policy=policy,
                created_at=now,
                persistent=False,
                session_id=session_id,
            )
            with self._session_lock:
                self._session[(session_id, normalized)] = decision
            return decision
        if session_id is not None:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "persistent permissions cannot bind session_id",
            )
        decision = PermissionDecision(
            project_id=self._project_id,
            origin=normalized,
            policy=policy,
            created_at=now,
            persistent=True,
        )
        with self._locked_file() as path:
            decisions = self._read_file(path)
            decisions[normalized] = decision
            self._write_file(path, decisions)
        return decision

    def list(self, session_id: str | None = None) -> tuple[PermissionDecision, ...]:
        if session_id is not None:
            self._validate_session_id(session_id)
        persistent = tuple(
            item
            for item in self._load_persistent().values()
            if not self._expired(item)
        )
        with self._session_lock:
            session = tuple(
                item
                for (item_session, _), item in self._session.items()
                if session_id is None or item_session == session_id
            )
        return tuple(
            sorted(
                persistent + session,
                key=lambda item: (item.origin, item.policy.value, item.session_id or ""),
            )
        )

    def clear_session(self, session_id: str) -> None:
        self._validate_session_id(session_id)
        with self._session_lock:
            keys = [key for key in self._session if key[0] == session_id]
            for key in keys:
                del self._session[key]

    def _load_persistent(self) -> dict[str, PermissionDecision]:
        with self._locked_file() as path:
            return self._read_file(path)

    @contextmanager
    def _locked_file(self) -> Iterator[Path]:
        directory = self._ensure_directory()
        path = directory / f"{self._scope_digest}.json"
        lock_path = directory / f"{self._scope_digest}.lock"
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise self._corrupt("Permission lock path is unsafe") from exc
        try:
            self._require_private_regular(fd, "Permission lock")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                raise TermuinatorError(
                    ErrorCode.SESSION_BUSY,
                    "Another process is updating origin permissions",
                ) from exc
            try:
                yield path
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _ensure_directory(self) -> Path:
        if self._root.is_symlink() or not self._root.is_dir():
            raise self._corrupt("Permission root must be a real directory")
        directory = self._root / "permissions"
        try:
            if directory.is_symlink():
                raise self._corrupt(
                    "Permission directory cannot be a symbolic link"
                )
            directory.mkdir(mode=0o700, exist_ok=True)
            info = directory.lstat()
        except TermuinatorError:
            raise
        except OSError as exc:
            raise self._corrupt("Permission directory path is unsafe") from exc
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
            raise self._corrupt("Permission directory must use mode 0700")
        return directory

    def _read_file(self, path: Path) -> dict[str, PermissionDecision]:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise self._corrupt("Permission record path is unsafe") from exc
        try:
            self._require_private_regular(fd, "Permission record")
            size = os.fstat(fd).st_size
            if not 1 <= size <= _MAX_FILE_BYTES:
                raise self._corrupt("Permission record size is invalid")
            chunks: list[bytes] = []
            remaining = size
            while remaining:
                chunk = os.read(fd, min(65_536, remaining))
                if not chunk:
                    raise self._corrupt("Permission record was truncated")
                chunks.append(chunk)
                remaining -= len(chunk)
        finally:
            os.close(fd)
        try:
            payload = json.loads(
                b"".join(chunks).decode("utf-8"),
                parse_constant=self._reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise self._corrupt("Permission record is invalid JSON") from exc
        return self._decode_payload(payload)

    def _decode_payload(self, payload: Any) -> dict[str, PermissionDecision]:
        if not isinstance(payload, Mapping) or set(payload) != {
            "format",
            "scope_digest",
            "decisions",
        }:
            raise self._corrupt("Permission record fields are invalid")
        if payload["format"] != _FORMAT or payload["scope_digest"] != self._scope_digest:
            raise self._corrupt("Permission record scope or format is invalid")
        values = payload["decisions"]
        if not isinstance(values, list) or len(values) > _MAX_DECISIONS:
            raise self._corrupt("Permission decision list is invalid")
        decoded: dict[str, PermissionDecision] = {}
        for value in values:
            if not isinstance(value, Mapping) or set(value) != {
                "origin",
                "policy",
                "created_at",
                "expires_at",
            }:
                raise self._corrupt("Stored permission fields are invalid")
            try:
                policy = PermissionPolicy(value["policy"])
                if policy not in {
                    PermissionPolicy.BLOCK,
                    PermissionPolicy.ALWAYS_ALLOW,
                }:
                    raise ValueError("stored permission is not persistent")
                decision = PermissionDecision(
                    project_id=self._project_id,
                    origin=canonical_origin(value["origin"]),
                    policy=policy,
                    created_at=value["created_at"],
                    persistent=True,
                    session_id=None,
                    expires_at=value["expires_at"],
                )
            except (TypeError, ValueError, TermuinatorError) as exc:
                raise self._corrupt("Stored permission violates its contract") from exc
            if decision.origin in decoded:
                raise self._corrupt("Stored permission origins must be unique")
            decoded[decision.origin] = decision
        return decoded

    def _write_file(
        self,
        path: Path,
        decisions: Mapping[str, PermissionDecision],
    ) -> None:
        if len(decisions) > _MAX_DECISIONS:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Permission store capacity is exhausted",
            )
        payload = {
            "format": _FORMAT,
            "scope_digest": self._scope_digest,
            "decisions": [
                {
                    "origin": item.origin,
                    "policy": item.policy.value,
                    "created_at": item.created_at,
                    "expires_at": item.expires_at,
                }
                for item in sorted(decisions.values(), key=lambda value: value.origin)
            ],
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
        if len(encoded) > _MAX_FILE_BYTES:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Permission store size limit is exhausted",
            )
        try:
            existing = path.lstat()
        except FileNotFoundError:
            existing = None
        if existing is not None and (
            not stat.S_ISREG(existing.st_mode)
            or stat.S_IMODE(existing.st_mode) != 0o600
        ):
            raise self._corrupt("Permission record path is unsafe")

        temporary = path.with_name(f".{path.name}.{secrets.token_hex(12)}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd: int | None = None
        try:
            fd = os.open(temporary, flags, 0o600)
            self._require_private_regular(fd, "Temporary permission record")
            written = 0
            while written < len(encoded):
                count = os.write(fd, encoded[written:])
                if count <= 0:
                    raise OSError("short permission write")
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
        except (OSError, TypeError, ValueError) as exc:
            raise self._corrupt("Permission record publication failed") from exc
        finally:
            if fd is not None:
                os.close(fd)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _expired(self, decision: PermissionDecision) -> bool:
        if decision.expires_at is None:
            return False
        expires = datetime.fromisoformat(decision.expires_at.replace("Z", "+00:00"))
        return self._current_time() >= expires

    def _current_time(self) -> datetime:
        value = self._now()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("permission clock must return a timezone-aware datetime")
        return value

    @staticmethod
    def _validate_session_id(session_id: str | None) -> None:
        if not isinstance(session_id, str) or not session_id:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "session_id is required for permission evaluation",
            )

    @staticmethod
    def _validate_scope(value: str, name: str) -> None:
        if (
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
            or "\x00" in value
            or len(value) > 4096
        ):
            raise ValueError(f"{name} must be a non-empty canonical identifier")

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


__all__ = ["DurablePermissionEngine"]
