"""Conservative cleanup of Linux Chromium singletons created by one owned launch.

Never adopt old profile locks or recurse through a SingletonSocket symlink. A
reaped direct child, PID lock, cookie pair, private directory identities and a
refused socket are all required before removing a captured socket. This is not
process containment and does not establish that every descendant has exited.
"""

from contextlib import ExitStack, contextmanager
import errno
import os
from pathlib import Path
import socket
import stat


_NAMES = ("SingletonLock", "SingletonSocket", "SingletonCookie")


class SingletonOwnershipError(RuntimeError):
    def __init__(self, reason="ownership_unverified"):
        if reason not in {"ownership_unverified", "preexisting_singleton", "process_not_reaped",
                          "socket_liveness_unknown", "socket_active", "process_identity_active"}:
            reason = "ownership_unverified"
        self.reason = reason
        super().__init__("Owned Chromium singleton cleanup is unverified")


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_mode)


@contextmanager
def _directory(path, *, parent=None, private=True):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, dir_fd=parent)
    try:
        info = os.fstat(descriptor)
        if private and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700):
            raise SingletonOwnershipError()
        yield descriptor, _identity(info)
    finally:
        os.close(descriptor)


def _entry(descriptor, name):
    try:
        info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if info.st_uid != os.getuid():
        raise SingletonOwnershipError()
    target = os.readlink(name, dir_fd=descriptor) if stat.S_ISLNK(info.st_mode) else None
    return _identity(info), target


class ChromiumSingletonOwner:
    def __init__(self, profile, tmp_root):
        self.profile = Path(profile).absolute()
        self.tmp_root = Path(tmp_root).absolute()
        self.pid = None
        self.snapshot = None
        with _directory(self.profile) as (descriptor, identity):
            if any(_entry(descriptor, name) is not None for name in _NAMES):
                raise SingletonOwnershipError("preexisting_singleton")
            self.profile_identity = identity
        with _directory(self.tmp_root, private=False) as (_, identity):
            self.tmp_identity = identity

    def _open(self, stack):
        profile, identity = stack.enter_context(_directory(self.profile))
        if identity != self.profile_identity:
            raise SingletonOwnershipError()
        tmp, identity = stack.enter_context(_directory(self.tmp_root, private=False))
        if identity != self.tmp_identity:
            raise SingletonOwnershipError()
        return profile, tmp

    def _inspect(self, profile, tmp, stack):
        entries = {name: _entry(profile, name) for name in _NAMES}
        if not any(entries.values()):
            return None
        if any(value is None or value[1] is None for value in entries.values()):
            raise SingletonOwnershipError()
        if (type(self.pid) is not int
                or entries["SingletonLock"][1] != f"{socket.gethostname()}-{self.pid}"):
            raise SingletonOwnershipError()
        cookie = entries["SingletonCookie"][1]
        if not 1 <= len(cookie) <= 256 or not cookie.isascii():
            raise SingletonOwnershipError()
        target = Path(entries["SingletonSocket"][1])
        try:
            relative = target.relative_to(self.tmp_root)
        except ValueError:
            raise SingletonOwnershipError() from None
        if (not target.is_absolute() or len(relative.parts) != 2
                or relative.parts[0] in {".", ".."} or relative.name != "SingletonSocket"):
            raise SingletonOwnershipError()
        remote, identity = stack.enter_context(_directory(relative.parts[0], parent=tmp))
        remote_entries = {name: _entry(remote, name) for name in _NAMES[1:]}
        endpoint = remote_entries["SingletonSocket"]
        remote_cookie = remote_entries["SingletonCookie"]
        if (endpoint is None or not stat.S_ISSOCK(endpoint[0][3])
                or remote_cookie is None or remote_cookie[1] != cookie):
            raise SingletonOwnershipError()
        return entries, relative.parts[0], identity, remote_entries

    def capture(self):
        """Capture before terminate, while Chromium still has its PID lock."""
        if self.snapshot is not None:
            return
        try:
            with ExitStack() as stack:
                profile, tmp = self._open(stack)
                self.snapshot = self._inspect(profile, tmp, stack)
        except (OSError, SingletonOwnershipError):
            # Termination must still run; cleanup will reject unproven entries.
            return

    def cleanup(self, *, reaped):
        if not reaped:
            raise SingletonOwnershipError("process_not_reaped")
        try:
            self._cleanup()
        except OSError as exc:
            raise SingletonOwnershipError() from exc

    def _require_inactive_pid(self):
        # The PID comes from our child handle, never from an untrusted link.
        # Reuse after reaping (or permission uncertainty) must block unlink.
        if type(self.pid) is not int or self.pid <= 0:
            raise SingletonOwnershipError()
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return
        raise SingletonOwnershipError("process_identity_active")

    def _cleanup(self):
        with ExitStack() as stack:
            profile, tmp = self._open(stack)
            snapshot = self.snapshot or self._inspect(profile, tmp, stack)
            if snapshot is None:
                return
            self._require_inactive_pid()
            entries, remote_name, identity, remote_entries = snapshot
            # Every surviving entry must be exactly the captured object. Missing
            # entries are allowed: Chromium normally removes its own links.
            def unchanged(descriptor, expected):
                for name, old in expected.items():
                    current = _entry(descriptor, name)
                    if current is not None and current != old:
                        raise SingletonOwnershipError()

            unchanged(profile, entries)
            try:
                remote, current_identity = stack.enter_context(_directory(remote_name, parent=tmp))
            except FileNotFoundError:
                # A full earlier capture still binds the profile links when
                # Chromium removes its temp directory before its profile links.
                if (_identity(os.lstat(self.profile)) != self.profile_identity
                        or _identity(os.lstat(self.tmp_root)) != self.tmp_identity):
                    raise SingletonOwnershipError()
                unchanged(profile, entries)
                self._require_inactive_pid()
                try:
                    os.stat(remote_name, dir_fd=tmp, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise SingletonOwnershipError()
                for name in entries:
                    if _entry(profile, name) is not None:
                        os.unlink(name, dir_fd=profile)
                self.snapshot = None
                return
            if current_identity != identity or not set(os.listdir(remote)) <= set(_NAMES[1:]):
                raise SingletonOwnershipError()
            unchanged(remote, remote_entries)
            endpoint = _entry(remote, "SingletonSocket")
            if endpoint is not None:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(0.2)
                    try:
                        probe.connect(str(self.tmp_root / remote_name / "SingletonSocket"))
                    except OSError as exc:
                        if exc.errno != errno.ECONNREFUSED:
                            raise SingletonOwnershipError("socket_liveness_unknown") from exc
                    else:
                        raise SingletonOwnershipError("socket_active")
            # Revalidate after the probe and use directory-relative unlink; no
            # symlink target is passed to recursive removal or arbitrary unlink.
            if _identity(os.stat(remote_name, dir_fd=tmp, follow_symlinks=False)) != identity:
                raise SingletonOwnershipError()
            if _identity(os.lstat(self.profile)) != self.profile_identity:
                raise SingletonOwnershipError()
            if _identity(os.lstat(self.tmp_root)) != self.tmp_identity:
                raise SingletonOwnershipError()
            unchanged(profile, entries)
            unchanged(remote, remote_entries)
            self._require_inactive_pid()
            for descriptor, expected in ((remote, remote_entries), (profile, entries)):
                for name in expected:
                    if _entry(descriptor, name) is not None:
                        os.unlink(name, dir_fd=descriptor)
            os.rmdir(remote_name, dir_fd=tmp)
            self.snapshot = None
