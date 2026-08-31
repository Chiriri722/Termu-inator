"""Deterministic regressions for the Firefox native JS bridge."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from src import commands
from src.native import NativeFirefoxSession, _navigate
from src.termuinator.backends.legacy_dom import observe_script


class NativeExecutionLatencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_keeps_missing_window_off_stderr_when_bidi_is_owned(
        self,
    ) -> None:
        events: list[str] = []

        class _CallbackServer:
            server_address = ("127.0.0.1", 43123)

            def __init__(self, *_args, **_kwargs) -> None:
                return None

            def serve_forever(self) -> None:
                return None

            def shutdown(self) -> None:
                events.append("callback_shutdown")

        class _Stderr:
            def __init__(self) -> None:
                self._lines = iter(
                    (
                        b"WebDriver BiDi listening on "
                        b"ws://127.0.0.1:46249\n",
                        b"",
                    )
                )

            async def readline(self) -> bytes:
                return next(self._lines, b"")

        class _FirefoxProcess:
            def __init__(self) -> None:
                self.returncode = None
                self.pid = 4242
                self.stderr = _Stderr()

            def terminate(self) -> None:
                events.append("firefox_terminate")

            def kill(self) -> None:
                events.append("firefox_kill")

            async def wait(self) -> int:
                self.returncode = 0
                return 0

        class _WindowSearchProcess:
            async def communicate(self) -> tuple[bytes, bytes]:
                return b"", b""

        class _Bidi:
            def __init__(self, endpoint: str) -> None:
                self.endpoint = endpoint

            async def connect(self, *, timeout: float):
                events.append("bidi_connect")
                return self

            async def close(self) -> None:
                events.append("bidi_close")

        firefox_process = _FirefoxProcess()
        launch_results = iter(
            (
                firefox_process,
                _WindowSearchProcess(),
                _WindowSearchProcess(),
            )
        )
        session = NativeFirefoxSession()
        session._cleanup_profile_locks = Mock()

        with (
            patch("src._utils.require_binaries"),
            patch("src.native.HTTPServer", _CallbackServer),
            patch(
                "src.native.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=lambda *_args, **_kwargs: next(launch_results)),
            ),
            patch("src.native.asyncio.sleep", new=AsyncMock()),
            patch("src.native.FirefoxBidiClient", _Bidi, create=True),
            patch("src.native.logger.warning") as warning,
        ):
            await session.connect()
            self.assertIsInstance(session._bidi, _Bidi)
            warning.assert_not_called()
            await session.close()

    async def test_connect_warns_when_window_and_bidi_are_both_unavailable(
        self,
    ) -> None:
        class _CallbackServer:
            server_address = ("127.0.0.1", 43123)

            def __init__(self, *_args, **_kwargs) -> None:
                return None

            def serve_forever(self) -> None:
                return None

            def shutdown(self) -> None:
                return None

        class _FirefoxProcess:
            def __init__(self) -> None:
                self.returncode = None
                self.pid = 4242
                self.stderr = None

            def terminate(self) -> None:
                return None

            def kill(self) -> None:
                return None

            async def wait(self) -> int:
                self.returncode = 0
                return 0

        class _WindowSearchProcess:
            async def communicate(self) -> tuple[bytes, bytes]:
                return b"", b""

        launch_results = iter(
            (
                _FirefoxProcess(),
                _WindowSearchProcess(),
                _WindowSearchProcess(),
            )
        )
        session = NativeFirefoxSession()
        session._cleanup_profile_locks = Mock()

        with (
            patch("src._utils.require_binaries"),
            patch("src.native.HTTPServer", _CallbackServer),
            patch(
                "src.native.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=lambda *_args, **_kwargs: next(launch_results)),
            ),
            patch("src.native.asyncio.sleep", new=AsyncMock()),
            patch("src.native.logger.warning") as warning,
        ):
            await session.connect()
            warning.assert_called_once_with(
                "Could not find main Firefox window ID"
            )
            await session.close()

    async def test_connect_owns_ephemeral_bidi_before_firefox_shutdown(
        self,
    ) -> None:
        events: list[str] = []
        endpoint_ready = asyncio.Event()
        real_sleep = asyncio.sleep
        real_wait_for = asyncio.wait_for

        class _CallbackServer:
            server_address = ("127.0.0.1", 43123)

            def __init__(self, *_args, **_kwargs) -> None:
                return None

            def serve_forever(self) -> None:
                return None

            def shutdown(self) -> None:
                events.append("callback_shutdown")

        class _Stderr:
            def __init__(self) -> None:
                self._lines = iter(
                    (
                        b"WebDriver BiDi listening on "
                        b"ws://127.0.0.1:46249\n",
                        b"",
                    )
                )

            async def readline(self) -> bytes:
                if not endpoint_ready.is_set():
                    await endpoint_ready.wait()
                return next(self._lines, b"")

        class _Process:
            def __init__(self) -> None:
                self.returncode = None
                self.pid = 4242
                self.stderr = _Stderr()

            def terminate(self) -> None:
                events.append("firefox_terminate")

            def kill(self) -> None:
                events.append("firefox_kill")

            async def wait(self) -> int:
                self.returncode = 0
                return 0

        class _Bidi:
            def __init__(self, endpoint: str) -> None:
                self.endpoint = endpoint

            async def connect(self, *, timeout: float):
                events.append("bidi_connect")
                self.timeout = timeout
                return self

            async def close(self) -> None:
                events.append("bidi_close")

        process = _Process()
        session = NativeFirefoxSession()
        session._cleanup_profile_locks = Mock()

        async def find_main_window() -> str:
            endpoint_ready.set()
            await real_sleep(0)
            return "4242"

        session._find_main_window = AsyncMock(side_effect=find_main_window)
        initial_endpoint_wait = True

        async def timeout_before_window(awaitable, timeout):
            nonlocal initial_endpoint_wait
            if timeout == 6 and initial_endpoint_wait:
                initial_endpoint_wait = False
                raise asyncio.TimeoutError
            return await real_wait_for(awaitable, timeout=timeout)

        with (
            patch("src._utils.require_binaries"),
            patch("src.native.HTTPServer", _CallbackServer),
            patch(
                "src.native.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ) as launch,
            patch("src.native.asyncio.sleep", new=AsyncMock()),
            patch("src.native.asyncio.wait_for", new=timeout_before_window),
            patch("src.native.FirefoxBidiClient", _Bidi, create=True),
        ):
            await session.connect()
            connected_bidi = session._bidi
            await session.close()

        self.assertIsInstance(connected_bidi, _Bidi)
        self.assertEqual(
            connected_bidi.endpoint,
            "ws://127.0.0.1:46249/session",
        )
        self.assertEqual(connected_bidi.timeout, 10)
        launch_args = launch.await_args.args
        self.assertIn("--remote-debugging-port", launch_args)
        self.assertEqual(
            launch_args[launch_args.index("--remote-debugging-port") + 1],
            "0",
        )
        self.assertIs(
            launch.await_args.kwargs["stderr"],
            asyncio.subprocess.PIPE,
        )
        self.assertLess(events.index("bidi_connect"), events.index("bidi_close"))
        self.assertLess(
            events.index("bidi_close"),
            events.index("firefox_terminate"),
        )

    async def test_cancelled_bidi_close_still_reaps_owned_firefox(self) -> None:
        events: list[str] = []

        class _CancelledBidi:
            async def close(self) -> None:
                events.append("bidi_close")
                raise asyncio.CancelledError()

        class _Process:
            def __init__(self) -> None:
                self.returncode = None

            def terminate(self) -> None:
                events.append("firefox_terminate")

            def kill(self) -> None:
                events.append("firefox_kill")

            async def wait(self) -> int:
                self.returncode = 0
                events.append("firefox_wait")
                return 0

        session = NativeFirefoxSession()
        session._bidi = _CancelledBidi()
        session._firefox_proc = _Process()

        with self.assertRaises(asyncio.CancelledError):
            await session.close()

        self.assertIn("firefox_terminate", events)
        self.assertIn("firefox_wait", events)
        self.assertIsNone(session._firefox_proc)

    def test_native_navigation_error_accepts_only_bounded_copy_reasons(
        self,
    ) -> None:
        try:
            error = commands.NativeNavigationError(
                "address_bar_copy",
                reason="read_failed",
            )
        except TypeError:
            self.fail("native navigation errors do not preserve a bounded reason")

        self.assertEqual(error.reason, "read_failed")
        with self.assertRaises(ValueError):
            commands.NativeNavigationError(
                "address_bar_copy",
                reason="private-device-error",
            )
        with self.assertRaises(ValueError):
            commands.NativeNavigationError(
                "metadata_validation",
                reason="read_failed",
            )

    async def test_cancelled_xdt_reaps_only_its_owned_process(self) -> None:
        class _CancelledProcess:
            returncode = None

            def __init__(self) -> None:
                self.killed = False
                self.waited = False

            async def communicate(self) -> tuple[bytes, bytes]:
                raise asyncio.CancelledError()

            def kill(self) -> None:
                self.killed = True

            async def wait(self) -> int:
                self.waited = True
                self.returncode = -9
                return -9

        process = _CancelledProcess()
        session = NativeFirefoxSession()
        with patch(
            "src.native.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await session._xdt(["key", "ctrl+l"])

        self.assertTrue(process.killed)
        self.assertTrue(process.waited)

    async def test_xdt_timeout_log_does_not_expose_arguments(self) -> None:
        private_value = "https://example.com/?token=must-not-be-logged"

        class _SlowProcess:
            returncode = None

            def __init__(self) -> None:
                self.killed = False
                self.waited = False

            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.Event().wait()
                raise AssertionError("unreachable")

            def kill(self) -> None:
                self.killed = True

            async def wait(self) -> int:
                self.waited = True
                self.returncode = -9
                return -9

        process = _SlowProcess()
        session = NativeFirefoxSession()
        with (
            patch(
                "src.native.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
            self.assertLogs("src.native", level="WARNING") as captured,
        ):
            result = await session._xdt(
                ["type", "--", private_value],
                timeout=0.001,
            )

        self.assertEqual(result, "")
        self.assertTrue(process.killed)
        self.assertTrue(process.waited)
        self.assertNotIn(private_value, "\n".join(captured.output))

    async def test_cancelled_clipboard_paste_reaps_owned_process(self) -> None:
        class _Stdin:
            def write(self, _payload: bytes) -> None:
                return None

            def close(self) -> None:
                return None

        class _PasteProcess:
            stdin = _Stdin()
            returncode = None

            def __init__(self) -> None:
                self.terminated = False
                self.waited = False

            def terminate(self) -> None:
                self.terminated = True

            async def wait(self) -> int:
                self.waited = True
                self.returncode = -15
                return -15

        process = _PasteProcess()
        session = NativeFirefoxSession()
        with (
            patch(
                "src.native.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
            patch(
                "src.native.asyncio.sleep",
                new=AsyncMock(side_effect=asyncio.CancelledError()),
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await session._clipboard_paste("private clipboard value")

        self.assertTrue(process.terminated)
        self.assertTrue(process.waited)

    async def test_clipboard_paste_keeps_owner_foreground_until_cleanup(
        self,
    ) -> None:
        class _Stdin:
            def write(self, _payload: bytes) -> None:
                return None

            def close(self) -> None:
                return None

        class _PasteProcess:
            def __init__(self) -> None:
                self.stdin = _Stdin()
                self.returncode: int | None = None
                self.terminated = False
                self.waited = False

            def terminate(self) -> None:
                self.terminated = True

            async def wait(self) -> int:
                self.waited = True
                self.returncode = -15
                return -15

        process = _PasteProcess()

        async def start_xclip(*args: str, **_kwargs: object) -> _PasteProcess:
            process.returncode = None if "-quiet" in args else 0
            return process

        session = NativeFirefoxSession()
        session._xdt = AsyncMock(return_value="")
        with (
            patch(
                "src.native.asyncio.create_subprocess_exec",
                new=start_xclip,
            ),
            patch("src.native.asyncio.sleep", new=AsyncMock()),
        ):
            result = await session._clipboard_paste("clipboard value")

        self.assertTrue(result)
        self.assertTrue(process.terminated)
        self.assertTrue(process.waited)

    async def test_clipboard_paste_error_log_is_value_free(self) -> None:
        private_value = "must-not-cross-clipboard-log"
        session = NativeFirefoxSession()
        with (
            patch(
                "src.native.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=OSError(private_value)),
            ),
            self.assertLogs("src.native", level="DEBUG") as captured,
        ):
            result = await session._clipboard_paste("private clipboard value")

        self.assertFalse(result)
        self.assertNotIn(private_value, "\n".join(captured.output))

    async def test_cancelled_clipboard_read_reaps_only_its_owned_process(
        self,
    ) -> None:
        class _CancelledReadProcess:
            returncode = None

            def __init__(self) -> None:
                self.killed = False
                self.waited = False

            async def communicate(self) -> tuple[bytes, bytes]:
                raise asyncio.CancelledError()

            def kill(self) -> None:
                self.killed = True

            async def wait(self) -> int:
                self.waited = True
                self.returncode = -9
                return -9

        process = _CancelledReadProcess()
        session = NativeFirefoxSession()
        with patch(
            "src.native.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await session._clipboard_read()

        self.assertTrue(process.killed)
        self.assertTrue(process.waited)

    async def test_clipboard_read_rejects_nonzero_xclip_status(self) -> None:
        class _FailedReadProcess:
            returncode = 1

            async def communicate(self) -> tuple[bytes, bytes]:
                return b"", b""

        session = NativeFirefoxSession()
        with patch(
            "src.native.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=_FailedReadProcess()),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "X11 clipboard read failed",
            ):
                await session._clipboard_read()

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

    async def test_exec_js_uses_bidi_without_console_or_clipboard(self) -> None:
        session = NativeFirefoxSession()
        source = observe_script("__bidi_registry_key")
        expected = {
            "ready_state": "complete",
            "dom_version": 0,
            "elements": [],
        }
        session._bidi = SimpleNamespace(
            evaluate=AsyncMock(return_value=expected)
        )
        session._exec_js_inner = AsyncMock(
            side_effect=AssertionError("console fallback must stay idle")
        )

        result = await session._exec_js(source, timeout=7)

        self.assertEqual(result, expected)
        session._bidi.evaluate.assert_awaited_once_with(source, timeout=7)
        session._exec_js_inner.assert_not_awaited()

    async def test_bidi_eval_timeout_is_bounded_without_console_retry(self) -> None:
        session = NativeFirefoxSession()
        private_error = "private BiDi timeout detail"
        session._bidi = SimpleNamespace(
            evaluate=AsyncMock(side_effect=TimeoutError(private_error))
        )
        session._exec_js_inner = AsyncMock(
            side_effect=AssertionError("console fallback must stay idle")
        )

        with self.assertRaises(commands.JavascriptExecutionTimeout) as caught:
            await session._exec_js("document.readyState", timeout=7)

        self.assertNotIn(private_error, str(caught.exception))
        session._bidi.evaluate.assert_awaited_once()
        session._exec_js_inner.assert_not_awaited()

    async def test_bidi_eval_failure_is_bounded_without_console_retry(self) -> None:
        session = NativeFirefoxSession()
        private_error = "private BiDi protocol detail"
        session._bidi = SimpleNamespace(
            evaluate=AsyncMock(side_effect=RuntimeError(private_error))
        )
        session._exec_js_inner = AsyncMock(
            side_effect=AssertionError("console fallback must stay idle")
        )

        with self.assertRaises(commands.JavascriptExecutionError) as caught:
            await session._exec_js("document.readyState", timeout=7)

        self.assertEqual(caught.exception.reason, "evaluation")
        self.assertNotIn(private_error, str(caught.exception))
        session._bidi.evaluate.assert_awaited_once()
        session._exec_js_inner.assert_not_awaited()

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
        session._main_wid = "4242"
        xdt_calls: list[list[str]] = []

        async def fake_exec_js(_expression: str, timeout: float = 60) -> str:
            return "ERR:Timeout - console did not respond"

        async def fake_close_console() -> None:
            return None

        async def fake_xdt(args: list[str]) -> str:
            xdt_calls.append(args)
            if args == ["getactivewindow"]:
                return "4242"
            if args == ["getwindowname", "4242"]:
                return "Example Domain — Mozilla Firefox"
            return ""

        async def fake_clipboard_paste(_text: str) -> bool:
            return True

        async def fake_clipboard_read() -> str:
            return "https://example.com/"

        session._exec_js = fake_exec_js
        session._close_console = fake_close_console
        session._xdt = fake_xdt
        session._clipboard_paste = fake_clipboard_paste
        session._clipboard_read = fake_clipboard_read
        session._prime_navigation_clipboard = AsyncMock(
            return_value=("navigation-marker", object())
        )
        session._release_clipboard_owner = AsyncMock()

        with patch("src.native.asyncio.sleep", new=AsyncMock()):
            await _navigate(
                session,
                {"url": "https://example.com"},
                timeout=5,
            )

        activation = ["windowactivate", "--sync", "4242"]
        self.assertIn(activation, xdt_calls)
        self.assertLess(
            xdt_calls.index(activation),
            xdt_calls.index(["key", "ctrl+l"]),
        )
        self.assertIn(["key", "ctrl+l"], xdt_calls)
        self.assertIn(["key", "Return"], xdt_calls)

    async def test_navigation_uses_bidi_metadata_without_gui_clipboard(
        self,
    ) -> None:
        session = NativeFirefoxSession()
        expected = {
            "url": "http://127.0.0.1:43123/forms?redirected=1",
            "title": "Forms",
        }
        session._bidi = SimpleNamespace(
            navigate=AsyncMock(return_value=expected)
        )
        session._exec_js = AsyncMock(
            side_effect=AssertionError("console navigation must stay idle")
        )
        session._close_console = AsyncMock(
            side_effect=AssertionError("console cleanup must stay idle")
        )
        session._focus_main_window = AsyncMock(
            side_effect=AssertionError("window focus must stay idle")
        )
        session._xdt = AsyncMock(
            side_effect=AssertionError("xdotool must stay idle")
        )
        session._clipboard_paste = AsyncMock(
            side_effect=AssertionError("clipboard paste must stay idle")
        )
        session._navigation_metadata = AsyncMock(
            side_effect=AssertionError("clipboard metadata must stay idle")
        )

        try:
            result = await _navigate(
                session,
                {"url": "http://127.0.0.1:43123/forms"},
                timeout=45,
            )
        except Exception as exc:
            self.fail(f"BiDi navigation did not bypass the GUI path: {type(exc)}")

        self.assertEqual(result.get("termuinatorNavigation"), expected)
        session._bidi.navigate.assert_awaited_once_with(
            "http://127.0.0.1:43123/forms",
            timeout=45,
        )
        session._exec_js.assert_not_awaited()
        session._close_console.assert_not_awaited()
        session._focus_main_window.assert_not_awaited()
        session._xdt.assert_not_awaited()
        session._clipboard_paste.assert_not_awaited()
        session._navigation_metadata.assert_not_awaited()

    async def test_bidi_navigation_timeout_does_not_retry_through_gui(
        self,
    ) -> None:
        session = NativeFirefoxSession()
        session._bidi = SimpleNamespace(
            navigate=AsyncMock(side_effect=TimeoutError("private timeout"))
        )
        session._exec_js = AsyncMock(
            side_effect=AssertionError("console fallback is unsafe")
        )
        session._close_console = AsyncMock(
            side_effect=AssertionError("GUI fallback is unsafe")
        )

        try:
            await _navigate(
                session,
                {"url": "https://example.com"},
                timeout=45,
            )
        except Exception as exc:
            self.assertIsInstance(exc, TimeoutError)
            self.assertNotIn("private timeout", str(exc))
        else:
            self.fail("BiDi timeout was accepted as a successful navigation")

        session._bidi.navigate.assert_awaited_once()
        session._exec_js.assert_not_awaited()
        session._close_console.assert_not_awaited()

    async def test_bidi_protocol_failure_is_bounded_without_gui_retry(
        self,
    ) -> None:
        session = NativeFirefoxSession()
        private_error = "private BiDi protocol response"
        session._bidi = SimpleNamespace(
            navigate=AsyncMock(side_effect=RuntimeError(private_error))
        )
        session._exec_js = AsyncMock(
            side_effect=AssertionError("console fallback is unsafe")
        )
        session._close_console = AsyncMock(
            side_effect=AssertionError("GUI fallback is unsafe")
        )

        with self.assertRaises(commands.NativeNavigationError) as caught:
            await _navigate(
                session,
                {"url": "https://example.com"},
                timeout=45,
            )

        self.assertEqual(caught.exception.stage, "bidi_navigation")
        self.assertNotIn(private_error, str(caught.exception))
        session._bidi.navigate.assert_awaited_once()
        session._exec_js.assert_not_awaited()
        session._close_console.assert_not_awaited()

    async def test_navigation_fallback_requires_a_main_window(self) -> None:
        navigation_error = getattr(commands, "NativeNavigationError", None)
        self.assertIsNotNone(navigation_error)
        assert navigation_error is not None
        session = NativeFirefoxSession()
        session._main_wid = None
        session._exec_js = AsyncMock(
            return_value="ERR:Timeout - console did not respond"
        )
        session._close_console = AsyncMock()
        session._focus_main_window = AsyncMock()
        session._xdt = AsyncMock(return_value="")
        session._clipboard_paste = AsyncMock(return_value=True)
        session._navigation_metadata = AsyncMock(
            return_value={
                "url": "https://example.com/",
                "title": "Example Domain",
            }
        )

        with patch("src.native.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(navigation_error) as caught:
                await _navigate(
                    session,
                    {"url": "https://example.com"},
                    timeout=5,
                )

        self.assertEqual(caught.exception.stage, "window_unavailable")
        session._xdt.assert_not_awaited()
        session._clipboard_paste.assert_not_awaited()

    async def test_native_navigation_returns_address_bar_metadata(self) -> None:
        session = NativeFirefoxSession()
        session._main_wid = "4242"
        xdt_calls: list[list[str]] = []

        async def fake_exec_js(_expression: str, timeout: float = 60) -> bool:
            return True

        async def fake_close_console() -> None:
            return None

        async def fake_focus_main_window() -> None:
            return None

        async def fake_xdt(args: list[str]) -> str:
            xdt_calls.append(args)
            if args == ["getactivewindow"]:
                return "4242"
            if args == ["getwindowname", "4242"]:
                return "Forms — Mozilla Firefox"
            return ""

        async def fake_clipboard_read() -> str:
            return "http://127.0.0.1:43123/forms?redirected=1"

        session._exec_js = fake_exec_js
        session._close_console = fake_close_console
        session._focus_main_window = fake_focus_main_window
        session._xdt = fake_xdt
        session._clipboard_read = fake_clipboard_read
        session._prime_navigation_clipboard = AsyncMock(
            return_value=("navigation-marker", object())
        )
        session._release_clipboard_owner = AsyncMock()

        with patch("src.native.asyncio.sleep", new=AsyncMock()):
            result = await _navigate(
                session,
                {"url": "http://127.0.0.1:43123/forms"},
                timeout=5,
            )

        self.assertEqual(
            result.get("termuinatorNavigation"),
            {
                "url": "http://127.0.0.1:43123/forms?redirected=1",
                "title": "Forms — Mozilla Firefox",
            },
        )
        self.assertIn(["key", "ctrl+l"], xdt_calls)
        self.assertIn(["key", "ctrl+c"], xdt_calls)
        self.assertIn(["key", "Escape"], xdt_calls)

    async def test_navigation_metadata_retries_delayed_address_bar_copy(
        self,
    ) -> None:
        session = NativeFirefoxSession()
        session._main_wid = "4242"
        marker = "termuinator-navigation-marker"
        expected_url = "http://127.0.0.1:43123/forms"
        clipboard_owner = object()
        xdt_calls: list[list[str]] = []

        async def fake_xdt(args: list[str]) -> str:
            xdt_calls.append(args)
            if args == ["getactivewindow"]:
                return "4242"
            if args == ["getwindowname", "4242"]:
                return "Forms — Mozilla Firefox"
            return ""

        session._focus_main_window = AsyncMock()
        session._xdt = fake_xdt
        session._clipboard_read = AsyncMock(
            side_effect=(marker, expected_url)
        )
        session._prime_navigation_clipboard = AsyncMock(
            return_value=(marker, clipboard_owner)
        )
        session._release_clipboard_owner = AsyncMock()

        with patch("src.native.asyncio.sleep", new=AsyncMock()):
            result = await session._navigation_metadata(timeout=5)

        self.assertEqual(
            result,
            {
                "url": expected_url,
                "title": "Forms — Mozilla Firefox",
            },
        )
        self.assertEqual(xdt_calls.count(["key", "ctrl+c"]), 2)
        self.assertEqual(xdt_calls.count(["key", "ctrl+l"]), 2)
        self.assertEqual(session._focus_main_window.await_count, 2)
        self.assertEqual(session._clipboard_read.await_count, 2)

    async def test_navigation_releases_marker_owner_before_browser_copy(
        self,
    ) -> None:
        session = NativeFirefoxSession()
        session._main_wid = "4242"
        marker = "termuinator-navigation-marker"
        expected_url = "http://127.0.0.1:43123/forms"
        clipboard_owner = object()
        owner_released = False

        async def release_owner(process: object) -> None:
            nonlocal owner_released
            self.assertIs(process, clipboard_owner)
            owner_released = True

        async def read_browser_clipboard() -> str:
            if owner_released:
                return expected_url
            return marker

        async def fake_xdt(args: list[str]) -> str:
            if args == ["getactivewindow"]:
                return "4242"
            if args == ["getwindowname", "4242"]:
                return "Forms — Mozilla Firefox"
            return ""

        session._focus_main_window = AsyncMock()
        session._xdt = fake_xdt
        session._clipboard_read = read_browser_clipboard
        session._prime_navigation_clipboard = AsyncMock(
            return_value=(marker, clipboard_owner)
        )
        session._release_clipboard_owner = AsyncMock(
            side_effect=release_owner
        )

        try:
            with patch("src.native.asyncio.sleep", new=AsyncMock()):
                result = await session._navigation_metadata(timeout=5)
        except commands.NativeNavigationError as exc:
            self.fail(
                "marker owner remained live during the browser copy: "
                f"{exc.stage}"
            )

        self.assertEqual(result["url"], expected_url)
        session._release_clipboard_owner.assert_awaited_once_with(
            clipboard_owner
        )

    async def test_navigation_accepts_slow_firefox_clipboard_delivery(
        self,
    ) -> None:
        session = NativeFirefoxSession()
        session._main_wid = "4242"
        expected_url = "http://127.0.0.1:43123/forms"
        clipboard_owner = object()

        async def read_browser_clipboard() -> str:
            await asyncio.sleep(1.2)
            return expected_url

        async def fake_xdt(args: list[str]) -> str:
            if args == ["getactivewindow"]:
                return "4242"
            if args == ["getwindowname", "4242"]:
                return "Forms — Mozilla Firefox"
            return ""

        session._focus_main_window = AsyncMock()
        session._xdt = fake_xdt
        session._clipboard_read = read_browser_clipboard
        session._prime_navigation_clipboard = AsyncMock(
            return_value=("termuinator-navigation-marker", clipboard_owner)
        )
        session._release_clipboard_owner = AsyncMock()

        try:
            result = await session._navigation_metadata(timeout=5)
        except commands.NativeNavigationError as exc:
            self.fail(
                "valid Firefox clipboard delivery exceeded the fixed read "
                f"window: {exc.stage}"
            )

        self.assertEqual(result["url"], expected_url)
        session._release_clipboard_owner.assert_awaited_once_with(
            clipboard_owner
        )

    async def test_navigation_bounds_marker_release_failure_stage(
        self,
    ) -> None:
        session = NativeFirefoxSession()
        clipboard_owner = object()
        private_error = "private-xclip-release-detail"

        session._prime_navigation_clipboard = AsyncMock(
            return_value=("termuinator-navigation-marker", clipboard_owner)
        )
        session._release_clipboard_owner = AsyncMock(
            side_effect=OSError(private_error)
        )

        try:
            with self.assertRaises(commands.NativeNavigationError) as raised:
                await session._navigation_metadata(timeout=5)
        except OSError as exc:
            self.fail(
                "clipboard cleanup replaced the bounded navigation error: "
                f"{exc}"
            )

        self.assertEqual(raised.exception.stage, "address_bar_copy")
        self.assertEqual(
            getattr(raised.exception, "reason", None),
            "owner_release_failed",
        )
        self.assertNotIn(private_error, str(raised.exception))

    async def test_navigation_rejects_unchanged_primed_clipboard(self) -> None:
        navigation_error = getattr(commands, "NativeNavigationError", None)
        self.assertIsNotNone(navigation_error)
        assert navigation_error is not None
        session = NativeFirefoxSession()
        session._main_wid = "4242"
        marker = "termuinator-navigation-marker"
        clipboard_owner = object()
        session._focus_main_window = AsyncMock()
        session._xdt = AsyncMock(return_value="4242")
        session._clipboard_read = AsyncMock(return_value=marker)
        session._prime_navigation_clipboard = AsyncMock(
            return_value=(marker, clipboard_owner)
        )
        session._release_clipboard_owner = AsyncMock()

        with patch("src.native.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(navigation_error) as caught:
                await session._navigation_metadata(timeout=5)

        self.assertEqual(caught.exception.stage, "address_bar_copy")
        self.assertEqual(
            getattr(caught.exception, "reason", None),
            "marker_unchanged",
        )
        self.assertEqual(session._clipboard_read.await_count, 3)
        session._prime_navigation_clipboard.assert_awaited_once_with()
        session._release_clipboard_owner.assert_awaited_once_with(
            clipboard_owner
        )

    async def test_navigation_bounds_clipboard_read_failure_stage(self) -> None:
        navigation_error = getattr(commands, "NativeNavigationError", None)
        self.assertIsNotNone(navigation_error)
        assert navigation_error is not None
        private_value = "must-not-cross-native-navigation"
        session = NativeFirefoxSession()
        session._main_wid = "4242"
        clipboard_owner = object()
        session._focus_main_window = AsyncMock()
        session._xdt = AsyncMock(return_value="4242")
        session._clipboard_read = AsyncMock(
            side_effect=OSError(private_value)
        )
        session._prime_navigation_clipboard = AsyncMock(
            return_value=("termuinator-navigation-marker", clipboard_owner)
        )
        session._release_clipboard_owner = AsyncMock()

        with patch("src.native.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(navigation_error) as caught:
                await session._navigation_metadata(timeout=5)

        self.assertEqual(caught.exception.stage, "address_bar_copy")
        self.assertEqual(
            getattr(caught.exception, "reason", None),
            "read_failed",
        )
        self.assertNotIn(private_value, str(caught.exception))
        session._release_clipboard_owner.assert_awaited_once_with(
            clipboard_owner
        )

    async def test_navigation_classifies_malformed_copied_url(self) -> None:
        navigation_error = getattr(commands, "NativeNavigationError", None)
        self.assertIsNotNone(navigation_error)
        assert navigation_error is not None
        session = NativeFirefoxSession()
        session._main_wid = "4242"
        clipboard_owner = object()
        session._focus_main_window = AsyncMock()
        session._xdt = AsyncMock(return_value="4242")
        session._clipboard_read = AsyncMock(return_value="https://[")
        session._prime_navigation_clipboard = AsyncMock(
            return_value=("termuinator-navigation-marker", clipboard_owner)
        )
        session._release_clipboard_owner = AsyncMock()

        with patch("src.native.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(navigation_error) as caught:
                await session._navigation_metadata(timeout=5)

        self.assertEqual(caught.exception.stage, "address_bar_copy")
        self.assertEqual(
            getattr(caught.exception, "reason", None),
            "invalid_url",
        )
        session._release_clipboard_owner.assert_awaited_once_with(
            clipboard_owner
        )

    async def test_navigation_classifies_empty_clipboard_selection(self) -> None:
        session = NativeFirefoxSession()
        session._main_wid = "4242"
        clipboard_owner = object()
        session._focus_main_window = AsyncMock()
        session._xdt = AsyncMock(return_value="4242")
        session._clipboard_read = AsyncMock(return_value="")
        session._prime_navigation_clipboard = AsyncMock(
            return_value=("termuinator-navigation-marker", clipboard_owner)
        )
        session._release_clipboard_owner = AsyncMock()

        with patch("src.native.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(commands.NativeNavigationError) as caught:
                await session._navigation_metadata(timeout=5)

        self.assertEqual(caught.exception.stage, "address_bar_copy")
        self.assertEqual(
            getattr(caught.exception, "reason", None),
            "selection_empty",
        )

    async def test_navigation_classifies_clipboard_read_timeout(self) -> None:
        session = NativeFirefoxSession()
        session._main_wid = "4242"
        clipboard_owner = object()
        session._focus_main_window = AsyncMock()
        session._xdt = AsyncMock(return_value="4242")
        session._clipboard_read = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )
        session._prime_navigation_clipboard = AsyncMock(
            return_value=("termuinator-navigation-marker", clipboard_owner)
        )
        session._release_clipboard_owner = AsyncMock()

        with patch("src.native.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(commands.NativeNavigationError) as caught:
                await session._navigation_metadata(timeout=5)

        self.assertEqual(caught.exception.stage, "address_bar_copy")
        self.assertEqual(
            getattr(caught.exception, "reason", None),
            "read_timeout",
        )

    async def test_navigation_verifies_main_window_focus_before_copy(self) -> None:
        session = NativeFirefoxSession()
        session._main_wid = "4242"
        clipboard_owner = object()
        session._focus_main_window = AsyncMock()
        session._xdt = AsyncMock(return_value="9001")
        session._clipboard_read = AsyncMock(
            return_value="http://127.0.0.1:43123/forms"
        )
        session._prime_navigation_clipboard = AsyncMock(
            return_value=("termuinator-navigation-marker", clipboard_owner)
        )
        session._release_clipboard_owner = AsyncMock()

        with patch("src.native.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(commands.NativeNavigationError) as caught:
                await session._navigation_metadata(timeout=5)

        self.assertEqual(caught.exception.stage, "address_bar_copy")
        self.assertEqual(
            getattr(caught.exception, "reason", None),
            "focus_unverified",
        )
        session._clipboard_read.assert_not_awaited()

    async def test_navigation_clipboard_marker_is_verified_and_cleaned(self) -> None:
        navigation_error = getattr(commands, "NativeNavigationError", None)
        self.assertIsNotNone(navigation_error)
        assert navigation_error is not None

        class _FakeStdin:
            def __init__(self) -> None:
                self.payload = b""
                self.closed = False

            def write(self, payload: bytes) -> None:
                self.payload = payload

            async def drain(self) -> None:
                return None

            def close(self) -> None:
                self.closed = True

        class _FakeProcess:
            def __init__(self) -> None:
                self.stdin = _FakeStdin()
                self.returncode = None
                self.terminated = False

            def terminate(self) -> None:
                self.terminated = True

            def kill(self) -> None:
                raise AssertionError("cooperative xclip should not be killed")

            async def wait(self) -> int:
                self.returncode = 0
                return 0

        session = NativeFirefoxSession()
        process = _FakeProcess()
        session._clipboard_read = AsyncMock(return_value="stale-valid-url")

        with (
            patch(
                "src.native.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ) as create_process,
            patch("src.native.asyncio.sleep", new=AsyncMock()),
        ):
            with self.assertRaises(navigation_error) as caught:
                await session._prime_navigation_clipboard()

        self.assertEqual(caught.exception.stage, "clipboard_prime")
        self.assertTrue(process.stdin.payload.startswith(b"TBP_NAV_"))
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.terminated)
        self.assertEqual(session._clipboard_read.await_count, 3)
        create_process.assert_awaited_once()

    async def test_navigation_clipboard_marker_retries_delayed_owner(self) -> None:
        class _FakeStdin:
            def write(self, _payload: bytes) -> None:
                return None

            async def drain(self) -> None:
                return None

            def close(self) -> None:
                return None

        class _FakeProcess:
            stdin = _FakeStdin()
            returncode = None

            def terminate(self) -> None:
                raise AssertionError("live marker owner must be returned")

        session = NativeFirefoxSession()
        process = _FakeProcess()
        session._clipboard_read = AsyncMock(
            side_effect=("previous-selection", "TBP_NAV_fixed")
        )

        with (
            patch(
                "src.native.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
            patch(
                "src.native.uuid.uuid4",
                return_value=SimpleNamespace(hex="fixed"),
            ),
            patch("src.native.asyncio.sleep", new=AsyncMock()),
        ):
            marker, owner = await session._prime_navigation_clipboard()

        self.assertEqual(marker, "TBP_NAV_fixed")
        self.assertIs(owner, process)
        self.assertEqual(session._clipboard_read.await_count, 2)

    async def test_navigation_clipboard_marker_keeps_owner_foreground(
        self,
    ) -> None:
        class _FakeStdin:
            def write(self, _payload: bytes) -> None:
                return None

            async def drain(self) -> None:
                return None

            def close(self) -> None:
                return None

        class _FakeProcess:
            def __init__(self) -> None:
                self.stdin = _FakeStdin()
                self.returncode: int | None = None
                self.terminated = False
                self.waited = False

            def terminate(self) -> None:
                self.terminated = True

            async def wait(self) -> int:
                self.waited = True
                self.returncode = -15
                return -15

        process = _FakeProcess()

        async def start_xclip(*args: str, **_kwargs: object) -> _FakeProcess:
            process.returncode = None if "-quiet" in args else 0
            return process

        session = NativeFirefoxSession()
        session._clipboard_read = AsyncMock(return_value="TBP_NAV_fixed")
        try:
            with (
                patch(
                    "src.native.asyncio.create_subprocess_exec",
                    new=start_xclip,
                ),
                patch(
                    "src.native.uuid.uuid4",
                    return_value=SimpleNamespace(hex="fixed"),
                ),
                patch("src.native.asyncio.sleep", new=AsyncMock()),
            ):
                marker, owner = await session._prime_navigation_clipboard()
        except commands.NativeNavigationError as exc:
            self.fail(
                "default-forked xclip parent was rejected instead of using "
                f"a foreground owner: {exc.stage}"
            )

        self.assertEqual(marker, "TBP_NAV_fixed")
        self.assertIs(owner, process)
        await session._release_clipboard_owner(owner)
        self.assertTrue(process.terminated)
        self.assertTrue(process.waited)

    async def test_page_commands_accept_verified_native_navigation_metadata(
        self,
    ) -> None:
        expected = {
            "url": "http://127.0.0.1:43123/forms",
            "title": "Forms — Mozilla Firefox",
        }

        class _NativeSession:
            async def send(
                self,
                method: str,
                params: dict[str, str],
                timeout: float | None = None,
            ) -> dict[str, object]:
                del timeout
                if method != "Page.navigate":
                    raise AssertionError(method)
                return {
                    "frameId": "native",
                    "termuinatorNavigation": expected,
                }

        page = commands.PageCommands(_NativeSession())
        page.evaluate = AsyncMock(
            side_effect=AssertionError("native navigation must not poll console")
        )
        result = await page.navigate(expected["url"], timeout=0)

        self.assertEqual(result, expected)
        page.evaluate.assert_not_awaited()

    async def test_page_commands_forward_navigation_timeout_to_transport(
        self,
    ) -> None:
        expected = {
            "url": "https://example.com/",
            "title": "Example Domain",
        }

        class _TimeoutRecordingSession:
            timeout: float | None = None

            async def send(
                self,
                _method: str,
                _params: dict[str, str],
                timeout: float | None = None,
            ) -> dict[str, object]:
                self.timeout = timeout
                return {
                    "frameId": "native",
                    "termuinatorNavigation": expected,
                }

        session = _TimeoutRecordingSession()
        page = commands.PageCommands(session)

        result = await page.navigate("https://example.com", timeout=7.25)

        self.assertEqual(result, expected)
        self.assertEqual(session.timeout, 7.25)

    async def test_networkidle_forwards_navigation_timeout_to_transport(
        self,
    ) -> None:
        private_failure = RuntimeError("stop-after-recording-timeout")

        class _TimeoutRecordingSession:
            timeout: float | None = None

            def on(self, *_args: object) -> None:
                return None

            def off(self, *_args: object) -> None:
                return None

            async def send(
                self,
                _method: str,
                _params: dict[str, str],
                timeout: float | None = None,
            ) -> dict[str, object]:
                self.timeout = timeout
                raise private_failure

        session = _TimeoutRecordingSession()
        page = commands.PageCommands(session)

        with self.assertRaises(RuntimeError) as caught:
            await page.navigate(
                "https://example.com",
                wait_until="networkidle",
                timeout=8.5,
            )

        self.assertIs(caught.exception, private_failure)
        self.assertEqual(session.timeout, 8.5)

    async def test_page_commands_classify_invalid_native_metadata(self) -> None:
        navigation_error = getattr(commands, "NativeNavigationError", None)
        self.assertIsNotNone(navigation_error)
        assert navigation_error is not None

        class _InvalidNativeSession:
            async def send(
                self,
                _method: str,
                _params: dict[str, str],
                timeout: float | None = None,
            ) -> dict[str, object]:
                del timeout
                return {
                    "frameId": "native",
                    "termuinatorNavigation": {
                        "url": "about:blank",
                        "title": "private-title-must-not-be-echoed",
                    },
                }

        page = commands.PageCommands(_InvalidNativeSession())

        with self.assertRaises(navigation_error) as caught:
            await page.navigate("https://example.com", timeout=1)

        self.assertEqual(caught.exception.stage, "metadata_validation")
        self.assertNotIn("private-title", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
