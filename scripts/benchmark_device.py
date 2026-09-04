#!/usr/bin/env python3
"""Canonical-bound Firefox/Chromium benchmark for a Termu-inator install.

The harness first requires a checksum-valid PASS manifest whose recorded
runtime still matches the current clean install. It changes no package or
repository configuration, starts and stops the browser daemon, writes private
raw diagnostics to one new output identity, and emits a separate sanitized
summary suitable for review.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from importlib import metadata as importlib_metadata
from importlib import util as importlib_util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import stat
import statistics
import subprocess
import sys
import sysconfig
import time
from typing import Any, Sequence


@dataclass(frozen=True)
class BenchmarkConfig:
    project_root: Path
    tbp: Path
    wheel: Path
    canonical_manifest: Path
    output: Path
    socket_path: Path
    pidfile: Path
    url: str
    backends: tuple[str, ...]
    cold_samples: int
    status_samples: int
    text_samples: int
    screenshot_samples: int
    settle_seconds: float
    network_kind: str
    tailscale_termux_state: str


class BenchmarkAuthorityError(RuntimeError):
    """A bounded failure that keeps a stale canonical benchmark closed."""


_BENCHMARK_IDENTITY_FIELDS = (
    "python",
    "kernel_release",
    "python_sys_platform",
    "platform_system",
    "native_cryptography",
    "mcp",
    "websockets",
    "termux_browser_pilot",
    "wheel_sha256",
    "source_tree_sha256",
    "installed_source_tree_sha256",
)


def _string_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) for key in value
    ):
        raise BenchmarkAuthorityError(f"{label} is not a string-keyed object")
    return value


def load_canonical_manifest(path: Path) -> tuple[dict[str, Any], str]:
    """Load a private canonical manifest only when its sidecar still matches."""

    if path.name != "final-verify-manifest.json":
        raise BenchmarkAuthorityError("canonical manifest name is invalid")
    try:
        parent_info = path.parent.lstat()
    except OSError as exc:
        raise BenchmarkAuthorityError(
            "canonical manifest parent is missing or unsafe"
        ) from exc
    if (
        not stat.S_ISDIR(parent_info.st_mode)
        or path.parent.is_symlink()
        or parent_info.st_uid != os.getuid()
        or parent_info.st_mode & 0o077
    ):
        raise BenchmarkAuthorityError(
            "canonical manifest parent is not owner-private"
        )
    checksum_path = path.with_name("final-verify-manifest.sha256")
    for candidate, label in (
        (path, "canonical manifest"),
        (checksum_path, "canonical manifest checksum"),
    ):
        try:
            info = candidate.lstat()
        except OSError as exc:
            raise BenchmarkAuthorityError(f"{label} is missing or unsafe") from exc
        if candidate.is_symlink() or not candidate.is_file():
            raise BenchmarkAuthorityError(f"{label} is missing or unsafe")
        if info.st_uid != os.getuid() or info.st_mode & 0o777 != 0o600:
            raise BenchmarkAuthorityError(f"{label} is not owner-private")
    data = path.read_bytes()
    if len(data) > 1_000_000:
        raise BenchmarkAuthorityError("canonical manifest is unbounded")
    observed = hashlib.sha256(data).hexdigest()
    expected_line = f"{observed}  final-verify-manifest.json\n"
    try:
        checksum = checksum_path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise BenchmarkAuthorityError(
            "canonical manifest checksum is invalid"
        ) from exc
    if checksum != expected_line:
        raise BenchmarkAuthorityError("canonical manifest checksum differs")
    try:
        manifest = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BenchmarkAuthorityError("canonical manifest is invalid JSON") from exc
    return _string_mapping(manifest, "canonical manifest"), observed


def validate_benchmark_authority(
    manifest: object,
    *,
    current_identity: dict[str, str],
    current_commit: str,
    clean_worktree: bool,
) -> dict[str, Any]:
    """Fail closed unless the benchmark runtime matches its canonical PASS."""

    root = _string_mapping(manifest, "canonical manifest")
    device = _string_mapping(root.get("device"), "canonical device summary")
    if (
        root.get("status") != "PASS"
        or root.get("benchmark_allowed") is not True
        or device.get("status") != "PASS"
        or device.get("benchmark_allowed") is not True
    ):
        raise BenchmarkAuthorityError("canonical manifest does not authorize benchmark")
    backend_items = device.get("backends")
    if not isinstance(backend_items, list):
        raise BenchmarkAuthorityError(
            "canonical backend status does not authorize benchmark"
        )
    backends: dict[str, object] = {}
    for item in backend_items:
        entry = _string_mapping(item, "canonical backend summary")
        name = entry.get("backend")
        if not isinstance(name, str) or name in backends:
            raise BenchmarkAuthorityError(
                "canonical backend status does not authorize benchmark"
            )
        backends[name] = entry.get("status")
    if backends != {"chromium": "PASS", "firefox": "PASS"}:
        raise BenchmarkAuthorityError(
            "canonical backend status does not authorize benchmark"
        )
    stdio = _string_mapping(device.get("stdio"), "canonical stdio summary")
    for profile in ("interactive", "observer_restart"):
        profile_summary = _string_mapping(
            stdio.get(profile), f"canonical {profile} stdio summary"
        )
        if profile_summary.get("stderr_bytes") != 0:
            raise BenchmarkAuthorityError("canonical stdio is not clean")
    source = _string_mapping(root.get("source"), "canonical source summary")
    if (
        source.get("commit") != current_commit
        or source.get("clean_worktree") is not True
        or not clean_worktree
    ):
        raise BenchmarkAuthorityError("current source differs from canonical manifest")
    environment_summary = _string_mapping(
        root.get("environment"), "canonical environment summary"
    )
    for field in _BENCHMARK_IDENTITY_FIELDS:
        expected = environment_summary.get(field)
        observed = current_identity.get(field)
        if not isinstance(expected, str) or observed != expected:
            raise BenchmarkAuthorityError(
                f"{field} differs from canonical manifest"
            )
    return {
        "commit": current_commit,
        **{field: current_identity[field] for field in _BENCHMARK_IDENTITY_FIELDS},
        "environment_match_verified": True,
    }


def _git_value(project_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", os.fspath(project_root), *arguments],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0 or completed.stderr:
        raise BenchmarkAuthorityError("current source identity cannot be verified")
    return completed.stdout.strip()


def _current_benchmark_identity(config: BenchmarkConfig) -> dict[str, str]:
    try:
        from scripts.final_verify import (
            VerificationFailure,
            _runtime_distribution,
            validate_android_termux_identity,
            validate_installed_source_binding,
            validate_wheel_provenance,
            validate_wheel_source_binding,
        )

        distribution = _runtime_distribution("termux-browser-pilot")
        versions = {
            "native_cryptography": importlib_metadata.version("cryptography"),
            "mcp": _runtime_distribution("mcp").version,
            "websockets": _runtime_distribution("websockets").version,
            "termux_browser_pilot": distribution.version,
        }
        wheel_digest = hashlib.sha256(config.wheel.read_bytes()).hexdigest()
        direct_url = distribution.read_text("direct_url.json")
        validate_wheel_provenance(
            direct_url,
            expected_sha256=wheel_digest,
            wheel_path=config.wheel,
        )
        wheel_binding = validate_wheel_source_binding(
            config.wheel,
            config.project_root,
        )
        console_entries = [
            entry
            for entry in distribution.entry_points
            if entry.group == "console_scripts"
        ]
        entrypoints = {entry.name: entry.value for entry in console_entries}
        if len(entrypoints) != len(console_entries):
            raise BenchmarkAuthorityError(
                "installed console entrypoints are ambiguous"
            )
        installed_roots = tuple(
            Path(value)
            for value in {
                sysconfig.get_path("purelib"),
                sysconfig.get_path("platlib"),
            }
            if value
        )
        installed_binding = validate_installed_source_binding(
            config.project_root,
            installed_roots=installed_roots,
            entrypoints=entrypoints,
        )
        crypto_spec = importlib_util.find_spec("cryptography")
        prefix_value = os.environ.get("PREFIX")
        if crypto_spec is None or crypto_spec.origin is None or not prefix_value:
            raise BenchmarkAuthorityError(
                "Termux native cryptography identity cannot be verified"
            )
        crypto_origin = Path(crypto_spec.origin).resolve(strict=True)
        prefix = Path(prefix_value).resolve(strict=True)
        prefix_lib = (prefix / "lib").resolve(strict=True)
        if prefix_lib != crypto_origin and prefix_lib not in crypto_origin.parents:
            raise BenchmarkAuthorityError(
                "Termux native cryptography identity cannot be verified"
            )
        validate_android_termux_identity(
            python_platform=sys.platform,
            system_name=platform.system(),
            android_root=os.environ.get("ANDROID_ROOT"),
        )
        expected_bin = (Path(sys.prefix) / "bin").resolve(strict=True)
        if config.tbp.parent.resolve(strict=True) != expected_bin:
            raise BenchmarkAuthorityError(
                "benchmark executable differs from verifier environment"
            )
    except BenchmarkAuthorityError:
        raise
    except (
        OSError,
        importlib_metadata.PackageNotFoundError,
        VerificationFailure,
    ) as exc:
        raise BenchmarkAuthorityError(
            "current benchmark environment cannot be verified"
        ) from exc
    return {
        "python": platform.python_version(),
        "kernel_release": platform.release(),
        "python_sys_platform": sys.platform,
        "platform_system": platform.system(),
        **versions,
        "wheel_sha256": wheel_digest,
        "source_tree_sha256": str(wheel_binding["source_tree_sha256"]),
        "installed_source_tree_sha256": str(
            installed_binding["installed_source_tree_sha256"]
        ),
    }


def authorize_benchmark(config: BenchmarkConfig) -> dict[str, Any]:
    """Bind a benchmark run to the still-current canonical environment."""

    manifest, manifest_sha256 = load_canonical_manifest(
        config.canonical_manifest
    )
    current_commit = _git_value(config.project_root, "rev-parse", "HEAD")
    clean_worktree = not _git_value(
        config.project_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    identity = _current_benchmark_identity(config)
    summary = validate_benchmark_authority(
        manifest,
        current_identity=identity,
        current_commit=current_commit,
        clean_worktree=clean_worktree,
    )
    summary["manifest_sha256"] = manifest_sha256
    return summary


def prepare_benchmark_output(path: Path) -> None:
    """Create one new owner-private output identity without reuse."""

    if not path.is_absolute() or ".." in path.parts:
        raise BenchmarkAuthorityError("benchmark output path is invalid")
    if path.exists() or path.is_symlink():
        raise BenchmarkAuthorityError("benchmark output identity already exists")
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        parent_info = parent.lstat()
    except OSError as exc:
        raise BenchmarkAuthorityError("benchmark output parent is unsafe") from exc
    if (
        not stat.S_ISDIR(parent_info.st_mode)
        or parent.is_symlink()
        or parent_info.st_uid != os.getuid()
        or parent_info.st_mode & 0o077
    ):
        raise BenchmarkAuthorityError("benchmark output parent is unsafe")
    try:
        path.mkdir(mode=0o700)
        output_info = path.lstat()
    except OSError as exc:
        raise BenchmarkAuthorityError(
            "benchmark output identity could not be created"
        ) from exc
    if (
        not stat.S_ISDIR(output_info.st_mode)
        or path.is_symlink()
        or output_info.st_uid != os.getuid()
        or output_info.st_mode & 0o777 != 0o700
    ):
        raise BenchmarkAuthorityError("benchmark output identity is unsafe")


def run_capture(argv: Sequence[str | os.PathLike[str]], timeout: float = 90) -> dict[str, Any]:
    command = [os.fspath(value) for value in argv]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "argv": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "wall_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    except Exception as exc:  # raw diagnostics intentionally retain the failure
        return {
            "argv": command,
            "returncode": None,
            "stdout": "",
            "stderr": repr(exc),
            "wall_ms": round((time.perf_counter() - started) * 1000, 3),
        }


def percentile(samples: list[float], quantile: float) -> float | None:
    if not samples:
        return None
    if len(samples) == 1:
        return round(samples[0], 3)
    ordered = sorted(samples)
    rank = (len(ordered) - 1) * quantile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)
    return round(value, 3)


def stats(samples: list[float], errors: int) -> dict[str, Any]:
    return {
        "raw_ms": [round(value, 3) for value in samples],
        "min_ms": round(min(samples), 3) if samples else None,
        "median_ms": round(statistics.median(samples), 3) if samples else None,
        "p95_ms": percentile(samples, 0.95),
        "max_ms": round(max(samples), 3) if samples else None,
        "success_count": len(samples),
        "error_count": errors,
    }


def stop_daemon(config: BenchmarkConfig) -> dict[str, Any]:
    result = run_capture([config.tbp, "stop", "--json"], timeout=45)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not config.socket_path.exists() and not config.pidfile.exists():
            break
        time.sleep(0.1)
    result["socket_absent_after_stop"] = not config.socket_path.exists()
    result["pidfile_absent_after_stop"] = not config.pidfile.exists()
    return result


def start_daemon(config: BenchmarkConfig, backend: str) -> dict[str, Any]:
    started = time.perf_counter()
    result = run_capture(
        [config.tbp, "start", "--browser", backend, "--json"], timeout=120
    )
    result["start_to_command_exit_ms"] = round(
        (time.perf_counter() - started) * 1000, 3
    )
    ready = False
    ready_ms = None
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if config.socket_path.exists():
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.settimeout(0.5)
                probe.connect(os.fspath(config.socket_path))
            except OSError:
                pass
            else:
                ready = True
                ready_ms = (time.perf_counter() - started) * 1000
                break
            finally:
                probe.close()
        time.sleep(0.1)
    result["start_to_socket_ready_ms"] = (
        round(ready_ms, 3) if ready_ms is not None else None
    )
    result["socket_ready_verified"] = ready
    result["pid"] = (
        config.pidfile.read_text(encoding="utf-8").strip()
        if config.pidfile.exists()
        else None
    )
    return result


def is_success(response: object) -> bool:
    return isinstance(response, dict) and response.get("success") is True


async def measured_command(
    action: str,
    params: dict[str, Any],
    backend: str,
    timeout: int = 120,
) -> tuple[float, dict[str, Any] | None, str | None]:
    from src.client import send_command

    started = time.perf_counter()
    try:
        response = await send_command(action, params, timeout=timeout, browser=backend)
        elapsed = (time.perf_counter() - started) * 1000
        error = None if is_success(response) else json.dumps(response, ensure_ascii=False)
        return elapsed, response, error
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return elapsed, None, repr(exc)


def ps_snapshot() -> dict[str, Any]:
    requested = ["ps", "-A", "-o", "PID,PPID,RSS,NAME,ARGS"]
    first = subprocess.run(
        requested, capture_output=True, text=True, timeout=30, check=False
    )
    if first.returncode == 0 and first.stdout.strip():
        effective = first
        effective_command = requested
    else:
        effective_command = ["ps", "-A", "-o", "pid,ppid,rss,comm,args"]
        effective = subprocess.run(
            effective_command,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    return {
        "requested_command": requested,
        "requested_returncode": first.returncode,
        "requested_stdout": first.stdout,
        "requested_stderr": first.stderr,
        "effective_command": effective_command,
        "effective_returncode": effective.returncode,
        "effective_stdout": effective.stdout,
        "effective_stderr": effective.stderr,
    }


def parse_ps(raw: str, backend: str, daemon_pid: str | None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines()[1:]:
        match = re.match(r"\s*(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(.*)$", line)
        if match:
            rows.append(
                {
                    "pid": int(match.group(1)),
                    "ppid": int(match.group(2)),
                    "rss_kb": int(match.group(3)),
                    "name": match.group(4),
                    "args": match.group(5),
                }
            )
    daemon_rows = [
        row
        for row in rows
        if (daemon_pid and str(row["pid"]) == daemon_pid)
        or "src.daemon" in row["args"]
    ]
    daemon_pids = {row["pid"] for row in daemon_rows}
    browser_term = "chromium" if backend == "chromium" else "firefox"
    browser_rows = [
        row
        for row in rows
        if row["pid"] not in daemon_pids
        and browser_term in f"{row['name']} {row['args']}".lower()
    ]

    def matching(term: str) -> list[dict[str, Any]]:
        return [row for row in rows if term in f"{row['name']} {row['args']}".lower()]

    return {
        "daemon_python": daemon_rows,
        "browser_processes": browser_rows,
        "xvfb": matching("xvfb"),
        "openbox": matching("openbox"),
        "note": "RSS process sums may double-count shared memory.",
    }


def file_check(path: Path) -> dict[str, Any]:
    data = path.read_bytes() if path.exists() else b""
    signature = bytes.fromhex("89504e470d0a1a0a")
    file_result = run_capture(["file", path], timeout=15)
    return {
        "path": os.fspath(path),
        "bytes": len(data),
        "png_signature": data[:8] == signature,
        "file_stdout": file_result["stdout"],
        "file_stderr": file_result["stderr"],
    }


def environment(config: BenchmarkConfig) -> dict[str, Any]:
    browser_versions: dict[str, Any] = {}
    for name in ("firefox", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            browser_versions[name] = {
                "path": path,
                "result": run_capture([path, "--version"], timeout=20),
            }
    return {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "device": platform.uname()._asdict(),
        "python": sys.version,
        "termux_version": os.environ.get("TERMUX_VERSION"),
        "tbp_version": run_capture([config.tbp, "--version"], timeout=20),
        "browser_versions": browser_versions,
        "network_kind": config.network_kind,
        "tailscale_termux_split_tunneling": config.tailscale_termux_state,
        "project": os.fspath(config.project_root),
    }


def _write_ps_capture(path: Path, capture: dict[str, Any]) -> None:
    path.write_text(
        "REQUESTED COMMAND: " + " ".join(capture["requested_command"]) + "\n"
        + f"REQUESTED EXIT_CODE: {capture['requested_returncode']}\n"
        + "REQUESTED STDOUT_BEGIN\n"
        + capture["requested_stdout"]
        + "REQUESTED STDOUT_END\n"
        + "REQUESTED STDERR_BEGIN\n"
        + capture["requested_stderr"]
        + "REQUESTED STDERR_END\n"
        + "EFFECTIVE COMMAND: "
        + " ".join(capture["effective_command"])
        + "\n"
        + f"EFFECTIVE EXIT_CODE: {capture['effective_returncode']}\n"
        + "EFFECTIVE STDOUT_BEGIN\n"
        + capture["effective_stdout"]
        + "EFFECTIVE STDOUT_END\n"
        + "EFFECTIVE STDERR_BEGIN\n"
        + capture["effective_stderr"]
        + "EFFECTIVE STDERR_END\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


async def benchmark_backend(config: BenchmarkConfig, backend: str) -> dict[str, Any]:
    backend_dir = config.output / backend
    backend_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    cold: list[dict[str, Any]] = []
    for sample in range(config.cold_samples):
        stop_daemon(config)
        result = start_daemon(config, backend)
        result["sample"] = sample + 1
        cold.append(result)
        stop_daemon(config)

    stop_daemon(config)
    warm_start = start_daemon(config, backend)
    load_ms, load_response, load_error = await measured_command(
        "goto", {"url": config.url, "timeout": 45}, backend, timeout=60
    )
    await asyncio.sleep(config.settle_seconds)
    daemon_pid = (
        config.pidfile.read_text(encoding="utf-8").strip()
        if config.pidfile.exists()
        else None
    )
    ps_info = ps_snapshot()
    ps_path = backend_dir / "ps-after-settle.txt"
    _write_ps_capture(ps_path, ps_info)
    rss = parse_ps(ps_info["effective_stdout"], backend, daemon_pid)
    rss["ps_capture"] = ps_info

    operation_counts = {
        "status": config.status_samples,
        "text": config.text_samples,
        "screenshot": config.screenshot_samples,
    }
    operation_samples: dict[str, list[float]] = {name: [] for name in operation_counts}
    operation_errors: dict[str, list[dict[str, Any]]] = {
        name: [] for name in operation_counts
    }
    screenshot_details: list[dict[str, Any]] = []

    for name, count in operation_counts.items():
        for sample in range(count):
            params: dict[str, Any] = {}
            timeout = 15
            if name == "text":
                params = {"limit": 500}
                timeout = 30
            elif name == "screenshot":
                path = backend_dir / f"screenshot-{sample + 1}.png"
                params = {"path": os.fspath(path)}
                timeout = 45
            elapsed, response, error = await measured_command(
                name, params, backend, timeout=timeout
            )
            if error is None:
                operation_samples[name].append(elapsed)
                if name == "screenshot":
                    screenshot_details.append(
                        {
                            "sample": sample + 1,
                            "latency_ms": round(elapsed, 3),
                            **file_check(Path(params["path"])),
                        }
                    )
            else:
                operation_errors[name].append(
                    {"ms": elapsed, "error": error, "response": response}
                )

    cold_values = [
        item["start_to_socket_ready_ms"]
        for item in cold
        if item.get("socket_ready_verified")
        and item.get("start_to_socket_ready_ms") is not None
    ]
    return {
        "backend": backend,
        "cold_start_samples": cold,
        "cold_start_stats": stats(cold_values, len(cold) - len(cold_values)),
        "warm_start": warm_start,
        "page_load": {
            "latency_ms": round(load_ms, 3),
            "response": load_response,
            "error": load_error,
        },
        "after_page_load_sleep_seconds": config.settle_seconds,
        "operations": {
            name: stats(values, len(operation_errors[name]))
            for name, values in operation_samples.items()
        },
        "operation_errors": operation_errors,
        "screenshots": screenshot_details,
        "rss": rss,
        "ps_raw_path": os.fspath(ps_path),
    }


def _summary_stats(values: dict[str, Any]) -> dict[str, Any]:
    keys = ("min_ms", "median_ms", "p95_ms", "max_ms", "success_count", "error_count")
    return {key: values.get(key) for key in keys}


def _rss_sum(rows: object) -> int:
    if not isinstance(rows, list):
        return 0
    return sum(
        row.get("rss_kb", 0)
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("rss_kb", 0), int)
    )


def sanitize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Remove local paths, PIDs, process arguments, and raw command output."""

    raw_environment = report.get("environment", {})
    device = raw_environment.get("device", {})
    browsers = {
        name: value.get("result", {}).get("stdout", "").strip()
        for name, value in raw_environment.get("browser_versions", {}).items()
        if isinstance(value, dict)
    }
    raw_authority = raw_environment.get("canonical_authority", {})
    authority_keys = {
        "commit",
        "manifest_sha256",
        *_BENCHMARK_IDENTITY_FIELDS,
        "environment_match_verified",
    }
    canonical_authority = {
        key: value
        for key, value in raw_authority.items()
        if key in authority_keys
    } if isinstance(raw_authority, dict) else {}
    environment_summary = {
        "measured_at_utc": raw_environment.get("measured_at_utc"),
        "device": {
            "system": device.get("system"),
            "release": device.get("release"),
            "machine": device.get("machine"),
        },
        "python": str(raw_environment.get("python", "")).splitlines()[0],
        "termux_version": raw_environment.get("termux_version"),
        "tbp_version": raw_environment.get("tbp_version", {}).get("stdout", "").strip(),
        "browser_versions": browsers,
        "network_kind": raw_environment.get("network_kind"),
        "tailscale_termux_split_tunneling": raw_environment.get(
            "tailscale_termux_split_tunneling"
        ),
        "canonical_authority": canonical_authority,
    }

    backend_summaries: list[dict[str, Any]] = []
    for backend in report.get("backends", []):
        operations = backend.get("operations", {})
        rss = backend.get("rss", {})
        screenshots = backend.get("screenshots", [])
        response = backend.get("page_load", {}).get("response")
        response_data = response.get("data", {}) if isinstance(response, dict) else {}
        backend_summaries.append(
            {
                "backend": backend.get("backend"),
                "cold_start": _summary_stats(backend.get("cold_start_stats", {})),
                "operations": {
                    name: _summary_stats(operations.get(name, {}))
                    for name in ("status", "text", "screenshot")
                },
                "page_load": {
                    "latency_ms": backend.get("page_load", {}).get("latency_ms"),
                    "success": is_success(response),
                    "url": response_data.get("url"),
                    "title": response_data.get("title"),
                    "error": backend.get("page_load", {}).get("error"),
                },
                "rss_kb": {
                    "daemon": _rss_sum(rss.get("daemon_python")),
                    "browser": _rss_sum(rss.get("browser_processes")),
                    "xvfb": _rss_sum(rss.get("xvfb")),
                    "openbox": _rss_sum(rss.get("openbox")),
                    "note": "Process RSS sums may double-count shared memory.",
                },
                "screenshots": {
                    "count": len(screenshots),
                    "bytes": sorted(
                        {
                            item.get("bytes", 0)
                            for item in screenshots
                            if isinstance(item, dict)
                        }
                    ),
                    "all_valid_png": bool(screenshots)
                    and all(
                        item.get("png_signature") is True
                        for item in screenshots
                        if isinstance(item, dict)
                    ),
                },
            }
        )
    return {
        "schema_version": 1,
        "environment": environment_summary,
        "backends": backend_summaries,
        "privacy": {
            "contains_process_arguments": False,
            "contains_absolute_artifact_paths": False,
            "raw_report_is_separate": True,
        },
    }


def write_private_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    path.chmod(0o600)


def parse_args(argv: Sequence[str] | None = None) -> BenchmarkConfig:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=repository)
    parser.add_argument("--tbp", type=Path, default=None)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--canonical-manifest", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path.home() / ".cache" / "termuinator" / "benchmark"
    )
    parser.add_argument("--socket", dest="socket_path", type=Path, default=Path.home() / ".tbp" / "daemon.sock")
    parser.add_argument("--pidfile", type=Path, default=Path.home() / ".tbp" / "daemon.pid")
    parser.add_argument("--url", default="https://example.com")
    parser.add_argument("--backend", action="append", choices=("firefox", "chromium"))
    parser.add_argument("--cold-samples", type=int, default=3)
    parser.add_argument("--status-samples", type=int, default=20)
    parser.add_argument("--text-samples", type=int, default=10)
    parser.add_argument("--screenshot-samples", type=int, default=5)
    parser.add_argument("--settle-seconds", type=float, default=10)
    parser.add_argument("--network-kind", default="unspecified")
    parser.add_argument("--tailscale-termux-state", default="unspecified")
    args = parser.parse_args(argv)

    tbp_value = args.tbp or os.environ.get("TERMUINATOR_TBP") or shutil.which("tbp")
    if not tbp_value:
        parser.error("--tbp or TERMUINATOR_TBP must identify the installed tbp executable")
    tbp = Path(tbp_value).expanduser().resolve()
    wheel = Path(os.path.abspath(os.fspath(args.wheel.expanduser())))
    canonical_manifest = Path(
        os.path.abspath(os.fspath(args.canonical_manifest.expanduser()))
    )
    project_root = args.project_root.expanduser().resolve()
    if not (project_root / "src" / "client.py").is_file():
        parser.error(f"project root does not contain src/client.py: {project_root}")
    if not tbp.is_file() or not os.access(tbp, os.X_OK):
        parser.error(f"tbp is not executable: {tbp}")
    if not wheel.is_file():
        parser.error(f"wheel is not a file: {wheel}")
    if not canonical_manifest.is_file():
        parser.error(f"canonical manifest is not a file: {canonical_manifest}")
    counts = (
        args.cold_samples,
        args.status_samples,
        args.text_samples,
        args.screenshot_samples,
    )
    if any(value < 1 for value in counts) or args.settle_seconds < 0:
        parser.error("sample counts must be positive and settle seconds must be non-negative")
    return BenchmarkConfig(
        project_root=project_root,
        tbp=tbp,
        wheel=wheel,
        canonical_manifest=canonical_manifest,
        output=Path(os.path.abspath(os.fspath(args.output.expanduser()))),
        socket_path=args.socket_path.expanduser().resolve(),
        pidfile=args.pidfile.expanduser().resolve(),
        url=args.url,
        backends=tuple(args.backend or ("firefox", "chromium")),
        cold_samples=args.cold_samples,
        status_samples=args.status_samples,
        text_samples=args.text_samples,
        screenshot_samples=args.screenshot_samples,
        settle_seconds=args.settle_seconds,
        network_kind=args.network_kind,
        tailscale_termux_state=args.tailscale_termux_state,
    )


async def run_benchmark(config: BenchmarkConfig) -> tuple[Path, Path, dict[str, Any]]:
    authority = authorize_benchmark(config)
    prepare_benchmark_output(config.output)
    report: dict[str, Any] = {
        "environment": {
            **environment(config),
            "canonical_authority": authority,
        },
        "backends": [],
    }
    try:
        for backend in config.backends:
            report["backends"].append(await benchmark_backend(config, backend))
    finally:
        stop_daemon(config)
    closing_authority = authorize_benchmark(config)
    if closing_authority != authority:
        raise BenchmarkAuthorityError(
            "benchmark environment changed during measurement"
        )
    raw_path = config.output / "baseline-report.json"
    summary_path = config.output / "baseline-summary.json"
    summary = sanitize_report(report)
    write_private_json(raw_path, report)
    write_private_json(summary_path, summary)
    return raw_path, summary_path, summary


def main(argv: Sequence[str] | None = None) -> int:
    config = parse_args(argv)
    sys.path.insert(0, os.fspath(config.project_root))
    os.chdir(config.project_root)
    try:
        raw_path, summary_path, summary = asyncio.run(run_benchmark(config))
    except BenchmarkAuthorityError as exc:
        print(f"benchmark_authority_error={exc}", file=sys.stderr)
        return 2
    print(f"raw_report={raw_path}")
    print(f"sanitized_summary={summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
