"""Regression tests for inherited Xvfb/browser lifecycle defects."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import src.browser as browser_module
from src.browser import BrowserPilot
from src.pilot import Pilot


class _Process:
    def __init__(
        self, *, pid: int, returncode: int | None, stderr: object | None = None
    ) -> None:
        self.pid = pid
        self.returncode = returncode
        self.stderr = stderr

    async def wait(self) -> int:
        return 0 if self.returncode is None else self.returncode


class _Stream:
    def __init__(self, *chunks: bytes) -> None:
        self._chunks = list(chunks)

    async def read(self, _limit: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class _ManagedProcess(_Process):
    def __init__(
        self,
        *,
        pid: int,
        returncode: int | None,
        events: list[str],
        label: str,
    ) -> None:
        super().__init__(pid=pid, returncode=returncode)
        self._events = events
        self._label = label

    def terminate(self) -> None:
        self._events.append(f"terminate:{self._label}")
        self.returncode = 0

    def kill(self) -> None:
        self._events.append(f"kill:{self._label}")
        self.returncode = -9

    async def wait(self) -> int:
        self._events.append(f"process-wait:{self._label}")
        return 0 if self.returncode is None else self.returncode


class BrowserLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def test_legacy_pilot_defaults_keep_fixed_v0_runtime_resources(self) -> None:
        pilot = Pilot()

        self.assertEqual(pilot._browser.display, ":99")
        self.assertEqual(pilot._browser.cdp_port, 9222)

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

    def test_chromium_tmpdir_falls_back_to_python_base_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base_prefix = Path(root) / "usr"
            expected = base_prefix / "tmp"
            expected.mkdir(parents=True)

            with patch("sys.base_prefix", str(base_prefix)):
                resolved = browser_module._validated_chromium_tmpdir(
                    {"PATH": "/usr/bin"}
                )

        self.assertEqual(resolved, str(expected))

    async def test_browser_start_cleans_owned_resources_on_failure(self) -> None:
        pilot = BrowserPilot(
            display="auto",
            cdp_port=0,
            chromium_bin="/usr/bin/chromium",
        )
        pilot._start_xvfb = AsyncMock()
        pilot._setup_gpu = AsyncMock()
        pilot._start_chromium = AsyncMock(
            side_effect=RuntimeError("startup failed")
        )
        pilot.stop = AsyncMock()

        with (
            patch("src._utils.require_binaries"),
            patch.object(
                pilot,
                "_resolve_chromium_binary",
                return_value="/usr/bin/chromium",
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "startup failed"):
                await pilot.start()

        pilot.stop.assert_awaited_once_with()

    async def test_xvfb_start_launches_exactly_one_window_manager(self) -> None:
        calls: list[tuple[object, ...]] = []

        async def launch(*args: object, **_: object) -> _Process:
            calls.append(args)
            return _Process(pid=1000 + len(calls), returncode=None)

        pilot = BrowserPilot(display=":77", window_size="800,600")
        with (
            patch("src.browser.asyncio.create_subprocess_exec", side_effect=launch),
            patch("src.browser.asyncio.sleep", new=AsyncMock()),
            patch("src.browser.os.unlink") as unlink,
            patch("src.browser.shutil.which", return_value="/usr/bin/openbox"),
        ):
            await pilot._start_xvfb()

        self.assertNotIn("pkill", [str(item[0]) for item in calls])
        unlink.assert_not_called()
        openbox_calls = [
            call for call in calls if Path(str(call[0])).name == "openbox"
        ]
        self.assertEqual(openbox_calls, [("/usr/bin/openbox",)])
        self.assertIsNotNone(pilot._wm_proc)

    async def test_auto_display_skips_an_existing_x_server(self) -> None:
        calls: list[tuple[object, ...]] = []
        occupied = {"/tmp/.X99-lock", "/tmp/.X11-unix/X99"}

        async def launch(*args: object, **_: object) -> _Process:
            calls.append(args)
            return _Process(pid=1500 + len(calls), returncode=None)

        with tempfile.TemporaryDirectory() as runtime_dir:
            pilot = BrowserPilot(display="auto", window_size="800,600")
            pilot._runtime_dir = Path(runtime_dir)
            with (
                patch(
                    "src.browser.os.path.exists",
                    side_effect=lambda path: str(path) in occupied,
                ),
                patch(
                    "src.browser.asyncio.create_subprocess_exec",
                    side_effect=launch,
                ),
                patch("src.browser.asyncio.sleep", new=AsyncMock()),
                patch("src.browser.shutil.which", return_value="/usr/bin/openbox"),
            ):
                await pilot._start_xvfb()

            xvfb_call = next(item for item in calls if item[0] == "Xvfb")
            self.assertEqual(pilot.display, ":100")
            self.assertEqual(xvfb_call[1], ":100")
            pilot._release_display_lease()

    def test_display_probe_checks_termux_temp_root(self) -> None:
        termux_tmp = "/data/data/com.termux/files/usr/tmp"
        occupied_socket = f"{termux_tmp}/.X11-unix/X99"
        observed: list[str] = []

        def exists(path: object) -> bool:
            observed.append(str(path))
            return str(path) == occupied_socket

        with (
            patch("src.browser.tempfile.gettempdir", return_value=termux_tmp),
            patch("src.browser.os.path.exists", side_effect=exists),
        ):
            occupied = BrowserPilot._display_in_use(":99")

        self.assertTrue(occupied)
        self.assertIn(occupied_socket, observed)

    async def test_auto_display_lease_prevents_two_pilots_claiming_same_slot(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as runtime_dir:
            first = BrowserPilot(display="auto")
            second = BrowserPilot(display="auto")
            first._runtime_dir = Path(runtime_dir)
            second._runtime_dir = Path(runtime_dir)

            with patch.object(BrowserPilot, "_display_in_use", return_value=False):
                first_display = first._resolve_display("auto")
                second_display = second._resolve_display("auto")

            self.assertEqual(first_display, ":99")
            self.assertEqual(second_display, ":100")

            await first.stop()
            self.assertFalse((Path(runtime_dir) / "display-99.lease").exists())

    def test_stale_auto_display_lease_is_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as runtime_dir:
            lease = Path(runtime_dir) / "display-99.lease"
            lease.write_text("99999999\n", encoding="ascii")
            lease.chmod(0o600)
            pilot = BrowserPilot(display="auto")
            pilot._runtime_dir = Path(runtime_dir)

            with patch.object(BrowserPilot, "_display_in_use", return_value=False):
                display = pilot._resolve_display("auto")

            self.assertEqual(display, ":99")
            self.assertEqual(lease.read_text(encoding="ascii"), f"{os.getpid()}\n")
            pilot._release_display_lease()

    def test_display_release_preserves_a_replaced_lease(self) -> None:
        with tempfile.TemporaryDirectory() as runtime_dir:
            pilot = BrowserPilot(display="auto")
            pilot._runtime_dir = Path(runtime_dir)
            with patch.object(BrowserPilot, "_display_in_use", return_value=False):
                self.assertEqual(pilot._resolve_display("auto"), ":99")

            lease = Path(runtime_dir) / "display-99.lease"
            lease.write_text("123456\n", encoding="ascii")
            pilot._release_display_lease()

            self.assertTrue(lease.is_file())
            self.assertEqual(lease.read_text(encoding="ascii"), "123456\n")

    def test_display_claim_preserves_a_lease_replaced_during_final_probe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as runtime_dir:
            pilot = BrowserPilot(display="auto")
            pilot._runtime_dir = Path(runtime_dir)
            lease = Path(runtime_dir) / "display-99.lease"
            probe_count = 0

            def display_in_use(_display: str) -> bool:
                nonlocal probe_count
                probe_count += 1
                if probe_count == 2:
                    lease.unlink()
                    lease.write_text("123456\n", encoding="ascii")
                    return True
                return False

            with patch.object(
                BrowserPilot,
                "_display_in_use",
                side_effect=display_in_use,
            ):
                claimed = pilot._claim_display(":99")

            self.assertFalse(claimed)
            self.assertTrue(lease.is_file())
            self.assertEqual(lease.read_text(encoding="ascii"), "123456\n")

    async def test_explicit_occupied_display_fails_without_launching(self) -> None:
        pilot = BrowserPilot(display=":77", window_size="800,600")
        with (
            patch(
                "src.browser.os.path.exists",
                side_effect=lambda path: str(path) == "/tmp/.X77-lock",
            ),
            patch("src.browser.asyncio.create_subprocess_exec") as launch,
        ):
            with self.assertRaisesRegex(RuntimeError, "display :77 is already in use"):
                await pilot._start_xvfb()

        launch.assert_not_called()

    async def test_failed_xvfb_releases_lease_before_window_manager_start(
        self,
    ) -> None:
        calls: list[tuple[object, ...]] = []

        async def launch(*args: object, **_: object) -> _Process:
            calls.append(args)
            return _Process(
                pid=1800 + len(calls),
                returncode=1 if args[0] == "Xvfb" else None,
            )

        with tempfile.TemporaryDirectory() as runtime_dir:
            pilot = BrowserPilot(display="auto", window_size="800,600")
            pilot._runtime_dir = Path(runtime_dir)
            with (
                patch.object(BrowserPilot, "_display_in_use", return_value=False),
                patch(
                    "src.browser.asyncio.create_subprocess_exec",
                    side_effect=launch,
                ),
                patch("src.browser.asyncio.sleep", new=AsyncMock()),
                patch("src.browser.shutil.which", return_value="/usr/bin/openbox"),
            ):
                with self.assertRaisesRegex(RuntimeError, "Xvfb failed to start"):
                    await pilot._start_xvfb()

            self.assertFalse(any(item[0] == "/usr/bin/openbox" for item in calls))
            self.assertFalse((Path(runtime_dir) / "display-99.lease").exists())

    async def test_xvfb_start_does_not_mutate_process_display(self) -> None:
        async def launch(*_: object, **__: object) -> _Process:
            return _Process(pid=1900, returncode=None)

        pilot = BrowserPilot(display=":77", window_size="800,600")
        with (
            patch.dict("src.browser.os.environ", {"DISPLAY": ":original"}),
            patch("src.browser.asyncio.create_subprocess_exec", side_effect=launch),
            patch("src.browser.asyncio.sleep", new=AsyncMock()),
            patch("src.browser.shutil.which", return_value="/usr/bin/openbox"),
        ):
            await pilot._start_xvfb()
            self.assertEqual(os.environ["DISPLAY"], ":original")

    async def test_auto_cdp_port_is_resolved_before_chromium_launch(self) -> None:
        launched: list[tuple[object, ...]] = []

        async def launch(*args: object, **_: object) -> _Process:
            launched.append(args)
            return _Process(pid=2001, returncode=None)

        with tempfile.TemporaryDirectory() as profile:
            pilot = BrowserPilot(
                display=":77",
                cdp_port=0,
                chromium_bin="/usr/bin/chromium",
                user_data_dir=profile,
            )
            pilot._user_data_dir = profile
            with (
                patch(
                    "src.browser.asyncio.create_subprocess_exec",
                    side_effect=launch,
                ),
                patch("src.browser.asyncio.sleep", new=AsyncMock()),
            ):
                await pilot._launch_chromium({}, extra_flags=[])

        debugging_flag = next(
            str(arg)
            for arg in launched[0]
            if str(arg).startswith("--remote-debugging-port=")
        )
        self.assertNotEqual(debugging_flag, "--remote-debugging-port=0")
        self.assertGreater(pilot.cdp_port, 0)

    async def test_chromium_child_derives_termux_tmpdir_when_stdio_omits_it(self) -> None:
        launched_environments: list[dict[str, str]] = []

        async def capture_launch(
            environment: dict[str, str], extra_flags: list[str]
        ) -> None:
            launched_environments.append(dict(environment))
            self.assertEqual(extra_flags, [])

        with tempfile.TemporaryDirectory() as root:
            prefix = Path(root) / "usr"
            termux_tmp = prefix / "tmp"
            profile = Path(root) / "profile"
            termux_tmp.mkdir(parents=True)
            profile.mkdir()
            pilot = BrowserPilot(
                display=":77",
                cdp_port=9333,
                chromium_bin="/usr/bin/chromium",
                user_data_dir=str(profile),
            )
            pilot._launch_chromium = capture_launch
            pilot._wait_for_cdp = AsyncMock(return_value="ws://127.0.0.1:9333")

            with patch.dict(
                "src.browser.os.environ",
                {"PATH": "/usr/bin", "PREFIX": str(prefix)},
                clear=True,
            ):
                await pilot._start_chromium()

        self.assertEqual(len(launched_environments), 1)
        self.assertEqual(
            launched_environments[0]["TMPDIR"],
            str(termux_tmp),
        )

    async def test_chromium_launch_keeps_stderr_and_has_no_fixed_sleep(self) -> None:
        kwargs: dict[str, object] = {}
        sleeps: list[float] = []

        async def launch(*_: object, **actual: object) -> _Process:
            kwargs.update(actual)
            return _Process(pid=2002, returncode=None)

        async def record_sleep(delay: float) -> None:
            sleeps.append(delay)

        with tempfile.TemporaryDirectory() as profile:
            pilot = BrowserPilot(
                display=":77",
                cdp_port=9333,
                chromium_bin="/usr/bin/chromium",
                user_data_dir=profile,
            )
            pilot._user_data_dir = profile
            with (
                patch(
                    "src.browser.asyncio.create_subprocess_exec",
                    side_effect=launch,
                ),
                patch("src.browser.asyncio.sleep", new=record_sleep),
            ):
                await pilot._launch_chromium({}, extra_flags=[])

        self.assertIs(kwargs["stderr"], asyncio.subprocess.PIPE)
        self.assertNotIn(3, sleeps)

    async def test_chromium_stderr_is_drained_into_a_bounded_tail(self) -> None:
        stream = _Stream(b"x" * 70000, b"fatal renderer error\n")

        async def launch(*_: object, **__: object) -> _Process:
            return _Process(pid=2004, returncode=None, stderr=stream)

        with tempfile.TemporaryDirectory() as profile:
            pilot = BrowserPilot(
                display=":77",
                cdp_port=9333,
                chromium_bin="/usr/bin/chromium",
                user_data_dir=profile,
            )
            pilot._user_data_dir = profile
            with patch(
                "src.browser.asyncio.create_subprocess_exec", side_effect=launch
            ):
                await pilot._launch_chromium({}, extra_flags=[])
                await asyncio.sleep(0)

        tail = getattr(pilot, "_chromium_stderr_tail", b"")
        self.assertLessEqual(len(tail), 65536)
        self.assertTrue(tail.endswith(b"fatal renderer error\n"))

    async def test_cdp_wait_reports_early_chromium_exit(self) -> None:
        pilot = BrowserPilot(cdp_port=9333)
        pilot._chrome_proc = _Process(pid=2003, returncode=17)

        with patch("src.browser.urllib.request.urlopen", side_effect=OSError):
            with self.assertRaises(Exception) as caught:
                await pilot._wait_for_cdp(timeout=0.05)

        self.assertIsInstance(caught.exception, RuntimeError)
        self.assertIn("returncode=17", str(caught.exception))

    async def test_chromium_retry_is_driven_by_cdp_readiness(self) -> None:
        pilot = BrowserPilot(
            display=":77",
            cdp_port=9333,
            chromium_bin="/usr/bin/chromium",
            gpu_mode="swiftshader",
        )
        attempts: list[tuple[str, ...]] = []
        readiness = 0

        async def launch(_env: dict[str, str], extra_flags: list[str]) -> None:
            attempts.append(tuple(extra_flags))
            pilot._chrome_proc = _Process(pid=3000 + len(attempts), returncode=None)

        async def wait_for_cdp(timeout: float = 20) -> str:
            nonlocal readiness
            readiness += 1
            if readiness == 1:
                pilot._chrome_proc.returncode = 17
                raise RuntimeError("Chromium exited before CDP (returncode=17)")
            return "ws://127.0.0.1:9333/devtools/browser/owned"

        with (
            patch.object(pilot, "_launch_chromium", side_effect=launch),
            patch.object(pilot, "_wait_for_cdp", side_effect=wait_for_cdp),
            patch.object(pilot, "_clear_profile_locks"),
            patch("src.browser.tempfile.mkdtemp", return_value="/tmp/tbp-test-profile"),
        ):
            with self.assertLogs("src.browser", level="WARNING"):
                ws_url = await pilot._start_chromium()

        self.assertEqual(
            attempts,
            [(), ("--single-process",)],
        )
        self.assertEqual(readiness, 2)
        self.assertEqual(ws_url, "ws://127.0.0.1:9333/devtools/browser/owned")

    async def test_chromium_retry_stops_timed_out_process_before_relaunch(
        self,
    ) -> None:
        pilot = BrowserPilot(
            display=":77",
            cdp_port=9333,
            chromium_bin="/usr/bin/chromium",
            gpu_mode="swiftshader",
        )
        events: list[str] = []
        attempts = 0

        async def launch(_env: dict[str, str], extra_flags: list[str]) -> None:
            nonlocal attempts
            attempts += 1
            label = "multi" if not extra_flags else "single"
            events.append(f"launch:{label}")
            pilot._chrome_proc = _ManagedProcess(
                pid=4000 + attempts,
                returncode=None,
                events=events,
                label=label,
            )

        async def wait_for_cdp(timeout: float = 20) -> str:
            label = "multi" if attempts == 1 else "single"
            events.append(f"cdp-wait:{label}")
            if attempts == 1:
                raise TimeoutError("CDP timed out")
            return "ws://127.0.0.1:9333/devtools/browser/owned"

        with (
            patch.object(pilot, "_launch_chromium", side_effect=launch),
            patch.object(pilot, "_wait_for_cdp", side_effect=wait_for_cdp),
            patch.object(pilot, "_clear_profile_locks"),
            patch("src.browser.tempfile.mkdtemp", return_value="/tmp/tbp-test-profile"),
        ):
            with self.assertLogs("src.browser", level="WARNING"):
                await pilot._start_chromium()

        self.assertIn("terminate:multi", events)
        self.assertLess(
            events.index("terminate:multi"),
            events.index("launch:single"),
        )
        self.assertIn("process-wait:multi", events)

    async def test_failed_chromium_start_writes_private_bounded_diagnostic(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as runtime_dir:
            pilot = BrowserPilot(
                display=":77",
                cdp_port=9333,
                chromium_bin="/usr/bin/chromium",
                gpu_mode="swiftshader",
            )
            pilot._runtime_dir = Path(runtime_dir)
            attempt = 0

            async def launch(
                _env: dict[str, str], extra_flags: list[str]
            ) -> None:
                nonlocal attempt
                attempt += 1
                pilot._chrome_proc = _Process(
                    pid=5000 + attempt,
                    returncode=20 + attempt,
                )
                pilot._chromium_stderr_tail = (
                    f"attempt={attempt} private startup detail\n".encode()
                )
                pilot._chromium_stderr_task = None

            with (
                patch.object(pilot, "_launch_chromium", side_effect=launch),
                patch.object(
                    pilot,
                    "_wait_for_cdp",
                    side_effect=RuntimeError("startup failed"),
                ),
                patch.object(pilot, "_clear_profile_locks"),
                patch(
                    "src.browser.tempfile.mkdtemp",
                    return_value="/tmp/tbp-test-profile",
                ),
            ):
                with self.assertLogs("src.browser", level="WARNING"):
                    with self.assertRaisesRegex(
                        RuntimeError, "Chromium failed to start"
                    ):
                        await pilot._start_chromium()

            diagnostic = Path(runtime_dir) / "chromium-startup.log"
            self.assertTrue(diagnostic.is_file())
            self.assertEqual(diagnostic.stat().st_mode & 0o777, 0o600)
            content = diagnostic.read_bytes()
            self.assertIn(b"attempt=1 private startup detail", content)
            self.assertIn(b"attempt=2 private startup detail", content)
            self.assertLessEqual(len(content), 3 * 65536 + 1024)

    async def test_diagnostic_write_failure_does_not_block_chromium_retry(
        self,
    ) -> None:
        pilot = BrowserPilot(
            display=":77",
            cdp_port=9333,
            chromium_bin="/usr/bin/chromium",
            gpu_mode="swiftshader",
        )
        attempts = 0

        async def launch(
            _env: dict[str, str], extra_flags: list[str]
        ) -> None:
            nonlocal attempts
            attempts += 1
            pilot._chrome_proc = _Process(
                pid=6000 + attempts,
                returncode=17 if attempts == 1 else None,
            )
            pilot._chromium_stderr_task = None

        async def wait_for_cdp(timeout: float = 20) -> str:
            if attempts == 1:
                raise RuntimeError("startup failed")
            return "ws://127.0.0.1:9333/devtools/browser/owned"

        with (
            patch.object(pilot, "_launch_chromium", side_effect=launch),
            patch.object(pilot, "_wait_for_cdp", side_effect=wait_for_cdp),
            patch.object(pilot, "_write_chromium_diagnostic", side_effect=OSError),
            patch.object(pilot, "_clear_profile_locks"),
            patch("src.browser.tempfile.mkdtemp", return_value="/tmp/tbp-test-profile"),
        ):
            with self.assertLogs("src.browser", level="WARNING"):
                try:
                    result = await pilot._start_chromium()
                except OSError:
                    self.fail("private diagnostic failure blocked Chromium fallback")

        self.assertEqual(attempts, 2)
        self.assertEqual(result, "ws://127.0.0.1:9333/devtools/browser/owned")
