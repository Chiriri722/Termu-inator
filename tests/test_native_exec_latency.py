"""Deterministic regressions for the Firefox native JS bridge."""

from __future__ import annotations

import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from src import commands
from src.native import NativeFirefoxSession, _navigate
from src.termuinator.backends.legacy_dom import observe_script


class NativeExecutionLatencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiline_dom_probe_is_preserved_inside_eval_wrapper(self) -> None:
        session = NativeFirefoxSession()
        source = observe_script("__diagnostic_registry_key")
        wrappers: list[str] = []

        async def capture_wrapper(
            javascript: str, _marker: str, _timeout: float
        ) -> dict[str, object]:
            wrappers.append(javascript)
            return {
                "ready_state": "complete",
                "dom_version": 0,
                "elements": [],
            }

        session._run_js_and_read = capture_wrapper

        result = await session._exec_js_inner(source, timeout=1)

        self.assertEqual(result["ready_state"], "complete")
        self.assertEqual(len(wrappers), 1)
        self.assertIn(f"eval({json.dumps(source.strip())})", wrappers[0])
        self.assertNotIn("shadow_path:shadowPath; });", wrappers[0])

    async def test_javascript_error_is_typed_without_echoing_expression_data(self) -> None:
        session = NativeFirefoxSession()
        secret = "do-not-echo-javascript-error-data"

        async def return_javascript_error(
            _javascript: str, _marker: str, _timeout: float
        ) -> str:
            return f"ERR:Unexpected token near {secret}"

        session._run_js_and_read = return_javascript_error

        with self.assertRaises(commands.JavascriptExecutionError) as caught:
            await session._exec_js_inner("invalid expression", timeout=1)

        self.assertEqual(caught.exception.reason, "evaluation")
        self.assertNotIn(secret, str(caught.exception))

    async def test_immediate_callback_is_polled_without_post_execute_delay(self) -> None:
        session = NativeFirefoxSession()
        session._console_synced = True
        session._console_open = True
        session._callback_server = SimpleNamespace(results={})
        sleep_calls: list[float] = []

        async def fake_xdt(args: list[str]) -> None:
            if args == ["key", "ctrl+Return"]:
                session._callback_server.results["request-id"] = json.dumps(
                    {"r": "ready"}
                )

        async def fake_clipboard_paste(_text: str) -> bool:
            return True

        async def fake_clipboard_read() -> str:
            return ""

        async def record_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        session._xdt = fake_xdt
        session._clipboard_paste = fake_clipboard_paste
        session._clipboard_read = fake_clipboard_read

        with patch("src.native.asyncio.sleep", new=record_sleep):
            result = await session._run_js_and_read(
                "1 + 1", "TBPrequest-id", timeout=1
            )

        self.assertEqual(result, "ready")
        self.assertNotIn(0.5, sleep_calls)

    async def test_timeout_invalidates_console_without_logging_clipboard(
        self,
    ) -> None:
        session = NativeFirefoxSession()
        session._console_synced = True
        session._console_open = True
        session._devtools_wid = "4242"
        session._page_has_focus = True
        session._callback_server = SimpleNamespace(results={})

        async def fake_xdt(_args: list[str]) -> None:
            return None

        async def fake_clipboard_paste(_text: str) -> bool:
            return True

        async def fake_clipboard_read() -> str:
            return "top-secret-clipboard-value"

        session._xdt = fake_xdt
        session._clipboard_paste = fake_clipboard_paste
        session._clipboard_read = fake_clipboard_read

        with (
            patch("src.native.asyncio.sleep", new=AsyncMock()),
            self.assertLogs("src.native", level="WARNING") as logged,
        ):
            with self.assertRaises(Exception) as caught:
                await session._run_js_and_read(
                    "document.readyState", "TBPrequest-id", timeout=0
                )

        timeout_type = getattr(commands, "JavascriptExecutionTimeout", None)
        self.assertIsNotNone(timeout_type)
        self.assertIsInstance(caught.exception, timeout_type)
        self.assertFalse(session._console_synced)
        self.assertFalse(session._console_open)
        self.assertIsNone(session._devtools_wid)
        self.assertFalse(session._page_has_focus)
        self.assertNotIn("top-secret-clipboard-value", "\n".join(logged.output))

    async def test_console_sync_fails_when_sentinel_is_never_observed(self) -> None:
        session = NativeFirefoxSession()
        clock_value = 0.0

        class _Clock:
            def time(self) -> float:
                nonlocal clock_value
                clock_value += 1.0
                return clock_value

        async def fake_xdt(_args: list[str]) -> None:
            return None

        async def fake_clipboard_paste(_text: str) -> bool:
            return True

        async def fake_clipboard_read() -> str:
            return ""

        async def fake_find_devtools_window() -> None:
            return None

        session._xdt = fake_xdt
        session._clipboard_paste = fake_clipboard_paste
        session._clipboard_read = fake_clipboard_read
        session._find_devtools_window = fake_find_devtools_window
        session._focus_main_window = AsyncMock()

        with (
            patch("src.native.asyncio.sleep", new=AsyncMock()),
            patch("src.native.asyncio.get_running_loop", return_value=_Clock()),
        ):
            with self.assertRaises(Exception) as caught:
                await session._sync_console_state()

        timeout_type = getattr(commands, "JavascriptExecutionTimeout", None)
        self.assertIsNotNone(timeout_type)
        self.assertIsInstance(caught.exception, timeout_type)
        self.assertFalse(session._console_synced)
        self.assertFalse(session._console_open)

    async def test_console_sync_reuses_a_verified_existing_devtools_window(
        self,
    ) -> None:
        session = NativeFirefoxSession()
        xdt_calls: list[list[str]] = []

        async def fake_xdt(args: list[str]) -> None:
            xdt_calls.append(args)

        async def fake_find_devtools_window() -> str:
            session._devtools_wid = "4242"
            return "4242"

        session._xdt = fake_xdt
        session._find_devtools_window = fake_find_devtools_window
        session._ensure_devtools_focused = AsyncMock(return_value=True)
        session._probe_console = AsyncMock(return_value=True)

        with patch("src.native.asyncio.sleep", new=AsyncMock()):
            await session._sync_console_state()

        self.assertTrue(session._console_synced)
        self.assertTrue(session._console_open)
        self.assertNotIn(["key", "ctrl+shift+k"], xdt_calls)

    async def test_navigation_falls_back_when_console_returns_timeout(self) -> None:
        session = NativeFirefoxSession()
        xdt_calls: list[list[str]] = []

        async def fake_exec_js(_expression: str, timeout: float = 60) -> str:
            return "ERR:Timeout - console did not respond"

        async def fake_close_console() -> None:
            return None

        async def fake_xdt(args: list[str]) -> None:
            xdt_calls.append(args)

        async def fake_clipboard_paste(_text: str) -> bool:
            return True

        session._exec_js = fake_exec_js
        session._close_console = fake_close_console
        session._xdt = fake_xdt
        session._clipboard_paste = fake_clipboard_paste

        with patch("src.native.asyncio.sleep", new=AsyncMock()):
            await _navigate(
                session,
                {"url": "https://example.com"},
                timeout=5,
            )

        self.assertIn(["key", "ctrl+l"], xdt_calls)
        self.assertIn(["key", "Return"], xdt_calls)


if __name__ == "__main__":
    unittest.main()
