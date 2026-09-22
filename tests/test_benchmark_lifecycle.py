"""Benchmark failures must not silently restart or cross daemon identities."""

from __future__ import annotations

import asyncio
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from scripts import benchmark_device as benchmark
from src import client


ROOT = Path(__file__).resolve().parents[1]
CLEAN = {"socket_absent_after_stop": True, "pidfile_absent_after_stop": True}
STARTED = {"returncode": 0, "socket_ready_verified": True,
           "start_to_socket_ready_ms": 1.0}


class BenchmarkLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="b")
        self.addCleanup(self.temp.cleanup)
        # Preserve the system's short temporary spelling (e.g. /var on macOS).
        # Resolving its alias can exceed the production Unix socket length gate.
        self.home = Path(self.temp.name)
        self.config = benchmark.BenchmarkConfig(
            project_root=ROOT, tbp=Path(sys.executable), wheel=self.home / "wheel.whl",
            canonical_manifest=self.home / "manifest.json", output=self.home / "out",
            socket_path=self.home / ".tbp/daemon.sock", pidfile=self.home / ".tbp/daemon.pid",
            url="http://127.0.0.1/forms", backends=("firefox", "chromium"),
            cold_samples=1, status_samples=1, text_samples=1, screenshot_samples=1,
            settle_seconds=0, network_kind="fixture", tailscale_termux_state="unchanged",
        )
        for manager in (
            patch.dict(os.environ, {"HOME": str(self.home)}),
            patch.object(client, "SOCKET_PATH", str(self.config.socket_path)),
            patch.object(client, "PID_PATH", str(self.config.pidfile)),
        ):
            manager.start()
            self.addCleanup(manager.stop)

    def run_with_process_results(self, stops, starts):
        with (
            patch.object(benchmark, "authorize_benchmark", return_value={"commit": "a"}),
            patch.object(benchmark, "environment", return_value={"python": "3.14"}),
            patch.object(benchmark, "stop_daemon", side_effect=stops),
            patch.object(benchmark, "start_daemon", side_effect=starts) as start,
            patch.object(benchmark, "measured_command", new_callable=AsyncMock,
                         return_value=(1.0, {"success": True}, None)) as command,
            patch.object(benchmark, "ps_snapshot", return_value={
                "requested_command": [], "requested_returncode": 0,
                "requested_stdout": "", "requested_stderr": "", "effective_command": [],
                "effective_returncode": 0, "effective_stdout": "", "effective_stderr": "",
            }),
        ):
            _, _, summary = asyncio.run(benchmark.run_benchmark(self.config))
        return summary, start, command

    def test_failed_transition_cleanup_stops_before_any_start(self) -> None:
        dirty = {**CLEAN, "socket_absent_after_stop": False}
        summary, start, command = self.run_with_process_results(
            lambda *_: dirty, lambda *_: dict(STARTED)
        )
        self.assertEqual(start.call_count, 0)
        self.assertEqual(command.await_count, 0)
        self.assertEqual(summary["quality"]["status"], "FAIL")
        self.assertEqual(summary.get("execution_failure", {}).get("reason"),
                         "unsafe_cleanup_state")

    def test_warm_start_failure_does_not_issue_goto_or_try_next_backend(self) -> None:
        starts = iter([dict(STARTED), {"returncode": 1, "socket_ready_verified": False}])
        summary, start, command = self.run_with_process_results(
            lambda *_: dict(CLEAN), lambda *_: next(starts, dict(STARTED))
        )
        self.assertEqual(command.await_count, 0)
        self.assertEqual(start.call_count, 2)
        self.assertEqual(summary.get("execution_failure", {}).get("reason"),
                         "warm_start_failed")

    def test_start_failure_retains_private_diagnostics_but_not_in_summary(self) -> None:
        failure = {"returncode": 1, "socket_ready_verified": False,
                   "stderr": "private startup token=SECRET"}
        starts = iter([dict(STARTED), failure])
        summary, _, _ = self.run_with_process_results(
            lambda *_: dict(CLEAN), lambda *_: next(starts)
        )
        raw = json.loads((self.config.output / "baseline-report.json").read_text())
        evidence = raw["execution_failure"].get("evidence", {})
        self.assertEqual(evidence.get("warm_start"), failure)
        self.assertNotIn("SECRET", json.dumps(summary))
        self.assertEqual((self.config.output / "baseline-report.json").stat().st_mode & 0o777,
                         0o600)

    def test_measured_command_does_not_autostart_a_missing_daemon(self) -> None:
        with patch.object(client, "ensure_daemon", new_callable=AsyncMock) as ensure:
            _, response, error = asyncio.run(benchmark.measured_command("status", {}, "firefox"))
        self.assertIsNone(response)
        self.assertIsNotNone(error)
        self.assertEqual(ensure.await_count, 0)

    def test_client_default_autostart_and_opt_out_preserve_protocol(self) -> None:
        for kwargs, expected_ensure in (({}, 1), ({"autostart": False}, 0)):
            with self.subTest(kwargs=kwargs):
                reader = SimpleNamespace(readline=AsyncMock(
                    return_value=b'{"success":true,"data":{"browser":"firefox"}}\n'
                ))
                writer = SimpleNamespace(write=Mock(), drain=AsyncMock(), close=Mock(),
                                         wait_closed=AsyncMock())
                with (
                    patch.object(client, "ensure_daemon", new_callable=AsyncMock) as ensure,
                    patch.object(client.asyncio, "open_unix_connection", new_callable=AsyncMock,
                                 return_value=(reader, writer)),
                ):
                    result = asyncio.run(client.send_command("status", **kwargs))
                self.assertEqual(result["data"]["browser"], "firefox")
                self.assertEqual(json.loads(writer.write.call_args.args[0]),
                                 {"id": 1, "action": "status", "params": {}})
                self.assertEqual(ensure.await_count, expected_ensure)
                self.assertEqual(writer.wait_closed.await_count, 1)

    def test_existing_runtime_is_preserved_before_any_stop_or_output(self) -> None:
        self.config.pidfile.parent.mkdir()
        self.config.pidfile.write_text("12345\n", encoding="ascii")
        with (
            patch.object(benchmark, "authorize_benchmark", return_value={}),
            patch.object(benchmark, "environment", return_value={"python": "3.14"}),
            patch.object(benchmark, "benchmark_backend", new_callable=AsyncMock,
                         return_value={"backend": "firefox"}),
            patch.object(benchmark, "stop_daemon", return_value=CLEAN) as stop,
        ):
            with self.assertRaisesRegex(
                benchmark.BenchmarkAuthorityError, "runtime already exists"
            ):
                asyncio.run(benchmark.run_benchmark(self.config))
        self.assertEqual(stop.call_count, 0)
        self.assertFalse(self.config.output.exists())
        self.assertEqual(self.config.pidfile.read_text(), "12345\n")

    def test_cold_start_failure_aborts_without_retry(self) -> None:
        summary, start, command = self.run_with_process_results(
            lambda *_: dict(CLEAN),
            lambda *_: {"returncode": 1, "socket_ready_verified": False},
        )
        self.assertEqual(start.call_count, 1)
        self.assertEqual(command.await_count, 0)
        self.assertEqual(summary["execution_failure"]["reason"], "cold_start_failed")

    def test_isolated_cli_rejects_path_overrides_and_reuse(self) -> None:
        runtime = self.home / "r"
        self.config.wheel.write_bytes(b"wheel")
        self.config.canonical_manifest.write_text("{}", encoding="utf-8")
        args = ["--project-root", str(ROOT), "--tbp", sys.executable,
                "--wheel", str(self.config.wheel), "--canonical-manifest",
                str(self.config.canonical_manifest), "--isolated-runtime", str(runtime)]
        for option in ("--output", "--socket", "--pidfile"):
            with self.subTest(option=option), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    benchmark.parse_args(args + [option, str(self.home / "override")])
        runtime.mkdir(mode=0o700)
        (runtime / "keep").write_text("preserve", encoding="ascii")
        with (
            patch.object(benchmark, "authorize_benchmark", return_value={}),
            patch.object(benchmark.subprocess, "run") as child,
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(benchmark.main(args), 2)
        self.assertEqual(child.call_count, 0)
        self.assertEqual((runtime / "keep").read_text(), "preserve")

    def test_duplicate_backends_are_rejected_before_execution(self) -> None:
        self.config.wheel.write_bytes(b"wheel")
        self.config.canonical_manifest.write_text("{}", encoding="utf-8")
        args = ["--project-root", str(ROOT), "--tbp", sys.executable,
                "--wheel", str(self.config.wheel), "--canonical-manifest",
                str(self.config.canonical_manifest), "--backend", "firefox",
                "--backend", "firefox"]
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                benchmark.parse_args(args)

    def test_sanitized_errors_expose_only_fixed_category_counts(self) -> None:
        raw = {
            "environment": {"python": "3.14"},
            "backends": [{"backend": "firefox", "operation_errors": {
                "screenshot": [
                    {"error": "screenshot_artifact_invalid"},
                    {"error": "private /home/key token=SECRET", "response": {"secret": "x"}},
                ],
                "text": [{"error": "private body"}],
            }}],
        }
        summary = benchmark.sanitize_report(raw)
        counts = summary["backends"][0].get("operation_error_counts", {})
        self.assertEqual(counts.get("screenshot"), {"artifact_invalid": 1, "command_failed": 1})
        self.assertEqual(counts.get("text"), {"artifact_invalid": 0, "command_failed": 1})
        self.assertNotIn("SECRET", json.dumps(summary))
        self.assertNotIn("private", json.dumps(summary))

    def test_custom_probe_paths_cannot_select_a_different_cli_target(self) -> None:
        config = replace(self.config, socket_path=self.home / "not-the-daemon.sock")
        with (
            patch.object(benchmark, "authorize_benchmark", return_value={}),
            patch.object(benchmark, "environment", return_value={"python": "3.14"}),
            patch.object(benchmark, "benchmark_backend", new_callable=AsyncMock,
                         return_value={"backend": "firefox"}),
            patch.object(benchmark, "stop_daemon", return_value=CLEAN) as stop,
        ):
            with self.assertRaisesRegex(benchmark.BenchmarkAuthorityError, "daemon paths"):
                asyncio.run(benchmark.run_benchmark(config))
        self.assertEqual(stop.call_count, 0)
        self.assertFalse(config.output.exists())

    def test_cached_client_paths_must_match_the_current_home(self) -> None:
        with (
            patch.object(client, "SOCKET_PATH", str(self.home / "old.sock")),
            patch.object(benchmark, "authorize_benchmark", return_value={}),
            patch.object(benchmark, "environment", return_value={"python": "3.14"}),
            patch.object(benchmark, "benchmark_backend", new_callable=AsyncMock,
                         return_value={"backend": "firefox"}),
            patch.object(benchmark, "stop_daemon", return_value=CLEAN) as stop,
        ):
            with self.assertRaisesRegex(benchmark.BenchmarkAuthorityError, "daemon paths"):
                asyncio.run(benchmark.run_benchmark(self.config))
        self.assertEqual(stop.call_count, 0)

    def test_dangling_socket_is_not_absent_cleanup(self) -> None:
        self.config.socket_path.parent.mkdir()
        self.config.socket_path.symlink_to(self.home / "missing")
        with (
            patch.object(benchmark, "run_capture", return_value={"returncode": 0}),
            patch.object(benchmark.time, "monotonic", side_effect=[0.0, 16.0]),
        ):
            result = benchmark.stop_daemon(self.config)
        self.assertIs(result["socket_absent_after_stop"], False)

    def test_isolated_cli_derives_output_from_child_home_without_changing_parent(self) -> None:
        runtime = self.home / "r"
        self.config.wheel.write_bytes(b"wheel")
        self.config.canonical_manifest.write_text("{}", encoding="utf-8")
        args = ["--project-root", str(ROOT), "--tbp", sys.executable,
                "--wheel", str(self.config.wheel), "--canonical-manifest",
                str(self.config.canonical_manifest), "--isolated-runtime", str(runtime)]
        with redirect_stderr(io.StringIO()):
            try:
                config = benchmark.parse_args(args)
            except SystemExit:
                self.fail("isolated-runtime must be a supported benchmark option")
        self.assertEqual(config.output, runtime / "h/benchmark")
        with (
            patch.object(benchmark, "authorize_benchmark", return_value={}),
            patch.object(benchmark.subprocess, "run", return_value=SimpleNamespace(returncode=1))
            as child,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(benchmark.main(args), 1)
        kwargs = child.call_args.kwargs
        argv = child.call_args.args[0]
        self.assertEqual(kwargs["env"]["HOME"], str(runtime / "h"))
        self.assertEqual(kwargs["umask"], 0o077)
        self.assertNotIn("--isolated-runtime", argv)
        self.assertEqual(argv[argv.index("--output") + 1], str(runtime / "h/benchmark"))
        self.assertEqual(os.environ["HOME"], str(self.home))
        self.assertFalse(config.output.exists())  # Only the real child may consume output.


if __name__ == "__main__":
    unittest.main()
