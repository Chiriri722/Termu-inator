"""Startup evidence must describe bounded facts, never private stderr or paths."""

from __future__ import annotations

import asyncio
import errno
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from src.browser import BrowserPilot, BrowserStartupError
from src.pilot import Pilot
from src.termuinator.backends.legacy import LegacyPilotBackend
from src.termuinator.contracts import Backend, ErrorCode
from src.termuinator.errors import TermuinatorError
from scripts import final_verify


class StartupEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def _exercise_failed_attempts(self, *, forced=False, virgl=False, spawn_error=False):
        """Use real owned child exits/cleanup; replace only the browser executable and deadline."""
        children = []
        flags = []
        with tempfile.TemporaryDirectory() as temp:
            pilot = BrowserPilot(headless_xvfb=False, user_data_dir=temp,
                                 gpu_mode="virgl" if virgl else "swiftshader")
            pilot._runtime_dir = Path(temp) / "runtime"
            if virgl:
                pilot._virgl = SimpleNamespace(get_env=lambda: {}, stop=AsyncMock())
            original_wait = pilot._wait_for_cdp

            async def launch(_env, extra_flags=None):
                pilot._startup_stage = "chromium_spawn"
                flags.append(tuple(extra_flags or ()))
                if spawn_error and len(flags) == 2:
                    raise PermissionError(errno.EACCES, "PRIVATE executable")
                # The first process is alive at readiness failure and exits 0 on SIGTERM.
                script = (
                    "import signal,sys,time; "
                    "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); "
                    "print('ready', flush=True); time.sleep(60)"
                    if len(flags) == 1 else f"raise SystemExit({20 + len(flags)})"
                )
                child = await asyncio.create_subprocess_exec(
                    sys.executable, "-I", "-u", "-c", script,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                children.append(child)
                pilot._chrome_proc = child
                pilot._chromium_stderr_tail = b"PRIVATE fixture startup text\n"
                if len(flags) == 1:
                    self.assertEqual(await asyncio.wait_for(child.stdout.readline(), 5), b"ready\n")
                else:
                    await asyncio.wait_for(child.wait(), 5)

            async def readiness():
                return await original_wait(timeout=0 if len(flags) == 1 else 1)

            adapter = LegacyPilotBackend(Backend.CHROMIUM, pilot_factory=lambda **_: pilot)
            try:
                with (patch("src._utils.require_binaries"),
                      patch.object(pilot, "_resolve_chromium_binary", return_value="/not-executed"),
                      patch.object(pilot, "_setup_gpu", new=AsyncMock()),
                      patch.object(pilot, "_launch_chromium", side_effect=launch),
                      patch.object(pilot, "_wait_for_cdp", side_effect=readiness),
                      patch("src.browser._FORCE_SINGLE_PROCESS", forced),
                      self.assertLogs("src.browser", level="WARNING")):
                    with self.assertRaises(TermuinatorError) as caught:
                        await adapter.start(Path(temp), None)
                content = (pilot._runtime_dir / "chromium-startup.log").read_text()
                self.assertTrue(all(child.returncode is not None for child in children))
                return caught.exception, content, flags
            finally:
                for child in children:
                    if child.returncode is None:
                        child.kill()
                    await child.wait()

    async def test_fallback_preserves_failure_time_and_cleanup_time_separately(self):
        error, content, flags = await self._exercise_failed_attempts()
        self.assertEqual(flags, [(), ("--single-process",)])
        self.assertEqual(error.code, ErrorCode.BACKEND_CRASHED)
        self.assertEqual(error.details.get("process_returncode"), 22)
        expected = {
            "startup_attempt_count": 2,
            "attempt_1_mode": "multi-process", "attempt_1_stage": "cdp_ready",
            "attempt_1_reason": "readiness_timeout", "attempt_1_exception_type": "TimeoutError",
            "attempt_1_exit_state": "not_observed", "attempt_1_cleanup_returncode": 0,
            "attempt_2_mode": "single-process", "attempt_2_stage": "cdp_ready",
            "attempt_2_reason": "process_exited", "attempt_2_exit_state": "exited",
            "attempt_2_process_returncode": 22, "attempt_2_cleanup_returncode": 22,
        }
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertEqual(error.details.get(key), value)
        self.assertNotIn("attempt_1_process_returncode", error.details)
        # Private headers are structured too; raw stderr is never part of public details.
        header = content.splitlines()[0].split("] ", 1)[1]
        self.assertTrue(header.startswith("{"), "Private header lacks failure-time fields")
        first = json.loads(header)
        self.assertEqual(first["reason"], "readiness_timeout")
        self.assertEqual(first["exit_state"], "not_observed")
        self.assertEqual(first["cleanup_returncode"], 0)
        self.assertNotIn("process_returncode", first)
        self.assertNotIn("PRIVATE", json.dumps(error.details))

        result = SimpleNamespace(isError=True, content=[SimpleNamespace(text=json.dumps({
            "code": error.code.value, "message": "PRIVATE", "details": error.details,
        }))])
        caller = final_verify._McpToolCaller(
            SimpleNamespace(call_tool=AsyncMock(return_value=result)), server_pid=123)
        with self.assertRaises(final_verify.VerificationFailure) as caught:
            await caller("browser_session_start", {})
        evidence = final_verify._verification_failure_evidence(caught.exception, "backend-chromium", [])
        summary = final_verify.verification_summary_ko({"status": "FAIL", "device": {
            "backends": [{"backend": "chromium", "status": "FAIL", **evidence}]}})
        for key, value in expected.items():
            self.assertEqual(evidence["failure_context"].get(key), value)
            self.assertIn(f"{key}={value}", summary)
        self.assertNotIn("PRIVATE", summary)

    async def test_forced_single_process_timeout_stays_timeout_after_zero_exit_cleanup(self):
        error, content, flags = await self._exercise_failed_attempts(forced=True)
        self.assertEqual(flags, [()])
        self.assertEqual(error.code, ErrorCode.TIMEOUT)
        self.assertEqual(error.details.get("startup_attempt_count"), 1)
        self.assertEqual(error.details.get("attempt_1_mode"), "single-process")
        self.assertEqual(error.details.get("attempt_1_cleanup_returncode"), 0)
        self.assertNotIn("process_returncode", error.details)
        self.assertTrue(content.startswith("[single-process] "))

    async def test_third_attempt_preserves_both_previous_failures(self):
        error, _content, flags = await self._exercise_failed_attempts(virgl=True)
        self.assertEqual(len(flags), 3)
        self.assertEqual(error.details.get("startup_attempt_count"), 3)
        self.assertEqual(error.details.get("attempt_1_reason"), "readiness_timeout")
        self.assertEqual(error.details.get("attempt_2_process_returncode"), 22)
        self.assertEqual(error.details.get("attempt_3_mode"), "swiftshader-single-process")
        self.assertEqual(error.details.get("attempt_3_process_returncode"), 23)
        self.assertEqual(error.details.get("process_returncode"), 23)

    async def test_later_spawn_failure_keeps_completed_attempt_evidence(self):
        error, _content, flags = await self._exercise_failed_attempts(spawn_error=True)
        self.assertEqual(len(flags), 2)
        self.assertEqual(error.details.get("stage"), "chromium_spawn")
        self.assertEqual(error.details.get("errno"), errno.EACCES)
        self.assertEqual(error.details.get("startup_attempt_count"), 1)
        self.assertEqual(error.details.get("attempt_1_reason"), "readiness_timeout")
        self.assertEqual(error.details.get("attempt_1_cleanup_returncode"), 0)
        self.assertNotIn("attempt_2_process_returncode", error.details)

    def test_public_attempt_fields_are_bounded_and_do_not_forward_raw_values(self):
        safe = {"startup_attempt_count": 3, "attempt_1_mode": "multi-process",
                "attempt_1_reason": "readiness_timeout", "attempt_1_exit_state": "not_observed",
                "attempt_1_cleanup_returncode": 0, "attempt_2_process_returncode": -5,
                "attempt_3_stage": "cdp_ready", "attempt_3_exception_type": "RuntimeError",
                "attempt_3_errno": 13}
        unsafe = {"attempt_4_mode": "single-process", "attempt_1_stderr": "PRIVATE",
                  "attempt_1_pid": 123, "attempt_2_reason": "PRIVATE", "attempt_2_errno": True,
                  "attempt_3_mode": "PRIVATE", "attempt_3_process_returncode": 100000}
        self.assertEqual(final_verify._safe_failure_context({**safe, **unsafe}), safe)
        for value in (True, None, -1, 0, 4, "PRIVATE", {}, []):
            with self.subTest(value=value):
                self.assertEqual(final_verify._safe_failure_context({"startup_attempt_count": value}), {})

    async def test_cancellation_is_not_mapped_from_stale_startup_metadata(self):
        fake = SimpleNamespace(
            start=AsyncMock(side_effect=asyncio.CancelledError()), stop=AsyncMock(),
            _startup_failure=BrowserStartupError("cdp_ready", TimeoutError()))
        adapter = LegacyPilotBackend(Backend.CHROMIUM, pilot_factory=lambda **_: fake)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(BaseException) as caught:
                await adapter.start(Path(temp), None)
        self.assertIsInstance(caught.exception, asyncio.CancelledError)

    async def test_session_connection_failure_is_not_lost_after_browser_launch(self):
        pilot = Pilot()
        pilot._browser.start = AsyncMock(return_value="ws://private.invalid")
        original = PermissionError(errno.EACCES, "PRIVATE connection")
        pilot._init_session = AsyncMock(side_effect=original)
        pilot.stop = AsyncMock()
        adapter = LegacyPilotBackend(Backend.CHROMIUM, pilot_factory=lambda **_: pilot)
        with tempfile.TemporaryDirectory() as temp, patch.object(pilot._lock, "acquire"):
            with self.assertRaises(Exception) as caught:
                await adapter.start(Path(temp), None)
        self.assertIsInstance(caught.exception, TermuinatorError)
        self.assertEqual(caught.exception.details.get("stage"), "session_initialization")
        self.assertEqual(caught.exception.details.get("errno"), errno.EACCES)
        self.assertNotIn("PRIVATE", str(caught.exception))

    async def test_spawn_permission_failure_keeps_stage_errno_without_private_message(self):
        with tempfile.TemporaryDirectory() as temp:
            pilot = BrowserPilot(headless_xvfb=False, user_data_dir=temp, gpu_mode="swiftshader")
            original = PermissionError(errno.EACCES, "PRIVATE executable /token=secret")
            with (patch("src._utils.require_binaries"),
                  patch.object(pilot, "_resolve_chromium_binary", return_value="/not-executed"),
                  patch("src.browser.asyncio.create_subprocess_exec", side_effect=original)):
                with self.assertRaises(Exception) as caught:
                    await pilot.start()
            details = getattr(caught.exception, "startup_details", {})
            self.assertEqual(details.get("stage"), "chromium_spawn")
            self.assertEqual(details.get("reason"), "permission_denied")
            self.assertEqual(details.get("errno"), errno.EACCES)
            self.assertEqual(details.get("exception_type"), "PermissionError")
            self.assertNotIn("PRIVATE", str(caught.exception))
            self.assertIs(caught.exception.__cause__, original)
            self.assertIsNone(pilot._chromium_singleton_owner,
                              "A failed exec created no child and must release its empty claim")

    async def test_actual_child_exit_is_recorded_before_cleanup_can_replace_returncode(self):
        child = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c", "raise SystemExit(23)")
        await child.wait()
        pilot = BrowserPilot()
        pilot._chrome_proc = child
        with self.assertRaises(Exception) as caught:
            await pilot._wait_for_cdp(timeout=0.1)
        details = getattr(caught.exception, "startup_details", {})
        self.assertEqual(details.get("stage"), "cdp_ready")
        self.assertEqual(details.get("reason"), "process_exited")
        self.assertEqual(details.get("process_returncode"), 23)

    async def test_readiness_timeout_maps_to_timeout_instead_of_crash(self):
        pilot = BrowserPilot()
        with self.assertRaises(Exception) as caught:
            await pilot._wait_for_cdp(timeout=0)
        original = caught.exception
        fake = SimpleNamespace(start=AsyncMock(side_effect=original), stop=AsyncMock())
        adapter = LegacyPilotBackend(Backend.CHROMIUM, pilot_factory=lambda **_: fake)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(Exception) as wrapped:
                await adapter.start(Path(temp), None)
        self.assertIsInstance(wrapped.exception, TermuinatorError)
        self.assertEqual(wrapped.exception.code, ErrorCode.TIMEOUT)
        self.assertEqual(wrapped.exception.details.get("operation"), "start")
        self.assertEqual(wrapped.exception.details.get("stage"), "cdp_ready")
        self.assertEqual(wrapped.exception.details.get("reason"), "readiness_timeout")
        self.assertNotIn("process_returncode", wrapped.exception.details)
        fake.stop.assert_awaited_once()

    async def test_mcp_public_failure_keeps_only_bounded_startup_metadata(self):
        details = {"backend": "chromium", "operation": "start", "stage": "chromium_spawn",
                   "reason": "permission_denied", "exception_type": "PermissionError",
                   "errno": 13, "process_returncode": -9, "stderr": "PRIVATE secret",
                   "path": "/PRIVATE", "pid": 999999}
        result = SimpleNamespace(isError=True, content=[SimpleNamespace(text=json.dumps({
            "code": "backend_crashed", "message": "PRIVATE", "details": details,
        }))])
        caller = final_verify._McpToolCaller(
            SimpleNamespace(call_tool=AsyncMock(return_value=result)), server_pid=123)
        with self.assertRaises(final_verify.VerificationFailure) as caught:
            await caller("browser_session_start", {})
        context = final_verify._safe_failure_context(caught.exception.verification_context)
        for key in ("operation", "stage", "reason", "exception_type", "errno",
                    "process_returncode"):
            self.assertEqual(context.get(key), details[key], key)
        self.assertNotIn("PRIVATE", json.dumps(context))
        self.assertNotIn("pid", context)

    def test_public_startup_numbers_reject_boolean_out_of_range_and_private_values(self):
        for value in (True, "PRIVATE", {}, [], -100000, 100000, None):
            with self.subTest(value=value):
                result = final_verify._safe_failure_context(
                    {"errno": value, "process_returncode": value})
                self.assertEqual(result, {})

    async def test_cancelled_rpc_stops_sampling_and_cancels_only_its_request(self):
        entered = asyncio.Event()
        stopped = asyncio.Event()
        samples = []

        async def call_tool(*args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        caller = final_verify._McpToolCaller(SimpleNamespace(call_tool=call_tool), server_pid=123,
                                            process_observer=lambda pid: samples.append(pid))
        request = asyncio.create_task(caller("browser_session_start", {}))
        await entered.wait()
        request.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await request
        self.assertTrue(stopped.is_set())
        count = len(samples)
        await asyncio.sleep(0.15)
        self.assertEqual(len(samples), count)


if __name__ == "__main__":
    unittest.main()
