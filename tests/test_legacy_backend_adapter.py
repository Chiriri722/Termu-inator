"""Tests for the typed adapter over the inherited browser lifecycle."""

from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path
import tempfile
import unittest

from src.commands import JavascriptExecutionTimeout
from src.termuinator.backends import (
    BackendAction,
    BackendArtifactPayload,
    BackendConsoleEntry,
    BackendDevtoolsQuery,
    BackendDomEntry,
    BackendNetworkEntry,
    BackendPageSnapshot,
    BackendPerformanceEntry,
    BackendStyleEntry,
    BrowserBackend,
    LegacyPilotBackend,
)
from src.termuinator.contracts import (
    ActionKind,
    Backend,
    CapabilityStatus,
    ChallengeKind,
    ChallengeState,
    ErrorCode,
    SessionState,
    Viewport,
    to_wire,
)
from src.termuinator.core.service import BrowserService
from src.termuinator.errors import TermuinatorError


class _RecordingPilot:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.current_url = "about:blank"

    async def start(self) -> None:
        self.calls.append("start")

    async def stop(self) -> None:
        self.calls.append("stop")

    async def goto(self, url: str, timeout: float) -> None:
        self.calls.append(("goto", url, timeout))
        self.current_url = url

    async def url(self) -> str:
        self.calls.append("url")
        return self.current_url

    async def title(self) -> str:
        self.calls.append("title")
        return "Example Domain"

    async def text(self) -> str:
        self.calls.append("text")
        return "abcdef"

    async def a11y_tree(self) -> str:
        self.calls.append("a11y_tree")
        return "[heading] Example Domain"

    async def a11y_nodes(self) -> list[dict[str, object]]:
        self.calls.append("a11y_nodes")
        return [
            {
                "nodeId": "private-generic-node",
                "role": {"type": "role", "value": "generic"},
                "name": {"type": "computedString", "value": ""},
            },
            {
                "nodeId": "private-ax-node",
                "role": {"type": "role", "value": "heading"},
                "name": {
                    "type": "computedString",
                    "value": "Example Domain",
                },
                "properties": [
                    {"name": "raw-private-property", "value": "not-public"}
                ],
            }
        ]

    async def evaluate(self, script: str) -> object:
        if "TERMUINATOR_DEVTOOLS_CONSOLE_V1" in script:
            self.calls.append("devtools_console")
            return {
                "entries": [
                    {
                        "level": "error",
                        "message": "console failure",
                        "timestamp": "2026-08-24T00:00:00+00:00",
                    }
                ],
                "truncated": False,
            }
        if "TERMUINATOR_DEVTOOLS_NETWORK_V1" in script:
            self.calls.append("devtools_network")
            return {
                "entries": [
                    {
                        "backend_request_id": "request_private_1",
                        "method": "GET",
                        "url": "https://example.com/api",
                        "status": 200,
                        "resource_type": "fetch",
                        "started_at": "2026-08-24T00:00:00+00:00",
                        "duration_ms": 12.5,
                    }
                ],
                "truncated": False,
            }
        if "TERMUINATOR_DEVTOOLS_DOM_V1" in script:
            self.calls.append("devtools_dom")
            return {
                "entries": [
                    {
                        "backend_node_id": "private-node-1",
                        "tag": "input",
                        "role": "textbox",
                        "name": "Account name",
                        "text": "",
                        "x": 20.0,
                        "y": 30.0,
                        "width": 120.0,
                        "height": 40.0,
                    }
                ],
                "truncated": False,
            }
        if "TERMUINATOR_DEVTOOLS_STYLE_V1" in script:
            self.calls.append("devtools_style")
            return {
                "entries": [{"name": "color", "value": "rgb(0, 0, 0)"}],
                "truncated": False,
            }
        if "TERMUINATOR_DEVTOOLS_PERFORMANCE_V1" in script:
            self.calls.append("devtools_performance")
            return {
                "entries": [
                    {"name": "domContentLoaded", "value": 12.5, "unit": "ms"}
                ],
                "truncated": False,
            }
        if "TERMUINATOR_OBSERVE_V1" in script:
            self.calls.append("observe_dom")
            return {
                "ready_state": "complete",
                "dom_version": 0,
                "elements": [],
            }
        raise AssertionError("unexpected recording pilot script")

    async def screenshot(
        self,
        path: str | None = None,
        full_page: bool = False,
    ) -> bytes:
        self.calls.append(("screenshot", path, full_page))
        return b"\x89PNG\r\n\x1a\nlegacy-image"


class _StructuredPilot(_RecordingPilot):
    def __init__(self) -> None:
        super().__init__()
        self.connected = True
        self.dom_version = 1
        self.value = ""
        self.checked = False
        self.selected = "a"
        self.hovered = False
        self.scroll_position = (0.0, 0.0)

    def _state(self) -> dict[str, object]:
        return {
            "connected": self.connected,
            "x": 20.0,
            "y": 30.0,
            "width": 120.0,
            "height": 40.0,
            "visible": True,
            "enabled": True,
            "value": self.value,
            "checked": self.checked,
            "selected": self.selected,
            "hovered": self.hovered,
            "scroll_x": self.scroll_position[0],
            "scroll_y": self.scroll_position[1],
            "dom_version": self.dom_version,
        }

    async def evaluate(self, script: str) -> object:
        if "TERMUINATOR_OBSERVE_V1" in script:
            self.calls.append("observe_dom")
            return {
                "ready_state": "complete",
                "dom_version": self.dom_version,
                "elements": [
                    {
                        "backend_node_id": "private-node-1",
                        "role": "textbox",
                        "accessible_name": "Account name",
                        "text": "",
                        "tag": "input",
                        "type": "text",
                        "x": 20.0,
                        "y": 30.0,
                        "width": 120.0,
                        "height": 40.0,
                        "visible": True,
                        "enabled": True,
                        "editable": True,
                        "checked": None,
                        "frame_path": [],
                        "shadow_path": [],
                    }
                ],
            }
        if "TERMUINATOR_ELEMENT_STATE_V1" in script:
            self.calls.append("element_state")
            if not self.connected:
                return None
            state = self._state()
            if '"private-node-2"' in script:
                state["x"] = 300.0
            return state
        if "TERMUINATOR_PAGE_STATE_V1" in script:
            self.calls.append("page_state")
            return {
                "scroll_x": self.scroll_position[0],
                "scroll_y": self.scroll_position[1],
                "dom_version": self.dom_version,
            }
        if "TERMUINATOR_SELECT_V1" in script:
            self.calls.append("select")
            self.selected = "b"
            self.dom_version += 1
            return {"dispatched": True}
        if "TERMUINATOR_CHECK_V1" in script:
            self.calls.append("check")
            self.checked = True
            self.dom_version += 1
            return {"dispatched": True}
        return await super().evaluate(script)

    async def click(
        self,
        selector: str | None = None,
        x: float | None = None,
        y: float | None = None,
        button: str = "left",
        count: int = 1,
        interval: float = 0.1,
    ) -> None:
        self.calls.append(("click", selector, x, y, button, count))
        self.dom_version += 1

    async def type(
        self,
        selector: str | None = None,
        text: str = "",
        x: float | None = None,
        y: float | None = None,
        mode: str = "auto",
    ) -> None:
        self.calls.append(("type", selector, text, x, y, mode))
        self.value = text
        self.dom_version += 1

    async def press(self, key: str, modifiers: int = 0) -> None:
        self.calls.append(("press", key, modifiers))
        self.dom_version += 1

    async def scroll(self, delta_y: float = 300, delta_x: float = 0) -> None:
        self.calls.append(("scroll", delta_x, delta_y))
        self.scroll_position = (
            self.scroll_position[0] + delta_x,
            self.scroll_position[1] + delta_y,
        )

    async def hover(
        self,
        selector: str | None = None,
        x: float | None = None,
        y: float | None = None,
    ) -> None:
        self.calls.append(("hover", selector, x, y))
        self.hovered = True

    async def drag(
        self,
        from_x: float,
        from_y: float,
        to_x: float,
        to_y: float,
    ) -> None:
        self.calls.append(("drag", from_x, from_y, to_x, to_y))
        self.dom_version += 1


class _TimeoutThenObservePilot(_StructuredPilot):
    def __init__(self) -> None:
        super().__init__()
        self.observe_attempts = 0

    async def evaluate(self, script: str) -> object:
        if "TERMUINATOR_OBSERVE_V1" in script:
            self.observe_attempts += 1
            if self.observe_attempts == 1:
                raise JavascriptExecutionTimeout(
                    "Firefox JavaScript execution timed out"
                )
        return await super().evaluate(script)


class _SensitiveStructuredPilot(_StructuredPilot):
    def __init__(self, *, field_type: str, accessible_name: str) -> None:
        super().__init__()
        self.field_type = field_type
        self.accessible_name = accessible_name
        self.value = "must-never-cross-the-adapter"

    async def text(self) -> str:
        self.calls.append("text")
        return "Sign in"

    async def evaluate(self, script: str) -> object:
        if "TERMUINATOR_OBSERVE_V1" in script:
            self.calls.append("observe_dom")
            return {
                "ready_state": "complete",
                "dom_version": self.dom_version,
                "elements": [
                    {
                        "backend_node_id": "private-sensitive-node",
                        "role": "textbox",
                        "accessible_name": self.accessible_name,
                        "text": "",
                        "tag": "input",
                        "type": self.field_type,
                        "x": 20.0,
                        "y": 30.0,
                        "width": 120.0,
                        "height": 40.0,
                        "visible": True,
                        "enabled": True,
                        "editable": True,
                        "checked": None,
                        "frame_path": [],
                        "shadow_path": [],
                    }
                ],
            }
        return await super().evaluate(script)


class _NoopSessionLock:
    def acquire(self) -> None:
        pass

    def release(self) -> None:
        pass


class LegacyBackendAdapterTests(unittest.TestCase):
    def test_backend_package_exports_legacy_pilot_adapter(self) -> None:
        module = importlib.import_module("src.termuinator.backends")
        self.assertIsNotNone(getattr(module, "LegacyPilotBackend", None))

    def test_adapter_requires_explicit_backend_and_accepts_injected_pilot(self) -> None:
        module = importlib.import_module("src.termuinator.backends")
        parameters = inspect.signature(module.LegacyPilotBackend).parameters
        self.assertIn("backend", parameters)
        self.assertIn("pilot_factory", parameters)
        self.assertIs(parameters["backend"].default, inspect.Parameter.empty)


class LegacyBackendLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_pilot_exposes_structured_accessibility_without_changing_summary(self) -> None:
        pilot_module = importlib.import_module("src.pilot")

        class Accessibility:
            def __init__(self) -> None:
                self.calls: list[str] = []

            async def get_tree(self) -> list[dict[str, object]]:
                self.calls.append("get_tree")
                return [{"role": {"value": "heading"}}]

            async def get_tree_summary(self) -> str:
                self.calls.append("get_tree_summary")
                return "[heading] Example Domain"

        accessibility = Accessibility()
        pilot = object.__new__(pilot_module.Pilot)
        pilot.accessibility = accessibility

        nodes = await pilot.a11y_nodes()
        summary = await pilot.a11y_tree()

        self.assertEqual(nodes, [{"role": {"value": "heading"}}])
        self.assertEqual(summary, "[heading] Example Domain")
        self.assertEqual(accessibility.calls, ["get_tree", "get_tree_summary"])

    async def test_start_and_stop_wrap_one_explicit_inherited_backend(self) -> None:
        pilot = _RecordingPilot()
        factory_calls: list[dict[str, object]] = []

        def factory(**kwargs: object) -> _RecordingPilot:
            factory_calls.append(kwargs)
            return pilot

        adapter = LegacyPilotBackend(Backend.CHROMIUM, pilot_factory=factory)
        self.assertTrue(callable(getattr(adapter, "start", None)))

        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir) / "profile"
            profile.mkdir(mode=0o700)
            capabilities = await adapter.start(
                profile, Viewport(width=1280, height=720)
            )

        self.assertEqual(
            factory_calls,
            [
                {
                    "browser": "chromium",
                    "user_data_dir": str(profile),
                    "window_size": "1280,720",
                    "display": "auto",
                    "cdp_port": 0,
                }
            ],
        )
        self.assertEqual(pilot.calls, ["start"])
        self.assertEqual(capabilities.backend, Backend.CHROMIUM)
        by_id = {item.capability_id: item for item in capabilities.capabilities}
        self.assertEqual(by_id["cached_status"].status, CapabilityStatus.SUPPORTED)
        self.assertEqual(by_id["navigate"].status, CapabilityStatus.PARTIAL)
        self.assertEqual(by_id["observe"].status, CapabilityStatus.PARTIAL)
        self.assertEqual(by_id["screenshot"].status, CapabilityStatus.PARTIAL)
        self.assertEqual(by_id["act"].status, CapabilityStatus.PARTIAL)
        self.assertEqual(by_id["navigate"].limits[0].value, "goto")
        self.assertTrue(adapter.cached_status().running)
        self.assertEqual(adapter.cached_status().backend, Backend.CHROMIUM)

        await adapter.stop()

        self.assertEqual(pilot.calls, ["start", "stop"])
        self.assertFalse(adapter.cached_status().running)
        self.assertEqual(adapter.cached_status().ready_state, "closed")

    async def test_typed_goto_and_text_observation_wrap_public_pilot_methods(self) -> None:
        pilot = _RecordingPilot()
        adapter = LegacyPilotBackend(Backend.FIREFOX, pilot_factory=lambda **_: pilot)
        self.assertIsInstance(adapter, BrowserBackend)
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir) / "profile"
            profile.mkdir(mode=0o700)
            capabilities = await adapter.start(
                profile, Viewport(width=1000, height=700)
            )

        navigated = await adapter.navigate(
            "goto", "https://example.com", 45_000
        )
        observed = await adapter.observe(
            include_screenshot=False,
            include_accessibility=True,
            text_limit=5,
        )

        self.assertIsInstance(navigated, BackendPageSnapshot)
        self.assertEqual(navigated.url, "https://example.com")
        self.assertEqual(pilot.calls[1], ("goto", "https://example.com", 45.0))
        self.assertEqual(observed.text, "abcde")
        self.assertTrue(observed.text_truncated)
        self.assertEqual(
            observed.accessibility,
            (
                {
                    "ref": None,
                    "role": "heading",
                    "name": "Example Domain",
                    "text": "",
                    "depth": 0,
                },
            ),
        )
        self.assertIn("a11y_nodes", pilot.calls)
        self.assertNotIn("a11y_tree", pilot.calls)
        self.assertEqual(adapter.cached_status().url, "https://example.com")
        by_id = {item.capability_id: item for item in capabilities.capabilities}
        self.assertEqual(by_id["navigate"].status, CapabilityStatus.PARTIAL)
        self.assertEqual(by_id["observe"].status, CapabilityStatus.PARTIAL)

    async def test_observe_bounds_accessibility_node_count(self) -> None:
        class UnboundedPilot(_RecordingPilot):
            async def a11y_nodes(self) -> list[dict[str, object]]:
                return [
                    {
                        "role": {"value": "button"},
                        "name": {"value": f"Button {index}"},
                    }
                    for index in range(201)
                ]

        pilot = UnboundedPilot()
        adapter = LegacyPilotBackend(
            Backend.CHROMIUM,
            pilot_factory=lambda **_: pilot,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir) / "profile"
            profile.mkdir(mode=0o700)
            await adapter.start(profile, Viewport(width=1000, height=700))

        observed = await adapter.observe(
            include_screenshot=False,
            include_accessibility=True,
            text_limit=0,
        )

        self.assertEqual(len(observed.accessibility), 200)
        self.assertEqual(
            observed.accessibility[-1],
            {
                "ref": None,
                "role": "button",
                "name": "Button 199",
                "text": "",
                "depth": 0,
            },
        )

    async def test_observe_rejects_invalid_accessibility_without_echoing_page_data(self) -> None:
        secret = "do-not-echo-accessibility-page-data"
        invalid_payloads: tuple[list[dict[str, object]], ...] = (
            [
                {
                    "role": {"value": {"secret": secret}},
                    "name": {"value": "Example Domain"},
                }
            ],
            [
                {
                    "role": {"value": "heading"},
                    "name": {"value": secret + ("x" * 513)},
                }
            ],
        )

        for payload in invalid_payloads:
            with self.subTest(payload_kind=type(payload[0]["role"]["value"]).__name__):
                class InvalidPilot(_RecordingPilot):
                    async def a11y_nodes(self) -> list[dict[str, object]]:
                        return payload

                pilot = InvalidPilot()
                adapter = LegacyPilotBackend(
                    Backend.CHROMIUM,
                    pilot_factory=lambda **_: pilot,
                )
                with tempfile.TemporaryDirectory() as temp_dir:
                    profile = Path(temp_dir) / "profile"
                    profile.mkdir(mode=0o700)
                    await adapter.start(profile, Viewport(width=1000, height=700))

                with self.assertRaises(TermuinatorError) as caught:
                    await adapter.observe(
                        include_screenshot=False,
                        include_accessibility=True,
                        text_limit=0,
                    )

                self.assertEqual(caught.exception.code, ErrorCode.BACKEND_CRASHED)
                self.assertNotIn(secret, str(caught.exception))
                self.assertNotIn(
                    secret,
                    json.dumps(dict(caught.exception.details), sort_keys=True),
                )

    async def test_viewport_full_and_observation_screenshots_return_raw_png(self) -> None:
        pilot = _RecordingPilot()
        adapter = LegacyPilotBackend(
            Backend.CHROMIUM,
            pilot_factory=lambda **_: pilot,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir) / "profile"
            profile.mkdir(mode=0o700)
            capabilities = await adapter.start(
                profile,
                Viewport(width=1000, height=700),
            )

        viewport = await adapter.screenshot("viewport")
        full = await adapter.screenshot("full")
        observed = await adapter.observe(
            include_screenshot=True,
            include_accessibility=False,
            text_limit=0,
        )

        self.assertIsInstance(viewport, BackendArtifactPayload)
        self.assertEqual(viewport.mime_type, "image/png")
        self.assertEqual(full.data, viewport.data)
        self.assertEqual(observed.screenshot, viewport)
        self.assertEqual(
            pilot.calls[1:],
            [
                ("screenshot", None, False),
                ("screenshot", None, True),
                "observe_dom",
                ("screenshot", None, False),
            ],
        )
        screenshot_capability = next(
            item
            for item in capabilities.capabilities
            if item.capability_id == "screenshot"
        )
        self.assertEqual(
            screenshot_capability.status,
            CapabilityStatus.PARTIAL,
        )
        self.assertEqual(
            screenshot_capability.limits[0].value,
            "viewport,full",
        )

    async def test_element_or_malformed_screenshot_fails_closed(self) -> None:
        pilot = _RecordingPilot()
        adapter = LegacyPilotBackend(
            Backend.FIREFOX,
            pilot_factory=lambda **_: pilot,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir) / "profile"
            profile.mkdir(mode=0o700)
            capabilities = await adapter.start(
                profile,
                Viewport(width=1000, height=700),
            )

        screenshot_capability = next(
            item
            for item in capabilities.capabilities
            if item.capability_id == "screenshot"
        )
        self.assertEqual(screenshot_capability.limits[0].value, "viewport")

        with self.assertRaises(TermuinatorError) as element:
            await adapter.screenshot("element", "private-node")
        self.assertEqual(
            element.exception.code,
            ErrorCode.UNSUPPORTED_CAPABILITY,
        )
        self.assertEqual(pilot.calls, ["start"])

        with self.assertRaises(TermuinatorError) as full:
            await adapter.screenshot("full")
        self.assertEqual(full.exception.code, ErrorCode.UNSUPPORTED_CAPABILITY)
        self.assertEqual(pilot.calls, ["start"])

        async def malformed(
            path: str | None = None,
            full_page: bool = False,
        ) -> bytes:
            return b"not-a-png"

        pilot.screenshot = malformed
        with self.assertRaises(TermuinatorError) as invalid:
            await adapter.screenshot("viewport")
        self.assertEqual(invalid.exception.code, ErrorCode.BACKEND_CRASHED)

    async def test_unmigrated_navigation_fails_as_structured_unsupported(self) -> None:
        adapter = LegacyPilotBackend(
            Backend.FIREFOX, pilot_factory=lambda **_: _RecordingPilot()
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir) / "profile"
            profile.mkdir(mode=0o700)
            await adapter.start(profile, Viewport(width=1000, height=700))

        with self.assertRaises(TermuinatorError) as caught:
            await adapter.navigate("reload", None, 30_000)

        self.assertEqual(caught.exception.code, ErrorCode.UNSUPPORTED_CAPABILITY)
        self.assertEqual(caught.exception.details["backend"], "firefox")
        self.assertEqual(caught.exception.details["capability"], "navigate")

    async def test_observe_normalizes_stable_private_dom_handles(self) -> None:
        pilot = _StructuredPilot()
        adapter = LegacyPilotBackend(
            Backend.CHROMIUM,
            pilot_factory=lambda **_: pilot,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir) / "profile"
            profile.mkdir(mode=0o700)
            capabilities = await adapter.start(
                profile,
                Viewport(width=1000, height=700),
            )

        first = await adapter.observe(
            include_screenshot=False,
            include_accessibility=False,
            text_limit=0,
        )
        second = await adapter.observe(
            include_screenshot=False,
            include_accessibility=False,
            text_limit=0,
        )

        self.assertEqual(len(first.interactive_elements), 1)
        self.assertEqual(
            first.interactive_elements[0].backend_node_id,
            "private-node-1",
        )
        self.assertEqual(
            second.interactive_elements[0].backend_node_id,
            first.interactive_elements[0].backend_node_id,
        )
        self.assertTrue(first.interactive_elements[0].editable)
        self.assertEqual(first.interactive_elements[0].bounds.width, 120.0)
        by_id = {item.capability_id: item for item in capabilities.capabilities}
        self.assertTrue(
            next(
                limit.value
                for limit in by_id["observe"].limits
                if limit.name == "stable_refs"
            )
        )
        self.assertEqual(by_id["act"].status, CapabilityStatus.PARTIAL)

    async def test_observe_retries_one_recoverable_firefox_timeout(self) -> None:
        pilot = _TimeoutThenObservePilot()
        adapter = LegacyPilotBackend(
            Backend.FIREFOX,
            pilot_factory=lambda **_: pilot,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir) / "profile"
            profile.mkdir(mode=0o700)
            await adapter.start(profile, Viewport(width=1000, height=700))

        try:
            observation = await adapter.observe(
                include_screenshot=False,
                include_accessibility=False,
                text_limit=0,
            )
        except TermuinatorError as exc:
            self.fail(f"recoverable Firefox timeout was not retried: {exc.code}")

        self.assertEqual(pilot.observe_attempts, 2)
        self.assertEqual(len(observation.interactive_elements), 1)

    async def test_click_and_type_resolve_private_handle_and_return_evidence(self) -> None:
        pilot = _StructuredPilot()
        adapter = LegacyPilotBackend(
            Backend.FIREFOX,
            pilot_factory=lambda **_: pilot,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir) / "profile"
            profile.mkdir(mode=0o700)
            await adapter.start(profile, Viewport(width=1000, height=700))
        observed = await adapter.observe(
            include_screenshot=False,
            include_accessibility=False,
            text_limit=0,
        )
        private_handle = observed.interactive_elements[0].backend_node_id

        clicked = await adapter.act(
            BackendAction(
                kind=ActionKind.CLICK,
                backend_node_id=private_handle,
                destination_backend_node_id=None,
                parameters={"button": "left", "click_count": 1},
                timeout_ms=5_000,
            )
        )
        typed = await adapter.act(
            BackendAction(
                kind=ActionKind.TYPE,
                backend_node_id=private_handle,
                destination_backend_node_id=None,
                parameters={"text": "hello", "clear": True},
                timeout_ms=5_000,
            )
        )

        self.assertTrue(clicked.evidence.target_event_dispatched)
        self.assertTrue(clicked.evidence.dom_changed)
        self.assertEqual(typed.evidence.after_value, "hello")
        self.assertTrue(typed.evidence.target_event_dispatched)
        self.assertIn(("click", None, 80.0, 50.0, "left", 1), pilot.calls)
        self.assertIn(("type", None, "hello", 80.0, 50.0, "auto"), pilot.calls)

    async def test_disconnected_private_handle_fails_before_input_dispatch(self) -> None:
        pilot = _StructuredPilot()
        adapter = LegacyPilotBackend(
            Backend.CHROMIUM,
            pilot_factory=lambda **_: pilot,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir) / "profile"
            profile.mkdir(mode=0o700)
            await adapter.start(profile, Viewport(width=1000, height=700))
        pilot.connected = False

        with self.assertRaises(TermuinatorError) as stale:
            await adapter.act(
                BackendAction(
                    kind=ActionKind.CLICK,
                    backend_node_id="private-node-1",
                    destination_backend_node_id=None,
                    parameters={},
                    timeout_ms=5_000,
                )
            )

        self.assertEqual(stale.exception.code, ErrorCode.TARGET_NOT_FOUND)
        self.assertFalse(any(isinstance(call, tuple) and call[0] == "click" for call in pilot.calls))

    async def test_malformed_dom_probe_fails_closed_without_echoing_page_data(self) -> None:
        class MalformedPilot(_RecordingPilot):
            async def evaluate(self, script: str) -> object:
                return {
                    "ready_state": "complete",
                    "dom_version": 1,
                    "elements": [
                        {
                            "backend_node_id": "node_valid_1234",
                            "role": {"password": "do-not-echo-this-secret"},
                        }
                    ],
                }

        pilot = MalformedPilot()
        adapter = LegacyPilotBackend(
            Backend.CHROMIUM,
            pilot_factory=lambda **_: pilot,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir) / "profile"
            profile.mkdir(mode=0o700)
            await adapter.start(profile, Viewport(width=1000, height=700))

        with self.assertRaises(TermuinatorError) as malformed:
            await adapter.observe(
                include_screenshot=False,
                include_accessibility=False,
                text_limit=0,
            )

        self.assertEqual(malformed.exception.code, ErrorCode.BACKEND_CRASHED)
        self.assertNotIn("do-not-echo-this-secret", str(malformed.exception))
        self.assertNotIn(
            "do-not-echo-this-secret",
            json.dumps(dict(malformed.exception.details), sort_keys=True),
        )

        async def unbounded(script: str) -> object:
            return {
                "ready_state": "complete",
                "dom_version": 1,
                "elements": [
                    {
                        "backend_node_id": "node_valid_1234",
                        "role": "button",
                        "accessible_name": "x" * 513,
                        "text": "",
                        "tag": "button",
                        "type": "button",
                        "x": 1,
                        "y": 1,
                        "width": 10,
                        "height": 10,
                        "visible": True,
                        "enabled": True,
                        "editable": False,
                        "checked": None,
                        "frame_path": [],
                        "shadow_path": [],
                    }
                ],
            }

        pilot.evaluate = unbounded
        with self.assertRaises(TermuinatorError) as oversized:
            await adapter.observe(
                include_screenshot=False,
                include_accessibility=False,
                text_limit=0,
            )
        self.assertEqual(oversized.exception.code, ErrorCode.BACKEND_CRASHED)

    async def test_service_wire_never_exposes_private_dom_handles_or_registry_key(self) -> None:
        pilot = _StructuredPilot()
        adapter = LegacyPilotBackend(
            Backend.CHROMIUM,
            pilot_factory=lambda **_: pilot,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            service = BrowserService(
                data_root=Path(temp_dir) / "runtime",
                owner_scope="legacy-wire-test",
                default_backend=Backend.CHROMIUM,
                profile_schema_version="v1",
                backend_factories={Backend.CHROMIUM: lambda: adapter},
                session_lock=_NoopSessionLock(),
            )
            started = await service.session_start(
                project_id="legacy-wire-project",
                viewport=Viewport(width=1000, height=700),
            )
            status = started.status
            self.assertIsNotNone(status.active_tab_id)
            self.assertIsNotNone(status.active_page_id)
            self.assertIsNotNone(status.page_revision)
            observation = await service.observe(
                session_id=started.session_id,
                tab_id=status.active_tab_id or "",
                page_id=status.active_page_id or "",
                expected_revision=status.page_revision,
                include_screenshot=False,
                include_accessibility=False,
                text_limit=0,
            )
            await service.session_stop(started.session_id)

        wire = json.dumps(to_wire(observation), sort_keys=True)
        self.assertNotIn("private-node-1", wire)
        self.assertNotIn(adapter._dom_registry_key, wire)
        self.assertRegex(
            observation.interactive_elements[0].ref,
            r"^ref_[A-Za-z0-9_-]{16,}$",
        )

    async def test_sensitive_legacy_fields_require_takeover_without_secret_or_handle_leakage(
        self,
    ) -> None:
        cases = (
            ("password", "Account secret"),
            ("text", "One-time code"),
        )
        for field_type, accessible_name in cases:
            with self.subTest(field_type=field_type, accessible_name=accessible_name):
                pilot = _SensitiveStructuredPilot(
                    field_type=field_type,
                    accessible_name=accessible_name,
                )
                adapter = LegacyPilotBackend(
                    Backend.CHROMIUM,
                    pilot_factory=lambda **_: pilot,
                )
                with tempfile.TemporaryDirectory() as temp_dir:
                    service = BrowserService(
                        data_root=Path(temp_dir) / "runtime",
                        owner_scope=f"legacy-sensitive-{field_type}",
                        default_backend=Backend.CHROMIUM,
                        profile_schema_version="v1",
                        backend_factories={Backend.CHROMIUM: lambda: adapter},
                        session_lock=_NoopSessionLock(),
                    )
                    started = await service.session_start(
                        project_id="legacy-sensitive-project",
                        viewport=Viewport(width=1000, height=700),
                    )
                    status = started.status
                    observation = await service.observe(
                        session_id=started.session_id,
                        tab_id=status.active_tab_id or "",
                        page_id=status.active_page_id or "",
                        expected_revision=status.page_revision,
                        include_screenshot=False,
                        include_accessibility=False,
                        text_limit=100,
                    )
                    paused = await service.session_status(started.session_id)
                    await service.session_stop(started.session_id)

                self.assertEqual(paused.state, SessionState.USER_TAKEOVER_REQUIRED)
                self.assertEqual(len(observation.challenges), 1)
                self.assertEqual(
                    observation.challenges[0].kind,
                    ChallengeKind.USER_TAKEOVER,
                )
                self.assertEqual(
                    observation.challenges[0].state,
                    ChallengeState.PENDING,
                )
                wire = json.dumps(to_wire(observation), sort_keys=True)
                self.assertNotIn("must-never-cross-the-adapter", wire)
                self.assertNotIn("private-sensitive-node", wire)
                self.assertNotIn(adapter._dom_registry_key, wire)

    async def test_closed_developer_queries_normalize_typed_results(self) -> None:
        pilot = _StructuredPilot()
        adapter = LegacyPilotBackend(
            Backend.CHROMIUM,
            pilot_factory=lambda **_: pilot,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir) / "profile"
            profile.mkdir(mode=0o700)
            capabilities = await adapter.start(
                profile,
                Viewport(width=1000, height=700),
            )
        await adapter.observe(
            include_screenshot=False,
            include_accessibility=False,
            text_limit=0,
        )

        cases = (
            BackendDevtoolsQuery("console", {"level": "error", "limit": 10}),
            BackendDevtoolsQuery("network", {"url_filter": "/api", "limit": 10}),
            BackendDevtoolsQuery(
                "dom",
                {"max_depth": 2},
                backend_node_id="private-node-1",
            ),
            BackendDevtoolsQuery(
                "style",
                {"properties": ["color"]},
                backend_node_id="private-node-1",
            ),
            BackendDevtoolsQuery("performance", {"scope": "summary"}),
        )
        results = [await adapter.devtools(query) for query in cases]

        self.assertIsInstance(results[0].entries[0], BackendConsoleEntry)
        self.assertIsInstance(results[1].entries[0], BackendNetworkEntry)
        self.assertIsInstance(results[2].entries[0], BackendDomEntry)
        self.assertIsInstance(results[3].entries[0], BackendStyleEntry)
        self.assertIsInstance(results[4].entries[0], BackendPerformanceEntry)
        devtools = next(
            item
            for item in capabilities.capabilities
            if item.capability_id == "devtools"
        )
        self.assertEqual(devtools.status, CapabilityStatus.PARTIAL)
        self.assertEqual(
            next(limit.value for limit in devtools.limits if limit.name == "queries"),
            "console,network,dom,style,performance",
        )

    async def test_remaining_supported_actions_return_kind_specific_evidence(self) -> None:
        pilot = _StructuredPilot()
        adapter = LegacyPilotBackend(
            Backend.FIREFOX,
            pilot_factory=lambda **_: pilot,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir) / "profile"
            profile.mkdir(mode=0o700)
            capabilities = await adapter.start(
                profile,
                Viewport(width=1000, height=700),
            )
        private_handle = "private-node-1"

        keyed = await adapter.act(
            BackendAction(
                kind=ActionKind.KEY,
                backend_node_id=None,
                destination_backend_node_id=None,
                parameters={"key": "Enter", "modifiers": ["Control", "Shift"]},
                timeout_ms=5_000,
            )
        )
        scrolled = await adapter.act(
            BackendAction(
                kind=ActionKind.SCROLL,
                backend_node_id=None,
                destination_backend_node_id=None,
                parameters={"delta_x": 10, "delta_y": 25},
                timeout_ms=5_000,
            )
        )
        selected = await adapter.act(
            BackendAction(
                kind=ActionKind.SELECT,
                backend_node_id=private_handle,
                destination_backend_node_id=None,
                parameters={"value": "b"},
                timeout_ms=5_000,
            )
        )
        checked = await adapter.act(
            BackendAction(
                kind=ActionKind.CHECK,
                backend_node_id=private_handle,
                destination_backend_node_id=None,
                parameters={"checked": True},
                timeout_ms=5_000,
            )
        )
        hovered = await adapter.act(
            BackendAction(
                kind=ActionKind.HOVER,
                backend_node_id=private_handle,
                destination_backend_node_id=None,
                parameters={},
                timeout_ms=5_000,
            )
        )

        self.assertTrue(keyed.evidence.dom_changed)
        self.assertEqual(scrolled.evidence.after_scroll, (10.0, 25.0))
        self.assertEqual(selected.evidence.after_selected, "b")
        self.assertIs(checked.evidence.after_checked, True)
        self.assertIs(hovered.evidence.after_hovered, True)
        self.assertIn(("press", "Enter", 10), pilot.calls)
        self.assertIn(("scroll", 10, 25), pilot.calls)
        self.assertIn(("hover", None, 80.0, 50.0), pilot.calls)
        act = next(
            item for item in capabilities.capabilities if item.capability_id == "act"
        )
        self.assertEqual(
            next(limit.value for limit in act.limits if limit.name == "operations"),
            "click,type,key,scroll,select,check,hover,drag",
        )

        dragged = await adapter.act(
            BackendAction(
                kind=ActionKind.DRAG,
                backend_node_id=private_handle,
                destination_backend_node_id="private-node-2",
                parameters={},
                timeout_ms=5_000,
            )
        )
        self.assertTrue(dragged.evidence.target_event_dispatched)
        self.assertTrue(dragged.evidence.dom_changed)
        self.assertIn(("drag", 80.0, 50.0, 360.0, 50.0), pilot.calls)


if __name__ == "__main__":
    unittest.main()
