"""Regression tests for inherited Xvfb/browser lifecycle defects."""

from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from src.browser import BrowserPilot


class _Process:
    def __init__(self, *, pid: int, returncode: int | None) -> None:
        self.pid = pid
        self.returncode = returncode

    async def wait(self) -> int:
        return 0 if self.returncode is None else self.returncode


class BrowserLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def test_chromium_binary_is_resolved_at_runtime_for_termux(self) -> None:
        pilot = BrowserPilot(chromium_bin=None, headless_xvfb=False)
        self.assertTrue(callable(getattr(pilot, "_resolve_chromium_binary", None)))

        def which(name: str) -> str | None:
            return "/data/data/com.termux/files/usr/bin/chromium" if name == "chromium" else None

        with patch("src.browser.shutil.which", side_effect=which):
            resolved = pilot._resolve_chromium_binary()

        self.assertEqual(
            resolved, "/data/data/com.termux/files/usr/bin/chromium"
        )

    async def test_xvfb_start_launches_exactly_one_window_manager(self) -> None:
        calls: list[tuple[object, ...]] = []

        async def launch(*args: object, **_: object) -> _Process:
            calls.append(args)
            is_pkill = args[0] == "pkill"
            return _Process(pid=1000 + len(calls), returncode=0 if is_pkill else None)

        pilot = BrowserPilot(display=":77", window_size="800,600")
        with (
            patch("src.browser.asyncio.create_subprocess_exec", side_effect=launch),
            patch("src.browser.asyncio.sleep", new=AsyncMock()),
            patch("src.browser.os.unlink", side_effect=FileNotFoundError),
            patch("src.browser.shutil.which", return_value="/usr/bin/openbox"),
        ):
            await pilot._start_xvfb()

        openbox_calls = [
            call for call in calls if Path(str(call[0])).name == "openbox"
        ]
        self.assertEqual(openbox_calls, [("/usr/bin/openbox",)])
        self.assertIsNotNone(pilot._wm_proc)
