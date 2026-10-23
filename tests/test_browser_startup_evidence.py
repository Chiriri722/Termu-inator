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
