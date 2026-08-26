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
import subprocess
import sys
import sysconfig
import time
from typing import Any
from urllib.parse import unquote, urlsplit
import zipfile


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
_PROCESS_TERMS = (
    "firefox",
    "chromium",
    "chrome",
    "xvfb",
    "openbox",
    "tbp-mcp-v1",
    "final_verify.py",
    "virgl_test_server_android",
    "xclip",
    "xdotool",
)
_MAX_CONTROL_SOCKET_PATH_BYTES = 100


class VerificationFailure(RuntimeError):
    """A bounded, page-data-free release-gate failure."""


ToolCaller = Callable[
    [str, dict[str, object]],
    Awaitable[Mapping[str, Any]],
]
PermissionGrant = Callable[[str, str], Awaitable[None]]


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
    if platform.system() != "Linux" or not os.environ.get("ANDROID_ROOT"):
        raise VerificationFailure("final verifier must run on Android/Termux")

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


def _require_private_directory(path: Path, label: str) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise VerificationFailure(f"{label} is missing or unsafe") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
        raise VerificationFailure(f"{label} must be a mode 0700 real directory")


def _read_private_regular(path: Path, label: str, maximum: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise VerificationFailure(f"{label} is missing or unsafe") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
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
        return b"".join(chunks)
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


def write_private_json(path: Path, value: object) -> None:
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


async def verify_backend(
    caller: ToolCaller,
    *,
    grant_permission: PermissionGrant,
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
    if not callable(caller) or not callable(grant_permission):
        raise ValueError("caller and grant_permission must be callable")
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
            data_root,
            owner_scope=owner_scope,
            project_id=project_id,
            artifact=artifact,
            reconstructed=screenshot,
        )
        _write_private_bytes(output_dir / f"{backend}.png", screenshot)
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
    def __init__(self, session: object) -> None:
        self._session = session

    async def __call__(
        self,
        name: str,
        arguments: dict[str, object],
    ) -> Mapping[str, Any]:
        call_tool = getattr(self._session, "call_tool", None)
        if not callable(call_tool):
            raise VerificationFailure("MCP client session has no call_tool method")
        result = await call_tool(
            name,
            arguments,
            read_timeout_seconds=timedelta(seconds=180),
        )
        if getattr(result, "isError", False):
            code = "mcp_error"
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
                if isinstance(envelope, Mapping) and isinstance(
                    envelope.get("code"), str
                ):
                    code = envelope["code"][:64]
                    break
            raise VerificationFailure(f"{name} returned MCP error code {code}")
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


def _require_private_control_socket(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise VerificationFailure("owner host-control socket is missing") from exc
    if not stat.S_ISSOCK(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        raise VerificationFailure("owner host-control socket is not private")


async def _wait_path_absent(path: Path, timeout_seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not path.exists() and not path.is_symlink():
            return True
        await asyncio.sleep(0.05)
    return not path.exists() and not path.is_symlink()


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
) -> tuple[dict[str, object], object | None]:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        raise VerificationFailure("MCP 1.29 client SDK cannot be imported") from exc

    server_parameters = StdioServerParameters(
        command=os.fspath(mcp_command),
        args=["--tool-profile", profile],
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
                    body_result = await body(_McpToolCaller(session))
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
    completed = _run_bounded(
        [
            control_command,
            "permission",
            session_id,
            origin,
            "session_allow",
        ],
        cwd=working_directory,
        environ=environ,
        timeout=15,
        label="owner permission grant",
    )
    if completed.returncode != 0 or completed.stderr:
        raise VerificationFailure("owner permission grant failed")
    try:
        response = json.loads(
            completed.stdout,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise VerificationFailure("owner permission grant returned invalid JSON") from exc
    if not isinstance(response, Mapping) or response.get("ok") is not True:
        raise VerificationFailure("owner permission grant was not accepted")


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


def _process_snapshot() -> dict[str, dict[str, str]]:
    proc = Path("/proc")
    if not proc.is_dir():
        return {}
    snapshot: dict[str, dict[str, str]] = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes()[:8192].replace(b"\x00", b" ")
            command_text = command.decode("utf-8", errors="replace").strip()
            comm = (entry / "comm").read_text(encoding="utf-8", errors="replace")[:256].strip()
        except OSError:
            continue
        searchable = f"{comm} {command_text}".lower()
        if any(term in searchable for term in _PROCESS_TERMS):
            snapshot[entry.name] = {"comm": comm, "command": command_text}
    return snapshot


async def _wait_for_new_processes(
    baseline: Mapping[str, object],
    *,
    timeout_seconds: float = 15.0,
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    deadline = time.monotonic() + timeout_seconds
    latest = _process_snapshot()
    while time.monotonic() < deadline:
        survivors = {
            pid: value for pid, value in latest.items() if pid not in baseline
        }
        if not survivors:
            return latest, {}
        await asyncio.sleep(0.25)
        latest = _process_snapshot()
    survivors = {pid: value for pid, value in latest.items() if pid not in baseline}
    return latest, survivors


def _cleanup_summary(data_root: Path, temporary_root: Path) -> dict[str, object]:
    paths = {
        "control_socket_absent": data_root / "runtime" / "control.sock",
        "session_lock_absent": data_root / "runtime" / "session.lock",
        "legacy_lock_absent": temporary_root / ".tbp_browser.lock",
    }
    summary = {
        name: not path.exists() and not path.is_symlink()
        for name, path in paths.items()
    }
    lease_root = temporary_root / "termuinator-runtime"
    lease_files = list(lease_root.glob("*.lease")) if lease_root.is_dir() else []
    summary["display_leases_absent"] = not lease_files
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
    backend_results: list[dict[str, object]] = []

    fixture = fixture_type()
    fixture.start()
    try:
        fixture_origin = fixture.base_url
        fixture_url = fixture.url("/forms")

        async def interactive_body(caller: _McpToolCaller) -> object:
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

                try:
                    result = await verify_backend(
                        caller,
                        grant_permission=grant,
                        backend=backend,
                        fixture_origin=fixture_origin,
                        fixture_url=fixture_url,
                        data_root=data_root,
                        owner_scope=owner_scope,
                        project_id=project_id,
                        output_dir=output_dir,
                    )
                except Exception as exc:
                    backend_results.append(
                        {
                            "status": "FAIL",
                            "backend": backend,
                            "failure_type": type(exc).__name__,
                        }
                    )
                    raw_errors.append(
                        {
                            "stage": f"backend-{backend}",
                            "type": type(exc).__name__,
                            "message": repr(exc)[:8192],
                        }
                    )
                    cleanup = _cleanup_summary(data_root, paths["tmp"])
                    if not all(cleanup.values()):
                        remaining = (
                            "firefox" if backend == "chromium" else None
                        )
                        if remaining is not None:
                            backend_results.append(
                                {
                                    "status": "SKIPPED",
                                    "backend": remaining,
                                    "reason": "unsafe_cleanup_state",
                                }
                            )
                        break
                else:
                    backend_results.append(result)
            return tuple(backend_results)

        interactive, _body_result = await _run_mcp_profile(
            profile="interactive",
            expected_tools=_INTERACTIVE_TOOL_NAMES,
            mcp_command=mcp_command,
            environ=environ,
            working_directory=paths["working"],
            control_socket=control_socket,
            stderr_path=output_dir / "interactive-stderr.log",
            body=interactive_body,
        )
        observer_restart, _ = await _run_mcp_profile(
            profile="observer",
            expected_tools=_OBSERVER_TOOL_NAMES,
            mcp_command=mcp_command,
            environ=environ,
            working_directory=paths["working"],
            control_socket=control_socket,
            stderr_path=output_dir / "observer-restart-stderr.log",
        )
    finally:
        fixture.stop()

    final_processes, survivors = await _wait_for_new_processes(
        baseline_processes
    )
    write_private_json(output_dir / "processes-after.json", final_processes)
    if survivors:
        write_private_json(output_dir / "process-survivors.json", survivors)
    cleanup = _cleanup_summary(data_root, paths["tmp"])
    cleanup["new_process_survivors"] = len(survivors)
    backend_pass = (
        len(backend_results) == 2
        and all(item.get("status") == "PASS" for item in backend_results)
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
    status = "PASS" if backend_pass and stdio_pass and cleanup_pass else "FAIL"
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
            "benchmark_allowed": status == "PASS",
        },
        raw_errors,
    )


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
    }
    try:
        git_summary = _git_preflight(
            project_root,
            arguments.expected_commit,
        )
        stage = "manifest"
        manifest_summary = _load_frozen_manifest(project_root)
        stage = "installed-environment"
        environment_summary = _installed_environment_preflight(
            project_root=project_root,
            mcp_command=arguments.mcp_command,
            control_command=arguments.control_command,
            wheel_path=arguments.wheel,
            expected_wheel_sha256=arguments.expected_wheel_sha256,
        )
        report["source"] = {**git_summary, "tool_manifest": manifest_summary}
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
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            failure_type = type(exc).__name__
        else:
            failure_type = type(exc).__name__
        report["failure"] = {"stage": stage, "type": failure_type}
        raw_errors.append(
            {
                "stage": stage,
                "type": failure_type,
                "message": repr(exc)[:8192],
            }
        )
    report["finished_at"] = _utc_now()
    if raw_errors:
        write_private_json(output_dir / "raw-errors.json", raw_errors)
    manifest_path = output_dir / "final-verify-manifest.json"
    write_private_json(manifest_path, report)
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    _write_private_bytes(
        output_dir / "final-verify-manifest.sha256",
        f"{manifest_sha256}  final-verify-manifest.json\n".encode("ascii"),
    )
    status = str(report["status"])
    print(
        json.dumps(
            {
                "status": status,
                "manifest": os.fspath(manifest_path),
                "manifest_sha256": manifest_sha256,
                "benchmark_allowed": report["benchmark_allowed"],
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
    "validate_artifact_store",
    "validate_installed_source_binding",
    "validate_observation",
    "validate_tool_inventory",
    "validate_wheel_provenance",
    "validate_wheel_source_binding",
    "verify_backend",
    "write_private_json",
]


if __name__ == "__main__":
    raise SystemExit(main())
