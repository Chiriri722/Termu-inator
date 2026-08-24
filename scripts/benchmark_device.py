#!/usr/bin/env python3
"""Portable Firefox/Chromium benchmark for an existing Termu-inator install.

The harness changes no package or repository configuration. It starts and
stops the browser daemon, writes private raw diagnostics to the selected output
directory, and emits a separate sanitized summary suitable for review.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import statistics
import subprocess
import sys
import time
from typing import Any, Sequence


@dataclass(frozen=True)
class BenchmarkConfig:
    project_root: Path
    tbp: Path
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
    project_root = args.project_root.expanduser().resolve()
    if not (project_root / "src" / "client.py").is_file():
        parser.error(f"project root does not contain src/client.py: {project_root}")
    if not tbp.is_file() or not os.access(tbp, os.X_OK):
        parser.error(f"tbp is not executable: {tbp}")
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
        output=args.output.expanduser().resolve(),
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
    config.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    config.output.chmod(0o700)
    report: dict[str, Any] = {"environment": environment(config), "backends": []}
    try:
        for backend in config.backends:
            report["backends"].append(await benchmark_backend(config, backend))
    finally:
        stop_daemon(config)
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
    raw_path, summary_path, summary = asyncio.run(run_benchmark(config))
    print(f"raw_report={raw_path}")
    print(f"sanitized_summary={summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
