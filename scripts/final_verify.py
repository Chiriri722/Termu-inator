#!/usr/bin/env python3
"""Fail-closed release verification for an installed Termu-inator wheel."""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
from collections.abc import Awaitable, Callable, Mapping, Sequence
import csv
from datetime import datetime, timedelta, timezone
from email import policy as email_policy
from email.parser import BytesParser
import errno
import fcntl
import hashlib
from importlib import metadata as importlib_metadata
from importlib import util as importlib_util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import secrets
import stat
import struct
import subprocess
import sys
import sysconfig
import time
from typing import Any
from urllib.parse import unquote, urlsplit
import zipfile
import zlib


_ARTIFACT_URI = re.compile(r"^artifact://sha256/[0-9a-f]{64}$")
_PUBLIC_REF = re.compile(r"^ref_[A-Za-z0-9_-]{16,}$")
_ACCESSIBILITY_KEYS = frozenset({"ref", "role", "name", "text", "depth"})
_ARTIFACT_CHUNK_KEYS = frozenset(
    {"uri", "offset", "next_offset", "eof", "data_base64"}
)
_ARTIFACT_KEYS = frozenset(
    {"uri", "sha256", "size_bytes", "mime_type", "created_at", "expires_at"}
)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_INTERACTIVE_TOOL_NAMES = (
    "browser_session_start",
    "browser_session_status",
    "browser_session_stop",
    "browser_navigate",
    "browser_observe",
    "browser_act",
    "browser_wait",
    "browser_tabs",
    "browser_screenshot",
    "browser_downloads",
    "browser_artifact_read",
    "browser_permissions",
    "browser_devtools",
    "browser_trace",
)
_OBSERVER_TOOL_NAMES = tuple(
    name
    for name in _INTERACTIVE_TOOL_NAMES
    if name not in {"browser_act", "browser_tabs"}
)
_EXPECTED_MCP_VERSION = "1.29.0"
_EXPECTED_WEBSOCKETS_VERSION = "17.0.1"
_EXPECTED_PACKAGE_VERSION = "0.1.0a1"
_EXPECTED_DIST_INFO_ROOT = (
    f"termux_browser_pilot-{_EXPECTED_PACKAGE_VERSION}.dist-info"
)
_EXPECTED_CONSOLE_ENTRYPOINTS = {
    "tbp": "cli:main",
    "tbp-control": "src.termuinator.host_control_cli:main",
    "tbp-mcp": "src.mcp_entrypoint:main",
    "tbp-mcp-v1": "src.mcp_entrypoint:main_v1",
}
_EXPECTED_ENTRY_POINTS_BYTES = (
    b"[console_scripts]\n"
    b"tbp = cli:main\n"
    b"tbp-control = src.termuinator.host_control_cli:main\n"
    b"tbp-mcp = src.mcp_entrypoint:main\n"
    b"tbp-mcp-v1 = src.mcp_entrypoint:main_v1\n"
)
_EXPECTED_DIST_INFO_FILES = frozenset(
    {
        "METADATA",
        "WHEEL",
        "entry_points.txt",
        "top_level.txt",
        "RECORD",
        "licenses/LICENSE",
        "licenses/NOTICE.md",
    }
)
_EXPECTED_METADATA_HEADERS = {
    "Metadata-Version": ("2.4",),
    "Name": ("termux-browser-pilot",),
    "Version": (_EXPECTED_PACKAGE_VERSION,),
    "Summary": (
        "AI-first Firefox and Chromium browser runtime for Termux/Android.",
    ),
    "Author": ("Termux Browser Pilot Contributors",),
    "License-Expression": ("MIT",),
    "Project-URL": (
        "Homepage, https://github.com/Chiriri722/Termu-inator",
        "Repository, https://github.com/Chiriri722/Termu-inator",
        "Upstream, https://github.com/salviz/termux-browser-pilot",
    ),
    "Keywords": ("browser,automation,termux,android,agent,mcp",),
    "Classifier": (
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Topic :: Internet :: WWW/HTTP :: Browsers",
        "Topic :: Software Development :: Testing",
    ),
    "Requires-Python": (">=3.10",),
    "Description-Content-Type": ("text/markdown",),
    "License-File": ("LICENSE", "NOTICE.md"),
    "Requires-Dist": (
        "websockets<18,>=13",
        'mcp==1.29.0; extra == "mcp"',
    ),
    "Provides-Extra": ("mcp",),
    "Dynamic": ("license-file",),
}
_EXPECTED_WHEEL_HEADERS = {
    "Wheel-Version": ("1.0",),
    "Root-Is-Purelib": ("true",),
    "Tag": ("py3-none-any",),
}
_MCP_ERROR_CODES = frozenset(
    {
        "action_failed",
        "artifact_not_found",
        "backend_crashed",
        "confirmation_required",
        "idempotency_conflict",
        "internal_error",
        "invalid_request",
        "outcome_unknown",
        "ownership_denied",
        "permission_denied",
        "permission_required",
        "session_busy",
        "session_not_found",
        "session_paused",
        "stale_observation",
        "target_not_found",
        "timeout",
        "unsupported_capability",
    }
)
_MCP_ERROR_DETAIL_VALUES = {
    "backend": frozenset({"chromium", "firefox"}),
    "operation": frozenset({"back", "forward", "goto", "observe", "reload"}),
    "stage": frozenset(
        {
            "adapter_metadata",
            "address_bar_copy",
            "address_bar_navigation",
            "bidi_navigation",
            "clipboard_prime",
            "metadata_validation",
            "observe_accessibility",
            "observe_dom",
            "observe_screenshot",
            "observe_text",
            "pilot_dispatch",
            "window_unavailable",
        }
    ),
    "reason": frozenset(
        {
            "focus_unverified",
            "invalid_url",
            "marker_unchanged",
            "owner_release_failed",
            "read_failed",
            "read_timeout",
            "selection_empty",
        }
    ),
}
_MAX_CONTROL_SOCKET_PATH_BYTES = 100
_MCP_EXEC_LAUNCHER = "\n".join(
    (
        "import os, sys",
        "pid_path, command = sys.argv[1:3]",
        "flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL",
        "flags |= getattr(os, 'O_CLOEXEC', 0)",
        "flags |= getattr(os, 'O_NOFOLLOW', 0)",
        "fd = os.open(pid_path, flags, 0o600)",
        "try:",
        "    payload = f'{os.getpid()}\\n'.encode('ascii')",
        "    written = os.write(fd, payload)",
        "    if written != len(payload): raise OSError('short PID write')",
        "    os.fsync(fd)",
        "finally:",
        "    os.close(fd)",
        "os.execv(command, [command, *sys.argv[3:]])",
    )
)


class VerificationFailure(RuntimeError):
    """A bounded, page-data-free release-gate failure."""

    mcp_code: str | None = None

class _ConfirmationRequired(VerificationFailure):
    def __init__(self, confirmation_id: str) -> None:
        super().__init__("fixture submission requires local confirmation")
        self.confirmation_id = confirmation_id


ToolCaller = Callable[
    [str, dict[str, object]],
    Awaitable[Mapping[str, Any]],
]
PermissionGrant = Callable[[str, str], Awaitable[None]]
ConfirmationApproval = Callable[[str, str], Awaitable[None]]
LocalTakeover = Callable[[str, str], Awaitable[None]]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="final_verify.py",
        description=(
            "Verify both compact browser backends against a loopback fixture "
            "using an installed release-candidate wheel."
        ),
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--mcp-command", type=Path, required=True)
    parser.add_argument("--control-command", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-wheel-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prepare_output_directory(path: Path, project_root: Path) -> None:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
        raise VerificationFailure("output must be an absolute canonical path")
    if path.exists() or path.is_symlink():
        raise VerificationFailure("output directory already exists; refusing overwrite")
    parent = path.parent
    try:
        parent_info = parent.lstat()
    except OSError as exc:
        raise VerificationFailure("output parent is missing or unsafe") from exc
    if not stat.S_ISDIR(parent_info.st_mode):
        raise VerificationFailure("output parent must be a real directory")
    try:
        resolved_project = project_root.resolve(strict=True)
        resolved_parent = parent.resolve(strict=True)
    except OSError as exc:
        raise VerificationFailure("project or output parent cannot be resolved") from exc
    if resolved_parent == resolved_project or resolved_project in resolved_parent.parents:
        raise VerificationFailure("verification output must stay outside the repository")
    try:
        path.mkdir(mode=0o700)
    except OSError as exc:
        raise VerificationFailure("verification output directory could not be created") from exc
    _require_private_directory(path, "verification output directory")


def _read_bounded_regular(path: Path, *, label: str, maximum: int) -> bytes:
    try:
        info = path.lstat()
    except OSError as exc:
        raise VerificationFailure(f"{label} is missing or unsafe") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_size < 1
        or info.st_size > maximum
    ):
        raise VerificationFailure(f"{label} is not a bounded regular file")
    return path.read_bytes()


def _run_bounded(
    argv: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path,
    environ: Mapping[str, str] | None = None,
    timeout: float = 30,
    label: str,
) -> subprocess.CompletedProcess[str]:
    command = [os.fspath(item) for item in argv]
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=None if environ is None else dict(environ),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise VerificationFailure(f"{label} could not be executed") from exc
    if len(completed.stdout) > 64 * 1024 or len(completed.stderr) > 64 * 1024:
        raise VerificationFailure(f"{label} output exceeded the verification bound")
    return completed


def _require_executable(path: Path, label: str) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise VerificationFailure(f"{label} must be an absolute canonical path")
    try:
        info = path.lstat()
    except OSError as exc:
        raise VerificationFailure(f"{label} is missing or unsafe") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or path.is_symlink()
        or not os.access(path, os.X_OK)
    ):
        raise VerificationFailure(f"{label} must be an executable regular file")


def _load_frozen_manifest(project_root: Path) -> dict[str, object]:
    path = project_root / "schemas" / "v1" / "tool-manifest.json"
    encoded = _read_bounded_regular(
        path,
        label="frozen tool manifest",
        maximum=2 * 1024 * 1024,
    )
    try:
        value = json.loads(
            encoded.decode("utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise VerificationFailure("frozen tool manifest is invalid JSON") from exc
    manifest = _mapping(value, "frozen tool manifest")
    tools = manifest.get("tools")
    if not isinstance(tools, list):
        raise VerificationFailure("frozen tool manifest has no tool list")
    names: list[str] = []
    for raw_tool in tools:
        tool = _mapping(raw_tool, "frozen tool")
        name = tool.get("name")
        if not isinstance(name, str):
            raise VerificationFailure("frozen tool has no canonical name")
        names.append(name)
    validate_tool_inventory(
        names,
        _INTERACTIVE_TOOL_NAMES,
        profile="interactive",
    )
    if (
        manifest.get("manifest_version") != "1.0"
        or manifest.get("contract_version") != "1.0"
        or manifest.get("default_tool_count") != 14
        or manifest.get("max_tool_count") != 16
    ):
        raise VerificationFailure("frozen tool manifest version or bounds differ")
    return {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "manifest_version": "1.0",
        "contract_version": "1.0",
        "interactive_tool_count": 14,
        "observer_tool_count": 12,
    }


def _git_preflight(project_root: Path, expected_commit: str) -> dict[str, object]:
    if re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None:
        raise VerificationFailure("expected commit must be a full lowercase Git SHA")
    if not project_root.is_absolute() or ".." in project_root.parts:
        raise VerificationFailure("project root must be an absolute canonical path")
    try:
        root_info = project_root.lstat()
    except OSError as exc:
        raise VerificationFailure("project root is missing or unsafe") from exc
    if not stat.S_ISDIR(root_info.st_mode) or project_root.is_symlink():
        raise VerificationFailure("project root must be a real directory")
    root = _run_bounded(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=project_root,
        label="Git root check",
    )
    if root.returncode != 0:
        raise VerificationFailure("project root is not a Git checkout")
    try:
        reported_root = Path(root.stdout.strip()).resolve(strict=True)
        expected_root = project_root.resolve(strict=True)
    except OSError as exc:
        raise VerificationFailure("Git root could not be resolved") from exc
    if reported_root != expected_root:
        raise VerificationFailure("project root differs from Git toplevel")
    head = _run_bounded(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        label="Git HEAD check",
    )
    if head.returncode != 0 or head.stdout.strip() != expected_commit:
        raise VerificationFailure("checkout HEAD differs from expected commit")
    status_result = _run_bounded(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=project_root,
        label="Git worktree check",
    )
    if status_result.returncode != 0 or status_result.stdout:
        raise VerificationFailure("release verification requires a clean checkout")
    return {"commit": expected_commit, "clean_worktree": True}


def _runtime_distribution(
    name: str,
    *,
    search_paths: Sequence[Path] | None = None,
) -> importlib_metadata.Distribution:
    if not isinstance(name, str) or not name:
        raise ValueError("distribution name must be non-empty")
    if search_paths is None:
        candidates = {
            Path(value).resolve()
            for value in (
                sysconfig.get_path("purelib"),
                sysconfig.get_path("platlib"),
            )
            if value
        }
    else:
        candidates = {path.resolve() for path in search_paths}
    normalized = re.sub(r"[-_.]+", "-", name).lower()
    matches = []
    for distribution in importlib_metadata.distributions(
        path=[os.fspath(path) for path in sorted(candidates)]
    ):
        raw_name = distribution.metadata.get("Name")
        if (
            isinstance(raw_name, str)
            and re.sub(r"[-_.]+", "-", raw_name).lower() == normalized
        ):
            matches.append(distribution)
    if len(matches) != 1:
        raise VerificationFailure(
            f"runtime distribution {name} is missing or ambiguous in the venv"
        )
    return matches[0]


def _read_source_regular(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise VerificationFailure(f"{label} is missing or unsafe") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 <= info.st_size <= 4 * 1024 * 1024:
            raise VerificationFailure(f"{label} is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise VerificationFailure(f"{label} was truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _tracked_source_bytes(project_root: Path) -> dict[str, bytes]:
    tracked = _run_bounded(
        ["git", "ls-files", "-z", "--", "cli.py", "src"],
        cwd=project_root,
        label="tracked wheel source inventory",
    )
    if tracked.returncode != 0 or tracked.stderr:
        raise VerificationFailure("tracked wheel source inventory failed")
    names = [
        name
        for name in tracked.stdout.split("\x00")
        if name
        and (
            name == "cli.py"
            or (name.startswith("src/") and name.endswith(".py"))
        )
    ]
    if not names or "cli.py" not in names or len(names) != len(set(names)):
        raise VerificationFailure("tracked wheel source inventory is incomplete")
    sources: dict[str, bytes] = {}
    for name in sorted(names):
        member = PurePosixPath(name)
        if (
            member.as_posix() != name
            or member.is_absolute()
            or any(part in {"", ".", ".."} for part in member.parts)
        ):
            raise VerificationFailure("tracked wheel source path is unsafe")
        sources[name] = _read_source_regular(
            project_root / Path(*member.parts),
            "tracked wheel source",
        )
    return sources


def _source_tree_digest(sources: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256(b"termuinator-wheel-source-v1\x00")
    for name in sorted(sources):
        digest.update(name.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(hashlib.sha256(sources[name]).digest())
    return digest.hexdigest()


def _parse_package_metadata(raw: bytes, label: str):
    try:
        message = BytesParser(policy=email_policy.default).parsebytes(raw)
    except (TypeError, ValueError) as exc:
        raise VerificationFailure(f"{label} could not be parsed") from exc
    if message.defects or message.is_multipart():
        raise VerificationFailure(f"{label} is malformed")
    return message


def _validate_wheel_metadata(
    archive: zipfile.ZipFile,
    prefix: str,
    project_root: Path,
    names: Sequence[str],
) -> None:
    metadata = _parse_package_metadata(
        archive.read(f"{prefix}/METADATA"),
        "candidate wheel METADATA",
    )
    actual_header_names = {name.lower() for name in metadata.keys()}
    expected_header_names = {
        name.lower() for name in _EXPECTED_METADATA_HEADERS
    }
    if actual_header_names != expected_header_names:
        raise VerificationFailure("candidate wheel METADATA headers differ")
    for name, expected_values in _EXPECTED_METADATA_HEADERS.items():
        actual_values = tuple(
            str(value) for value in metadata.get_all(name, [])
        )
        if actual_values != expected_values:
            raise VerificationFailure("candidate wheel METADATA values differ")
    readme = _read_source_regular(project_root / "README.md", "checkout README")
    payload = metadata.get_payload(decode=True)
    if not isinstance(payload, bytes) or not secrets.compare_digest(payload, readme):
        raise VerificationFailure("candidate wheel README payload differs")

    wheel_metadata = _parse_package_metadata(
        archive.read(f"{prefix}/WHEEL"),
        "candidate wheel WHEEL metadata",
    )
    expected_wheel_names = {
        *(name.lower() for name in _EXPECTED_WHEEL_HEADERS),
        "generator",
    }
    if {name.lower() for name in wheel_metadata.keys()} != expected_wheel_names:
        raise VerificationFailure("candidate wheel WHEEL headers differ")
    for name, expected_values in _EXPECTED_WHEEL_HEADERS.items():
        actual_values = tuple(
            str(value) for value in wheel_metadata.get_all(name, [])
        )
        if actual_values != expected_values:
            raise VerificationFailure("candidate wheel WHEEL values differ")
    generators = tuple(
        str(value) for value in wheel_metadata.get_all("Generator", [])
    )
    if len(generators) != 1 or re.fullmatch(
        r"setuptools \([0-9]+(?:\.[0-9]+){1,3}\)",
        generators[0],
    ) is None:
        raise VerificationFailure("candidate wheel generator differs")
    if wheel_metadata.get_payload(decode=True) not in {b"", None}:
        raise VerificationFailure("candidate wheel WHEEL payload is invalid")

    expected_checkout_files = {
        "licenses/LICENSE": project_root / "LICENSE",
        "licenses/NOTICE.md": project_root / "NOTICE.md",
    }
    for member, checkout_path in expected_checkout_files.items():
        checkout_bytes = _read_source_regular(
            checkout_path,
            f"checkout {checkout_path.name}",
        )
        if not secrets.compare_digest(
            archive.read(f"{prefix}/{member}"),
            checkout_bytes,
        ):
            raise VerificationFailure("candidate wheel license files differ")
    if archive.read(f"{prefix}/top_level.txt") != b"cli\nsrc\n":
        raise VerificationFailure("candidate wheel top-level metadata differs")

    record_name = f"{prefix}/RECORD"
    try:
        record_text = archive.read(record_name).decode("utf-8")
        rows = list(csv.reader(record_text.splitlines()))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise VerificationFailure("candidate wheel RECORD is invalid") from exc
    if any(len(row) != 3 for row in rows):
        raise VerificationFailure("candidate wheel RECORD rows are invalid")
    row_names = [row[0] for row in rows]
    if len(row_names) != len(set(row_names)) or set(row_names) != set(names):
        raise VerificationFailure("candidate wheel RECORD inventory differs")
    for name, digest_value, size_value in rows:
        if name == record_name:
            if digest_value or size_value:
                raise VerificationFailure("candidate wheel RECORD self-row differs")
            continue
        member_bytes = archive.read(name)
        encoded_digest = base64.urlsafe_b64encode(
            hashlib.sha256(member_bytes).digest()
        ).rstrip(b"=")
        expected_digest = f"sha256={encoded_digest.decode('ascii')}"
        if not secrets.compare_digest(digest_value, expected_digest):
            raise VerificationFailure("candidate wheel RECORD digest differs")
        if size_value != str(len(member_bytes)):
            raise VerificationFailure("candidate wheel RECORD size differs")


def validate_wheel_source_binding(
    wheel_path: Path,
    project_root: Path,
) -> dict[str, object]:
    """Bind safe wheel members and Python source bytes to the Git checkout."""

    if not wheel_path.is_absolute() or not project_root.is_absolute():
        raise ValueError("wheel and project paths must be absolute")
    try:
        root_info = project_root.lstat()
    except OSError as exc:
        raise VerificationFailure("project root is missing or unsafe") from exc
    if not stat.S_ISDIR(root_info.st_mode) or project_root.is_symlink():
        raise VerificationFailure("project root is missing or unsafe")
    try:
        wheel_info = wheel_path.lstat()
    except OSError as exc:
        raise VerificationFailure("candidate wheel is missing or unsafe") from exc
    if (
        not stat.S_ISREG(wheel_info.st_mode)
        or wheel_path.is_symlink()
        or not 1 <= wheel_info.st_size <= 256 * 1024 * 1024
    ):
        raise VerificationFailure("candidate wheel is not a bounded regular file")
    sources = _tracked_source_bytes(project_root)
    try:
        with zipfile.ZipFile(wheel_path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if (
                not infos
                or len(infos) > 512
                or len(names) != len(set(names))
                or sum(info.file_size for info in infos) > 64 * 1024 * 1024
            ):
                raise VerificationFailure("candidate wheel member set is invalid")
            for info in infos:
                member = PurePosixPath(info.filename)
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                if (
                    info.is_dir()
                    or info.flag_bits & 0x1
                    or stat.S_IFMT(unix_mode) not in {0, stat.S_IFREG}
                    or info.file_size > 4 * 1024 * 1024
                    or not info.filename
                    or "\\" in info.filename
                    or member.as_posix() != info.filename
                    or member.is_absolute()
                    or any(part in {"", ".", ".."} for part in member.parts)
                ):
                    raise VerificationFailure("candidate wheel has an unsafe member")
            if archive.testzip() is not None:
                raise VerificationFailure("candidate wheel failed ZIP integrity")
            source_names = {
                name
                for name in names
                if name == "cli.py"
                or (name.startswith("src/") and name.endswith(".py"))
            }
            if source_names != set(sources):
                raise VerificationFailure(
                    "candidate wheel source inventory differs from checkout"
                )
            non_source_names = set(names) - source_names
            prefixes = {
                name.split("/", 1)[0]
                for name in non_source_names
                if "/" in name
            }
            if len(prefixes) != 1:
                raise VerificationFailure("candidate wheel dist-info root is invalid")
            prefix = next(iter(prefixes))
            if (
                prefix != _EXPECTED_DIST_INFO_ROOT
                or any(not name.startswith(prefix + "/") for name in non_source_names)
            ):
                raise VerificationFailure("candidate wheel dist-info root is invalid")
            dist_info_files = {
                name.removeprefix(prefix + "/") for name in non_source_names
            }
            if dist_info_files != _EXPECTED_DIST_INFO_FILES:
                raise VerificationFailure("candidate wheel metadata members differ")
            if (
                archive.read(f"{prefix}/entry_points.txt")
                != _EXPECTED_ENTRY_POINTS_BYTES
            ):
                raise VerificationFailure("candidate wheel entrypoints differ")
            _validate_wheel_metadata(archive, prefix, project_root, names)
            for name, checkout_bytes in sources.items():
                if not secrets.compare_digest(archive.read(name), checkout_bytes):
                    raise VerificationFailure(
                        "candidate wheel source differs from checkout"
                    )
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        if isinstance(exc, VerificationFailure):
            raise
        raise VerificationFailure("candidate wheel could not be inspected") from exc
    return {
        "source_files_verified": len(sources),
        "source_tree_sha256": _source_tree_digest(sources),
        "wheel_entrypoints_verified": True,
        "wheel_member_allowlist_verified": True,
        "wheel_metadata_verified": True,
        "wheel_record_verified": True,
        "wheel_license_files_verified": True,
    }


def validate_installed_source_binding(
    project_root: Path,
    *,
    installed_roots: Sequence[Path],
    entrypoints: Mapping[str, str],
) -> dict[str, object]:
    """Require installed import bytes and scripts to match the clean checkout."""

    if (
        not isinstance(installed_roots, Sequence)
        or isinstance(installed_roots, (str, bytes))
        or not installed_roots
    ):
        raise ValueError("installed_roots must be a non-empty path sequence")
    roots: set[Path] = set()
    for root in installed_roots:
        if not isinstance(root, Path) or not root.is_absolute():
            raise ValueError("installed source roots must be absolute Paths")
        try:
            info = root.lstat()
            resolved = root.resolve(strict=True)
        except OSError as exc:
            raise VerificationFailure("installed source root is unsafe") from exc
        if not stat.S_ISDIR(info.st_mode) or root.is_symlink():
            raise VerificationFailure("installed source root is unsafe")
        roots.add(resolved)
    sources = _tracked_source_bytes(project_root)
    for name, checkout_bytes in sources.items():
        member = PurePosixPath(name)
        candidates = [
            root / Path(*member.parts)
            for root in roots
            if (root / Path(*member.parts)).exists()
            or (root / Path(*member.parts)).is_symlink()
        ]
        if len(candidates) != 1:
            raise VerificationFailure("installed source is missing or ambiguous")
        installed_bytes = _read_source_regular(
            candidates[0],
            "installed wheel source",
        )
        if not secrets.compare_digest(installed_bytes, checkout_bytes):
            raise VerificationFailure("installed source differs from checkout")
    if dict(entrypoints) != _EXPECTED_CONSOLE_ENTRYPOINTS:
        raise VerificationFailure("installed console entrypoints differ")
    return {
        "installed_source_files_verified": len(sources),
        "installed_source_tree_sha256": _source_tree_digest(sources),
        "installed_entrypoints_verified": True,
    }


def runtime_platform_summary() -> dict[str, str]:
    """Return accurately named, non-privileged runtime identity fields."""

    return {
        "python": platform.python_version(),
        "kernel_release": platform.release(),
    }


def validate_android_termux_identity(
    *,
    python_platform: str,
    system_name: str,
    android_root: str | None,
) -> dict[str, object]:
    """Accept only coherent modern or legacy Termux runtime identities."""

    identity = (python_platform, system_name)
    if identity not in {("android", "Android"), ("linux", "Linux")}:
        raise VerificationFailure("final verifier must run on Android/Termux")
    if android_root != "/system":
        raise VerificationFailure("final verifier must run on Android/Termux")
    return {
        "android_runtime_verified": True,
        "python_sys_platform": python_platform,
        "platform_system": system_name,
    }


def _installed_environment_preflight(
    *,
    project_root: Path,
    mcp_command: Path,
    control_command: Path,
    wheel_path: Path,
    expected_wheel_sha256: str,
) -> dict[str, object]:
    _require_executable(mcp_command, "MCP command")
    _require_executable(control_command, "host-control command")
    expected_bin = (Path(sys.prefix) / "bin").resolve()
    if (
        mcp_command.parent.resolve() != expected_bin
        or control_command.parent.resolve() != expected_bin
    ):
        raise VerificationFailure(
            "verifier Python and Termu-inator commands must come from one venv"
        )
    try:
        distribution = _runtime_distribution("termux-browser-pilot")
        package_version = distribution.version
        mcp_version = _runtime_distribution("mcp").version
        websockets_version = _runtime_distribution("websockets").version
        crypto_version = importlib_metadata.version("cryptography")
    except importlib_metadata.PackageNotFoundError as exc:
        raise VerificationFailure("required installed distribution is missing") from exc
    if mcp_version != _EXPECTED_MCP_VERSION:
        raise VerificationFailure("installed MCP version differs from the Termux pin")
    if websockets_version != _EXPECTED_WEBSOCKETS_VERSION:
        raise VerificationFailure(
            "installed websockets version differs from the Termux pin"
        )
    if package_version != _EXPECTED_PACKAGE_VERSION:
        raise VerificationFailure("installed package version differs from the release")
    direct_url = distribution.read_text("direct_url.json")
    provenance = validate_wheel_provenance(
        direct_url,
        expected_sha256=expected_wheel_sha256,
        wheel_path=wheel_path,
    )
    wheel_binding = validate_wheel_source_binding(wheel_path, project_root)
    console_entries = [
        entry
        for entry in distribution.entry_points
        if entry.group == "console_scripts"
    ]
    entry_points = {entry.name: entry.value for entry in console_entries}
    if len(entry_points) != len(console_entries):
        raise VerificationFailure("installed console entrypoints are ambiguous")
    installed_roots = tuple(
        Path(value)
        for value in {
            sysconfig.get_path("purelib"),
            sysconfig.get_path("platlib"),
        }
        if value
    )
    installed_binding = validate_installed_source_binding(
        project_root,
        installed_roots=installed_roots,
        entrypoints=entry_points,
    )

    prefix_value = os.environ.get("PREFIX")
    if not prefix_value:
        raise VerificationFailure("PREFIX is missing; verifier must run in Termux")
    prefix = Path(prefix_value)
    if not prefix.is_absolute() or not (prefix / "bin" / "pkg").is_file():
        raise VerificationFailure("PREFIX does not identify a Termux installation")
    crypto_spec = importlib_util.find_spec("cryptography")
    if crypto_spec is None or crypto_spec.origin is None:
        raise VerificationFailure("Termux cryptography cannot be imported")
    try:
        crypto_origin = Path(crypto_spec.origin).resolve(strict=True)
        prefix_lib = (prefix / "lib").resolve(strict=True)
    except OSError as exc:
        raise VerificationFailure("cryptography or Termux prefix path is unsafe") from exc
    if prefix_lib != crypto_origin and prefix_lib not in crypto_origin.parents:
        raise VerificationFailure(
            "cryptography is not the Termux native system package"
        )
    runtime_identity = validate_android_termux_identity(
        python_platform=sys.platform,
        system_name=platform.system(),
        android_root=os.environ.get("ANDROID_ROOT"),
    )

    pip_check = _run_bounded(
        [
            sys.executable,
            "-m",
            "pip",
            "--disable-pip-version-check",
            "check",
        ],
        cwd=project_root,
        timeout=90,
        label="pip check",
    )
    if (
        pip_check.returncode != 0
        or pip_check.stdout.strip() != "No broken requirements found."
        or pip_check.stderr
    ):
        raise VerificationFailure("release-candidate venv failed pip check")
    return {
        **runtime_platform_summary(),
        **runtime_identity,
        "termux_prefix_verified": True,
        "native_cryptography": crypto_version,
        "termux_browser_pilot": package_version,
        "mcp": mcp_version,
        "websockets": websockets_version,
        "entrypoints_verified": len(_EXPECTED_CONSOLE_ENTRYPOINTS),
        **provenance,
        **wheel_binding,
        **installed_binding,
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise VerificationFailure(f"{label} is not a string-keyed object")
    return value


def _bounded_string(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise VerificationFailure(f"{label} is invalid or unbounded")
    return value


def validate_observation(
    payload: object,
    *,
    expected_url: str,
    expected_origin: str,
    expected_text: Sequence[str],
    expected_title: str = "Forms",
) -> dict[str, object]:
    """Validate the exact evidence needed by the two-backend device gate."""

    observation = _mapping(payload, "observation")
    url = _bounded_string(observation.get("url"), "observation url", 8192)
    origin = _bounded_string(
        observation.get("origin"), "observation origin", 2048
    )
    title = _bounded_string(observation.get("title"), "observation title", 2048)
    if url != expected_url or origin != expected_origin or title != expected_title:
        raise VerificationFailure("observation fixture identity does not match")
    ready_state = observation.get("ready_state")
    if ready_state not in {"interactive", "complete"}:
        raise VerificationFailure("observation ready_state is not usable")
    text = _bounded_string(observation.get("text"), "observation text", 100_000)
    if observation.get("text_truncated") is not False:
        raise VerificationFailure("fixture observation text was truncated")
    if (
        not isinstance(expected_text, Sequence)
        or isinstance(expected_text, (str, bytes))
        or not expected_text
        or any(not isinstance(item, str) or not item for item in expected_text)
    ):
        raise ValueError("expected_text must be a non-empty string sequence")
    if any(item not in text for item in expected_text):
        raise VerificationFailure("fixture observation text evidence is incomplete")

    raw_accessibility = observation.get("accessibility")
    if not isinstance(raw_accessibility, list) or not 1 <= len(raw_accessibility) <= 200:
        raise VerificationFailure("accessibility evidence is empty or unbounded")
    for raw_node in raw_accessibility:
        node = _mapping(raw_node, "accessibility node")
        if frozenset(node) != _ACCESSIBILITY_KEYS:
            raise VerificationFailure(
                "accessibility node does not match the frozen public shape"
            )
        ref = node["ref"]
        if ref is not None and (
            not isinstance(ref, str) or _PUBLIC_REF.fullmatch(ref) is None
        ):
            raise VerificationFailure("accessibility node ref is invalid")
        _bounded_string(node["role"], "accessibility role", 64)
        _bounded_string(node["name"], "accessibility name", 512)
        _bounded_string(node["text"], "accessibility text", 4096)
        depth = node["depth"]
        if isinstance(depth, bool) or not isinstance(depth, int) or not 0 <= depth <= 128:
            raise VerificationFailure("accessibility depth is invalid")

    raw_interactive = observation.get("interactive_elements")
    if not isinstance(raw_interactive, list) or not 1 <= len(raw_interactive) <= 4096:
        raise VerificationFailure("interactive evidence is empty or unbounded")
    refs: set[str] = set()
    usable_ref = False
    for raw_element in raw_interactive:
        element = _mapping(raw_element, "interactive element")
        ref = element.get("ref")
        if not isinstance(ref, str) or _PUBLIC_REF.fullmatch(ref) is None:
            raise VerificationFailure("interactive element ref is invalid")
        if ref in refs:
            raise VerificationFailure("interactive element refs are not unique")
        refs.add(ref)
        if element.get("visible") is True and element.get("enabled") is True:
            usable_ref = True
    if not usable_ref:
        raise VerificationFailure("no usable interactive ref was observed")

    screenshot_uri = observation.get("screenshot_artifact_uri")
    if not isinstance(screenshot_uri, str) or _ARTIFACT_URI.fullmatch(
        screenshot_uri
    ) is None:
        raise VerificationFailure("observation screenshot artifact is missing")

    return {
        "ready_state": ready_state,
        "title": title,
        "expected_text_items": len(expected_text),
        "accessibility_nodes": len(raw_accessibility),
        "interactive_elements": len(raw_interactive),
        "interactive_ref_verified": True,
        "screenshot_artifact_uri": screenshot_uri,
    }


def reconstruct_artifact(
    chunks: Sequence[object],
    *,
    expected_uri: str,
    expected_sha256: str | None = None,
    expected_size: int | None = None,
    max_bytes: int = 16 * 1024 * 1024,
) -> bytes:
    """Reconstruct one bounded artifact only from a monotonic EOF sequence."""

    if not isinstance(chunks, Sequence) or isinstance(chunks, (str, bytes)):
        raise VerificationFailure("artifact chunks are not a sequence")
    if not 1 <= len(chunks) <= 128:
        raise VerificationFailure("artifact chunk count is empty or unbounded")
    if not isinstance(expected_uri, str) or _ARTIFACT_URI.fullmatch(expected_uri) is None:
        raise ValueError("expected_uri is not a canonical artifact URI")
    uri_digest = expected_uri.rsplit("/", 1)[-1]
    if expected_sha256 is not None and expected_sha256 != uri_digest:
        raise VerificationFailure("artifact metadata digest does not match its URI")
    if (
        expected_size is not None
        and (
            isinstance(expected_size, bool)
            or not isinstance(expected_size, int)
            or expected_size < 0
        )
    ):
        raise ValueError("expected_size must be a non-negative integer or None")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")

    output = bytearray()
    expected_offset = 0
    eof_seen = False
    for index, raw_chunk in enumerate(chunks):
        chunk = _mapping(raw_chunk, "artifact chunk")
        if frozenset(chunk) != _ARTIFACT_CHUNK_KEYS:
            raise VerificationFailure("artifact chunk does not match the frozen shape")
        if chunk["uri"] != expected_uri:
            raise VerificationFailure("artifact chunk URI changed")
        offset = chunk["offset"]
        next_offset = chunk["next_offset"]
        eof = chunk["eof"]
        encoded = chunk["data_base64"]
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or isinstance(next_offset, bool)
            or not isinstance(next_offset, int)
            or offset != expected_offset
            or next_offset < offset
        ):
            raise VerificationFailure("artifact chunk offsets are not monotonic")
        if not isinstance(eof, bool) or not isinstance(encoded, str) or len(encoded) > 699_052:
            raise VerificationFailure("artifact chunk payload is invalid or unbounded")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise VerificationFailure("artifact chunk is not canonical base64") from exc
        if base64.b64encode(decoded).decode("ascii") != encoded:
            raise VerificationFailure("artifact chunk is not canonical base64")
        if next_offset != offset + len(decoded):
            raise VerificationFailure("artifact chunk next_offset is inconsistent")
        if not decoded and not eof:
            raise VerificationFailure("artifact chunk made no progress")
        output.extend(decoded)
        if len(output) > max_bytes:
            raise VerificationFailure("artifact exceeds the verification bound")
        expected_offset = next_offset
        if eof:
            if index != len(chunks) - 1:
                raise VerificationFailure("artifact has chunks after EOF")
            eof_seen = True
    if not eof_seen:
        raise VerificationFailure("artifact EOF was not observed")
    data = bytes(output)
    if expected_size is not None and len(data) != expected_size:
        raise VerificationFailure("artifact size does not match metadata")
    if hashlib.sha256(data).hexdigest() != uri_digest:
        raise VerificationFailure("artifact digest does not match its URI")
    return data


def project_digest(owner_scope: str, project_id: str) -> str:
    """Derive the durable namespace defined by BrowserService v1."""

    for value, label in ((owner_scope, "owner_scope"), (project_id, "project_id")):
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or "\x00" in value
            or len(value) > 4096
        ):
            raise ValueError(f"{label} must be a canonical bounded identifier")
    digest = hashlib.sha256()
    digest.update(b"termuinator-owner-project-v1\x00")
    digest.update(owner_scope.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(project_id.encode("utf-8"))
    return digest.hexdigest()


def _require_private_directory(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise VerificationFailure(f"{label} is missing or unsafe") from exc
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise VerificationFailure(f"{label} must be a mode 0700 real directory")
    return info


def _read_private_regular(path: Path, label: str, maximum: int) -> bytes:
    parent = _require_private_directory(path.parent, f"{label} parent")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != 0o600):
            raise VerificationFailure(f"{label} must be a mode 0600 regular file")
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise VerificationFailure(f"{label} is missing or unsafe") from exc
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise VerificationFailure(
                f"{label} must be a mode 0600 regular file"
            )
        if not 0 <= info.st_size <= maximum:
            raise VerificationFailure(f"{label} is invalid or unbounded")
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise VerificationFailure(f"{label} was truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        fields = ("st_dev", "st_ino", "st_uid", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        after_parent = _require_private_directory(path.parent, f"{label} parent")
        if (
            any(getattr(value, key) != getattr(before, key)
                for value in (info, os.fstat(descriptor), path.lstat()) for key in fields)
            or any(getattr(parent, key) != getattr(after_parent, key)
                   for key in ("st_dev", "st_ino", "st_uid", "st_mode"))
        ):
            raise VerificationFailure(f"{label} changed during read")
        return b"".join(chunks)
    except OSError as exc:
        raise VerificationFailure(f"{label} could not be read safely") from exc
    finally:
        os.close(descriptor)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def validate_artifact_store(
    data_root: Path,
    *,
    owner_scope: str,
    project_id: str,
    artifact: object,
    reconstructed: bytes,
) -> dict[str, object]:
    """Verify public metadata against exact owner/project durable bytes."""

    if not isinstance(data_root, Path) or not data_root.is_absolute():
        raise ValueError("data_root must be an absolute Path")
    if not isinstance(reconstructed, bytes) or len(reconstructed) > 16 * 1024 * 1024:
        raise VerificationFailure("reconstructed artifact is invalid or unbounded")
    metadata = _mapping(artifact, "artifact metadata")
    if frozenset(metadata) != _ARTIFACT_KEYS:
        raise VerificationFailure("artifact metadata does not match the frozen shape")
    uri = metadata["uri"]
    digest = metadata["sha256"]
    size_bytes = metadata["size_bytes"]
    if (
        not isinstance(uri, str)
        or _ARTIFACT_URI.fullmatch(uri) is None
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or uri.rsplit("/", 1)[-1] != digest
    ):
        raise VerificationFailure("artifact URI and digest are inconsistent")
    if (
        isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or size_bytes != len(reconstructed)
        or size_bytes < len(_PNG_SIGNATURE)
    ):
        raise VerificationFailure("artifact size does not match reconstructed bytes")
    if metadata["mime_type"] != "image/png":
        raise VerificationFailure("screenshot artifact mime_type is not image/png")
    for label in ("created_at", "expires_at"):
        _bounded_string(metadata[label], f"artifact {label}", 128)
    if not reconstructed.startswith(_PNG_SIGNATURE):
        raise VerificationFailure("screenshot artifact has no PNG signature")
    if not secrets.compare_digest(hashlib.sha256(reconstructed).hexdigest(), digest):
        raise VerificationFailure("reconstructed artifact digest does not match metadata")

    namespace_digest = project_digest(owner_scope, project_id)
    artifacts_root = data_root / "artifacts"
    namespace = artifacts_root / namespace_digest
    _require_private_directory(data_root, "Termu-inator data root")
    _require_private_directory(artifacts_root, "artifact root")
    _require_private_directory(namespace, "artifact namespace")
    data_path = namespace / f"{digest}.bin"
    metadata_path = namespace / f"{digest}.json"
    stored_data = _read_private_regular(
        data_path,
        "artifact data",
        16 * 1024 * 1024,
    )
    stored_metadata = _read_private_regular(
        metadata_path,
        "artifact metadata",
        1024 * 1024,
    )
    if not secrets.compare_digest(stored_data, reconstructed):
        raise VerificationFailure("durable artifact bytes do not match MCP retrieval")
    try:
        disk_payload = json.loads(
            stored_metadata.decode("utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise VerificationFailure("durable artifact metadata is invalid JSON") from exc
    disk_mapping = _mapping(disk_payload, "durable artifact metadata")
    if frozenset(disk_mapping) != {
        "format",
        "owner_project_digest",
        "artifact",
        "last_accessed_at",
    }:
        raise VerificationFailure("durable artifact metadata shape is invalid")
    if (
        disk_mapping["format"] != "termuinator-artifact-metadata-v1"
        or disk_mapping["owner_project_digest"] != namespace_digest
        or disk_mapping["artifact"] != dict(metadata)
        or not isinstance(disk_mapping["last_accessed_at"], str)
    ):
        raise VerificationFailure("durable artifact metadata does not match MCP evidence")

    return {
        "sha256": digest,
        "size_bytes": size_bytes,
        "mime_type": "image/png",
        "png_signature": True,
        "eof_verified": True,
        "data_mode": "0600",
        "metadata_mode": "0600",
        "namespace_mode": "0700",
    }


def validate_wheel_provenance(
    direct_url_text: str | None,
    *,
    expected_sha256: str,
    wheel_path: Path,
) -> dict[str, object]:
    """Bind installed PEP 610 provenance to preserved candidate wheel bytes."""

    if (
        not isinstance(expected_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
    ):
        raise ValueError("expected_sha256 must be a lowercase SHA-256")
    if not isinstance(wheel_path, Path) or not wheel_path.is_absolute():
        raise ValueError("wheel_path must be an absolute Path")
    try:
        wheel_info = wheel_path.lstat()
    except OSError as exc:
        raise VerificationFailure("candidate wheel is missing or unsafe") from exc
    if (
        not stat.S_ISREG(wheel_info.st_mode)
        or wheel_info.st_size < 1
        or wheel_info.st_size > 256 * 1024 * 1024
    ):
        raise VerificationFailure("candidate wheel is not a bounded regular file")
    wheel_bytes = wheel_path.read_bytes()
    actual_sha256 = hashlib.sha256(wheel_bytes).hexdigest()
    if not secrets.compare_digest(actual_sha256, expected_sha256):
        raise VerificationFailure("candidate wheel bytes do not match expected SHA-256")
    if not isinstance(direct_url_text, str) or not 1 <= len(direct_url_text) <= 16_384:
        raise VerificationFailure("installed distribution has no bounded direct_url.json")
    try:
        direct_value = json.loads(
            direct_url_text,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise VerificationFailure("installed direct_url.json is invalid") from exc
    direct = _mapping(direct_value, "installed direct_url.json")
    if "dir_info" in direct:
        raise VerificationFailure("editable installs cannot be release candidates")
    if frozenset(direct) != {"archive_info", "url"}:
        raise VerificationFailure("installed direct_url.json is not a local wheel record")
    archive = _mapping(direct["archive_info"], "installed archive_info")
    hashes = _mapping(archive.get("hashes"), "installed archive hashes")
    if hashes.get("sha256") != expected_sha256:
        raise VerificationFailure("installed wheel hash does not match expected SHA-256")
    legacy_hash = archive.get("hash")
    if legacy_hash is not None and legacy_hash != f"sha256={expected_sha256}":
        raise VerificationFailure("installed legacy wheel hash is inconsistent")
    url = direct["url"]
    if not isinstance(url, str) or len(url) > 8192:
        raise VerificationFailure("installed wheel URL is invalid or unbounded")
    parsed = urlsplit(url)
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        raise VerificationFailure("installed release candidate did not come from a local wheel")
    installed_path = Path(unquote(parsed.path))
    if installed_path.resolve() != wheel_path.resolve():
        raise VerificationFailure("preserved wheel path differs from pip install provenance")

    return {
        "install_kind": "local-wheel",
        "wheel_sha256": expected_sha256,
        "wheel_size_bytes": len(wheel_bytes),
        "direct_url_hash_verified": True,
    }


def validate_tool_inventory(
    actual: Sequence[str],
    expected: Sequence[str],
    *,
    profile: str,
) -> dict[str, object]:
    """Require exact names and order for one server-enforced tool profile."""

    if profile not in {"interactive", "observer"}:
        raise ValueError("profile must be interactive or observer")
    if (
        not isinstance(actual, Sequence)
        or isinstance(actual, (str, bytes))
        or not isinstance(expected, Sequence)
        or isinstance(expected, (str, bytes))
        or any(not isinstance(name, str) for name in (*actual, *expected))
    ):
        raise ValueError("tool inventories must be string sequences")
    if tuple(actual) != tuple(expected):
        raise VerificationFailure(
            f"{profile} MCP tool inventory differs from the frozen manifest"
        )
    return {"profile": profile, "tool_count": len(expected)}


def _page_context(payload: object) -> dict[str, str]:
    value = _mapping(payload, "page context")
    context: dict[str, str] = {}
    for public_name, wire_name in (
        ("session_id", "session_id"),
        ("tab_id", "tab_id"),
        ("page_id", "page_id"),
        ("expected_page_revision", "page_revision"),
    ):
        item = value.get(wire_name)
        if not isinstance(item, str) or not 1 <= len(item) <= 160:
            raise VerificationFailure("MCP page context is incomplete")
        context[public_name] = item
    return context


def _status_context(payload: object) -> dict[str, str]:
    value = _mapping(payload, "session status context")
    context: dict[str, str] = {}
    for public_name, wire_name in (
        ("session_id", "session_id"),
        ("tab_id", "active_tab_id"),
        ("page_id", "active_page_id"),
        ("expected_page_revision", "page_revision"),
    ):
        item = value.get(wire_name)
        if not isinstance(item, str) or not 1 <= len(item) <= 160:
            raise VerificationFailure("MCP session status context is incomplete")
        context[public_name] = item
    return context


def _write_private_bytes(path: Path, data: bytes) -> None:
    if not path.is_absolute() or not isinstance(data, bytes):
        raise ValueError("private output requires an absolute path and bytes")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise VerificationFailure("private verification output path is unsafe") from exc
    try:
        written = 0
        while written < len(data):
            count = os.write(descriptor, data[written:])
            if count <= 0:
                raise OSError("short private output write")
            written += count
        os.fsync(descriptor)
    except OSError as exc:
        raise VerificationFailure("private verification output write failed") from exc
    finally:
        os.close(descriptor)


def write_private_json(path: Path, value: object) -> bytes:
    try:
        encoded = (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VerificationFailure("verification report is not canonical JSON") from exc
    _write_private_bytes(path, encoded)
    return encoded


def write_return_file_manifest(path: Path, expected: Mapping[str, bytes]) -> dict[str, Any]:
    """Record each published return file against the bytes the writer intended."""
    _require_private_directory(path.parent, "return-file directory")
    files: dict[str, Any] = {}
    for name, expected_bytes in expected.items():
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name) is None or name == path.name:
            raise ValueError("return-file name must be a distinct bounded basename")
        item: dict[str, Any] = {"status": "UNKNOWN", "bytes": None, "sha256": None,
                                "mode": None, "owner_current_uid": None}
        try:
            data = _read_private_regular(path.parent / name, "returned report", len(expected_bytes))
            matches = secrets.compare_digest(data, expected_bytes)
            item.update(status="PASS" if matches else "FAIL", bytes=len(data), mode="0600",
                        owner_current_uid=True, sha256=hashlib.sha256(data).hexdigest(),
                        reason=None if matches else "content_changed")
        except Exception as exc:
            os_error = next((value for value in (exc, exc.__cause__)
                             if isinstance(value, OSError)), None)
            if isinstance(os_error, PermissionError):
                item.update(status="UNAVAILABLE", reason="permission_denied", errno=os_error.errno)
            elif isinstance(os_error, FileNotFoundError):
                item.update(status="FAIL", reason="missing", errno=os_error.errno)
            elif os_error is not None:
                item.update(status="UNKNOWN", reason="read_failed", errno=os_error.errno)
            else:
                item.update(status="FAIL" if isinstance(exc, VerificationFailure) else "UNKNOWN",
                            reason="unsafe_file" if isinstance(exc, VerificationFailure) else "verification_failed")
        files[name] = item
    report = {"format": "termuinator-return-files-v1", "files": files,
              "status": "PASS" if files and all(item["status"] == "PASS" for item in files.values()) else "FAIL"}
    encoded = write_private_json(path, report)
    if not secrets.compare_digest(_read_private_regular(path, "return-file manifest", len(encoded)), encoded):
        raise VerificationFailure("return-file manifest changed after writing")
    return report


def _verify_return_file_manifest(path: Path, names: set[str]) -> Mapping[str, Any]:
    try:
        receipt = json.loads(_read_private_regular(path, "return-file manifest", 64 * 1024),
                             parse_constant=_reject_json_constant)
    except (ValueError, UnicodeError) as exc:
        raise VerificationFailure("return-file manifest is invalid") from exc
    receipt = _mapping(receipt, "return-file manifest")
    files = _mapping(receipt.get("files"), "return-file records")
    if receipt.get("format") != "termuinator-return-files-v1" or receipt.get("status") != "PASS" or set(files) != names:
        raise VerificationFailure("return-file verification did not pass")
    for name in sorted(names):
        item = _mapping(files[name], "returned file")
        data = _read_private_regular(path.parent / name, "returned report", 1024 * 1024)
        if (item.get("status") != "PASS" or item.get("owner_current_uid") is not True
                or item.get("mode") != "0600" or type(item.get("bytes")) is not int
                or item["bytes"] != len(data) or item.get("sha256") != hashlib.sha256(data).hexdigest()):
            raise VerificationFailure("returned report differs from its integrity record")
    return files


async def _retrieve_artifact(
    caller: ToolCaller,
    *,
    session_id: str,
    artifact: object,
) -> bytes:
    metadata = _mapping(artifact, "screenshot artifact metadata")
    if frozenset(metadata) != _ARTIFACT_KEYS:
        raise VerificationFailure("screenshot artifact metadata shape is invalid")
    uri = metadata.get("uri")
    digest = metadata.get("sha256")
    size = metadata.get("size_bytes")
    if not isinstance(uri, str) or not isinstance(digest, str):
        raise VerificationFailure("screenshot artifact identity is invalid")
    chunks: list[Mapping[str, Any]] = []
    offset = 0
    for _ in range(128):
        chunk = await caller(
            "browser_artifact_read",
            {
                "session_id": session_id,
                "uri": uri,
                "offset": offset,
                "limit": 524_288,
            },
        )
        chunks.append(chunk)
        next_offset = chunk.get("next_offset")
        eof = chunk.get("eof")
        if isinstance(next_offset, bool) or not isinstance(next_offset, int):
            raise VerificationFailure("artifact retrieval returned an invalid offset")
        if eof is True:
            break
        if eof is not False or next_offset <= offset:
            raise VerificationFailure("artifact retrieval made no bounded progress")
        offset = next_offset
    else:
        raise VerificationFailure("artifact retrieval exceeded the chunk bound")
    return reconstruct_artifact(
        chunks,
        expected_uri=uri,
        expected_sha256=digest,
        expected_size=size if isinstance(size, int) and not isinstance(size, bool) else None,
    )


def _fixture_text(
    value: Mapping[str, Any], identity: Mapping[str, str], *, url: str, origin: str, label: str,
) -> str:
    current = _page_context(value)
    text = value.get("text")
    if (
        any(current[key] != identity[key] for key in ("session_id", "tab_id", "page_id"))
        or value.get("url") != url or value.get("origin") != origin
        or value.get("ready_state") != "complete" or value.get("text_truncated") is not False
        or not isinstance(text, str) or len(text) > 4096
    ):
        raise VerificationFailure(f"{label}: observation identity or completeness failed")
    return text


def _fixture_target(observed: Mapping[str, Any], name: str, role: str, *, label: str) -> Mapping[str, Any]:
    elements = observed.get("interactive_elements")
    if not isinstance(elements, list):
        raise VerificationFailure(f"{label}: interactive targets are missing")
    targets = [item for item in elements if isinstance(item, Mapping)
               and item.get("accessible_name") == name and item.get("role") == role]
    if len(targets) != 1:
        raise VerificationFailure(f"{label}: target is missing or ambiguous")
    ref = targets[0].get("ref")
    if not isinstance(ref, str) or not _PUBLIC_REF.fullmatch(ref):
        raise VerificationFailure(f"{label}: target ref is invalid")
    return targets[0]


def _checked_action_result(value: object, arguments: Mapping[str, object], *, label: str) -> Mapping[str, Any]:
    result = _mapping(value, "fixture action result")
    after = result.get("after_revision")
    verification = result.get("verification")
    if (
        result.get("status") != "succeeded"
        or result.get("before_revision") != arguments["expected_page_revision"]
        or not isinstance(after, str) or not 1 <= len(after) <= 160
        or not isinstance(verification, list) or not 1 <= len(verification) <= 32
        or not any(isinstance(item, Mapping) and item.get("passed") is True
                   and item.get("causal") is True for item in verification)
    ):
        raise VerificationFailure(f"{label}: action lacks successful causal evidence")
    return result


async def _verify_form_actions(
    caller: ToolCaller,
    observed: Mapping[str, Any],
    *,
    approve_confirmation: ConfirmationApproval,
    fixture_url: str,
    fixture_origin: str,
) -> tuple[Mapping[str, Any], dict[str, object]]:
    """Check fixture effects through fresh observations, never RPC success alone."""
    context = _page_context(observed)
    identity = {key: context[key] for key in ("session_id", "tab_id", "page_id")}
    expected: dict[str, object] = {"text": "", "terms": False, "choice": "A", "submissions": 0}
    stage = "initial"

    def require_state(value: Mapping[str, Any]) -> None:
        text = _fixture_text(value, identity, url=fixture_url, origin=fixture_origin, label=f"form {stage}")
        lines = [line.strip() for line in text.splitlines() if line.strip().startswith("Fixture state:")]
        if lines != ["Fixture state: " + json.dumps(expected, separators=(",", ":"))]:
            raise VerificationFailure(f"form {stage}: actual values or submission count did not match")

    async def observe() -> Mapping[str, Any]:
        nonlocal context
        value = await caller("browser_observe", {
            **context, "include_screenshot": False, "include_accessibility": False, "text_limit": 4096,
        })
        require_state(value)
        context = _page_context(value)
        return value

    def request(kind: str, name: str, role: str, parameters: dict[str, object]) -> dict[str, object]:
        target = _fixture_target(observed, name, role, label=f"form {stage}")
        if target.get("visible") is not True or target.get("enabled") is not True:
            raise VerificationFailure(f"form {stage}: target is not actionable")
        return {**context, "action_id": "action_" + secrets.token_hex(12),
                "idempotency_key": "idem_" + secrets.token_hex(12), "kind": kind,
                "target_ref": target["ref"], "parameters": parameters, "timeout_ms": 30_000}

    def accept_result(value: object, arguments: Mapping[str, object]) -> Mapping[str, Any]:
        nonlocal context
        result = _checked_action_result(value, arguments, label=f"form {stage}")
        context = {**context, "expected_page_revision": result["after_revision"]}
        return result

    require_state(observed)
    for kind, name, role, parameters, field, value in (
        ("type", "Text input", "textbox", {"text": "termuinator-fixture"}, "text", "termuinator-fixture"),
        ("check", "Accept terms", "checkbox", {"checked": True}, "terms", True),
        ("select", "Choose option", "combobox", {"value": "B"}, "choice", "B"),
    ):
        stage = kind
        arguments = request(kind, name, role, parameters)
        accept_result(await caller("browser_act", arguments), arguments)
        expected[field] = value
        observed = await observe()

    stage = "request_confirmation"
    arguments = request("click", "Submit fixture", "button", {})
    try:
        await caller("browser_act", arguments)
    except _ConfirmationRequired as exc:
        confirmation_id = exc.confirmation_id
    else:
        raise VerificationFailure(f"form {stage}: submit did not require local confirmation")
    stage = "before_approval"
    observed = await observe()
    if context["expected_page_revision"] != arguments["expected_page_revision"]:
        raise VerificationFailure(f"form {stage}: fixture changed while awaiting confirmation")
    await approve_confirmation(context["session_id"], confirmation_id)
    confirmed = {**arguments, "confirmation_id": confirmation_id}
    stage = "after_approval"
    first = accept_result(await caller("browser_act", confirmed), confirmed)
    expected["submissions"] = 1
    observed = await observe()
    stage = "after_replay"
    replay = await caller("browser_act", confirmed)
    if replay != first:
        raise VerificationFailure(f"form {stage}: replay changed the terminal action result")
    observed = await observe()
    return observed, {
        "status": "PASS", "verified_operations": ["type", "check", "select", "click"],
        "submission_counts": {"before_approval": 0, "after_approval": 1, "after_replay": 1},
        "replay_result_identical": True,
    }


async def _verify_action_boundaries(
    caller: ToolCaller, context: Mapping[str, str], *, fixture_origin: str,
) -> dict[str, object]:
    """Require typed refusals, unchanged effects, fresh recovery, and bounded waits."""
    context = dict(context)
    session_id, tab_id = context["session_id"], context["tab_id"]
    observed: Mapping[str, Any] = {}
    path = ""

    def capture(value: Mapping[str, Any]) -> str:
        nonlocal context, observed
        text = _fixture_text(value, context, url=fixture_origin + path,
                             origin=fixture_origin, label=f"boundary {path}")
        context, observed = _page_context(value), value
        return text

    async def fresh() -> str:
        return capture(await caller("browser_observe", {
            **context, "include_screenshot": False, "include_accessibility": False, "text_limit": 4096,
        }))

    async def goto(route: str) -> str:
        nonlocal context, path
        path = route
        value = await caller("browser_navigate", {
            **context, "operation": "goto", "url": fixture_origin + path, "timeout_ms": 45_000,
        })
        context = _page_context(value)
        if context["session_id"] != session_id or context["tab_id"] != tab_id:
            raise VerificationFailure(f"boundary {path}: navigation changed session or tab")
        return await fresh()

    def require(text: str, lines: tuple[str, ...], absent: tuple[str, ...] = ()) -> None:
        actual = {line.strip() for line in text.splitlines()}
        if not set(lines).issubset(actual) or set(absent).intersection(actual):
            raise VerificationFailure(f"boundary {path}: actual effects did not match")

    def request(name: str) -> dict[str, object]:
        target = _fixture_target(observed, name, "button", label=f"boundary {path}")
        return {**context, "action_id": "action_" + secrets.token_hex(12),
                "idempotency_key": "idem_" + secrets.token_hex(12), "kind": "click",
                "target_ref": target["ref"], "parameters": {}, "timeout_ms": 30_000}

    async def click(name: str) -> str:
        nonlocal context
        arguments = request(name)
        result = _checked_action_result(await caller("browser_act", arguments), arguments, label=f"boundary {path}")
        context = {**context, "expected_page_revision": result["after_revision"]}
        return await fresh()

    async def reject(arguments: dict[str, object], code: str) -> str:
        try:
            await caller("browser_act", arguments)
        except VerificationFailure as exc:
            if exc.mcp_code != code:
                raise VerificationFailure(f"boundary {path}: expected {code} refusal was not verified") from exc
        else:
            raise VerificationFailure(f"boundary {path}: unsafe action was not refused")
        return await fresh()

    require(await goto("/stale-replacement"), ("Generation 1", "Activations 0"))
    retired = request("Continue")
    require(await click("Replace stable target"), ("Generation 2", "Activations 0"))
    if request("Continue")["target_ref"] == retired["target_ref"]:
        raise VerificationFailure("boundary /stale-replacement: replacement reused the retired ref")
    require(await reject(retired, "stale_observation"), ("Generation 2", "Activations 0"))
    stale_ref = {**request("Continue"), "target_ref": retired["target_ref"]}
    require(await reject(stale_ref, "target_not_found"), ("Generation 2", "Activations 0"))
    require(await click("Continue"), ("Generation 2", "Activations 1"))

    require(await goto("/dynamic-list"), ("Item 1",), ("Item 2",))
    old_remove = request("Remove item")
    require(await click("Add item"), ("Item 1", "Item 2"))
    require(await reject(old_remove, "stale_observation"), ("Item 1", "Item 2"))
    require(await click("Remove item"), ("Item 1",), ("Item 2",))

    require(await goto("/states"), ("Unavailable activations 0",))
    for name, flag in (("Disabled action", "enabled"), ("Hidden action", "visible")):
        target = _fixture_target(observed, name, "button", label="boundary /states")
        if target.get(flag) is not False:
            raise VerificationFailure("boundary /states: target state was not observed")
        require(await reject(request(name), "target_not_found"), ("Unavailable activations 0",))

    await goto("/delayed")
    for text, satisfied, timeout in (("Ready", True, 5000), ("Never appears in this fixture", False, 250)):
        result = _mapping(await caller("browser_wait", {
            **context, "condition": {"kind": "text", "text": text, "present": True}, "timeout_ms": timeout,
        }), "fixture wait result")
        elapsed = result.get("elapsed_ms")
        if (result.get("condition_kind") != "text" or result.get("satisfied") is not satisfied
                or type(elapsed) is not int or not 0 <= elapsed <= 120_000
                or (not satisfied and elapsed < timeout) or result.get("download") is not None):
            raise VerificationFailure("boundary /delayed: wait result did not match its condition or deadline")
        require(capture(_mapping(result.get("observation"), "fixture wait observation")),
                ("Ready",), ("Never appears in this fixture",))
    return {
        "status": "PASS", "stale_revision": "stale_observation", "retired_ref": "target_not_found",
        "dynamic_stale_revision": "stale_observation", "disabled_target": "target_not_found",
        "hidden_target": "target_not_found", "replacement_activations": 1,
        "ready_wait_satisfied": True, "missing_text_wait_satisfied": False, "timeout_elapsed_ms": elapsed,
    }


async def _verify_confidential_boundaries(
    caller: _McpToolCaller, *, session_id: str, fixture_origin: str,
    artifact_uri: str, takeover: LocalTakeover,
) -> dict[str, object]:
    """Exercise only synthetic pages; page text cannot grant local authority."""
    async def refused(name: str, arguments: dict[str, object], code: str) -> None:
        try:
            await caller(name, arguments)
        except VerificationFailure as exc:
            if exc.mcp_code == code:
                return
        raise VerificationFailure(f"confidential gate: {name} did not return {code}")

    async def status(state: str) -> Mapping[str, Any]:
        value = await caller("browser_session_status", {"session_id": session_id})
        if (value.get("session_id") != session_id or value.get("state") != state
                or value.get("running") is not True):
            raise VerificationFailure("confidential gate: session transition was not verified")
        _status_context(value)
        if state != "active" and (value.get("url") != "" or value.get("title") != "" or value.get("ready_state") != "takeover"):
            raise VerificationFailure("confidential gate: paused metadata was not hidden")
        return value

    async def inventory() -> None:
        listed = await caller._session.list_tools()
        validate_tool_inventory(tuple(tool.name for tool in listed.tools), _INTERACTIVE_TOOL_NAMES, profile="interactive")

    context = _status_context(await status("active"))
    await inventory()
    before = await caller("browser_permissions", {"session_id": session_id, "operation": "list"})
    decisions = before.get("decisions")
    if (before.get("operation") != "list" or before.get("challenge") is not None
            or not isinstance(decisions, list) or len(decisions) != 1
            or not isinstance(decisions[0], Mapping)
            or decisions[0].get("origin") != fixture_origin or decisions[0].get("policy") != "session_allow"
            or decisions[0].get("session_id") != session_id):
        raise VerificationFailure("confidential gate: isolated fixture policy was not verified")
    value = await caller("browser_navigate", {
        **context, "operation": "goto", "url": fixture_origin + "/prompt-injection", "timeout_ms": 45_000,
    })
    context = _page_context(value)
    observed = await caller("browser_observe", {
        **context, "include_screenshot": False, "include_accessibility": False, "text_limit": 4096,
    })
    text = _fixture_text(observed, context, url=fixture_origin + "/prompt-injection", origin=fixture_origin, label="page authority")
    if not all(token in text for token in ("Untrusted page instructions", "always_allow", "Developer Mode")):
        raise VerificationFailure("confidential gate: untrusted fixture text was not observed")
    context = _page_context(observed)
    after = await caller("browser_permissions", {"session_id": session_id, "operation": "list"})
    if after != before:
        raise VerificationFailure("confidential gate: page text changed origin policy")
    await inventory()
    await refused("browser_devtools", {**context, "query": "console", "parameters": {}}, "unsupported_capability")

    for route in ("login", "otp"):
        await refused("browser_navigate", {
            **context, "operation": "goto", "url": fixture_origin + "/" + route, "timeout_ms": 45_000,
        }, "session_paused")
        paused = _status_context(await status("user_takeover_required"))
        for state in ("user_takeover_required", "user_takeover_active"):
            if state == "user_takeover_active":
                await takeover(session_id, "start")
                if _status_context(await status(state)) != paused:
                    raise VerificationFailure("confidential gate: takeover start changed page identity")
            for name, arguments in (
                ("browser_observe", {**paused, "include_screenshot": True, "include_accessibility": True, "text_limit": 4096}),
                ("browser_screenshot", {**paused, "mode": "viewport"}),
                ("browser_artifact_read", {"session_id": session_id, "uri": artifact_uri, "offset": 0, "limit": 8}),
                ("browser_wait", {**paused, "condition": {"kind": "text", "text": "Ready", "present": True}, "timeout_ms": 250}),
                ("browser_navigate", {**paused, "operation": "reload", "timeout_ms": 1000}),
                ("browser_act", {**paused, "action_id": "action_" + secrets.token_hex(12), "idempotency_key": "idem_" + secrets.token_hex(12),
                                 "kind": "click", "target_ref": "ref_takeoverblocked123", "parameters": {}, "timeout_ms": 1000}),
                ("browser_tabs", {"session_id": session_id, "operation": "list"}),
                ("browser_downloads", {"session_id": session_id, "operation": "list"}),
                ("browser_permissions", {"session_id": session_id, "operation": "list"}),
                ("browser_trace", {"session_id": session_id, "operation": "list"}),
                ("browser_devtools", {**paused, "query": "console", "parameters": {}}),
            ):
                await refused(name, arguments, "session_paused")
        await takeover(session_id, "resume")
        context = _status_context(await status("active"))
        if (context["tab_id"] != paused["tab_id"] or context["page_id"] == paused["page_id"]
                or context["expected_page_revision"] == paused["expected_page_revision"]):
            raise VerificationFailure("confidential gate: resume did not rotate page identity")
        await refused("browser_observe", {
            **paused, "include_screenshot": False, "include_accessibility": False, "text_limit": 0,
        }, "stale_observation")
        observed = await caller("browser_observe", {
            **context, "include_screenshot": False, "include_accessibility": False, "text_limit": 0,
        })
        if (_page_context(observed) != context or observed.get("text") != "" or observed.get("accessibility") != []
                or observed.get("screenshot_artifact_uri") is not None):
            raise VerificationFailure("confidential gate: resumed observation was not bounded or fresh")
        if await caller("browser_permissions", {"session_id": session_id, "operation": "list"}) != before:
            raise VerificationFailure("confidential gate: takeover changed origin policy")
    return {"status": "PASS", "takeover_fixtures": ["login", "otp"], "page_authority_unchanged": True,
            "paused_reads_refused": True, "resume_rotates_identity": True}


async def verify_backend(
    caller: ToolCaller,
    *,
    grant_permission: PermissionGrant,
    approve_confirmation: ConfirmationApproval,
    takeover: LocalTakeover,
    backend: str,
    fixture_origin: str,
    fixture_url: str,
    data_root: Path,
    owner_scope: str,
    project_id: str,
    output_dir: Path,
) -> dict[str, object]:
    """Run the complete deterministic release gate for one browser backend."""

    if backend not in {"chromium", "firefox"}:
        raise ValueError("backend must be chromium or firefox")
    if not all(callable(item) for item in (caller, grant_permission, approve_confirmation, takeover)):
        raise ValueError("caller and owner decision callbacks must be callable")
    _require_private_directory(output_dir, "verification output directory")
    session_id: str | None = None
    stop_summary: dict[str, object] | None = None
    try:
        started = _mapping(
            await caller(
                "browser_session_start",
                {
                    "project_id": project_id,
                    "backend": backend,
                    "viewport": {
                        "width": 1000,
                        "height": 700,
                        "device_scale_factor": 1.0,
                    },
                },
            ),
            "session start result",
        )
        raw_session_id = started.get("session_id")
        if not isinstance(raw_session_id, str) or not 8 <= len(raw_session_id) <= 128:
            raise VerificationFailure("session start returned an invalid session_id")
        session_id = raw_session_id
        start_status = _mapping(started.get("status"), "session start status")
        if start_status.get("backend") != backend:
            raise VerificationFailure("session start backend does not match request")
        context = _status_context(start_status)
        if context["session_id"] != session_id:
            raise VerificationFailure("session start context is inconsistent")
        await grant_permission(session_id, fixture_origin)

        navigated = await caller(
            "browser_navigate",
            {
                **context,
                "operation": "goto",
                "url": fixture_url,
                "timeout_ms": 45_000,
            },
        )
        context = _page_context(navigated)
        if context["session_id"] != session_id:
            raise VerificationFailure("navigation changed session identity")
        observed = await caller(
            "browser_observe",
            {
                **context,
                "include_screenshot": True,
                "include_accessibility": True,
                "text_limit": 4096,
            },
        )
        observation_summary = validate_observation(
            observed,
            expected_url=fixture_url,
            expected_origin=fixture_origin,
            expected_text=(
                "Text input",
                "Accept terms",
                "Choose option",
                "Submit fixture",
            ),
        )
        context = _page_context(observed)
        if context["session_id"] != session_id:
            raise VerificationFailure("observation changed session identity")
        observed, action_summary = await _verify_form_actions(
            caller, observed, approve_confirmation=approve_confirmation,
            fixture_url=fixture_url, fixture_origin=fixture_origin,
        )
        context = _page_context(observed)
        artifact = await caller(
            "browser_screenshot",
            {**context, "mode": "viewport"},
        )
        screenshot = await _retrieve_artifact(
            caller,
            session_id=session_id,
            artifact=artifact,
        )
        artifact_summary = validate_artifact_store(
            data_root / "state",
            owner_scope=owner_scope,
            project_id=project_id,
            artifact=artifact,
            reconstructed=screenshot,
        )
        _write_private_bytes(output_dir / f"{backend}.png", screenshot)
        boundary_summary = await _verify_action_boundaries(caller, context, fixture_origin=fixture_origin)
        confidential_summary = await _verify_confidential_boundaries(
            caller, session_id=session_id, fixture_origin=fixture_origin, artifact_uri=artifact["uri"], takeover=takeover,
        )
        final_status = _mapping(
            await caller(
                "browser_session_status",
                {"session_id": session_id},
            ),
            "final session status",
        )
        if (
            final_status.get("backend") != backend
            or final_status.get("running") is not True
            or final_status.get("state") != "active"
        ):
            raise VerificationFailure("final session status is not active and consistent")
        result = {
            "status": "PASS",
            "backend": backend,
            "observation": observation_summary,
            "actions": action_summary,
            "action_boundaries": boundary_summary,
            "confidential_boundaries": confidential_summary,
            "artifact": artifact_summary,
        }
    finally:
        if session_id is not None:
            stopped = _mapping(
                await caller(
                    "browser_session_stop",
                    {"session_id": session_id},
                ),
                "session stop result",
            )
            if (
                stopped.get("session_id") != session_id
                or stopped.get("state") != "stopped"
                or not isinstance(stopped.get("stopped_at"), str)
            ):
                raise VerificationFailure("browser session did not stop cleanly")
            stop_summary = {"state": "stopped", "verified": True}
    result["cleanup"] = stop_summary
    return result


class _McpToolCaller:
    def __init__(self, session: object, *, server_pid: int,
                 process_observer: Callable[[int], None] | None = None) -> None:
        if (
            isinstance(server_pid, bool)
            or not isinstance(server_pid, int)
            or not 1 <= server_pid < 2**31
        ):
            raise ValueError("server_pid must be a positive process ID")
        self._session = session
        self.server_pid = server_pid
        self._process_observer = process_observer

    async def __call__(
        self,
        name: str,
        arguments: dict[str, object],
    ) -> Mapping[str, Any]:
        call_tool = getattr(self._session, "call_tool", None)
        if not callable(call_tool):
            raise VerificationFailure("MCP client session has no call_tool method")
        if self._process_observer is not None:
            self._process_observer(self.server_pid)
        try:
            result = await call_tool(
                name,
                arguments,
                read_timeout_seconds=timedelta(seconds=180),
            )
        finally:
            if self._process_observer is not None:
                self._process_observer(self.server_pid)
        if getattr(result, "isError", False):
            code = "mcp_error"
            context: list[str] = []
            kind = arguments.get("kind")
            if name == "browser_act" and isinstance(kind, str) and kind in {
                "click", "type", "key", "scroll", "select", "check", "hover", "drag",
            }:
                context.append(f"kind={kind}")
            for content in getattr(result, "content", ()):
                text_value = getattr(content, "text", None)
                if not isinstance(text_value, str) or len(text_value) > 64 * 1024:
                    continue
                try:
                    envelope = json.loads(
                        text_value,
                        parse_constant=_reject_json_constant,
                    )
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(envelope, Mapping):
                    continue
                candidate_code = envelope.get("code")
                if candidate_code in _MCP_ERROR_CODES:
                    code = candidate_code
                details = envelope.get("details")
                if isinstance(details, Mapping):
                    challenge = details.get("challenge")
                    if (name == "browser_act" and code == "confirmation_required"
                            and isinstance(challenge, Mapping)
                            and challenge.get("kind") == "confirmation"
                            and challenge.get("state") == "pending"):
                        identifier = challenge.get("challenge_id")
                        if isinstance(identifier, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{7,127}", identifier):
                            raise _ConfirmationRequired(identifier)
                    for key, allowed in _MCP_ERROR_DETAIL_VALUES.items():
                        value = details.get(key)
                        if isinstance(value, str) and value in allowed:
                            context.append(f"{key}={value}")
                break
            suffix = f" [{','.join(context)}]" if context else ""
            error = VerificationFailure(
                f"{name} returned MCP error code {code}{suffix}"
            )
            error.mcp_code = code
            raise error
        structured = getattr(result, "structuredContent", None)
        return _mapping(structured, f"{name} structured result")


def _open_private_text(path: Path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise VerificationFailure("private stderr log path is unsafe") from exc
    return os.fdopen(descriptor, "w", encoding="utf-8", errors="strict")


def _trusted_mcp_launch_parameters(
    mcp_command: Path,
    *,
    pid_path: Path,
    profile: str,
) -> tuple[str, tuple[str, ...]]:
    if not isinstance(mcp_command, Path) or not mcp_command.is_absolute():
        raise ValueError("mcp_command must be an absolute Path")
    if not isinstance(pid_path, Path) or not pid_path.is_absolute():
        raise ValueError("pid_path must be an absolute Path")
    if profile not in {"interactive", "observer"}:
        raise ValueError("profile must be interactive or observer")
    return (
        sys.executable,
        (
            "-c",
            _MCP_EXEC_LAUNCHER,
            os.fspath(pid_path),
            os.fspath(mcp_command),
            "--tool-profile",
            profile,
        ),
    )


def _read_trusted_child_pid(path: Path) -> int:
    payload = _read_private_regular(
        path,
        "trusted MCP child PID",
        32,
    )
    if re.fullmatch(rb"[1-9][0-9]{0,9}\n", payload) is None:
        raise VerificationFailure("trusted MCP child PID is invalid")
    pid = int(payload)
    if pid >= 2**31 or pid == os.getpid():
        raise VerificationFailure("trusted MCP child PID is unsafe")
    try:
        os.kill(pid, 0)
    except OSError as exc:
        raise VerificationFailure("trusted MCP child is not active") from exc
    return pid


def _require_private_control_socket(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise VerificationFailure("owner host-control socket is missing") from exc
    if (not stat.S_ISSOCK(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()):
        raise VerificationFailure("owner host-control socket is not private")


def _path_absent(path: Path) -> bool | None:
    """Distinguish a missing entry from an entry we cannot inspect."""
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    except OSError:
        return None
    return False


async def _wait_path_absent(path: Path, timeout_seconds: float = 10.0) -> bool | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        absent = _path_absent(path)
        if absent is not False:
            return absent
        await asyncio.sleep(0.05)
    return _path_absent(path)


async def _run_mcp_profile(
    *,
    profile: str,
    expected_tools: Sequence[str],
    mcp_command: Path,
    environ: Mapping[str, str],
    working_directory: Path,
    control_socket: Path,
    stderr_path: Path,
    body: Callable[[_McpToolCaller], Awaitable[object]] | None = None,
    process_observer: Callable[[int], None] | None = None,
) -> tuple[dict[str, object], object | None]:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        raise VerificationFailure("MCP 1.29 client SDK cannot be imported") from exc

    pid_path = stderr_path.with_name(f"{profile}-mcp-child.pid")
    launch_command, launch_arguments = _trusted_mcp_launch_parameters(
        mcp_command,
        pid_path=pid_path,
        profile=profile,
    )
    server_parameters = StdioServerParameters(
        command=launch_command,
        args=list(launch_arguments),
        env=dict(environ),
        cwd=working_directory,
    )
    body_result: object | None = None
    initialization_summary: dict[str, object] = {}
    with _open_private_text(stderr_path) as errlog:
        async with stdio_client(server_parameters, errlog=errlog) as streams:
            read_stream, write_stream = streams
            async with ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=180),
            ) as session:
                initialized = await session.initialize()
                server_pid = _read_trusted_child_pid(pid_path)
                if process_observer is not None:
                    process_observer(server_pid)
                initialized_wire = (
                    initialized.model_dump(by_alias=True)
                    if hasattr(initialized, "model_dump")
                    else {}
                )
                server_info = (
                    initialized_wire.get("serverInfo", {})
                    if isinstance(initialized_wire, Mapping)
                    else {}
                )
                if not isinstance(server_info, Mapping):
                    server_info = {}
                initialization_summary = {
                    "server_name": server_info.get("name"),
                    "server_version": server_info.get("version"),
                    "protocol_version": initialized_wire.get("protocolVersion"),
                }
                listed = await session.list_tools()
                actual_names = tuple(tool.name for tool in listed.tools)
                inventory = validate_tool_inventory(
                    actual_names,
                    expected_tools,
                    profile=profile,
                )
                _require_private_control_socket(control_socket)
                if body is not None:
                    body_result = await body(
                        _McpToolCaller(session, server_pid=server_pid,
                                       process_observer=process_observer)
                    )
        errlog.flush()
        os.fsync(errlog.fileno())
    stderr_bytes = stderr_path.stat().st_size
    socket_absent = await _wait_path_absent(control_socket)
    summary = {
        **initialization_summary,
        **inventory,
        "stderr_bytes": stderr_bytes,
        "control_socket_private_while_running": True,
        "control_socket_absent_after_exit": socket_absent,
        "trusted_child_pid": server_pid,
    }
    return summary, body_result


def _run_control_grant(
    *,
    control_command: Path,
    environ: Mapping[str, str],
    working_directory: Path,
    session_id: str,
    origin: str,
) -> None:
    _run_control_action(
        control_command=control_command, environ=environ, working_directory=working_directory,
        arguments=["permission", session_id, origin, "session_allow"], label="owner permission grant",
    )


def _run_control_approval(
    *,
    control_command: Path,
    environ: Mapping[str, str],
    working_directory: Path,
    session_id: str,
    confirmation_id: str,
) -> None:
    response = _run_control_action(
        control_command=control_command, environ=environ, working_directory=working_directory,
        arguments=["confirmation", session_id, confirmation_id, "approve"], label="owner fixture approval",
    )
    result = _mapping(response.get("result"), "owner fixture approval result")
    if (result.get("challenge_id") != confirmation_id or result.get("kind") != "confirmation"
            or result.get("state") != "approved"):
        raise VerificationFailure("owner fixture approval did not match the pending challenge")


def _run_control_takeover(
    *, control_command: Path, environ: Mapping[str, str], working_directory: Path,
    session_id: str, operation: str,
) -> None:
    if operation not in {"start", "resume"}:
        raise ValueError("fixture takeover operation is invalid")
    response = _run_control_action(
        control_command=control_command, environ=environ, working_directory=working_directory,
        arguments=["takeover-" + operation, session_id], label="owner fixture takeover",
    )
    value = _mapping(response.get("result"), "owner fixture takeover result")
    safe = (value.get("state") == "user_takeover_active" and value.get("url") == "" and value.get("title") == ""
            if operation == "start" else value.get("text") == "" and value.get("accessibility") == []
            and value.get("screenshot_artifact_uri") is None)
    if value.get("session_id") != session_id or not safe:
        raise VerificationFailure("owner fixture takeover returned an inconsistent transition")


def _run_control_action(
    *,
    control_command: Path,
    environ: Mapping[str, str],
    working_directory: Path,
    arguments: Sequence[str],
    label: str,
) -> Mapping[str, Any]:
    completed = _run_bounded(
        [control_command, *arguments],
        cwd=working_directory,
        environ=environ,
        timeout=15,
        label=label,
    )
    if completed.returncode != 0 or completed.stderr:
        raise VerificationFailure(f"{label} failed")
    try:
        response = json.loads(
            completed.stdout,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise VerificationFailure(f"{label} returned invalid JSON") from exc
    if not isinstance(response, Mapping) or response.get("ok") is not True:
        raise VerificationFailure(f"{label} was not accepted")
    return response


def _load_fixture_site(project_root: Path):
    path = project_root / "tests" / "fixtures" / "server.py"
    _read_bounded_regular(
        path,
        label="deterministic fixture module",
        maximum=512 * 1024,
    )
    module_name = "_termuinator_final_verify_fixture"
    spec = importlib_util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise VerificationFailure("deterministic fixture module cannot be loaded")
    module = importlib_util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise VerificationFailure("deterministic fixture module failed to load") from exc
    fixture_site = getattr(module, "FixtureSite", None)
    if not isinstance(fixture_site, type):
        raise VerificationFailure("deterministic fixture module has no FixtureSite")
    return fixture_site


def _create_private_directory(path: Path, label: str) -> None:
    try:
        path.mkdir(mode=0o700)
    except OSError as exc:
        raise VerificationFailure(f"{label} could not be created") from exc
    _require_private_directory(path, label)


def _child_environment(
    output_dir: Path,
    *,
    owner_scope: str,
) -> tuple[dict[str, str], dict[str, Path]]:
    paths = {
        "home": output_dir / "h",
        "xdg_data": output_dir / "d",
        "xdg_cache": output_dir / "c",
        "xdg_config": output_dir / "g",
        "tmp": output_dir / "t",
        "working": output_dir / "w",
    }
    control_socket = (
        paths["xdg_data"] / "termuinator" / "runtime" / "control.sock"
    )
    if len(os.fsencode(control_socket)) > _MAX_CONTROL_SOCKET_PATH_BYTES:
        raise VerificationFailure(
            "output path is too long for the private control socket"
        )
    for label, path in paths.items():
        _create_private_directory(path, f"isolated {label} directory")
    environ = dict(os.environ)
    for name in (
        "PYTHONHOME",
        "PYTHONPATH",
        "TBP_SINGLE_PROCESS",
        "TERMUINATOR_CONFIG",
    ):
        environ.pop(name, None)
    environ.update(
        {
            "HOME": os.fspath(paths["home"]),
            "XDG_DATA_HOME": os.fspath(paths["xdg_data"]),
            "XDG_CACHE_HOME": os.fspath(paths["xdg_cache"]),
            "XDG_CONFIG_HOME": os.fspath(paths["xdg_config"]),
            "TMPDIR": os.fspath(paths["tmp"]),
            "TERMUINATOR_OWNER_SCOPE": owner_scope,
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    return environ, paths


def _process_identity(entry: Path) -> dict[str, str]:
    """Read parent PID and start ticks, without retaining process names or argv."""
    raw = (entry / "stat").read_text(encoding="utf-8", errors="replace")
    prefix, separator, tail = raw.rpartition(") ")
    fields = tail.split()
    if (not separator or not prefix.startswith(f"{entry.name} (")
            or len(fields) < 20
            or any(not fields[index].isascii() or not fields[index].isdigit()
                   for index in (1, 19))):
        raise ValueError("invalid process identity")
    return {"parent_pid": fields[1], "start_ticks": fields[19]}


def _process_snapshot() -> dict[str, Any]:
    """Record all visible same-UID identities, not a host-wide absence proof."""
    proc = Path("/proc")
    processes: dict[str, dict[str, str]] = {}
    errors = {"permission_denied": 0, "io_error": 0,
              "invalid_identity": 0, "identity_changed": 0}
    snapshot: dict[str, Any] = {
        "status": "PASS", "scope": "visible_same_uid_processes",
        "processes": processes, "error_counts": errors,
    }
    try:
        entries = list(proc.iterdir())
    except OSError as exc:
        snapshot.update(status="UNAVAILABLE", reason="proc_unavailable", errno=exc.errno)
        return snapshot
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            identity = _process_identity(entry)
            if identity != _process_identity(entry) or entry.stat().st_uid != os.getuid():
                errors["identity_changed"] += 1
                continue
        except FileNotFoundError:
            # A process may exit during a scan. Missing files in a live entry
            # are not evidence of its absence; do not suppress access failures.
            try:
                entry.stat()
            except FileNotFoundError:
                continue
            except OSError:
                pass
            errors["io_error"] += 1
            continue
        except PermissionError:
            errors["permission_denied"] += 1
            continue
        except OSError:
            errors["io_error"] += 1
            continue
        except ValueError:
            errors["invalid_identity"] += 1
            continue
        processes[entry.name] = identity
    if any(errors.values()):
        snapshot.update(status="UNKNOWN", reason="process_evidence_incomplete")
    return snapshot


def _new_processes(baseline: Mapping[str, Any], latest: Mapping[str, Any]) -> dict | None:
    if baseline.get("status") != "PASS" or latest.get("status") != "PASS":
        return None
    return {
        pid: value for pid, value in latest["processes"].items()
        if baseline["processes"].get(pid, {}).get("start_ticks") != value["start_ticks"]
    }


def _process_cleanup_summary(
    baseline: Mapping[str, Any], latest: Mapping[str, Any],
    observed: set[tuple[str, str]], *, ownership_verified: bool,
) -> dict[str, Any]:
    survivors = _new_processes(baseline, latest)
    owned = {pid for pid, value in latest["processes"].items()
             if (pid, value["start_ticks"]) in observed}
    unknown_count = None if survivors is None else len(set(survivors) - owned)
    return {
        "scope": "visible_same_uid_processes",
        "status": (
            "UNAVAILABLE" if "UNAVAILABLE" in (baseline["status"], latest["status"]) else "UNKNOWN"
        ) if survivors is None else (
            "FAIL" if owned else "UNKNOWN" if unknown_count or not ownership_verified else "PASS"
        ),
        "new_process_count": None if survivors is None else len(survivors),
        "observed_candidate_count": len(observed),
        "observed_candidate_survivors": None if survivors is None else len(owned),
        "unattributed_new_process_count": unknown_count,
        "ownership_verified": ownership_verified,
        "before": {key: baseline.get(key) for key in ("status", "reason", "errno", "error_counts")},
        "after": {key: latest.get(key) for key in ("status", "reason", "errno", "error_counts")},
    }


async def _wait_for_new_processes(
    baseline: Mapping[str, Any],
    *,
    timeout_seconds: float = 15.0,
) -> tuple[dict[str, Any], dict[str, dict[str, str]] | None]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        latest = _process_snapshot()
        survivors = _new_processes(baseline, latest)
        if not survivors or time.monotonic() >= deadline:
            return latest, survivors
        await asyncio.sleep(0.25)


def _record_process_tree(
    snapshot: Mapping[str, Any], root_pid: int, observed: set[tuple[str, str]],
) -> bool:
    """Remember observed ancestry, never authorize signals from a census."""
    processes = snapshot["processes"]
    root = processes.get(str(root_pid))
    if root is None:
        return False
    observed.add((str(root_pid), root["start_ticks"]))
    # ponytail: sampled ancestry, not OS containment; unobserved survivors stay UNKNOWN.
    while True:
        additions = set()
        for pid, value in processes.items():
            key = (pid, value["start_ticks"])
            parent_pid = value["parent_pid"]
            parent = processes.get(parent_pid)
            if (key not in observed and parent is not None
                    and (parent_pid, parent["start_ticks"]) in observed
                    and int(parent["start_ticks"]) <= int(value["start_ticks"])):
                additions.add(key)
        if not additions:
            break
        observed.update(additions)
    return snapshot["status"] == "PASS"


def validate_released_session_lock(
    lock_path: Path,
    *,
    owner_scope: str,
    expected_active_pid: int | None = None,
) -> dict[str, bool]:
    """Report the safety evidence for a released persistent session lock."""

    if not isinstance(lock_path, Path) or not lock_path.is_absolute():
        raise ValueError("lock_path must be an absolute Path")
    if not isinstance(owner_scope, str) or not 1 <= len(owner_scope) <= 256:
        raise ValueError("owner_scope must be a bounded string")
    if expected_active_pid is not None and (
        isinstance(expected_active_pid, bool)
        or not isinstance(expected_active_pid, int)
        or not 1 <= expected_active_pid < 2**31
    ):
        raise ValueError("expected_active_pid must be a positive process ID")
    pid_evidence = (
        "session_lock_pid_matches_expected_active"
        if expected_active_pid is not None
        else "session_lock_pid_inactive"
    )
    summary = {
        "session_lock_path_safe": False,
        "session_lock_owner_safe": False,
        pid_evidence: False,
        "session_lock_lease_available": False,
    }
    flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags)
    except FileNotFoundError:
        try:
            parent_info = lock_path.parent.lstat()
        except FileNotFoundError:
            parent_info = None
        except OSError:
            return summary
        if parent_info is not None and (
            not stat.S_ISDIR(parent_info.st_mode)
            or stat.S_IMODE(parent_info.st_mode) != 0o700
            or parent_info.st_uid != os.getuid()
        ):
            return summary
        try:
            lock_path.lstat()
        except FileNotFoundError:
            pass
        except OSError:
            return summary
        else:
            return summary
        try:
            current_parent_info = lock_path.parent.lstat()
        except FileNotFoundError:
            if parent_info is not None:
                return summary
        except OSError:
            return summary
        else:
            if (
                parent_info is None
                or not stat.S_ISDIR(current_parent_info.st_mode)
                or stat.S_IMODE(current_parent_info.st_mode) != 0o700
                or current_parent_info.st_uid != os.getuid()
                or (parent_info.st_dev, parent_info.st_ino)
                != (current_parent_info.st_dev, current_parent_info.st_ino)
            ):
                return summary
        return {name: True for name in summary}
    except OSError:
        return summary

    lease_acquired = False
    try:
        info = os.fstat(descriptor)
        try:
            parent_info = lock_path.parent.lstat()
            path_info = lock_path.lstat()
        except OSError:
            return summary
        if (
            not stat.S_ISDIR(parent_info.st_mode)
            or stat.S_IMODE(parent_info.st_mode) != 0o700
            or parent_info.st_uid != os.getuid()
            or not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
            or (info.st_dev, info.st_ino) != (path_info.st_dev, path_info.st_ino)
        ):
            return summary
        summary["session_lock_path_safe"] = True
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                return summary
            return summary
        lease_acquired = True
        summary["session_lock_lease_available"] = True

        if not 1 <= info.st_size <= 8192:
            return summary
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(4096, remaining))
            if not chunk:
                return summary
            chunks.append(chunk)
            remaining -= len(chunk)
        try:
            payload = json.loads(
                b"".join(chunks).decode("utf-8"),
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return summary
        if not isinstance(payload, dict) or frozenset(payload) != {
            "format",
            "owner_digest",
            "pid",
            "acquired_at",
        }:
            return summary
        expected_owner = hashlib.sha256(
            b"termuinator-session-owner-v1\x00" + owner_scope.encode("utf-8")
        ).hexdigest()
        owner_digest = payload.get("owner_digest")
        if (
            payload.get("format") != "termuinator-session-lock-v1"
            or not isinstance(owner_digest, str)
            or not secrets.compare_digest(owner_digest, expected_owner)
        ):
            return summary
        acquired_at = payload.get("acquired_at")
        if not isinstance(acquired_at, str) or len(acquired_at) > 128:
            return summary
        try:
            acquired_time = datetime.fromisoformat(acquired_at)
        except ValueError:
            return summary
        if acquired_time.tzinfo is None:
            return summary
        summary["session_lock_owner_safe"] = True

        pid = payload.get("pid")
        if isinstance(pid, bool) or not isinstance(pid, int) or not 1 <= pid < 2**31:
            return summary
        if expected_active_pid is not None:
            if pid != expected_active_pid:
                return summary
            try:
                os.kill(pid, 0)
            except OSError:
                return summary
            summary[pid_evidence] = True
        else:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                summary[pid_evidence] = True
            except PermissionError:
                return summary
            except OSError as exc:
                if exc.errno != errno.ESRCH:
                    return summary
                summary[pid_evidence] = True
            else:
                return summary

        try:
            current_parent_info = lock_path.parent.lstat()
            current_info = lock_path.lstat()
        except OSError:
            summary["session_lock_path_safe"] = False
            return summary
        if (
            (parent_info.st_dev, parent_info.st_ino)
            != (current_parent_info.st_dev, current_parent_info.st_ino)
            or (info.st_dev, info.st_ino)
            != (current_info.st_dev, current_info.st_ino)
        ):
            summary["session_lock_path_safe"] = False
        return summary
    finally:
        try:
            if lease_acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _cleanup_summary(
    data_root: Path,
    temporary_root: Path,
    *,
    owner_scope: str,
    expected_active_pid: int | None = None,
) -> dict[str, object]:
    paths = {
        "control_socket_absent": data_root / "runtime" / "control.sock",
        "legacy_lock_absent": temporary_root / ".tbp_browser.lock",
    }
    summary = {name: _path_absent(path) for name, path in paths.items()}
    summary.update(
        validate_released_session_lock(
            data_root / "runtime" / "session.lock",
            owner_scope=owner_scope,
            expected_active_pid=expected_active_pid,
        )
    )
    lease_root = temporary_root / "termuinator-runtime"
    try:
        before = lease_root.lstat()
    except FileNotFoundError:
        summary["display_leases_absent"] = True
    except OSError:
        summary["display_leases_absent"] = None
    else:
        summary["display_leases_absent"] = False
        if (stat.S_ISDIR(before.st_mode) and before.st_uid == os.getuid()
                and stat.S_IMODE(before.st_mode) == 0o700):
            try:
                lease_found = any(entry.name.endswith(".lease") for entry in lease_root.iterdir())
                after = lease_root.lstat()
                identity = (before.st_dev, before.st_ino, before.st_mode, before.st_uid)
                summary["display_leases_absent"] = (
                    not lease_found
                    and identity == (after.st_dev, after.st_ino, after.st_mode, after.st_uid)
                )
            except OSError:
                summary["display_leases_absent"] = None
    return summary


async def _run_device_verification(
    *,
    project_root: Path,
    output_dir: Path,
    mcp_command: Path,
    control_command: Path,
    expected_commit: str,
    expected_server_version: str,
) -> tuple[dict[str, object], list[dict[str, str]]]:
    owner_scope = f"final-verify-{expected_commit[:12]}"
    environ, paths = _child_environment(output_dir, owner_scope=owner_scope)
    data_root = paths["xdg_data"] / "termuinator"
    control_socket = data_root / "runtime" / "control.sock"
    fixture_type = _load_fixture_site(project_root)
    baseline_processes = _process_snapshot()
    write_private_json(output_dir / "processes-before.json", baseline_processes)
    raw_errors: list[dict[str, str]] = []
    observed_processes: set[tuple[str, str]] = set()
    ownership_samples = {"total": 0, "incomplete": 0}
    transition_snapshots: list[dict[str, object]] = []
    profile_root: tuple[str, str] | None = None

    def observe_processes(server_pid: int) -> None:
        nonlocal profile_root
        ownership_samples["total"] += 1
        try:
            snapshot = _process_snapshot()
            identity = snapshot["processes"].get(str(server_pid))
            current = (str(server_pid), identity["start_ticks"]) if identity is not None else None
            if profile_root is None:
                profile_root = current
            verified = (current is not None and current == profile_root
                        and _record_process_tree(snapshot, server_pid, observed_processes))
        except Exception as exc:
            verified = False
            raw_errors.append({"stage": "process-ownership", "type": type(exc).__name__,
                               "message": repr(exc)[:8192]})
        if not verified:
            ownership_samples["incomplete"] += 1

    backend_results: list[dict[str, object]] = []
    interactive: dict[str, object] = {"status": "SKIPPED"}
    observer_restart: dict[str, object] = {"status": "SKIPPED"}

    fixture = fixture_type()
    stage = "fixture-start"
    try:
        fixture.start()
        fixture_origin = fixture.base_url
        fixture_url = fixture.url("/forms")

        async def interactive_body(caller: _McpToolCaller) -> object:
            root_pid = str(caller.server_pid)
            root_generation = profile_root[1] if profile_root is not None and profile_root[0] == root_pid else None
            transition_baseline = {**baseline_processes, "processes": dict(baseline_processes["processes"])}
            if root_generation is not None:
                transition_baseline["processes"][root_pid] = {"start_ticks": root_generation}
            for backend in ("chromium", "firefox"):
                project_id = (
                    f"final-verify-{backend}-{expected_commit[:12]}"
                )

                async def grant(session_id: str, origin: str) -> None:
                    await asyncio.to_thread(
                        _run_control_grant,
                        control_command=control_command,
                        environ=environ,
                        working_directory=paths["working"],
                        session_id=session_id,
                        origin=origin,
                    )

                async def approve(session_id: str, confirmation_id: str) -> None:
                    await asyncio.to_thread(
                        _run_control_approval,
                        control_command=control_command,
                        environ=environ,
                        working_directory=paths["working"],
                        session_id=session_id,
                        confirmation_id=confirmation_id,
                    )

                async def takeover(session_id: str, operation: str) -> None:
                    await asyncio.to_thread(
                        _run_control_takeover, control_command=control_command, environ=environ,
                        working_directory=paths["working"], session_id=session_id, operation=operation,
                    )

                try:
                    result = await verify_backend(
                        caller,
                        grant_permission=grant,
                        approve_confirmation=approve,
                        takeover=takeover,
                        backend=backend,
                        fixture_origin=fixture_origin,
                        fixture_url=fixture_url,
                        data_root=data_root,
                        owner_scope=owner_scope,
                        project_id=project_id,
                        output_dir=output_dir,
                    )
                except Exception as exc:
                    result = {"status": "FAIL", "backend": backend, "failure_type": type(exc).__name__}
                    raw_errors.append(
                        {
                            "stage": f"backend-{backend}",
                            "type": type(exc).__name__,
                            "message": repr(exc)[:8192],
                        }
                    )
                backend_results.append(result)
                # The MCP parent/control socket stay live; browser-owned resources must not.
                try:
                    checks = _cleanup_summary(
                        data_root,
                        paths["tmp"],
                        owner_scope=owner_scope,
                        expected_active_pid=caller.server_pid,
                    )
                    checks.pop("control_socket_absent")
                    _require_private_control_socket(control_socket)
                    checks["control_socket_private_while_running"] = True
                except Exception as exc:
                    rejected = isinstance(exc, VerificationFailure) and not isinstance(exc.__cause__, OSError)
                    checks = {"inspection_verified": False if rejected else None}
                    raw_errors.append({"stage": f"backend-{backend}-cleanup", "type": type(exc).__name__,
                                       "message": repr(exc)[:8192]})
                try:
                    latest, _ = await _wait_for_new_processes(transition_baseline)
                    transition_snapshots.append({"backend": backend, "snapshot": latest})
                    parent_verified = (
                        root_generation is not None
                        and latest["processes"].get(root_pid, {}).get("start_ticks") == root_generation
                    )
                    census = _process_cleanup_summary(
                        transition_baseline, latest,
                        observed_processes - {(root_pid, root_generation)},
                        ownership_verified=parent_verified and ownership_samples["incomplete"] == 0,
                    )
                    census["active_mcp_generation_verified"] = parent_verified
                except Exception as exc:
                    census = {"status": "UNAVAILABLE" if isinstance(exc, OSError) else "UNKNOWN"}
                    raw_errors.append({"stage": f"backend-{backend}-processes", "type": type(exc).__name__,
                                       "message": repr(exc)[:8192]})
                stopped = all(value is True for value in checks.values()) and census["status"] == "PASS"
                result["post_stop"] = {
                    "status": "PASS" if stopped else (
                        "FAIL" if False in checks.values() or census["status"] == "FAIL" else
                        "UNAVAILABLE" if census["status"] == "UNAVAILABLE" else "UNKNOWN"
                    ),
                    "checks": checks, "process_census": census,
                }
                if not stopped:
                    if backend == "chromium":
                        backend_results.append({"status": "SKIPPED", "backend": "firefox",
                                                "reason": "unsafe_cleanup_state"})
                    break
            return tuple(backend_results)

        stage = "interactive-mcp"
        interactive, _body_result = await _run_mcp_profile(
            profile="interactive",
            expected_tools=_INTERACTIVE_TOOL_NAMES,
            mcp_command=mcp_command,
            environ=environ,
            working_directory=paths["working"],
            control_socket=control_socket,
            stderr_path=output_dir / "interactive-stderr.log",
            body=interactive_body,
            process_observer=observe_processes,
        )
        if backend_results and all(item.get("post_stop", {}).get("status") == "PASS"
                                   for item in backend_results):
            stage = "interactive-cleanup"
            exited, _ = await _wait_for_new_processes(baseline_processes)
            transition_snapshots.append({"profile": "interactive-exit", "snapshot": exited})
            census = _process_cleanup_summary(
                baseline_processes, exited, observed_processes,
                ownership_verified=ownership_samples["total"] > 0 and ownership_samples["incomplete"] == 0,
            )
            interactive["exit_process_census"] = census
            checks = _cleanup_summary(data_root, paths["tmp"], owner_scope=owner_scope)
            interactive["exit_cleanup"] = checks
            if (census["status"] != "PASS" or not all(value is True for value in checks.values())
                    or interactive.get("control_socket_absent_after_exit") is not True):
                raise VerificationFailure("interactive MCP cleanup does not authorize observer restart")
            stage = "observer-mcp"
            profile_root = None  # Only a new trusted launch may bind a new root generation.
            observer_restart, _ = await _run_mcp_profile(
                profile="observer",
                expected_tools=_OBSERVER_TOOL_NAMES,
                mcp_command=mcp_command,
                environ=environ,
                working_directory=paths["working"],
                control_socket=control_socket,
                stderr_path=output_dir / "observer-restart-stderr.log",
                process_observer=observe_processes,
            )
        else:
            observer_restart = {"status": "SKIPPED", "reason": "unsafe_cleanup_state"}
    except (Exception, asyncio.CancelledError) as exc:
        raw_errors.append({"stage": stage, "type": type(exc).__name__,
                           "message": repr(exc)[:8192]})
        failed = {"status": "FAIL", "failure_type": type(exc).__name__}
        if stage in {"interactive-mcp", "interactive-cleanup"}:
            interactive.update(failed)
            observer_restart = {"status": "SKIPPED", "reason": "unsafe_cleanup_state"}
        elif stage == "observer-mcp":
            observer_restart = failed
    finally:
        try:
            fixture.stop()
        except Exception as exc:
            raw_errors.append({"stage": "fixture-stop", "type": type(exc).__name__,
                               "message": repr(exc)[:8192]})

    try:
        final_processes, survivors = await _wait_for_new_processes(baseline_processes)
    except Exception as exc:
        final_processes = {"status": "UNAVAILABLE" if isinstance(exc, OSError) else "UNKNOWN",
                           "processes": {}, "reason": "inspection_failed"}
        if isinstance(exc, OSError):
            final_processes["errno"] = exc.errno
        survivors = None
        raw_errors.append({"stage": "process-readback", "type": type(exc).__name__,
                           "message": repr(exc)[:8192]})
    process_records = {
        "processes-after.json": final_processes,
        "processes-observed.json": {
            "samples": ownership_samples,
            "backend_transitions": transition_snapshots,
            "identities": [{"pid": pid, "start_ticks": generation}
                           for pid, generation in sorted(observed_processes)],
        },
    }
    if survivors:
        process_records["process-survivors.json"] = survivors
    for name, value in process_records.items():
        try:
            write_private_json(output_dir / name, value)
        except Exception as exc:
            raw_errors.append({"stage": name, "type": type(exc).__name__,
                               "message": repr(exc)[:8192]})
    try:
        cleanup = _cleanup_summary(data_root, paths["tmp"], owner_scope=owner_scope)
    except Exception as exc:
        cleanup = {"inspection_verified": False}
        raw_errors.append({"stage": "cleanup-readback", "type": type(exc).__name__,
                           "message": repr(exc)[:8192]})
    cleanup["new_process_survivors"] = None if survivors is None else len(survivors)
    cleanup["process_census_verified"] = survivors is not None
    ownership_verified = ownership_samples["total"] > 0 and ownership_samples["incomplete"] == 0
    process_census = _process_cleanup_summary(
        baseline_processes, final_processes, observed_processes, ownership_verified=ownership_verified,
    )
    process_census["ownership_samples"] = ownership_samples
    cleanup["owned_process_observation_verified"] = ownership_verified
    cleanup["observed_candidate_survivors"] = process_census["observed_candidate_survivors"]
    backend_pass = (
        len(backend_results) == 2
        and all(item.get("status") == "PASS" and item.get("post_stop", {}).get("status") == "PASS"
                for item in backend_results)
    )
    stdio_pass = (
        interactive.get("server_name") == "termu-inator"
        and interactive.get("server_version") == expected_server_version
        and interactive.get("protocol_version") == "2025-11-25"
        and interactive.get("stderr_bytes") == 0
        and interactive.get("control_socket_absent_after_exit") is True
        and observer_restart.get("server_name") == "termu-inator"
        and observer_restart.get("server_version") == expected_server_version
        and observer_restart.get("protocol_version") == "2025-11-25"
        and observer_restart.get("stderr_bytes") == 0
        and observer_restart.get("control_socket_absent_after_exit") is True
    )
    cleanup_pass = all(
        value is True if isinstance(value, bool) else value == 0
        for value in cleanup.values()
    )
    status = "PASS" if backend_pass and stdio_pass and cleanup_pass and not raw_errors else "FAIL"
    return (
        {
            "status": status,
            "backends": backend_results,
            "stdio": {
                "interactive": interactive,
                "observer_restart": observer_restart,
                "control_socket_path_bytes": len(os.fsencode(control_socket)),
                "same_data_root_restart_verified": (
                    interactive.get("control_socket_absent_after_exit") is True
                    and observer_restart.get("control_socket_absent_after_exit") is True
                ),
            },
            "cleanup": cleanup,
            "process_census": process_census,
            "benchmark_allowed": status == "PASS",
        },
        raw_errors,
    )


def validate_png_file(path: Path) -> dict[str, Any]:
    """Check a bounded private PNG container, not just a successful RPC."""
    result: dict[str, Any] = {
        "path": os.fspath(path),
        "bytes": None,
        "status": "FAIL",
        "reason": "invalid_png",
        "png_signature": False,
        "valid_png": False,
    }
    try:
        parent = path.parent.lstat()
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid()
                or stat.S_IMODE(parent.st_mode) != 0o700):
            result["reason"] = "unsafe_parent"
            return result
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 0 < before.st_size <= 64 * 1024 * 1024
        ):
            result["reason"] = "unsafe_file"
            return result
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                return result
            data = stream.read(64 * 1024 * 1024 + 1)
            after = os.fstat(stream.fileno())
        # Reading may legitimately update atime on Android/Linux. Compare only
        # identity, permissions and content-mutation indicators.
        stable_fields = (
            "st_dev", "st_ino", "st_uid", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns",
        )
        current = path.lstat()
        current_parent = path.parent.lstat()
        if (
            any(getattr(value, key) != getattr(before, key)
                for value in (opened, after, current) for key in stable_fields)
            or len(data) != before.st_size
            or any(getattr(parent, key) != getattr(current_parent, key)
                   for key in ("st_dev", "st_ino", "st_uid", "st_mode"))
        ):
            result["reason"] = "changed_during_read"
            return result
        result.update(
            bytes=len(data),
            mode="0600",
            sha256=hashlib.sha256(data).hexdigest(),
            png_signature=data.startswith(b"\x89PNG\r\n\x1a\n"),
        )
        if not result["png_signature"]:
            return result
        offset = 8
        seen_header = seen_data = False
        compressed = bytearray()
        while offset + 12 <= len(data):
            size = struct.unpack_from(">I", data, offset)[0]
            end = offset + 12 + size
            if end > len(data):
                return result
            kind = data[offset + 4:offset + 8]
            payload = data[offset + 8:end - 4]
            crc = struct.unpack_from(">I", data, end - 4)[0]
            if zlib.crc32(kind + payload) != crc:
                return result
            if not seen_header:
                if kind != b"IHDR" or size != 13:
                    return result
                width, height = struct.unpack_from(">II", payload)
                if not width or not height:
                    return result
                result.update(width=width, height=height)
                seen_header = True
            elif kind == b"IHDR":
                return result
            if kind == b"IDAT" and size:
                seen_data = True
                compressed.extend(payload)
            if kind == b"IEND":
                if size != 0 or not seen_data or end != len(data):
                    return result
                decoder = zlib.decompressobj()
                pixels = decoder.decompress(compressed, 64 * 1024 * 1024 + 1)
                result["valid_png"] = (
                    0 < len(pixels) <= 64 * 1024 * 1024 and decoder.eof
                    and not decoder.unused_data and not decoder.unconsumed_tail
                )
                if result["valid_png"]:
                    result.update(status="PASS", reason=None)
                return result
            offset = end
    except FileNotFoundError:
        result["reason"] = "missing"
    except PermissionError as exc:
        result.update(status="UNAVAILABLE", reason="permission_denied", errno=exc.errno)
    except OSError as exc:
        result.update(status="UNKNOWN", reason="io_error", errno=exc.errno)
    except (ValueError, struct.error, zlib.error):
        pass
    return result


def _canonical_post_run_checks(
    arguments: argparse.Namespace, report: Mapping[str, Any], raw_errors: list[dict[str, str]],
) -> dict[str, Any]:
    checks: dict[str, Any] = {"pngs": []}
    for name, expected, readback in (
        ("checkout", report.get("source"), lambda: {
            **_git_preflight(arguments.project_root, arguments.expected_commit),
            "tool_manifest": _load_frozen_manifest(arguments.project_root),
        }),
        ("environment", report.get("environment"), lambda: _installed_environment_preflight(
            project_root=arguments.project_root, mcp_command=arguments.mcp_command,
            control_command=arguments.control_command, wheel_path=arguments.wheel,
            expected_wheel_sha256=arguments.expected_wheel_sha256,
        )),
    ):
        if expected is None:
            checks[name] = {"status": "SKIPPED", "reason": "preflight_incomplete"}
            continue
        try:
            matches = readback() == expected
            checks[name] = {"status": "PASS" if matches else "FAIL",
                            "reason": None if matches else "identity_mismatch"}
        except Exception as exc:
            os_error = next((value for value in (exc, exc.__cause__)
                             if isinstance(value, OSError)), None)
            checks[name] = (
                {"status": "UNAVAILABLE", "reason": "read_failed", "errno": os_error.errno}
                if os_error else {"status": "FAIL" if isinstance(exc, VerificationFailure) else "UNKNOWN",
                                  "reason": "verification_rejected" if isinstance(exc, VerificationFailure)
                                  else "verification_failed"}
            )
            raw_errors.append({"stage": f"post-run-{name}", "type": type(exc).__name__,
                               "message": repr(exc)[:8192]})

    for backend in ("chromium", "firefox"):
        if "environment" not in report:
            checks["pngs"].append({"backend": backend, "status": "SKIPPED",
                                   "reason": "preflight_incomplete"})
            continue
        try:
            actual = validate_png_file(arguments.output / f"{backend}.png")
        except Exception as exc:
            actual = {"status": "UNKNOWN", "reason": "verification_failed",
                      "valid_png": False, "bytes": None}
            raw_errors.append({"stage": f"post-run-{backend}-png", "type": type(exc).__name__,
                               "message": repr(exc)[:8192]})
        actual.pop("path", None)
        recorded = [item for item in report.get("device", {}).get("backends", [])
                    if item.get("backend") == backend]
        expected = recorded[0].get("artifact") if len(recorded) == 1 else None
        if actual.get("valid_png"):
            if not isinstance(expected, dict):
                actual.update(status="UNKNOWN", reason="unbound_artifact")
            elif expected.get("sha256") != actual.get("sha256") or expected.get("size_bytes") != actual.get("bytes"):
                actual.update(status="FAIL", reason="artifact_changed")
        checks["pngs"].append({"backend": backend, **actual})
    return checks


def verification_summary_ko(report: Mapping[str, Any]) -> str:
    """Project only fixed statuses, never private failure text, into an operator note."""
    device = report.get("device", {})
    backends = {item.get("backend"): item.get("status")
                for item in device.get("backends", [])}
    transitions = {item.get("backend"): item.get("post_stop", {}).get("status", "SKIPPED")
                   for item in device.get("backends", [])}
    allowed = {"PASS", "FAIL", "UNKNOWN", "UNAVAILABLE", "SKIPPED"}
    census = device.get("process_census", {}).get("status", "UNKNOWN")
    status = "PASS" if report.get("status") == "PASS" else "FAIL"
    lines = ["실행: 종료 (모든 항목의 실행·통과를 의미하지 않음)", f"Canonical: {status}"]
    for backend in ("chromium", "firefox"):
        value = backends.get(backend, "SKIPPED")
        lines.append(f"{backend}: {value if value in allowed else 'UNKNOWN'}")
        transition = transitions.get(backend, "SKIPPED")
        lines.append(f"{backend} 종료·전환: {transition if transition in allowed else 'UNKNOWN'}")
    cleanup = device.get("cleanup", {})
    incomplete = []
    for name in (
        "control_socket_absent", "legacy_lock_absent", "display_leases_absent",
        "session_lock_path_safe", "session_lock_owner_safe", "session_lock_pid_inactive",
        "session_lock_lease_available", "process_census_verified", "new_process_survivors",
        "owned_process_observation_verified", "observed_candidate_survivors",
    ):
        value = cleanup.get(name)
        if not (value is True if isinstance(value, bool) else value == 0):
            incomplete.append(name)
    lines.append("미통과·미확인 정리 항목 (미실행 포함): " + (", ".join(incomplete) or "없음"))
    closing = report.get("post_run", {})
    for name, label in (("checkout", "Git"), ("environment", "환경")):
        value = closing.get(name, {}).get("status", "UNKNOWN")
        lines.append(f"사후 {label} 확인: {value if value in allowed else 'UNKNOWN'}")
    for backend in ("chromium", "firefox"):
        items = [item for item in closing.get("pngs", []) if item.get("backend") == backend]
        value = items[0].get("status") if len(items) == 1 else "UNKNOWN"
        lines.append(f"사후 {backend} PNG: {value if value in allowed else 'UNKNOWN'}")
    lines.extend((
        f"프로세스 관측: {census if census in allowed else 'UNKNOWN'}",
        "관측 범위: 현재 UID의 보이는 프로세스; 후보 귀속은 관측한 PID·시작 시점·부모 관계로 구분",
        "전역 Unix 소켓 목록: 이 검사에서는 조회하지 않음",
        "Benchmark: 아직 미실행; 현재 환경 재확인 후 조건부 허용"
        if report.get("benchmark_allowed") is True else "Benchmark: 미허용",
        "추가 작업: 봉인된 지시의 다음 단계를 따름; 동일 회차를 재실행하지 않음"
        if status == "PASS" else "추가 작업: 미통과·미확인 항목 검토; 동일 회차를 재실행하지 않음",
        "Production 승인: 미승인",
        "반환 파일 무결성: final-verify-files.json과 종료 코드를 별도 확인",
    ))
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    project_root = arguments.project_root
    output_dir = arguments.output
    try:
        _prepare_output_directory(output_dir, project_root)
    except VerificationFailure as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "stage": "output",
                    "failure_type": type(exc).__name__,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    started_at = _utc_now()
    stage = "git"
    raw_errors: list[dict[str, str]] = []
    report: dict[str, object] = {
        "format": "termuinator-final-verify-v1",
        "status": "FAIL",
        "started_at": started_at,
        "benchmark_allowed": False,
        "return_files_manifest": "final-verify-files.json",
    }
    try:
        git_summary = _git_preflight(
            project_root,
            arguments.expected_commit,
        )
        stage = "manifest"
        manifest_summary = _load_frozen_manifest(project_root)
        report["source"] = {**git_summary, "tool_manifest": manifest_summary}
        stage = "installed-environment"
        environment_summary = _installed_environment_preflight(
            project_root=project_root,
            mcp_command=arguments.mcp_command,
            control_command=arguments.control_command,
            wheel_path=arguments.wheel,
            expected_wheel_sha256=arguments.expected_wheel_sha256,
        )
        report["environment"] = environment_summary
        stage = "device-browser-gate"
        device_summary, device_errors = asyncio.run(
            _run_device_verification(
                project_root=project_root,
                output_dir=output_dir,
                mcp_command=arguments.mcp_command,
                control_command=arguments.control_command,
                expected_commit=arguments.expected_commit,
                expected_server_version=str(
                    environment_summary["termux_browser_pilot"]
                ),
            )
        )
        raw_errors.extend(device_errors)
        report["device"] = device_summary
        report["status"] = device_summary["status"]
        report["benchmark_allowed"] = device_summary["benchmark_allowed"]
    except BaseException as exc:
        failure_type = type(exc).__name__
        report["failure"] = {"stage": stage, "type": failure_type}
        raw_errors.append(
            {
                "stage": stage,
                "type": failure_type,
                "message": repr(exc)[:8192],
            }
        )
    report["post_run"] = _canonical_post_run_checks(arguments, report, raw_errors)
    closing = report["post_run"]
    if any(item.get("status") != "PASS" for item in (
        closing["checkout"], closing["environment"], *closing["pngs"],
    )):
        report["status"] = "FAIL"
        report["benchmark_allowed"] = False
    report["finished_at"] = _utc_now()
    if raw_errors:
        try:
            write_private_json(output_dir / "raw-errors.json", raw_errors)
            report["private_diagnostics_written"] = True
        except Exception:
            report["private_diagnostics_written"] = False
            report["status"] = "FAIL"
            report["benchmark_allowed"] = False
    manifest_path = output_dir / "final-verify-manifest.json"
    manifest_bytes = write_private_json(manifest_path, report)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    checksum_bytes = f"{manifest_sha256}  final-verify-manifest.json\n".encode("ascii")
    _write_private_bytes(
        output_dir / "final-verify-manifest.sha256",
        checksum_bytes,
    )
    note_bytes = verification_summary_ko(report).encode("utf-8")
    _write_private_bytes(
        output_dir / "final-verify-summary.ko.txt",
        note_bytes,
    )
    status = str(report["status"])
    try:
        publication = write_return_file_manifest(output_dir / "final-verify-files.json", {
            manifest_path.name: manifest_bytes,
            "final-verify-manifest.sha256": checksum_bytes,
            "final-verify-summary.ko.txt": note_bytes,
        })
        publication_pass = publication["status"] == "PASS"
    except Exception:
        publication_pass = False
    if not publication_pass:
        status = "FAIL"
    print(
        json.dumps(
            {
                "status": status,
                "manifest": os.fspath(manifest_path),
                "manifest_sha256": manifest_sha256,
                "benchmark_allowed": report["benchmark_allowed"] and publication_pass,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if status == "PASS" else 1


__all__ = [
    "VerificationFailure",
    "build_parser",
    "main",
    "project_digest",
    "reconstruct_artifact",
    "runtime_platform_summary",
    "validate_android_termux_identity",
    "validate_artifact_store",
    "validate_installed_source_binding",
    "validate_observation",
    "validate_released_session_lock",
    "validate_tool_inventory",
    "validate_wheel_provenance",
    "validate_wheel_source_binding",
    "verify_backend",
    "write_private_json",
]


if __name__ == "__main__":
    raise SystemExit(main())
