"""Regression tests for the warm daemon status control plane."""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
from contextlib import redirect_stdout
import asyncio
import io
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from src.daemon import Daemon, _handle_status
import cli
from src import client


class _PageIODetector:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def url(self) -> str:
        self.calls.append("url")
        raise AssertionError("status must not perform page I/O")

    async def title(self) -> str:
        self.calls.append("title")
        raise AssertionError("status must not perform page I/O")


class DaemonStatusCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_start_cleans_owned_pilot_and_preserves_other_socket(self) -> None:
        for error in (RuntimeError("start failed"), asyncio.CancelledError()):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                socket, pidfile = root / "daemon.sock", root / "daemon.pid"
                socket.write_bytes(b"unowned marker")
                pilot = SimpleNamespace(start=AsyncMock(side_effect=error),
                                        stop=AsyncMock(), save_cookies=AsyncMock())
                daemon = Daemon()
                with (
                    patch("src.daemon.TBP_DIR", str(root)),
                    patch("src.daemon.DOWNLOAD_DIR", str(root / "downloads")),
                    patch("src.daemon.FIREFOX_PROFILE_DIR", str(root / "profile")),
                    patch("src.daemon.SOCKET_PATH", str(socket)),
                    patch("src.daemon.PID_PATH", str(pidfile)),
                    patch("src.pilot.Pilot", return_value=pilot),
                ):
                    with self.assertRaises(type(error)) as caught:
                        await daemon.run()
                    self.assertIs(caught.exception, error)
                    pilot.stop.assert_awaited_once()
                    self.assertFalse(pidfile.exists())
                    self.assertEqual(socket.read_bytes(), b"unowned marker")

    async def test_stop_command_never_autostarts_during_a_socket_exit_race(self) -> None:
        with (
            patch.object(client, "is_daemon_running", return_value=True),
            patch.object(client, "ensure_daemon", new_callable=AsyncMock) as ensure,
            patch.object(client.asyncio, "open_unix_connection", new_callable=AsyncMock,
                         side_effect=ConnectionRefusedError),
            redirect_stdout(io.StringIO()),
        ):
            await cli.cmd_stop(SimpleNamespace())
        ensure.assert_not_awaited()

    async def test_failed_owned_cleanup_does_not_remove_daemon_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            socket, pidfile = root / "daemon.sock", root / "daemon.pid"
            socket.write_bytes(b"socket marker")
            pidfile.write_text("123\n")
            daemon = Daemon()
            daemon._socket_identity = (socket.stat().st_dev, socket.stat().st_ino)
            daemon._pid_identity = (pidfile.stat().st_dev, pidfile.stat().st_ino)
            daemon.pilot = SimpleNamespace(
                save_cookies=AsyncMock(),
                stop=AsyncMock(side_effect=[RuntimeError("child still live"), None]),
            )
            with (
                patch("src.daemon.SOCKET_PATH", str(socket)),
                patch("src.daemon.PID_PATH", str(pidfile)),
                patch("src.daemon.TBP_DIR", str(root)),
            ):
                with self.assertRaises(RuntimeError):
                    await daemon._cleanup()
                self.assertTrue(socket.exists())
                self.assertTrue(pidfile.exists())
                await daemon._cleanup()
                self.assertFalse(socket.exists())
                self.assertFalse(pidfile.exists())

    async def test_cleanup_does_not_unlink_replaced_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            socket = Path(directory) / "daemon.sock"
            socket.write_bytes(b"owned marker")
            daemon = Daemon()
            daemon._socket_identity = (socket.stat().st_dev, socket.stat().st_ino)
            socket.rename(Path(directory) / "original.sock")
            socket.write_bytes(b"replacement marker")
            with (
                patch("src.daemon.SOCKET_PATH", str(socket)),
                patch("src.daemon.PID_PATH", str(Path(directory) / "daemon.pid")),
            ):
                with self.assertRaises(RuntimeError):
                    await daemon._cleanup()
            self.assertEqual(socket.read_bytes(), b"replacement marker")

    async def test_cancelled_cookie_save_does_not_skip_daemon_pilot_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            daemon = Daemon()
            daemon.pilot = SimpleNamespace(save_cookies=AsyncMock(side_effect=asyncio.CancelledError()),
                                           stop=AsyncMock())
            with (
                patch("src.daemon.TBP_DIR", directory),
                patch("src.daemon.SOCKET_PATH", str(Path(directory) / "daemon.sock")),
                patch("src.daemon.PID_PATH", str(Path(directory) / "daemon.pid")),
            ):
                with self.assertRaises(asyncio.CancelledError):
                    await daemon._cleanup()
            daemon.pilot.stop.assert_awaited_once()

    async def test_listener_close_failure_still_stops_owned_pilot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            daemon = Daemon()
            daemon._server = SimpleNamespace(close=lambda: None,
                                             wait_closed=AsyncMock(side_effect=RuntimeError("listener failed")))
            daemon.pilot = SimpleNamespace(save_cookies=AsyncMock(), stop=AsyncMock())
            with (
                patch("src.daemon.TBP_DIR", directory),
                patch("src.daemon.SOCKET_PATH", str(Path(directory) / "daemon.sock")),
                patch("src.daemon.PID_PATH", str(Path(directory) / "daemon.pid")),
            ):
                with self.assertRaises(RuntimeError):
                    await daemon._cleanup()
            daemon.pilot.stop.assert_awaited_once()

    async def test_listener_drain_has_a_deadline_before_owned_pilot_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            async def stuck_listener():
                await asyncio.Future()

            real_wait_for = asyncio.wait_for

            async def short_deadline(awaitable, timeout):
                self.assertEqual(timeout, 5)
                return await real_wait_for(awaitable, timeout=0.01)

            daemon = Daemon()
            daemon._server = SimpleNamespace(close=lambda: None, wait_closed=stuck_listener)
            daemon.pilot = SimpleNamespace(save_cookies=AsyncMock(), stop=AsyncMock())
            with (
                patch("src.daemon.TBP_DIR", directory),
                patch("src.daemon.SOCKET_PATH", str(Path(directory) / "daemon.sock")),
                patch("src.daemon.PID_PATH", str(Path(directory) / "daemon.pid")),
                patch("src.daemon.asyncio.wait_for", new=AsyncMock(side_effect=short_deadline)) as bounded,
            ):
                with self.assertRaises(TimeoutError):
                    await real_wait_for(daemon._cleanup(), timeout=1)
                bounded.assert_awaited_once()
            daemon.pilot.stop.assert_awaited_once()

    async def test_status_reads_cached_control_plane_without_page_io(self) -> None:
        pilot = _PageIODetector()
        daemon = SimpleNamespace(
            pilot=pilot,
            _browser_type="firefox",
            _start_time=100.0,
            _status_cache={
                "url": "https://example.com/",
                "title": "Example Domain",
                "updated_at_monotonic": 10.0,
            },
        )

        with (
            patch("src.daemon.time.time", return_value=125.0),
            patch("src.daemon.time.monotonic", return_value=10.125),
            patch("src.daemon.os.getpid", return_value=1234),
        ):
            result = await _handle_status(daemon, {})

        self.assertEqual(pilot.calls, [])
        self.assertEqual(result["url"], "https://example.com/")
        self.assertEqual(result["title"], "Example Domain")
        self.assertEqual(result["freshness_ms"], 125)
