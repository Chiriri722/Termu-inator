"""Process-scoped single-session lease."""

from __future__ import annotations

from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Protocol

from ..contracts import ErrorCode
from ..errors import TermuinatorError


class SessionLock(Protocol):
    def acquire(self) -> None:
        ...

    def release(self) -> None:
        ...


class ProcessSessionLock:
    """Hold a kernel-released exclusive lease for one browser process."""

    def __init__(self, *, lock_path: Path, owner_scope: str) -> None:
        if not lock_path.is_absolute():
            raise ValueError("lock_path must be absolute")
        if not isinstance(owner_scope, str) or not owner_scope.strip():
            raise ValueError("owner_scope must be a non-empty string")
        self.lock_path = lock_path
        self._owner_digest = hashlib.sha256(
            b"termuinator-session-owner-v1\x00" + owner_scope.encode("utf-8")
        ).hexdigest()
        self._fd: int | None = None

    def acquire(self) -> None:
        if self._fd is not None:
            raise TermuinatorError(
                ErrorCode.SESSION_BUSY,
                "This service already holds the browser session lease",
            )
        parent = self.lock_path.parent
        if parent.is_symlink():
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Session lock directory cannot be a symbolic link",
            )
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if parent.is_symlink():
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Session lock directory cannot be a symbolic link",
            )
        parent.chmod(0o700)

        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.lock_path, flags, 0o600)
        except OSError as exc:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Session lock path is not a safe regular file",
            ) from exc

        try:
            file_stat = os.fstat(fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Session lock path is not a regular file",
                )
            if stat.S_IMODE(file_stat.st_mode) != 0o600:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Session lock file must have mode 0600",
                )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                raise TermuinatorError(
                    ErrorCode.SESSION_BUSY,
                    "Another browser session holds the process lease",
                ) from exc

            metadata = json.dumps(
                {
                    "format": "termuinator-session-lock-v1",
                    "owner_digest": self._owner_digest,
                    "pid": os.getpid(),
                    "acquired_at": datetime.now(timezone.utc).isoformat(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            os.ftruncate(fd, 0)
            os.write(fd, metadata)
            os.fsync(fd)
        except Exception:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
            raise
        self._fd = fd

    def release(self) -> None:
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def __enter__(self) -> "ProcessSessionLock":
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


__all__ = ["ProcessSessionLock", "SessionLock"]
