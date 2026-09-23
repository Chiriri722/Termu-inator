"""Benchmark failures must not silently restart or cross daemon identities."""

from __future__ import annotations

import asyncio
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import errno
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from scripts import benchmark_device as benchmark
from scripts import final_verify
from src import client


ROOT = Path(__file__).resolve().parents[1]
CLEAN = {"socket_absent_after_stop": True, "pidfile_absent_after_stop": True,
         "process_cleanup": {"status": "PASS"}}
STARTED = {"returncode": 0, "socket_ready_verified": True,
           "start_to_socket_ready_ms": 1.0, "daemon_identity_verified": True,
           "process_observation_verified": True}


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

    def start_with_peer(self, *, peer_pid=12345, peer_uid=None, pidfile_pid=12345, live_status="PASS"):
        self.config.socket_path.parent.mkdir(mode=0o700)
        self.config.pidfile.write_text(str(pidfile_pid))
        self.config.pidfile.chmod(0o600)
        peer = SimpleNamespace(
            settimeout=lambda *_: None, connect=lambda *_: None, close=lambda: None,
            getsockopt=lambda *_: struct.pack(
                "3i", peer_pid, os.getuid() if peer_uid is None else peer_uid, os.getgid(),
            ),
        )
        identity = {"parent_pid": "1", "start_ticks": "100"}
        empty = {"status": "PASS", "processes": {}, "error_counts": {}}
        live = {**empty, "status": live_status, "processes": {str(peer_pid): identity}}
        # Real private Unix socket metadata; only Linux-only peer/proc reads are simulated.
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(self.config.socket_path))
            self.config.socket_path.chmod(0o600)
            with (
                patch.object(benchmark.socket, "SO_PEERCRED", 17, create=True),
                patch.object(benchmark.socket, "socket", return_value=peer),
                patch.object(benchmark, "run_capture", return_value={"returncode": 0}),
                patch.object(final_verify, "_process_identity", return_value=identity),
                patch.object(final_verify, "_process_snapshot", side_effect=[empty, live]),
            ):
                return benchmark.start_daemon(self.config, "firefox")

    def test_start_binds_daemon_to_socket_peer_pidfile_and_generation(self) -> None:
        result = self.start_with_peer()
        self.assertIs(result.get("daemon_identity_verified"), True)
        self.assertEqual(result.get("daemon_identity"), {"pid": "12345", "start_ticks": "100"})

    def test_start_does_not_trust_a_different_pid_from_private_pidfile(self) -> None:
        result = self.start_with_peer(pidfile_pid=12346)
        self.assertIs(result.get("daemon_identity_verified"), False)

    def test_start_does_not_trust_another_uid_even_with_matching_pid(self) -> None:
        result = self.start_with_peer(peer_uid=os.getuid() + 1)
        self.assertIs(result.get("daemon_identity_verified"), False)

    def test_unavailable_baseline_prevents_daemon_launch(self) -> None:
        with (
            patch.object(final_verify, "_process_snapshot", return_value={
                "status": "UNAVAILABLE", "processes": {}, "errno": errno.EACCES,
            }),
            patch.object(benchmark, "run_capture", return_value={"returncode": 1}) as start,
            patch.object(benchmark.time, "monotonic", side_effect=[0.0, 46.0]),
        ):
            try:
                benchmark.start_daemon(self.config, "firefox")
            except benchmark.BenchmarkExecutionError:
                pass
        start.assert_not_called()

    def test_incomplete_ancestry_keeps_authenticated_daemon_for_safe_shutdown(self) -> None:
        launched = self.start_with_peer(live_status="UNKNOWN")
        self.assertIs(launched.get("daemon_identity_verified"), True)
        self.assertIs(launched.get("process_observation_verified"), False)

    def test_unverified_start_identity_blocks_measurement_and_further_launches(self) -> None:
        summary, start, command = self.run_with_process_results(
            lambda *_: dict(CLEAN), lambda *_: {**STARTED, "daemon_identity_verified": False},
        )
        self.assertEqual(start.call_count, 1)
        self.assertEqual(command.await_count, 0)
        self.assertEqual(summary.get("execution_failure", {}).get("reason"), "cold_start_failed")

    def test_stop_never_runs_a_command_against_unowned_daemon_state(self) -> None:
        self.config.socket_path.parent.mkdir(mode=0o700)
        self.config.socket_path.write_text("not a candidate socket")
        with (patch.object(benchmark, "run_capture", return_value={"returncode": 0}) as command,
              patch.object(benchmark.time, "monotonic", side_effect=[0.0, 16.0])):
            result = benchmark.stop_daemon(self.config)
        self.assertEqual(command.call_count, 0)
        self.assertIs(result["socket_absent_after_stop"], False)

    def test_process_survivor_or_unknown_blocks_transition_even_without_files(self) -> None:
        for status in ("FAIL", "UNKNOWN", "UNAVAILABLE"):
            with self.subTest(status=status), patch.object(benchmark, "stop_daemon", return_value={
                **CLEAN, "process_cleanup": {"status": status},
            }):
                with self.assertRaisesRegex(benchmark.BenchmarkExecutionError, "unsafe_cleanup_state"):
                    benchmark.require_stopped(self.config)

    def test_stop_does_not_send_shutdown_to_a_reused_pid(self) -> None:
        launched = self.start_with_peer()
        current = {"parent_pid": "1", "start_ticks": "200"}
        live = {"status": "PASS", "processes": {"12345": current}, "error_counts": {}}
        peer = SimpleNamespace(
            settimeout=lambda *_: None, connect=lambda *_: None, close=lambda: None,
            getsockopt=lambda *_: struct.pack("3i", 12345, os.getuid(), os.getgid()),
            sendall=Mock(),
        )
        with (
            patch.object(benchmark.socket, "SO_PEERCRED", 17, create=True),
            patch.object(benchmark.socket, "socket", return_value=peer),
            patch.object(final_verify, "_process_identity", return_value=current),
            patch.object(final_verify, "_process_snapshot", return_value=live),
            patch.object(benchmark.time, "monotonic", side_effect=[0.0, 16.0]),
        ):
            try:
                result = benchmark.stop_daemon(self.config, launched)
            except TypeError:
                self.fail("stop must bind to the recorded candidate launch")
        self.assertEqual(peer.sendall.call_count, 0)
        self.assertEqual(result.get("process_cleanup", {}).get("status"), "UNKNOWN")

    def test_verified_shutdown_checks_process_exit_after_socket_files_disappear(self) -> None:
        launched = self.start_with_peer()
        before = launched.get("process_ready", {})
        empty = {"status": "PASS", "processes": {}, "error_counts": {}}

        def shutdown(payload):
            self.assertEqual(json.loads(payload), {"action": "shutdown", "params": {}})
            self.config.socket_path.unlink()
            self.config.pidfile.unlink()

        peer = SimpleNamespace(
            settimeout=lambda *_: None, connect=lambda *_: None, close=lambda: None,
            getsockopt=lambda *_: struct.pack("3i", 12345, os.getuid(), os.getgid()),
            sendall=Mock(side_effect=shutdown),
            makefile=lambda *_: io.BytesIO(b'{"success":true}\n'),
        )
        with (
            patch.object(benchmark.socket, "SO_PEERCRED", 17, create=True),
            patch.object(benchmark.socket, "socket", return_value=peer),
            patch.object(final_verify, "_process_identity", return_value={
                "parent_pid": "1", "start_ticks": "100",
            }),
            patch.object(final_verify, "_process_snapshot", side_effect=[before, empty]),
        ):
            try:
                result = benchmark.stop_daemon(self.config, launched)
            except TypeError:
                self.fail("stop must bind to the recorded candidate launch")
        self.assertEqual(peer.sendall.call_count, 1)
        self.assertEqual(result.get("process_cleanup", {}).get("status"), "PASS")
        self.assertIs(result["socket_absent_after_stop"], True)
        self.assertIs(result["pidfile_absent_after_stop"], True)

    def test_owned_stop_keeps_first_unavailable_file_observation(self) -> None:
        launched = self.start_with_peer()
        empty = {"status": "PASS", "processes": {}, "error_counts": {}}
        with (
            patch.object(final_verify, "_path_absent", side_effect=[None, True, True, True]),
            patch.object(final_verify, "_process_snapshot", return_value=empty),
        ):
            result = benchmark.stop_daemon(self.config, launched)
        self.assertIsNone(result["socket_absent_after_stop"])

    def test_stop_retains_reparented_descendant_after_daemon_files_disappear(self) -> None:
        launched = self.start_with_peer()
        before = launched["process_ready"]
        before["processes"]["12346"] = {"parent_pid": "12345", "start_ticks": "101"}
        after = {"status": "PASS", "error_counts": {}, "processes": {
            "12346": {"parent_pid": "1", "start_ticks": "101"},
        }}
        self.config.socket_path.unlink()
        self.config.pidfile.unlink()
        with (
            patch.object(final_verify, "_process_snapshot", side_effect=[before, after]),
            patch.object(benchmark.time, "monotonic", side_effect=[0.0, 16.0]),
        ):
            result = benchmark.stop_daemon(self.config, launched)
        self.assertIs(result["shutdown_sent"], False)
        self.assertIs(result["socket_absent_after_stop"], True)
        self.assertEqual(result["process_cleanup"]["status"], "FAIL")
        self.assertEqual(result["process_cleanup"]["observed_candidate_survivors"], 1)

    def test_commands_observe_descendants_outside_latency_even_on_failure_or_cancel(self) -> None:
        for outcome in (None, RuntimeError("PRIVATE failure"), asyncio.CancelledError()):
            with self.subTest(outcome=type(outcome).__name__):
                events = []
                launched = {
                    "daemon_identity_verified": True, "process_observation_verified": True,
                    "daemon_identity": {"pid": "12345", "start_ticks": "100"},
                    "observed_processes": [("12345", "100")],
                }

                def snapshot():
                    events.append("observe")
                    return {"status": "PASS", "processes": {
                        "12345": {"parent_pid": "1", "start_ticks": "100"},
                        "12346": {"parent_pid": "12345", "start_ticks": "101"},
                    }}

                def clock():
                    events.append("clock")
                    return 1.0

                async def command(*_args, **_kwargs):
                    events.append("command")
                    if outcome is not None:
                        raise outcome
                    return {"success": True}

                with (
                    patch.object(final_verify, "_process_snapshot", side_effect=snapshot),
                    patch.object(benchmark.time, "perf_counter", side_effect=clock),
                    patch.object(client, "send_command", side_effect=command),
                ):
                    try:
                        asyncio.run(benchmark.measured_command("status", {}, "firefox", launched=launched))
                    except asyncio.CancelledError:
                        self.assertIsInstance(outcome, asyncio.CancelledError)
                    except TypeError:
                        self.fail("measured commands must observe their recorded launch")
                expected = ["observe", "clock", "command"]
                if not isinstance(outcome, asyncio.CancelledError):
                    expected.append("clock")
                self.assertEqual(events, [*expected, "observe"])
                self.assertIn(("12346", "101"), launched["observed_processes"])

    def test_process_observation_failure_remains_unknown_after_successful_readback(self) -> None:
        launched = {"daemon_identity_verified": True, "process_observation_verified": True,
                    "daemon_identity": {"pid": "12345", "start_ticks": "100"}}
        empty = {"status": "PASS", "processes": {}}
        with patch.object(final_verify, "_process_snapshot", side_effect=[
            PermissionError(errno.EACCES, "PRIVATE census"), empty,
        ]):
            benchmark._observe_daemon(launched, allow_exited=True)
            benchmark._observe_daemon(launched, allow_exited=True)
        self.assertIs(launched["process_observation_verified"], False)

    def test_public_process_cleanup_excludes_raw_identities(self) -> None:
        raw = {"environment": {"python": "3.14"}, "backends": [], "cleanup": {**CLEAN, "process_cleanup": {
            "status": "FAIL", "scope": "visible_same_uid_processes",
            "observed_candidate_survivors": 1, "processes": {"12345": "PRIVATE"},
            "command": "PRIVATE argv", "path": "/PRIVATE",
        }}}
        public = benchmark.sanitize_report(raw)
        self.assertEqual(public.get("process_cleanup", {}).get("status"), "FAIL")
        self.assertEqual(public["process_cleanup"].get("observed_candidate_survivors"), 1)
        self.assertNotIn("PRIVATE", json.dumps(public))
        self.assertNotIn("12345", json.dumps(public))

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

    def test_stop_does_not_convert_permission_denial_to_socket_absence(self) -> None:
        real_lstat = os.lstat
        real_stat = os.stat

        def file_stat(path, *args, **kwargs):
            if Path(path) == self.config.socket_path:
                raise PermissionError(errno.EACCES, "private socket detail")
            return real_lstat(path, *args, **kwargs)

        def path_stat(path, *args, **kwargs):
            if Path(path) == self.config.socket_path:
                raise PermissionError(errno.EACCES, "private socket detail")
            return real_stat(path, *args, **kwargs)

        with (
            patch.object(os, "lstat", file_stat),
            patch.object(os, "stat", path_stat),
            patch.object(benchmark, "run_capture", return_value={"returncode": 0}),
            patch.object(benchmark.time, "monotonic", side_effect=[0.0, 16.0]),
        ):
            result = benchmark.stop_daemon(self.config)
        self.assertIsNone(result["socket_absent_after_stop"])
        self.assertIs(result["pidfile_absent_after_stop"], True)

    def test_stop_preserves_first_unavailable_observation_without_retry(self) -> None:
        real_lstat = os.lstat
        real_stat = os.stat
        lookups = 0

        def metadata(reader, path, *args, **kwargs):
            nonlocal lookups
            if Path(path) == self.config.socket_path:
                lookups += 1
                if lookups == 1:
                    raise PermissionError(errno.EACCES, "not visible")
            return reader(path, *args, **kwargs)

        with (
            patch.object(os, "lstat", lambda *a, **kw: metadata(real_lstat, *a, **kw)),
            patch.object(os, "stat", lambda *a, **kw: metadata(real_stat, *a, **kw)),
            patch.object(benchmark, "run_capture", return_value={"returncode": 0}),
            patch.object(benchmark.time, "monotonic", side_effect=[0.0, 0.0]),
        ):
            result = benchmark.stop_daemon(self.config)
        self.assertIsNone(result["socket_absent_after_stop"])

    def test_uninspectable_runtime_is_rejected_before_output_or_stop(self) -> None:
        real_lstat = os.lstat
        real_stat = os.stat

        def metadata(reader, path, *args, **kwargs):
            if Path(path) == self.home / ".tbp":
                raise PermissionError(errno.EACCES, "not visible")
            return reader(path, *args, **kwargs)

        with (
            patch.object(os, "lstat", lambda *a, **kw: metadata(real_lstat, *a, **kw)),
            patch.object(os, "stat", lambda *a, **kw: metadata(real_stat, *a, **kw)),
            patch.object(benchmark, "authorize_benchmark", return_value={}),
            patch.object(benchmark, "environment", return_value={"python": "3.14"}),
            patch.object(benchmark, "benchmark_backend", new_callable=AsyncMock,
                         return_value={"backend": "firefox"}),
            patch.object(benchmark, "stop_daemon", return_value=CLEAN) as stop,
        ):
            try:
                with self.assertRaises(benchmark.BenchmarkAuthorityError):
                    asyncio.run(benchmark.run_benchmark(self.config))
            except OSError as exc:
                self.fail(
                    f"Raw metadata error escaped the authority boundary: {type(exc).__name__}"
                )
        self.assertEqual(stop.call_count, 0)
        self.assertFalse(self.config.output.exists())

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

    def test_completed_run_writes_private_korean_summary(self) -> None:
        summary, _, _ = self.run_with_process_results(
            lambda *_: dict(CLEAN),
            lambda *_: {"returncode": 1, "socket_ready_verified": False},
        )
        report_path = self.config.output / "baseline-summary.ko.txt"
        self.assertTrue(report_path.is_file(), "JSON result needs a completion summary")
        text = report_path.read_text()
        self.assertIn(f"Benchmark 품질: {summary['quality']['status']}", text)
        self.assertIn("실행: 종료", text)
        self.assertIn("프로세스·display lease·session lock: 별도 확인 필요", text)
        self.assertIn("Production 승인: 미승인", text)
        self.assertEqual(report_path.stat().st_mode & 0o777, 0o600)

    def test_closing_failures_preserve_results_and_continue_independent_checks(self) -> None:
        for failure in ("environment", "cleanup", "measurement", "environment_capture"):
            with self.subTest(failure=failure):
                config = replace(self.config, output=self.home / failure)
                authority = {"commit": "a" * 40}
                results = [{"backend": "firefox"}, {"backend": "chromium"}]
                if failure == "measurement":
                    results[1] = RuntimeError("PRIVATE measurement failure")
                with (
                    patch.object(benchmark, "authorize_benchmark", side_effect=[
                        authority, benchmark.BenchmarkAuthorityError("PRIVATE environment failure")
                        if failure == "environment" else authority]),
                    patch.object(benchmark, "environment", return_value={"python": "3.14"},
                                 side_effect=OSError("PRIVATE capture")
                                 if failure == "environment_capture" else None),
                    patch.object(benchmark, "benchmark_backend", new=AsyncMock(side_effect=results)),
                    patch.object(benchmark, "stop_daemon", side_effect=PermissionError("PRIVATE cleanup")
                                 if failure == "cleanup" else None, return_value=CLEAN) as stop,
                    patch("scripts.final_verify._git_preflight", return_value={"clean_worktree": True}) as git,
                ):
                    try:
                        raw_path, summary_path, summary = asyncio.run(benchmark.run_benchmark(config))
                    except Exception as exc:
                        self.fail(f"Post-run evidence was discarded: {type(exc).__name__}")
                raw = json.loads(raw_path.read_text())
                if failure == "environment_capture":
                    self.assertEqual(raw["backends"], [])
                    stop.assert_not_called()
                else:
                    self.assertEqual(raw["backends"][0]["backend"], "firefox")
                    stop.assert_called_once()
                self.assertEqual(summary["quality"]["status"], "FAIL")
                self.assertEqual(json.loads(summary_path.read_text()), summary)
                git.assert_called_once()
                self.assertEqual(len(raw.get("post_run", {}).get("pngs", [])), 2)
                self.assertNotIn("PRIVATE", json.dumps(summary))
                if failure == "cleanup":
                    self.assertEqual(summary["cleanup"]["status"], "UNKNOWN")

    def test_png_read_denial_is_unavailable_not_a_missing_file(self) -> None:
        path = self.home / "unreadable.png"
        original_lstat, original_stat = os.lstat, os.stat

        def denied(reader, candidate, *args, **kwargs):
            if Path(candidate) == path:
                raise PermissionError(errno.EACCES, "PRIVATE denial")
            return reader(candidate, *args, **kwargs)

        # pathlib uses different stat/lstat paths across supported interpreters.
        with (
            patch.object(os, "lstat", side_effect=lambda *a, **kw: denied(original_lstat, *a, **kw)),
            patch.object(os, "stat", side_effect=lambda *a, **kw: denied(original_stat, *a, **kw)),
        ):
            result = benchmark.file_check(path)
        self.assertEqual(result.get("status"), "UNAVAILABLE")
        self.assertEqual(result.get("errno"), errno.EACCES)
        self.assertIsNone(result.get("bytes"))
        missing = benchmark.file_check(self.home / "absent.png")
        self.assertEqual(missing.get("status"), "FAIL")
        self.assertEqual(missing.get("reason"), "missing")

    def test_report_writer_never_overwrites_an_existing_or_symlinked_file(self) -> None:
        from scripts.final_verify import VerificationFailure

        target = self.home / "preserve.json"
        target.write_text("preserve")
        target.chmod(0o600)
        link = self.home / "report.json"
        link.symlink_to(target)
        for path in (target, link):
            with self.subTest(path=path.name), self.assertRaises(VerificationFailure):
                benchmark.write_private_json(path, {"new": "report"})
            self.assertEqual(target.read_text(), "preserve")

    def test_failed_png_readback_does_not_skip_the_other_backend(self) -> None:
        authority = {"commit": "a" * 40}
        report = {"backends": []}
        with (
            patch.object(benchmark, "authorize_benchmark", return_value=authority),
            patch("scripts.final_verify._git_preflight", return_value={"clean_worktree": True}),
            patch.object(benchmark, "file_check", side_effect=[
                RuntimeError("PRIVATE reader failure"),
                {"valid_png": False, "status": "FAIL", "reason": "missing", "bytes": None},
            ]) as read,
        ):
            try:
                result = benchmark.post_run_checks(self.config, report, authority)
            except RuntimeError:
                self.fail("Independent PNG readback was skipped")
        self.assertEqual(read.call_count, 2)
        self.assertEqual([item["status"] for item in result["pngs"]], ["UNKNOWN", "FAIL"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_post_run_distinguishes_rejected_checkout_from_unavailable_git(self) -> None:
        from scripts.final_verify import VerificationFailure

        denied = VerificationFailure("PRIVATE Git could not execute")
        denied.__cause__ = PermissionError(errno.EACCES, "PRIVATE denied")
        for error, status in ((VerificationFailure("PRIVATE dirty checkout"), "FAIL"),
                              (denied, "UNAVAILABLE")):
            with self.subTest(status=status), \
                    patch.object(benchmark, "authorize_benchmark", return_value={"commit": "a" * 40}), \
                    patch("scripts.final_verify._git_preflight", side_effect=error):
                result = benchmark.post_run_checks(self.config, {"backends": []}, {"commit": "a" * 40})
            self.assertEqual(result["checkout"]["status"], status)
            self.assertEqual(len(result["pngs"]), 2)
            self.assertNotIn("PRIVATE", json.dumps(result))
            if status == "UNAVAILABLE":
                self.assertEqual(result["checkout"].get("errno"), errno.EACCES)

    def test_public_cleanup_distinguishes_failure_from_unavailable(self) -> None:
        for actual, expected in ((True, "PASS"), (False, "FAIL"), (None, "UNKNOWN")):
            with self.subTest(actual=actual):
                raw = {
                    "environment": {"python": "3.14"}, "backends": [],
                    "cleanup": {"socket_absent_after_stop": actual,
                                "pidfile_absent_after_stop": True,
                                "stderr": "PRIVATE failure details"},
                }
                public = benchmark.sanitize_report(raw)
                evidence = public.get("cleanup", {})
                self.assertEqual(evidence.get("status"), expected)
                self.assertEqual(evidence.get("scope"), "daemon_files_only")
                self.assertIs(evidence.get("socket_absent_after_stop"), actual)
                self.assertNotIn("PRIVATE", json.dumps(public))

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
