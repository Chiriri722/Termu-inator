"""Owner-local control protocol kept outside the model-visible MCP surface."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
from typing import TYPE_CHECKING, Any

from .contracts import ErrorCode, PermissionPolicy, to_wire
from .errors import TermuinatorError

if TYPE_CHECKING:
    from .core.service import BrowserService


_OPAQUE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{7,127}$")
_REQUEST_FIELDS = {
    "permission_record": frozenset(
        {"version", "operation", "session_id", "origin", "policy"}
    ),
    "confirmation_decide": frozenset(
        {
            "version",
            "operation",
            "session_id",
            "decision",
            "confirmation_id",
        }
    ),
    "developer_mode_set": frozenset(
        {"version", "operation", "session_id", "origin", "enabled"}
    ),
    "takeover_start": frozenset({"version", "operation", "session_id"}),
    "takeover_resume": frozenset({"version", "operation", "session_id"}),
}
_RECORDABLE_POLICIES = {
    PermissionPolicy.BLOCK.value: PermissionPolicy.BLOCK,
    PermissionPolicy.SESSION_ALLOW.value: PermissionPolicy.SESSION_ALLOW,
    PermissionPolicy.ALWAYS_ALLOW.value: PermissionPolicy.ALWAYS_ALLOW,
}
_MAX_REQUEST_BYTES = 64 * 1024
_MAX_PORTABLE_SOCKET_PATH_BYTES = 100
_REQUEST_TIMEOUT_SECONDS = 5.0


class HostControlRouter:
    """Dispatch a closed v1 host protocol to one process-owned browser service."""

    def __init__(self, service: BrowserService) -> None:
        self._service = service

    async def dispatch(self, request: object) -> dict[str, object]:
        payload = self._validate_envelope(request)
        operation = payload["operation"]
        session_id = self._opaque_id(payload["session_id"], "session_id")

        if operation == "permission_record":
            origin = self._bounded_string(payload["origin"], "origin", 4096)
            policy_name = self._bounded_string(payload["policy"], "policy", 32)
            policy = _RECORDABLE_POLICIES.get(policy_name)
            if policy is None:
                raise self._invalid(
                    "Permission policy must be block, session_allow, or always_allow"
                )
            result = await self._service.local_permission_record(
                session_id=session_id,
                origin=origin,
                policy=policy,
            )
        elif operation == "developer_mode_set":
            enabled = payload["enabled"]
            if not isinstance(enabled, bool):
                raise self._invalid("Developer Mode enabled must be a boolean")
            result = await self._service.local_developer_mode_set(
                session_id=session_id,
                origin=self._bounded_string(payload["origin"], "origin", 4096),
                enabled=enabled,
            )
        elif operation == "confirmation_decide":
            decision = self._bounded_string(payload["decision"], "decision", 16)
            if decision not in {"approve", "deny"}:
                raise self._invalid(
                    "Confirmation decision must be approve or deny"
                )
            result = await self._service.local_confirmation_decide(
                session_id=session_id,
                operation=decision,
                confirmation_id=self._opaque_id(
                    payload["confirmation_id"],
                    "confirmation_id",
                ),
            )
        elif operation == "takeover_start":
            result = await self._service.local_takeover_start(session_id)
        else:
            result = await self._service.local_takeover_resume(session_id)

        return {"ok": True, "result": to_wire(result)}

    @staticmethod
    def error_payload(error: TermuinatorError) -> dict[str, object]:
        if not isinstance(error, TermuinatorError):
            raise TypeError("error must be TermuinatorError")
        return {"ok": False, "error": to_wire(error.to_envelope())}

    @staticmethod
    def _validate_envelope(request: object) -> Mapping[str, Any]:
        if not isinstance(request, Mapping) or any(
            not isinstance(key, str) for key in request
        ):
            raise HostControlRouter._invalid("Host-control request must be an object")
        version = request.get("version")
        if isinstance(version, bool) or version != 1:
            raise HostControlRouter._invalid(
                "Host-control request version must be integer 1"
            )
        operation = request.get("operation")
        if not isinstance(operation, str) or operation not in _REQUEST_FIELDS:
            raise HostControlRouter._invalid("Host-control operation is unsupported")
        if frozenset(request) != _REQUEST_FIELDS[operation]:
            raise HostControlRouter._invalid(
                "Host-control request fields do not match the operation"
            )
        return request

    @staticmethod
    def _bounded_string(value: object, name: str, maximum: int) -> str:
        if (
            not isinstance(value, str)
            or not value
            or "\x00" in value
            or len(value) > maximum
        ):
            raise HostControlRouter._invalid(f"{name} is invalid")
        return value

    @classmethod
    def _opaque_id(cls, value: object, name: str) -> str:
        text = cls._bounded_string(value, name, 128)
        if not _OPAQUE_ID.fullmatch(text):
            raise cls._invalid(f"{name} is invalid")
        return text

    @staticmethod
    def _invalid(message: str) -> TermuinatorError:
        return TermuinatorError(ErrorCode.INVALID_REQUEST, message)


class UnixHostControlServer:
    """Serve one bounded JSON request per owner-private Unix connection."""

    def __init__(
        self,
        *,
        path: Path,
        router: HostControlRouter,
        owner_uid: int | None = None,
    ) -> None:
        if not isinstance(path, Path):
            raise TypeError("path must be pathlib.Path")
        if not path.is_absolute() or ".." in path.parts or "\x00" in str(path):
            raise ValueError("control socket path must be absolute and canonical")
        if len(os.fsencode(path)) > _MAX_PORTABLE_SOCKET_PATH_BYTES:
            raise ValueError("control socket path exceeds the portable Unix limit")
        if not isinstance(router, HostControlRouter):
            raise TypeError("router must be HostControlRouter")
        resolved_uid = os.getuid() if owner_uid is None else owner_uid
        if (
            isinstance(resolved_uid, bool)
            or not isinstance(resolved_uid, int)
            or resolved_uid < 0
        ):
            raise ValueError("owner_uid must be a non-negative integer")
        self._path = path
        self._router = router
        self._owner_uid = resolved_uid
        self._server: asyncio.AbstractServer | None = None
        self._bound_identity: tuple[int, int] | None = None

    @property
    def path(self) -> Path:
        return self._path

    async def start(self) -> None:
        if self._server is not None:
            raise ValueError("control socket server is already running")
        self._prepare_parent()
        try:
            os.lstat(self._path)
        except FileNotFoundError:
            pass
        else:
            raise ValueError("control socket path already exists")

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        bound_identity: tuple[int, int] | None = None
        try:
            previous_umask = os.umask(0o177)
            try:
                listener.bind(str(self._path))
            finally:
                os.umask(previous_umask)
            listener.listen(socket.SOMAXCONN)
            listener.setblocking(False)
            os.chmod(self._path, 0o600)
            metadata = os.lstat(self._path)
            if (
                not stat.S_ISSOCK(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != self._owner_uid
            ):
                raise ValueError("control socket is not an owner-private Unix socket")
            bound_identity = (metadata.st_dev, metadata.st_ino)
            server = await asyncio.start_unix_server(
                self._handle_connection,
                sock=listener,
                limit=_MAX_REQUEST_BYTES + 1,
            )
        except Exception:
            listener.close()
            if bound_identity is not None:
                self._unlink_if_identity(bound_identity)
            raise

        self._bound_identity = bound_identity
        self._server = server

    async def close(self) -> None:
        server = self._server
        identity = self._bound_identity
        self._server = None
        self._bound_identity = None
        if server is not None:
            server.close()
            await server.wait_closed()
        if identity is not None:
            self._unlink_if_identity(identity)

    def _prepare_parent(self) -> None:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = os.lstat(self._path.parent)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != self._owner_uid
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise ValueError("control socket directory must be owner-private")

    def _unlink_if_identity(self, identity: tuple[int, int]) -> None:
        try:
            metadata = os.lstat(self._path)
        except FileNotFoundError:
            return
        if (
            (metadata.st_dev, metadata.st_ino) == identity
            and stat.S_ISSOCK(metadata.st_mode)
            and metadata.st_uid == self._owner_uid
        ):
            self._path.unlink()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            if not self._peer_is_owner(writer):
                raise TermuinatorError(
                    ErrorCode.PERMISSION_DENIED,
                    "Local control peer does not match the runtime owner",
                )
            try:
                request = await self._read_request(reader)
            except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Local control request must be bounded UTF-8 JSON",
                ) from exc
            response = await self._router.dispatch(request)
        except TermuinatorError as error:
            response = self._router.error_payload(error)
        except Exception:
            response = self._router.error_payload(
                TermuinatorError(
                    ErrorCode.INTERNAL_ERROR,
                    "Local control request failed",
                )
            )

        encoded = (
            json.dumps(
                response,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        try:
            writer.write(encoded)
            await writer.drain()
        except (BrokenPipeError, ConnectionError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (BrokenPipeError, ConnectionError):
                pass

    async def _read_request(self, reader: asyncio.StreamReader) -> object:
        data = await asyncio.wait_for(
            reader.readline(),
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        if not data or not data.endswith(b"\n") or len(data) > _MAX_REQUEST_BYTES:
            raise ValueError("local control request is empty, incomplete, or oversized")
        encoded = data[:-1]
        if encoded.endswith(b"\r"):
            encoded = encoded[:-1]
        if not encoded:
            raise ValueError("local control request is empty")
        return json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=self._closed_json_object,
            parse_constant=self._reject_json_constant,
        )

    @staticmethod
    def _closed_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    @staticmethod
    def _reject_json_constant(value: str) -> object:
        raise ValueError(f"non-finite JSON constant is not allowed: {value}")

    def _peer_is_owner(self, writer: asyncio.StreamWriter) -> bool:
        peer_socket = writer.get_extra_info("socket")
        if peer_socket is None:
            return False
        getpeereid = getattr(peer_socket, "getpeereid", None)
        if callable(getpeereid):
            peer_uid, _peer_gid = getpeereid()
            return peer_uid == self._owner_uid
        if hasattr(socket, "SO_PEERCRED"):
            size = struct.calcsize("3i")
            credentials = peer_socket.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, size)
            _peer_pid, peer_uid, _peer_gid = struct.unpack("3i", credentials)
            return peer_uid == self._owner_uid
        return True


__all__ = ["HostControlRouter", "UnixHostControlServer"]
