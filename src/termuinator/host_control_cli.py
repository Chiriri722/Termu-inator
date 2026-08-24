"""Small owner-local CLI for permission, confirmation, and takeover mutation."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import socket
import stat
import sys
from typing import TextIO

from .config import load_runtime_config
from .contracts import ErrorCode, to_wire
from .errors import TermuinatorError


_MAX_REQUEST_BYTES = 64 * 1024
_MAX_RESPONSE_BYTES = 1024 * 1024
_MAX_PORTABLE_SOCKET_PATH_BYTES = 100


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tbp-control",
        description=(
            "Owner-local Termu-inator permission, Developer Mode, and takeover control."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Absolute path to a private Termu-inator runtime config.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    permission = commands.add_parser(
        "permission",
        help="Record one active-session origin policy.",
    )
    permission.add_argument("session_id")
    permission.add_argument("origin")
    permission.add_argument(
        "policy",
        choices=("block", "session_allow", "always_allow"),
    )

    confirmation = commands.add_parser(
        "confirmation",
        help="Approve or deny one server-owned challenge.",
    )
    confirmation.add_argument("session_id")
    confirmation.add_argument("confirmation_id")
    confirmation.add_argument("decision", choices=("approve", "deny"))

    developer_mode = commands.add_parser(
        "developer-mode",
        help="Enable or disable read-only Developer queries for the active origin.",
    )
    developer_mode.add_argument("session_id")
    developer_mode.add_argument("origin")
    developer_mode.add_argument("decision", choices=("enable", "disable"))

    takeover_start = commands.add_parser(
        "takeover-start",
        help="Enter local user control after a confidential handoff.",
    )
    takeover_start.add_argument("session_id")

    takeover_resume = commands.add_parser(
        "takeover-resume",
        help="Rotate page refs and resume remote automation.",
    )
    takeover_resume.add_argument("session_id")
    return parser


def request_from_args(arguments: argparse.Namespace) -> dict[str, object]:
    command = arguments.command
    if command == "permission":
        return {
            "version": 1,
            "operation": "permission_record",
            "session_id": arguments.session_id,
            "origin": arguments.origin,
            "policy": arguments.policy,
        }
    if command == "confirmation":
        return {
            "version": 1,
            "operation": "confirmation_decide",
            "session_id": arguments.session_id,
            "confirmation_id": arguments.confirmation_id,
            "decision": arguments.decision,
        }
    if command == "developer-mode":
        return {
            "version": 1,
            "operation": "developer_mode_set",
            "session_id": arguments.session_id,
            "origin": arguments.origin,
            "enabled": arguments.decision == "enable",
        }
    if command == "takeover-start":
        return {
            "version": 1,
            "operation": "takeover_start",
            "session_id": arguments.session_id,
        }
    if command == "takeover-resume":
        return {
            "version": 1,
            "operation": "takeover_resume",
            "session_id": arguments.session_id,
        }
    raise ValueError("host-control command is unsupported")


def send_control_request(
    path: Path,
    request: Mapping[str, object],
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, object]:
    _validate_socket_path(path)
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not 0 < timeout_seconds <= 30
    ):
        raise ValueError("timeout_seconds must be between 0 and 30")
    encoded = (
        json.dumps(
            request,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    if len(encoded) > _MAX_REQUEST_BYTES:
        raise ValueError("host-control request exceeds 64 KiB")

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(float(timeout_seconds))
    try:
        client.connect(str(path))
        client.sendall(encoded)
        client.shutdown(socket.SHUT_WR)
        response = bytearray()
        while b"\n" not in response:
            chunk = client.recv(64 * 1024)
            if not chunk:
                break
            response.extend(chunk)
            if len(response) > _MAX_RESPONSE_BYTES:
                raise ValueError("host-control response exceeds 1 MiB")
    finally:
        client.close()

    line, separator, trailing = bytes(response).partition(b"\n")
    if not separator or trailing or not line:
        raise ValueError("host-control response must contain exactly one JSON line")
    payload = json.loads(
        line.decode("utf-8"),
        object_pairs_hook=_closed_json_object,
        parse_constant=_reject_json_constant,
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
        raise ValueError("host-control response envelope is invalid")
    expected = {"ok", "result"} if payload["ok"] else {"ok", "error"}
    if set(payload) != expected or not isinstance(
        payload["result" if payload["ok"] else "error"],
        Mapping,
    ):
        raise ValueError("host-control response envelope is invalid")
    return payload


def _validate_socket_path(path: Path) -> None:
    if not isinstance(path, Path):
        raise TypeError("path must be pathlib.Path")
    if (
        not path.is_absolute()
        or ".." in path.parts
        or "\x00" in str(path)
        or len(os.fsencode(path)) > _MAX_PORTABLE_SOCKET_PATH_BYTES
    ):
        raise ValueError("control socket path must be absolute and canonical")
    metadata = os.lstat(path)
    if (
        not stat.S_ISSOCK(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError("control socket must be an owner-private Unix socket")


def _config_path(
    arguments: argparse.Namespace,
    environ: Mapping[str, str],
) -> Path | None:
    value: object = arguments.config
    if value is None:
        value = environ.get("TERMUINATOR_CONFIG")
    if value is None:
        return None
    path = value if isinstance(value, Path) else Path(str(value))
    if not path.is_absolute() or ".." in path.parts or "\x00" in str(path):
        raise ValueError("config path must be absolute and canonical")
    return path


def _closed_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    source = os.environ if environ is None else environ
    destination = sys.stdout if stdout is None else stdout
    try:
        config = load_runtime_config(
            _config_path(arguments, source),
            environ=source,
        )
        response = send_control_request(
            config.data_root / "runtime" / "control.sock",
            request_from_args(arguments),
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        code = (
            ErrorCode.BACKEND_CRASHED
            if isinstance(exc, OSError)
            else ErrorCode.INVALID_REQUEST
        )
        response = {
            "ok": False,
            "error": to_wire(
                TermuinatorError(
                    code,
                    "Local host-control client could not complete the request",
                    details={"reason_code": "control_client_failure"},
                ).to_envelope()
            ),
        }
        exit_code = 2
    else:
        exit_code = 0 if response["ok"] else 1

    destination.write(
        json.dumps(
            response,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    destination.flush()
    return exit_code


__all__ = [
    "build_parser",
    "main",
    "request_from_args",
    "send_control_request",
]
