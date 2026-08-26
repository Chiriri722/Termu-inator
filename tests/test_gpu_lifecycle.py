"""Ownership regressions for optional VirGL acceleration."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from src.gpu import VirglManager


class _FakeProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.pid = 12345
        self.terminated = False
        self.killed = False

    async def wait(self) -> int:
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class VirglOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_start_reuses_the_owned_live_process(self) -> None:
        manager = VirglManager()
        manager._available = True
        process = _FakeProcess()
        launch = AsyncMock(return_value=process)

        with (
            patch("src.gpu.asyncio.create_subprocess_exec", launch),
            patch("src.gpu.asyncio.sleep", AsyncMock()),
        ):
            first = await manager.start()
            second = await manager.start()

        self.assertTrue(first)
        self.assertTrue(second)
        launch.assert_awaited_once()

    async def test_start_never_kills_an_unowned_virgl_process(self) -> None:
        manager = VirglManager()
        manager._available = True
        process = _FakeProcess()
        launch = AsyncMock(return_value=process)

        with (
            patch("src.gpu.asyncio.create_subprocess_exec", launch),
            patch("src.gpu.asyncio.sleep", AsyncMock()),
        ):
            started = await manager.start()

        self.assertTrue(started)
        launch.assert_awaited_once()
        self.assertEqual(
            launch.await_args.args,
            ("virgl_test_server_android",),
        )

    async def test_optional_start_failure_returns_false_for_software_fallback(self) -> None:
        manager = VirglManager()
        manager._available = True

        with (
            self.assertLogs("src.gpu", level="WARNING") as logs,
            patch(
                "src.gpu.asyncio.create_subprocess_exec",
                AsyncMock(side_effect=OSError("exec failed")),
            ),
        ):
            started = await manager.start()

        self.assertFalse(started)
        self.assertIsNone(manager._proc)
        self.assertEqual(
            logs.output,
            ["WARNING:src.gpu:virgl_test_server_android could not be executed"],
        )


if __name__ == "__main__":
    unittest.main()
