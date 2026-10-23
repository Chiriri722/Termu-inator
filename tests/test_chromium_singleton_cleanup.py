"""Real Unix-socket fixtures for candidate-owned Chromium singleton cleanup."""

import asyncio
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from src.browser import BrowserPilot


class SingletonCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="ts-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.profile = self.root / "p"
        self.tmp = self.root / "t"
        self.profile.mkdir(mode=0o700)
        self.tmp.mkdir(mode=0o700)
        self.remote = self.tmp / "sc"
        self.child = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c", "raise SystemExit(23)")
        await self.child.wait()
        self.pilot = BrowserPilot(chromium_bin="unused", user_data_dir=str(self.profile))
        self.pilot._user_data_dir = str(self.profile)

    async def launch_fixture(self, *, live=False, cookie="owned-cookie"):
        async def spawn(*args, **kwargs):
            self.remote.mkdir(mode=0o700)
            endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            endpoint.bind(str(self.remote / "SingletonSocket"))
            if live:
                endpoint.listen(1)
                self.addCleanup(endpoint.close)
            else:
                endpoint.close()
            (self.remote / "SingletonCookie").symlink_to(cookie)
            (self.profile / "SingletonCookie").symlink_to("owned-cookie")
            (self.profile / "SingletonSocket").symlink_to(self.remote / "SingletonSocket")
            (self.profile / "SingletonLock").symlink_to(f"{socket.gethostname()}-{self.child.pid}")
            return self.child

        with patch("src.browser.asyncio.create_subprocess_exec", side_effect=spawn):
            await self.pilot._launch_chromium({"TMPDIR": str(self.tmp)}, [])

    async def test_owned_refused_socket_and_links_are_removed_after_child_is_reaped(self):
        await self.launch_fixture()
        await self.pilot.stop()
        self.assertFalse(os.path.lexists(self.profile / "SingletonSocket"))
        self.assertFalse(os.path.lexists(self.profile / "SingletonLock"))
        self.assertFalse(os.path.lexists(self.profile / "SingletonCookie"))
        self.assertFalse(self.remote.exists())
        self.assertTrue(self.profile.is_dir(), "persistent profile must remain")

    async def test_live_socket_is_preserved_and_cleanup_does_not_claim_success(self):
        await self.launch_fixture(live=True)
        with self.assertRaises(RuntimeError):
            self.pilot._clear_profile_locks()
        self.assertTrue(os.path.lexists(self.profile / "SingletonSocket"))
        self.assertTrue((self.remote / "SingletonSocket").exists())

    async def test_cookie_mismatch_does_not_delete_any_entries(self):
        await self.launch_fixture(cookie="foreign-cookie")
        try:
            self.pilot._clear_profile_locks()
        except RuntimeError:
            pass
        self.assertTrue(os.path.lexists(self.profile / "SingletonLock"))
        self.assertTrue(os.path.lexists(self.profile / "SingletonCookie"))
        self.assertTrue((self.remote / "SingletonSocket").exists())

    async def test_preexisting_singleton_is_not_adopted_or_deleted(self):
        (self.profile / "SingletonLock").symlink_to("foreign-host-123")
        launch = AsyncMock(return_value=self.child)
        with patch("src.browser.asyncio.create_subprocess_exec", launch):
            try:
                await self.pilot._launch_chromium({"TMPDIR": str(self.tmp)}, [])
            except RuntimeError:
                pass
        launch.assert_not_awaited()
        self.assertEqual(os.readlink(self.profile / "SingletonLock"), "foreign-host-123")

    async def test_ownership_failure_does_not_consume_compatibility_retries(self):
        (self.profile / "SingletonLock").symlink_to("foreign-host-123")
        finish = AsyncMock()
        with patch.object(self.pilot, "_finish_failed_chromium_attempt", finish):
            with self.assertRaises(RuntimeError):
                await self.pilot._start_chromium()
        finish.assert_not_awaited()

    async def test_additional_remote_file_is_preserved_without_partial_unlink(self):
        await self.launch_fixture()
        (self.remote / "foreign-data").touch(mode=0o600)
        with self.assertRaises(RuntimeError):
            self.pilot._clear_profile_locks()
        self.assertTrue(os.path.lexists(self.profile / "SingletonLock"))
        self.assertTrue((self.remote / "foreign-data").exists())

    async def test_unknown_socket_liveness_preserves_all_evidence(self):
        await self.launch_fixture()
        with patch("socket.socket.connect", side_effect=PermissionError(13, "private")):
            with self.assertRaises(RuntimeError) as caught:
                self.pilot._clear_profile_locks()
        self.assertEqual(caught.exception.startup_details.get("errno"), 13)
        self.assertEqual(caught.exception.startup_details.get("exception_type"), "PermissionError")
        self.assertTrue(os.path.lexists(self.profile / "SingletonLock"))
        self.assertTrue((self.remote / "SingletonSocket").exists())

    async def test_wrong_pid_is_not_ownership_even_with_matching_cookies(self):
        await self.launch_fixture()
        (self.profile / "SingletonLock").unlink()
        (self.profile / "SingletonLock").symlink_to(f"{socket.gethostname()}-{self.child.pid + 1}")
        with self.assertRaises(RuntimeError):
            self.pilot._clear_profile_locks()
        self.assertTrue((self.remote / "SingletonSocket").exists())

    async def test_reused_or_still_live_pid_cannot_authorize_unlink(self):
        await self.launch_fixture()
        with patch("src.chromium_singleton.os.kill", return_value=None):
            with self.assertRaises(RuntimeError):
                self.pilot._clear_profile_locks()
        self.assertTrue(os.path.lexists(self.profile / "SingletonLock"))

    async def test_replaced_cookie_after_capture_is_not_deleted(self):
        await self.launch_fixture()
        self.pilot._chromium_singleton_owner.capture()
        (self.remote / "SingletonCookie").unlink()
        (self.remote / "SingletonCookie").symlink_to("replacement")
        with self.assertRaises(RuntimeError):
            self.pilot._clear_profile_locks()
        self.assertTrue(os.path.lexists(self.profile / "SingletonLock"))
        self.assertEqual(os.readlink(self.remote / "SingletonCookie"), "replacement")

    async def test_symlink_remote_directory_and_unrelated_files_are_preserved(self):
        await self.launch_fixture()
        moved = self.tmp / "foreign"
        self.remote.rename(moved)
        self.remote.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            self.pilot._clear_profile_locks()
        self.assertTrue(os.path.lexists(self.profile / "SingletonLock"))
        self.assertTrue((moved / "SingletonSocket").exists())

    async def test_temp_root_swap_during_probe_is_rejected(self):
        await self.launch_fixture()
        connect = socket.socket.connect
        moved = self.root / "moved"

        def swap(endpoint, path):
            try:
                return connect(endpoint, path)
            finally:
                self.tmp.rename(moved)
                self.tmp.mkdir(mode=0o700)

        with patch("socket.socket.connect", swap):
            with self.assertRaises(RuntimeError):
                self.pilot._clear_profile_locks()
        self.assertTrue(os.path.lexists(self.profile / "SingletonLock"))
        self.assertTrue((moved / "sc" / "SingletonSocket").exists())

    async def test_normal_child_cleanup_may_remove_profile_links_before_our_cleanup(self):
        await self.launch_fixture()
        self.pilot._chromium_singleton_owner.capture()
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            (self.profile / name).unlink()
        await self.pilot.stop()
        self.assertFalse(self.remote.exists())

    async def test_port_reservation_failure_releases_empty_pre_spawn_claim(self):
        self.pilot._auto_cdp_port = True
        with patch("socket.socket.bind", side_effect=PermissionError(13, "private")):
            with self.assertRaises(PermissionError):
                await self.pilot._launch_chromium({"TMPDIR": str(self.tmp)}, [])
        failure = None
        try:
            await self.pilot.stop()
        except RuntimeError as exc:
            failure = exc
        self.assertIsNone(failure, "No child was created, so the empty claim must not block stop")
        self.assertIsNone(self.pilot._chromium_singleton_owner)
        self.assertTrue(self.profile.is_dir())

    async def test_captured_links_can_be_cleaned_after_browser_removed_remote_directory(self):
        await self.launch_fixture()
        self.pilot._chromium_singleton_owner.capture()
        self.assertIsNotNone(self.pilot._chromium_singleton_owner.snapshot)
        for name in ("SingletonCookie", "SingletonSocket"):
            (self.remote / name).unlink()
        self.remote.rmdir()
        failure = None
        try:
            await self.pilot.stop()
        except RuntimeError as exc:
            failure = exc
        self.assertIsNone(failure, "The captured, now-absent remote is not an unowned socket")
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            self.assertFalse(os.path.lexists(self.profile / name))
        self.assertIsNone(self.pilot._chromium_singleton_owner)

    async def test_missing_remote_does_not_authorize_replaced_profile_link(self):
        await self.launch_fixture()
        self.pilot._chromium_singleton_owner.capture()
        for name in ("SingletonCookie", "SingletonSocket"):
            (self.remote / name).unlink()
        self.remote.rmdir()
        (self.profile / "SingletonCookie").unlink()
        (self.profile / "SingletonCookie").symlink_to("foreign-cookie")
        with self.assertRaises(RuntimeError):
            self.pilot._clear_profile_locks()
        self.assertEqual(os.readlink(self.profile / "SingletonCookie"), "foreign-cookie")
        self.assertTrue(os.path.lexists(self.profile / "SingletonLock"))

    async def test_missing_remote_without_prior_capture_is_preserved(self):
        await self.launch_fixture()
        for name in ("SingletonCookie", "SingletonSocket"):
            (self.remote / name).unlink()
        self.remote.rmdir()
        with self.assertRaises(RuntimeError):
            self.pilot._clear_profile_locks()
        self.assertTrue(os.path.lexists(self.profile / "SingletonLock"))
        self.assertTrue(os.path.lexists(self.profile / "SingletonCookie"))


if __name__ == "__main__":
    unittest.main()
