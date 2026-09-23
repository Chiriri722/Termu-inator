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
import math
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import stat
import statistics
import struct
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
    isolated_runtime: Path | None = None


class BenchmarkAuthorityError(RuntimeError):
    """A bounded failure that keeps a stale canonical benchmark closed."""


class BenchmarkExecutionError(RuntimeError):
    """A fixed lifecycle failure that stops measurement but preserves a FAIL report."""

    def __init__(self, reason: str, evidence: dict[str, Any]):
        super().__init__(reason)
        self.evidence = evidence


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
    from scripts.final_verify import VerificationFailure, _read_private_regular, _verify_return_file_manifest

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
    try:
        data = _read_private_regular(path, "canonical manifest", 1_000_000)
        checksum = _read_private_regular(checksum_path, "canonical manifest checksum", 256).decode("ascii")
    except (VerificationFailure, UnicodeError) as exc:
        raise BenchmarkAuthorityError("canonical manifest or checksum is missing or unsafe") from exc
    observed = hashlib.sha256(data).hexdigest()
    expected_line = f"{observed}  final-verify-manifest.json\n"
    if checksum != expected_line:
        raise BenchmarkAuthorityError("canonical manifest checksum differs")
    try:
        manifest = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BenchmarkAuthorityError("canonical manifest is invalid JSON") from exc
    manifest = _string_mapping(manifest, "canonical manifest")
    if "return_files_manifest" in manifest:
        try:
            if manifest["return_files_manifest"] != "final-verify-files.json":
                raise VerificationFailure("canonical return-file manifest name is invalid")
            files = _verify_return_file_manifest(path.parent / "final-verify-files.json", {
                "final-verify-manifest.json", "final-verify-manifest.sha256", "final-verify-summary.ko.txt",
            })
            if files[path.name]["sha256"] != observed:
                raise VerificationFailure("canonical manifest changed during verification")
        except (VerificationFailure, OSError) as exc:
            raise BenchmarkAuthorityError("canonical return-file integrity is unverified") from exc
    return manifest, observed


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
        if "post_stop" in entry:
            stopped = _string_mapping(entry["post_stop"], "canonical backend cleanup")
            if stopped.get("status") != "PASS":
                raise BenchmarkAuthorityError("canonical backend cleanup does not authorize benchmark")
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
    # Match the daemon's existing screenshot boundary; do not relax it for a
    # handoff that accidentally places output outside its isolated HOME.
    from src._utils import validate_path

    try:
        validate_path(os.fspath(path))
    except (ValueError, OSError) as exc:
        raise BenchmarkAuthorityError("output is outside benchmark HOME") from exc
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


def _observe_daemon(launched: dict[str, Any], *, allow_exited: bool = False) -> dict[str, Any]:
    from scripts.final_verify import _process_snapshot, _record_process_tree

    try:
        latest = _process_snapshot()
        identity = launched.get("daemon_identity", {})
        pid = identity.get("pid")
        current = latest["processes"].get(pid)
        observed = {tuple(item) for item in launched.get("observed_processes", [])}
        verified = latest["status"] == "PASS" and launched.get("daemon_identity_verified") is True
        if current is not None and current["start_ticks"] == identity.get("start_ticks"):
            verified = _record_process_tree(latest, int(pid), observed) and verified
        elif not allow_exited:
            verified = False
        launched["observed_processes"] = sorted(observed)
    except Exception as exc:
        latest = {"status": "UNAVAILABLE" if isinstance(exc, OSError) else "UNKNOWN",
                  "processes": {}, "reason": "inspection_failed"}
        if isinstance(exc, OSError):
            latest["errno"] = exc.errno
        launched["process_observation_error"] = {"type": type(exc).__name__, "message": repr(exc)[:8192]}
        verified = False
    if not verified:
        launched["process_observation_verified"] = False
    launched["process_latest"] = latest
    return latest


def stop_daemon(config: BenchmarkConfig, launched: dict[str, Any] | None = None) -> dict[str, Any]:
    from scripts.final_verify import VerificationFailure, _path_absent, _process_cleanup_summary

    states = (_path_absent(config.socket_path), _path_absent(config.pidfile))
    result: dict[str, Any] = {"shutdown_sent": False}
    if launched is None:
        # No recorded launch means no authority to stop anything at this path.
        result.update(socket_absent_after_stop=states[0], pidfile_absent_after_stop=states[1],
                      process_cleanup={"scope": "no_recorded_launch", "status": (
                          "PASS" if all(value is True for value in states) else "UNKNOWN"
                      )})
        return result

    _observe_daemon(launched, allow_exited=True)
    if (launched.get("daemon_identity_verified") is True
            and not launched.get("shutdown_attempted") and all(value is False for value in states)):
        launched["shutdown_attempted"] = True
        peer = None
        try:
            peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            peer.settimeout(10)
            peer.connect(os.fspath(config.socket_path))
            if _daemon_peer_identity(config, peer) != launched["daemon_identity"]:
                raise VerificationFailure("benchmark daemon generation differs from launch")
            # Keep the authenticated connection: reconnecting through the CLI would lose this binding.
            peer.sendall(b'{"action":"shutdown","params":{}}\n')
            result["shutdown_sent"] = True
            with peer.makefile("rb") as reader:
                reply = reader.readline(65_537)
            result["shutdown_acknowledged"] = (
                len(reply) <= 65_536 and reply.endswith(b"\n") and is_success(json.loads(reply))
            )
        except Exception as exc:
            result["shutdown_error"] = {"type": type(exc).__name__, "message": repr(exc)[:8192]}
        finally:
            if peer is not None:
                peer.close()

    deadline = time.monotonic() + 15
    while True:
        states = tuple(
            None if previous is None else _path_absent(path)
            for previous, path in zip(states, (config.socket_path, config.pidfile))
        )
        latest = _observe_daemon(launched, allow_exited=True)
        census = _process_cleanup_summary(
            launched.get("process_baseline", {"status": "UNKNOWN", "processes": {}}), latest,
            {tuple(item) for item in launched.get("observed_processes", [])},
            ownership_verified=launched.get("process_observation_verified") is True,
        )
        if (all(value is True for value in states) and census["status"] == "PASS"
                or None in states or census["status"] in {"UNKNOWN", "UNAVAILABLE"}
                or time.monotonic() >= deadline):
            break
        time.sleep(0.1)
    result["socket_absent_after_stop"], result["pidfile_absent_after_stop"] = states
    result["process_cleanup"] = census
    launched["cleanup"] = result
    return result


def require_stopped(config: BenchmarkConfig, launched: dict[str, Any] | None = None) -> None:
    result = stop_daemon(config, launched)
    if (result.get("socket_absent_after_stop") is not True
            or result.get("pidfile_absent_after_stop") is not True
            or result.get("process_cleanup", {}).get("status") != "PASS"):
        raise BenchmarkExecutionError("unsafe_cleanup_state", {"cleanup": result})


def _daemon_peer_identity(config: BenchmarkConfig, peer: socket.socket) -> dict[str, str]:
    """Bind an already connected Unix peer to private state and proc generation."""
    from scripts.final_verify import VerificationFailure, _process_identity, _read_private_regular

    before = config.socket_path.lstat()
    if (not stat.S_ISSOCK(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_uid != os.getuid()):
        raise VerificationFailure("benchmark daemon socket is unsafe")
    option = getattr(socket, "SO_PEERCRED", None)
    if option is None:
        raise VerificationFailure("benchmark daemon peer credentials unavailable")
    pid, uid, _gid = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, option, 12))
    payload = _read_private_regular(config.pidfile, "benchmark daemon PID", 32)
    if (not 1 <= pid < 2**31 or uid != os.getuid()
            or re.fullmatch(rb"[1-9][0-9]{0,9}\n?", payload) is None
            or int(payload) != pid):
        raise VerificationFailure("benchmark daemon peer identity differs")
    entry = Path("/proc") / str(pid)
    identity = _process_identity(entry)
    after = config.socket_path.lstat()
    if (identity != _process_identity(entry)
            or (before.st_dev, before.st_ino, before.st_uid, before.st_mode)
            != (after.st_dev, after.st_ino, after.st_uid, after.st_mode)
            or payload != _read_private_regular(config.pidfile, "benchmark daemon PID", 32)):
        raise VerificationFailure("benchmark daemon identity changed")
    return {"pid": str(pid), "start_ticks": identity["start_ticks"]}


def start_daemon(config: BenchmarkConfig, backend: str) -> dict[str, Any]:
    from scripts.final_verify import VerificationFailure, _process_snapshot, _record_process_tree

    baseline = _process_snapshot()
    if baseline["status"] != "PASS":
        raise BenchmarkExecutionError("process_evidence_unavailable", {"process_baseline": baseline})
    started = time.perf_counter()
    result = run_capture(
        [config.tbp, "start", "--browser", backend, "--json"], timeout=120
    )
    result["start_to_command_exit_ms"] = round(
        (time.perf_counter() - started) * 1000, 3
    )
    ready = False
    ready_ms = None
    result.update(daemon_identity_verified=False, process_baseline=baseline)
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
                try:
                    identity = _daemon_peer_identity(config, probe)
                    live = _process_snapshot()
                    observed: set[tuple[str, str]] = set()
                    pid = identity["pid"]
                    if (baseline["processes"].get(pid, {}).get("start_ticks") == identity["start_ticks"]
                            or live["processes"].get(pid, {}).get("start_ticks") != identity["start_ticks"]):
                        raise VerificationFailure("benchmark daemon launch ownership unverified")
                    ancestry_verified = _record_process_tree(live, int(pid), observed)
                    result.update(daemon_identity_verified=True, daemon_identity=identity,
                                  observed_processes=sorted(observed), process_ready=live,
                                  process_observation_verified=ancestry_verified)
                except (VerificationFailure, OSError, ValueError, struct.error) as exc:
                    result["identity_failure"] = {"type": type(exc).__name__, "message": repr(exc)[:8192]}
                break
            finally:
                probe.close()
        time.sleep(0.1)
    result["start_to_socket_ready_ms"] = (
        round(ready_ms, 3) if ready_ms is not None else None
    )
    result["socket_ready_verified"] = ready
    result["pid"] = result.get("daemon_identity", {}).get("pid")
    return result


def is_success(response: object) -> bool:
    return isinstance(response, dict) and response.get("success") is True


async def measured_command(
    action: str,
    params: dict[str, Any],
    backend: str,
    timeout: int = 120,
    *,
    launched: dict[str, Any] | None = None,
) -> tuple[float, dict[str, Any] | None, str | None]:
    from src.client import send_command

    if launched is not None:
        _observe_daemon(launched)
    started = time.perf_counter()
    try:
        response = await send_command(
            action, params, timeout=timeout, browser=backend, autostart=False
        )
        elapsed = (time.perf_counter() - started) * 1000
        error = None if is_success(response) else json.dumps(response, ensure_ascii=False)
        return elapsed, response, error
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return elapsed, None, repr(exc)
    finally:
        if launched is not None:
            _observe_daemon(launched)


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
    from scripts.final_verify import validate_png_file

    return validate_png_file(path)


def post_run_checks(
    config: BenchmarkConfig, report: dict[str, Any], authority: dict[str, Any],
) -> dict[str, Any]:
    """Read each independent checkpoint once, even if an earlier one failed."""
    from scripts.final_verify import VerificationFailure, _git_preflight

    checks: dict[str, Any] = {"pngs": []}
    for name, readback in (
        ("environment", lambda: authorize_benchmark(config) == authority),
        ("checkout", lambda: _git_preflight(config.project_root, authority["commit"])),
    ):
        try:
            verified = bool(readback())
            checks[name] = {"status": "PASS" if verified else "FAIL",
                            "reason": None if verified else "identity_mismatch"}
        except Exception as exc:
            os_error = next((error for error in (exc, exc.__cause__)
                             if isinstance(error, OSError)), None)
            if os_error is not None:
                checks[name] = {"status": "UNAVAILABLE", "reason": "read_failed",
                                "errno": os_error.errno}
            else:
                rejected = isinstance(exc, (BenchmarkAuthorityError, VerificationFailure))
                checks[name] = {"status": "FAIL" if rejected else "UNKNOWN",
                                "reason": "verification_rejected" if rejected else "verification_failed"}
            report.setdefault("post_run_errors", []).append({
                "stage": name, "type": type(exc).__name__, "message": repr(exc)[:8192],
            })

    for backend in config.backends:
        recorded = [item for item in report["backends"] if item.get("backend") == backend]
        screenshots = recorded[0].get("screenshots", []) if len(recorded) == 1 else []
        for sample in range(1, config.screenshot_samples + 1):
            # Never follow a path supplied by a daemon response or raw report.
            try:
                actual = file_check(config.output / backend / f"screenshot-{sample}.png")
            except Exception as exc:
                actual = {"status": "UNKNOWN", "reason": "verification_failed",
                          "valid_png": False, "bytes": None}
                report.setdefault("post_run_errors", []).append({
                    "stage": f"{backend}.png.{sample}",
                    "type": type(exc).__name__, "message": repr(exc)[:8192],
                })
            actual.pop("path", None)
            expected = [item for item in screenshots if item.get("sample") == sample]
            if actual["valid_png"]:
                if len(expected) != 1:
                    actual.update(status="UNKNOWN", reason="unbound_sample")
                elif any(expected[0].get(key) != actual.get(key)
                         for key in ("sha256", "bytes", "width", "height", "mode")):
                    actual.update(status="FAIL", reason="artifact_changed")
            checks["pngs"].append({"backend": backend, "sample": sample, **actual})
    return checks


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


async def benchmark_backend(
    config: BenchmarkConfig, backend: str, launches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    launches = [] if launches is None else launches
    backend_dir = config.output / backend
    backend_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    cold: list[dict[str, Any]] = []
    for sample in range(config.cold_samples):
        require_stopped(config, launches[-1] if launches else None)
        result = start_daemon(config, backend)
        launches.append(result)
        result["sample"] = sample + 1
        cold.append(result)
        require_stopped(config, result)
        if (result.get("returncode") != 0 or result.get("socket_ready_verified") is not True
                or result.get("daemon_identity_verified") is not True
                or result.get("process_observation_verified") is not True):
            raise BenchmarkExecutionError("cold_start_failed", {"cold_start_samples": cold})

    require_stopped(config, launches[-1] if launches else None)
    warm_start = start_daemon(config, backend)
    launches.append(warm_start)
    if (warm_start.get("returncode") != 0 or warm_start.get("socket_ready_verified") is not True
            or warm_start.get("daemon_identity_verified") is not True
            or warm_start.get("process_observation_verified") is not True):
        raise BenchmarkExecutionError(
            "warm_start_failed", {"cold_start_samples": cold, "warm_start": warm_start}
        )
    load_ms, load_response, load_error = await measured_command(
        "goto", {"url": config.url, "timeout": 45}, backend, timeout=60, launched=warm_start,
    )
    await asyncio.sleep(config.settle_seconds)
    daemon_pid = warm_start.get("pid")
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
                name, params, backend, timeout=timeout, launched=warm_start,
            )
            if error is None and name == "screenshot":
                details = file_check(Path(params["path"]))
                if details["valid_png"]:
                    screenshot_details.append({
                        "sample": sample + 1, "latency_ms": round(elapsed, 3), **details,
                    })
                else:
                    error = "screenshot_artifact_invalid"
            if error is None:
                operation_samples[name].append(elapsed)
            else:
                operation_errors[name].append(
                    {"ms": elapsed, "error": error, "response": response}
                )

    cold_values = [
        item["start_to_socket_ready_ms"]
        for item in cold
        if item.get("socket_ready_verified")
        and item.get("returncode") == 0
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


def evaluate_quality(report: dict[str, Any], config: BenchmarkConfig) -> dict[str, Any]:
    """Require every requested sample, valid artifacts, budgets, and cleanup."""
    counts = {
        "status": config.status_samples,
        "text": config.text_samples,
        "screenshot": config.screenshot_samples,
    }
    budgets = {"status": 300.0, "text": 2000.0, "screenshot": 4000.0}
    checks: dict[str, bool] = {}
    checks["execution_completed"] = report.get("execution_failure") is None
    post_run = report.get("post_run", {})
    checks["environment_after_run"] = post_run.get("environment", {}).get("status") == "PASS"
    checks["checkout_after_run"] = post_run.get("checkout", {}).get("status") == "PASS"
    pngs = post_run.get("pngs", [])
    checks["artifacts_after_run"] = (
        len(pngs) == len(config.backends) * config.screenshot_samples
        and all(item.get("status") == "PASS" for item in pngs)
    )
    backends = report["backends"]
    checks["requested_backends"] = (
        len(backends) == len(config.backends) == len(set(config.backends))
        and {item.get("backend") for item in backends} == set(config.backends)
    )
    for name in config.backends:
        matches = [item for item in backends if item.get("backend") == name]
        if len(matches) != 1:
            continue
        backend = matches[0]
        cold = backend.get("cold_start_stats", {})
        checks[f"{name}.cold_samples"] = (
            cold.get("success_count") == config.cold_samples and cold.get("error_count") == 0
        )
        launches = backend.get("cold_start_samples", [])
        checks[f"{name}.cold_identity"] = (
            len(launches) == config.cold_samples
            and all(item.get("daemon_identity_verified") is True
                    and item.get("process_observation_verified") is True for item in launches)
        )
        warm = backend.get("warm_start", {})
        checks[f"{name}.warm_start"] = (
            warm.get("returncode") == 0 and warm.get("socket_ready_verified") is True
            and warm.get("daemon_identity_verified") is True
            and warm.get("process_observation_verified") is True
        )
        page = backend.get("page_load", {})
        checks[f"{name}.page_load"] = (
            is_success(page.get("response")) and page.get("error") is None
        )
        for operation, count in counts.items():
            values = backend.get("operations", {}).get(operation, {})
            checks[f"{name}.{operation}.samples"] = (
                values.get("success_count") == count and values.get("error_count") == 0
                and not backend.get("operation_errors", {}).get(operation)
            )
            median = values.get("median_ms")
            checks[f"{name}.{operation}.latency"] = (
                type(median) in (float, int) and math.isfinite(median)
                and 0 <= median <= budgets[operation]
            )
        screenshots = backend.get("screenshots", [])
        checks[f"{name}.artifacts"] = (
            len(screenshots) == config.screenshot_samples
            and all(isinstance(item, dict) and item.get("valid_png") is True
                    for item in screenshots)
        )
    cleanup = report.get("cleanup", {})
    checks["daemon_cleanup"] = (
        cleanup.get("socket_absent_after_stop") is True
        and cleanup.get("pidfile_absent_after_stop") is True
    )
    checks["process_cleanup"] = cleanup.get("process_cleanup", {}).get("status") == "PASS"
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "latency_budgets_ms": budgets,
        "expected_samples": {"cold": config.cold_samples, **counts},
    }


def sanitize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Remove local paths, PIDs, process arguments, and raw command output."""

    raw_cleanup = report.get("cleanup", {})
    if not isinstance(raw_cleanup, dict):
        raw_cleanup = {}
    cleanup = {
        key: raw_cleanup.get(key) if type(raw_cleanup.get(key)) is bool else None
        for key in ("socket_absent_after_stop", "pidfile_absent_after_stop")
    }
    cleanup_status = (
        "FAIL" if any(value is False for value in cleanup.values())
        else "UNKNOWN" if None in cleanup.values() else "PASS"
    )
    failure = report.get("execution_failure")
    public_failure = None
    if isinstance(failure, dict):
        reason = failure.get("reason")
        backend = failure.get("backend")
        public_failure = {
            "backend": backend if backend in ("firefox", "chromium") else None,
            "reason": reason if reason in (
                "unsafe_cleanup_state", "cold_start_failed", "warm_start_failed",
                "process_evidence_unavailable",
            ) else "execution_failed",
        }
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
        error_counts = {}
        for name in ("status", "text", "screenshot"):
            counts = {"artifact_invalid": 0, "command_failed": 0}
            for item in backend.get("operation_errors", {}).get(name, []):
                category = (
                    "artifact_invalid" if isinstance(item, dict)
                    and item.get("error") == "screenshot_artifact_invalid" else "command_failed"
                )
                counts[category] += 1
            error_counts[name] = counts
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
                "operation_error_counts": error_counts,
                "page_load": {
                    "latency_ms": backend.get("page_load", {}).get("latency_ms"),
                    "success": is_success(response),
                    "url": response_data.get("url"),
                    "title": response_data.get("title"),
                    "error": (
                        "page_load_failed" if backend.get("page_load", {}).get("error") else None
                    ),
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
                        isinstance(item, dict) and item.get("valid_png") is True
                        for item in screenshots
                    ),
                },
            }
        )
    post_run = report.get("post_run", {})
    allowed_statuses = {"PASS", "FAIL", "UNKNOWN", "UNAVAILABLE"}
    raw_processes = raw_cleanup.get("process_cleanup", {})
    if not isinstance(raw_processes, dict):
        raw_processes = {}
    process_summary = {
        "scope": raw_processes.get("scope") if raw_processes.get("scope") in {
            "visible_same_uid_processes", "no_recorded_launch",
        } else "unknown",
        "status": raw_processes.get("status")
        if raw_processes.get("status") in allowed_statuses else "UNKNOWN",
        **{key: raw_processes.get(key) if type(raw_processes.get(key)) is int
           and raw_processes[key] >= 0 else None for key in (
               "new_process_count", "observed_candidate_count", "observed_candidate_survivors",
               "unattributed_new_process_count",
           )},
    }
    post_summary = {
        name: post_run.get(name, {}).get("status")
        if post_run.get(name, {}).get("status") in allowed_statuses else "UNKNOWN"
        for name in ("environment", "checkout")
    }
    post_summary["png_counts"] = {status: 0 for status in sorted(allowed_statuses)}
    for item in post_run.get("pngs", []):
        status = item.get("status")
        post_summary["png_counts"][status if status in allowed_statuses else "UNKNOWN"] += 1
    return {
        "schema_version": 2,
        "quality": report.get("quality", {"status": "NOT_EVALUATED"}),
        "post_run": post_summary,
        "cleanup": {"scope": "daemon_files_only", "status": cleanup_status, **cleanup},
        "process_cleanup": process_summary,
        "execution_failure": public_failure,
        "environment": environment_summary,
        "backends": backend_summaries,
        "privacy": {
            "contains_process_arguments": False,
            "contains_absolute_artifact_paths": False,
            "raw_report_is_separate": True,
        },
    }


def benchmark_summary_ko(summary: dict[str, Any]) -> str:
    """Describe the completed run without promoting file absence into process proof."""
    quality = summary.get("quality", {}).get("status")
    quality = quality if quality in {"PASS", "FAIL"} else "UNKNOWN"
    cleanup = summary["cleanup"]["status"]
    return "\n".join((
        "실행: 종료 (일부 측정이 미실행일 수 있음)",
        f"Benchmark 품질: {quality}",
        f"Daemon socket·pidfile 확인: {cleanup}",
        f"후보 프로세스 관측: {summary['process_cleanup']['status']} "
        f"(범위: {summary['process_cleanup']['scope']})",
        f"사후 환경 확인: {summary['post_run']['environment']}",
        f"사후 Git 확인: {summary['post_run']['checkout']}",
        f"사후 PNG 확인: {summary['post_run']['png_counts']}",
        "프로세스·display lease·session lock: 별도 확인 필요",
        "전역 Unix 소켓 목록: 이 검사에서는 조회하지 않음",
        "추가 작업: 소유 자원의 종료 증거 검토; 동일 회차를 재실행하지 않음",
        "Production 승인: 미승인",
        "",
    ))


def write_private_json(path: Path, value: object) -> bytes:
    from scripts.final_verify import _write_private_bytes

    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _write_private_bytes(path, encoded)
    return encoded


def parse_args(argv: Sequence[str] | None = None) -> BenchmarkConfig:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=repository)
    parser.add_argument("--tbp", type=Path, default=None)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--canonical-manifest", type=Path, required=True)
    parser.add_argument("--isolated-runtime", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--socket", dest="socket_path", type=Path)
    parser.add_argument("--pidfile", type=Path)
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
    if args.backend and len(args.backend) != len(set(args.backend)):
        parser.error("each backend may be measured only once per output identity")

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
    runtime = (
        Path(os.path.abspath(os.fspath(args.isolated_runtime.expanduser())))
        if args.isolated_runtime is not None else None
    )
    if runtime is not None and any(
        item is not None for item in (args.output, args.socket_path, args.pidfile)
    ):
        parser.error("--isolated-runtime derives --output, --socket and --pidfile")
    home = runtime / "h" if runtime is not None else Path.home()
    output = args.output or (
        home / "benchmark" if runtime is not None else home / ".cache/termuinator/benchmark"
    )
    return BenchmarkConfig(
        project_root=project_root,
        tbp=tbp,
        wheel=wheel,
        canonical_manifest=canonical_manifest,
        output=Path(os.path.abspath(os.fspath(output.expanduser()))),
        socket_path=Path(os.path.abspath(os.fspath(
            (args.socket_path or home / ".tbp/daemon.sock").expanduser()
        ))),
        pidfile=Path(os.path.abspath(os.fspath(
            (args.pidfile or home / ".tbp/daemon.pid").expanduser()
        ))),
        url=args.url,
        backends=tuple(args.backend or ("firefox", "chromium")),
        cold_samples=args.cold_samples,
        status_samples=args.status_samples,
        text_samples=args.text_samples,
        screenshot_samples=args.screenshot_samples,
        settle_seconds=args.settle_seconds,
        network_kind=args.network_kind,
        tailscale_termux_state=args.tailscale_termux_state,
        isolated_runtime=runtime,
    )


def validate_daemon_paths(config: BenchmarkConfig) -> None:
    """CLI, cached client constants and probes must select the same daemon."""
    from src import client
    from scripts.final_verify import _path_absent

    runtime = Path.home() / ".tbp"
    expected = (runtime / "daemon.sock", runtime / "daemon.pid")
    if (
        (config.socket_path, config.pidfile) != expected
        or (Path(client.SOCKET_PATH), Path(client.PID_PATH)) != expected
    ):
        raise BenchmarkAuthorityError("benchmark daemon paths differ from current HOME")
    # An absent runtime cannot contain sockets or symlinks. lstat also rejects
    # a dangling runtime link and preserves access errors on every Python version.
    if _path_absent(runtime) is not True:
        raise BenchmarkAuthorityError(
            "benchmark runtime already exists or is unreadable; use a fresh isolated HOME"
        )


def run_isolated_benchmark(config: BenchmarkConfig) -> int:
    """Prepare a fresh child HOME and launch once; never mutate the parent's HOME."""
    from scripts.final_verify import VerificationFailure, _child_environment

    authorize_benchmark(config)
    if config.isolated_runtime is None:
        raise BenchmarkAuthorityError("isolated runtime is required")
    prepare_benchmark_output(config.isolated_runtime)
    try:
        environ, paths = _child_environment(config.isolated_runtime, owner_scope="benchmark")
    except VerificationFailure as exc:
        raise BenchmarkAuthorityError("isolated runtime could not be prepared") from exc
    output = paths["home"] / "benchmark"
    argv = [
        sys.executable, os.fspath(config.project_root / "scripts/benchmark_device.py"),
        "--project-root", os.fspath(config.project_root), "--tbp", os.fspath(config.tbp),
        "--wheel", os.fspath(config.wheel),
        "--canonical-manifest", os.fspath(config.canonical_manifest),
        "--output", os.fspath(output),
        "--url", config.url, "--network-kind", config.network_kind,
        "--tailscale-termux-state", config.tailscale_termux_state,
        "--cold-samples", str(config.cold_samples), "--status-samples", str(config.status_samples),
        "--text-samples", str(config.text_samples),
        "--screenshot-samples", str(config.screenshot_samples),
        "--settle-seconds", str(config.settle_seconds),
    ]
    for backend in config.backends:
        argv.extend(["--backend", backend])
    try:
        return subprocess.run(
            argv, cwd=config.project_root, env=environ, umask=0o077, check=False,
        ).returncode
    except OSError as exc:
        raise BenchmarkAuthorityError("isolated benchmark could not be launched") from exc


async def run_benchmark(config: BenchmarkConfig) -> tuple[Path, Path, dict[str, Any]]:
    from scripts.final_verify import (
        VerificationFailure, _path_absent, _write_private_bytes, write_return_file_manifest,
    )

    authority = authorize_benchmark(config)
    validate_daemon_paths(config)
    prepare_benchmark_output(config.output)
    report: dict[str, Any] = {
        "environment": {
            "python": sys.version,
            "canonical_authority": authority,
        },
        "backends": [],
        "process_launches": [],
    }
    backend = None
    try:
        report["environment"].update(environment(config))
        for backend in config.backends:
            report["backends"].append(await benchmark_backend(config, backend, report["process_launches"]))
    except BenchmarkExecutionError as exc:
        report["execution_failure"] = {
            "backend": backend, "reason": str(exc), "evidence": exc.evidence,
        }
    except (Exception, asyncio.CancelledError) as exc:
        report["execution_failure"] = {
            "backend": backend, "reason": "execution_failed",
            "evidence": {"type": type(exc).__name__, "message": repr(exc)[:8192]},
        }
    finally:
        try:
            report["cleanup"] = stop_daemon(
                config, report["process_launches"][-1] if report["process_launches"] else None,
            ) if backend is not None else {
                "socket_absent_after_stop": _path_absent(config.socket_path),
                "pidfile_absent_after_stop": _path_absent(config.pidfile),
            }
        except Exception as exc:
            report["cleanup"] = {
                "socket_absent_after_stop": None, "pidfile_absent_after_stop": None,
                "type": type(exc).__name__, "message": repr(exc)[:8192],
            }
    report["post_run"] = post_run_checks(config, report, authority)
    raw_path = config.output / "baseline-report.json"
    summary_path = config.output / "baseline-summary.json"
    report["quality"] = evaluate_quality(report, config)
    summary = sanitize_report(report)
    summary["return_files_manifest"] = "baseline-files.json"
    write_private_json(raw_path, report)
    summary_bytes = write_private_json(summary_path, summary)
    note_bytes = benchmark_summary_ko(summary).encode("utf-8")
    _write_private_bytes(
        config.output / "baseline-summary.ko.txt", note_bytes,
    )
    publication = write_return_file_manifest(config.output / "baseline-files.json", {
        summary_path.name: summary_bytes, "baseline-summary.ko.txt": note_bytes,
    })
    if publication["status"] != "PASS":
        raise VerificationFailure("benchmark return-file verification failed")
    return raw_path, summary_path, summary


def main(argv: Sequence[str] | None = None) -> int:
    config = parse_args(argv)
    sys.path.insert(0, os.fspath(config.project_root))
    os.chdir(config.project_root)
    from scripts.final_verify import VerificationFailure

    try:
        if config.isolated_runtime is not None:
            return run_isolated_benchmark(config)
        raw_path, summary_path, summary = asyncio.run(run_benchmark(config))
    except BenchmarkAuthorityError as exc:
        print(f"benchmark_authority_error={exc}", file=sys.stderr)
        return 2
    except VerificationFailure:
        print("report_publication=FAIL; preserve reports and inspect baseline-files.json")
        return 1
    print(f"raw_report={raw_path}")
    print(f"sanitized_summary={summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("quality", {}).get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
