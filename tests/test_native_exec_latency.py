"""Deterministic regressions for the Firefox native JS bridge."""

from __future__ import annotations

import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.native import NativeFirefoxSession


class NativeExecutionLatencyTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
