"""Typed migration adapter for the inherited browser pilot lifecycle."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import math
from pathlib import Path
import secrets
import time
from typing import Any, Callable, Mapping, NoReturn

from ...commands import JavascriptExecutionTimeout
from ..contracts import (
    ActionKind,
    Backend,
    CapabilityLimit,
    CapabilityRecord,
    CapabilitySet,
    CapabilityStatus,
    ErrorCode,
    Viewport,
)
from ..errors import TermuinatorError
from .base import (
    BackendAction,
    BackendActionEvidence,
    BackendActionOutcome,
    BackendArtifactPayload,
    BackendDevtoolsQuery,
    BackendDevtoolsResult,
    BackendDownloadsResult,
    BackendPageSnapshot,
    BackendStatus,
    BackendTabsResult,
    RawInteractiveElement,
)
from .legacy_dom import (
    check_script,
    element_state_script,
    normalize_element_state,
    normalize_mutation_result,
    normalize_observation,
    normalize_page_state,
    observe_script,
    page_state_script,
    select_script,
)
from .legacy_devtools import devtools_script, normalize_devtools_result


def _create_legacy_pilot(**kwargs: object) -> object:
    from ...pilot import Pilot

    return Pilot(**kwargs)


class LegacyPilotBackend:
    """Wrap the inherited Pilot without exposing its untyped surface."""

    def __init__(
        self,
        backend: Backend,
        *,
        pilot_factory: Callable[..., object] | None = None,
    ) -> None:
        if backend not in (Backend.CHROMIUM, Backend.FIREFOX):
            raise ValueError("legacy adapter backend must be chromium or firefox")
        self.backend = backend
        self._pilot_factory = pilot_factory or _create_legacy_pilot
        self._pilot: object | None = None
        self._viewport: Viewport | None = None
        self._dom_registry_key = "__" + secrets.token_urlsafe(24)
        self._status = BackendStatus(
            backend=backend,
            running=False,
            url="",
            title="",
            ready_state="closed",
            updated_at_monotonic=time.monotonic(),
        )

    async def start(
        self, profile_dir: Path, viewport: Viewport | None
    ) -> CapabilitySet:
        window_size = (
            f"{viewport.width},{viewport.height}" if viewport is not None else "auto"
        )
        pilot = self._pilot_factory(
            browser=self.backend.value,
            user_data_dir=str(profile_dir),
            window_size=window_size,
            display="auto",
            cdp_port=0,
        )
        self._pilot = pilot
        self._viewport = viewport
        try:
            await pilot.start()  # type: ignore[attr-defined]
        except Exception:
            try:
                await pilot.stop()  # type: ignore[attr-defined]
            finally:
                self._pilot = None
            raise

        self._status = BackendStatus(
            backend=self.backend,
            running=True,
            url="about:blank",
            title="",
            ready_state="complete",
            updated_at_monotonic=time.monotonic(),
        )
        probed_at = datetime.now(timezone.utc).isoformat()
        capability_ids = (
            "session.lifecycle",
            "cached_status",
            "navigate",
            "observe",
            "act",
            "wait",
            "tabs",
            "screenshot",
            "downloads",
            "devtools",
        )
        return CapabilitySet(
            backend=self.backend,
            revision=f"legacy-pilot-{self.backend.value}-v1",
            browser_version="unprobed",
            transport_version="legacy-pilot-v0",
            capabilities=tuple(
                CapabilityRecord(
                    capability_id=capability_id,
                    status=(
                        CapabilityStatus.SUPPORTED
                        if capability_id in {"session.lifecycle", "cached_status"}
                        else CapabilityStatus.PARTIAL
                        if capability_id in {
                            "navigate",
                            "observe",
                            "act",
                            "screenshot",
                            "devtools",
                        }
                        else CapabilityStatus.UNSUPPORTED
                    ),
                    reason_code=(
                        None
                        if capability_id in {"session.lifecycle", "cached_status"}
                        else "goto_only"
                        if capability_id == "navigate"
                        else "main_world_dom_registry"
                        if capability_id == "observe"
                        else "subset_only"
                        if capability_id == "act"
                        else "closed_page_probes"
                        if capability_id == "devtools"
                        else (
                            "element_unsupported"
                            if self.backend is Backend.CHROMIUM
                            else "viewport_only"
                        )
                        if capability_id == "screenshot"
                        else "adapter_not_migrated"
                    ),
                    limits=(
                        (CapabilityLimit("operations", "goto"),)
                        if capability_id == "navigate"
                        else (
                            CapabilityLimit("stable_refs", True),
                            CapabilityLimit("max_elements", 512),
                            CapabilityLimit("cross_origin_frames", False),
                            CapabilityLimit("screenshot", True),
                        )
                        if capability_id == "observe"
                        else (
                            CapabilityLimit(
                                "operations",
                                "click,type,key,scroll,select,check,hover,drag",
                            ),
                            CapabilityLimit("coordinate_source", "observed_ref"),
                        )
                        if capability_id == "act"
                        else (
                            CapabilityLimit(
                                "queries",
                                "console,network,dom,style,performance",
                            ),
                            CapabilityLimit("raw_eval", False),
                            CapabilityLimit("network_bodies", False),
                            CapabilityLimit("console_scope", "since_first_query"),
                        )
                        if capability_id == "devtools"
                        else (
                            CapabilityLimit(
                                "operations",
                                (
                                    "viewport,full"
                                    if self.backend is Backend.CHROMIUM
                                    else "viewport"
                                ),
                            ),
                        )
                        if capability_id == "screenshot"
                        else ()
                    ),
                    last_probed_at=probed_at,
                )
                for capability_id in capability_ids
            ),
        )

    async def stop(self) -> None:
        pilot = self._pilot
        self._pilot = None
        try:
            if pilot is not None:
                await pilot.stop()  # type: ignore[attr-defined]
        finally:
            self._status = BackendStatus(
                backend=self.backend,
                running=False,
                url=self._status.url,
                title=self._status.title,
                ready_state="closed",
                updated_at_monotonic=time.monotonic(),
            )

    def cached_status(self) -> BackendStatus:
        return self._status

    def _unsupported(self, capability: str, **details: object) -> NoReturn:
        raise TermuinatorError(
            ErrorCode.UNSUPPORTED_CAPABILITY,
            f"The {capability} adapter has not been migrated for {self.backend.value}",
            details={
                "backend": self.backend.value,
                "capability": capability,
                **details,
            },
        )

    async def navigate(
        self, operation: str, url: str | None, timeout_ms: int
    ) -> BackendPageSnapshot:
        if operation != "goto":
            self._unsupported("navigate", operation=operation)
        if not isinstance(url, str) or not url or len(url) > 8_192:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "goto requires a bounded URL",
            )
        if (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or not 1 <= timeout_ms <= 120_000
        ):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "navigation timeout_ms must be between 1 and 120000",
            )
        pilot = self._require_pilot()
        await pilot.goto(url, timeout=timeout_ms / 1000)  # type: ignore[attr-defined]
        current_url = await pilot.url()  # type: ignore[attr-defined]
        title = await pilot.title()  # type: ignore[attr-defined]
        if not isinstance(current_url, str) or not isinstance(title, str):
            raise TermuinatorError(
                ErrorCode.BACKEND_CRASHED,
                "Inherited browser returned invalid navigation metadata",
            )
        self._status = BackendStatus(
            backend=self.backend,
            running=True,
            url=current_url,
            title=title,
            ready_state="complete",
            updated_at_monotonic=time.monotonic(),
        )
        return self._snapshot()

    async def observe(
        self,
        *,
        include_screenshot: bool,
        include_accessibility: bool,
        text_limit: int,
    ) -> BackendPageSnapshot:
        if (
            isinstance(text_limit, bool)
            or not isinstance(text_limit, int)
            or not 0 <= text_limit <= 100_000
        ):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "text_limit must be between 0 and 100000",
            )
        pilot = self._require_pilot()
        ready_state, _, interactive_elements = await self._collect_dom(pilot)
        self._status = BackendStatus(
            backend=self.backend,
            running=True,
            url=self._status.url,
            title=self._status.title,
            ready_state=ready_state,
            updated_at_monotonic=time.monotonic(),
        )
        text = ""
        text_truncated = False
        if text_limit:
            raw_text = await pilot.text()  # type: ignore[attr-defined]
            if not isinstance(raw_text, str):
                raise TermuinatorError(
                    ErrorCode.BACKEND_CRASHED,
                    "Inherited browser returned invalid page text",
                )
            text_truncated = len(raw_text) > text_limit
            text = raw_text[:text_limit]

        accessibility: tuple[Mapping[str, Any], ...] = ()
        if include_accessibility:
            raw_accessibility = await pilot.a11y_tree()  # type: ignore[attr-defined]
            if isinstance(raw_accessibility, Mapping):
                accessibility = (raw_accessibility,)
            elif isinstance(raw_accessibility, (list, tuple)) and all(
                isinstance(item, Mapping) for item in raw_accessibility
            ):
                accessibility = tuple(raw_accessibility)
            else:
                raise TermuinatorError(
                    ErrorCode.BACKEND_CRASHED,
                    "Inherited browser returned invalid accessibility data",
                )
        screenshot = (
            await self.screenshot("viewport")
            if include_screenshot
            else None
        )
        return self._snapshot(
            text=text,
            text_truncated=text_truncated,
            accessibility=accessibility,
            interactive_elements=interactive_elements,
            screenshot=screenshot,
        )

    def _snapshot(
        self,
        *,
        text: str = "",
        text_truncated: bool = False,
        accessibility: tuple[Mapping[str, Any], ...] = (),
        interactive_elements: tuple[RawInteractiveElement, ...] = (),
        screenshot: BackendArtifactPayload | None = None,
    ) -> BackendPageSnapshot:
        return BackendPageSnapshot(
            url=self._status.url,
            title=self._status.title,
            ready_state=self._status.ready_state,
            viewport=self._viewport,
            text=text,
            text_truncated=text_truncated,
            accessibility=accessibility,
            interactive_elements=interactive_elements,
            screenshot=screenshot,
        )

    async def _collect_dom(
        self, pilot: object
    ) -> tuple[str, int, tuple[RawInteractiveElement, ...]]:
        script = observe_script(self._dom_registry_key)
        for attempt in range(2):
            try:
                payload = await pilot.evaluate(script)  # type: ignore[attr-defined]
                return normalize_observation(payload)
            except JavascriptExecutionTimeout as exc:
                if self.backend is Backend.FIREFOX and attempt == 0:
                    continue
                raise TermuinatorError(
                    ErrorCode.BACKEND_CRASHED,
                    "Inherited browser DOM observation failed",
                    retryable=True,
                    details={
                        "backend": self.backend.value,
                        "capability": "observe",
                    },
                ) from exc
            except TermuinatorError:
                raise
            except Exception as exc:
                raise TermuinatorError(
                    ErrorCode.BACKEND_CRASHED,
                    "Inherited browser DOM observation failed",
                    retryable=True,
                    details={
                        "backend": self.backend.value,
                        "capability": "observe",
                    },
                ) from exc
        raise AssertionError("unreachable DOM observation retry state")

    async def _element_state(
        self, pilot: object, backend_node_id: str
    ) -> Mapping[str, Any] | None:
        try:
            payload = await pilot.evaluate(  # type: ignore[attr-defined]
                element_state_script(self._dom_registry_key, backend_node_id)
            )
            return normalize_element_state(payload)
        except TermuinatorError:
            raise
        except Exception as exc:
            raise TermuinatorError(
                ErrorCode.BACKEND_CRASHED,
                "Inherited browser element-state probe failed",
                retryable=True,
                details={"backend": self.backend.value, "capability": "act"},
            ) from exc

    def _require_pilot(self) -> object:
        if self._pilot is None or not self._status.running:
            raise TermuinatorError(
                ErrorCode.BACKEND_CRASHED,
                "Inherited browser is not running",
            )
        return self._pilot

    async def act(self, action: BackendAction) -> BackendActionOutcome:
        if not isinstance(action, BackendAction):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Backend action must use the typed action contract",
            )
        supported = {
            ActionKind.CLICK,
            ActionKind.TYPE,
            ActionKind.KEY,
            ActionKind.SCROLL,
            ActionKind.SELECT,
            ActionKind.CHECK,
            ActionKind.HOVER,
            ActionKind.DRAG,
        }
        if action.kind not in supported:
            self._unsupported("act", operation=action.kind.value)
        parameters = self._validate_action_parameters(action)

        pilot = self._require_pilot()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + action.timeout_ms / 1000
        before_url = self._status.url
        target_kinds = {
            ActionKind.CLICK,
            ActionKind.TYPE,
            ActionKind.SELECT,
            ActionKind.CHECK,
            ActionKind.HOVER,
            ActionKind.DRAG,
        }
        before: Mapping[str, Any] | None = None
        before_destination: Mapping[str, Any] | None = None
        x: float | None = None
        y: float | None = None
        if action.kind in target_kinds:
            before = await self._run_action_call(
                "target revalidation",
                deadline,
                lambda: self._element_state(pilot, action.backend_node_id or ""),
            )
            self._require_actionable_target(before)
            x = before["x"] + before["width"] / 2
            y = before["y"] + before["height"] / 2
            if action.kind is ActionKind.DRAG:
                before_destination = await self._run_action_call(
                    "drag destination revalidation",
                    deadline,
                    lambda: self._element_state(
                        pilot,
                        action.destination_backend_node_id or "",
                    ),
                )
                self._require_actionable_target(before_destination)
        before_page = await self._run_action_call(
            "page-state revalidation",
            deadline,
            lambda: self._page_state(pilot),
        )

        if action.kind is ActionKind.CLICK:
            await self._run_action_call(
                "click dispatch",
                deadline,
                lambda: pilot.click(  # type: ignore[attr-defined]
                    selector=None,
                    x=x,
                    y=y,
                    button=parameters["button"],
                    count=parameters["click_count"],
                ),
            )
        elif action.kind is ActionKind.TYPE:
            await self._run_action_call(
                "type dispatch",
                deadline,
                lambda: pilot.type(  # type: ignore[attr-defined]
                    selector=None,
                    text=parameters["text"],
                    x=x,
                    y=y,
                    mode="auto",
                ),
            )
        elif action.kind is ActionKind.KEY:
            await self._run_action_call(
                "key dispatch",
                deadline,
                lambda: pilot.press(  # type: ignore[attr-defined]
                    parameters["key"],
                    modifiers=parameters["modifier_mask"],
                ),
            )
        elif action.kind is ActionKind.SCROLL:
            await self._run_action_call(
                "scroll dispatch",
                deadline,
                lambda: pilot.scroll(  # type: ignore[attr-defined]
                    delta_y=parameters["delta_y"],
                    delta_x=parameters["delta_x"],
                ),
            )
        elif action.kind is ActionKind.SELECT:
            await self._run_action_call(
                "select dispatch",
                deadline,
                lambda: self._mutate_element(
                    pilot,
                    select_script(
                        self._dom_registry_key,
                        action.backend_node_id or "",
                        parameters["value"],
                    ),
                ),
            )
        elif action.kind is ActionKind.CHECK:
            await self._run_action_call(
                "check dispatch",
                deadline,
                lambda: self._mutate_element(
                    pilot,
                    check_script(
                        self._dom_registry_key,
                        action.backend_node_id or "",
                        parameters["checked"],
                    ),
                ),
            )
        elif action.kind is ActionKind.HOVER:
            await self._run_action_call(
                "hover dispatch",
                deadline,
                lambda: pilot.hover(  # type: ignore[attr-defined]
                    selector=None,
                    x=x,
                    y=y,
                ),
            )
        else:
            await self._run_action_call(
                "drag dispatch",
                deadline,
                lambda: pilot.drag(  # type: ignore[attr-defined]
                    x,
                    y,
                    before_destination["x"] + before_destination["width"] / 2,
                    before_destination["y"] + before_destination["height"] / 2,
                ),
            )

        after: Mapping[str, Any] | None = None
        if action.kind in target_kinds:
            after = await self._run_action_call(
                "post-action target probe",
                deadline,
                lambda: self._element_state(pilot, action.backend_node_id or ""),
            )
        after_destination: Mapping[str, Any] | None = None
        if action.kind is ActionKind.DRAG:
            after_destination = await self._run_action_call(
                "post-drag destination probe",
                deadline,
                lambda: self._element_state(
                    pilot,
                    action.destination_backend_node_id or "",
                ),
            )
        after_page = await self._run_action_call(
            "post-action page-state probe",
            deadline,
            lambda: self._page_state(pilot),
        )
        current_url = await self._run_action_call(
            "post-action URL probe",
            deadline,
            lambda: pilot.url(),  # type: ignore[attr-defined]
        )
        title = await self._run_action_call(
            "post-action title probe",
            deadline,
            lambda: pilot.title(),  # type: ignore[attr-defined]
        )
        ready_state, dom_version, interactive_elements = await self._run_action_call(
            "post-action DOM observation",
            deadline,
            lambda: self._collect_dom(pilot),
        )
        if not isinstance(current_url, str) or not isinstance(title, str):
            raise TermuinatorError(
                ErrorCode.BACKEND_CRASHED,
                "Inherited browser returned invalid post-action metadata",
                retryable=True,
                details={"backend": self.backend.value},
            )
        self._status = BackendStatus(
            backend=self.backend,
            running=True,
            url=current_url,
            title=title,
            ready_state=ready_state,
            updated_at_monotonic=time.monotonic(),
        )
        document_changed = before_url != current_url
        after_version = after["dom_version"] if after is not None else dom_version
        dom_changed = bool(
            not document_changed
            and (
                before_page["dom_version"] != after_version
                or (action.kind in target_kinds and after is None)
            )
        )
        source_moved = bool(
            action.kind is ActionKind.DRAG
            and before is not None
            and after is not None
            and (before["x"], before["y"]) != (after["x"], after["y"])
        )
        target_changed = bool(
            action.kind is ActionKind.DRAG
            and before_destination is not None
            and (
                after_destination is None
                or self._element_effect_state(before_destination)
                != self._element_effect_state(after_destination)
            )
        )
        evidence = BackendActionEvidence(
            target_event_dispatched=True,
            before_url=before_url,
            after_url=current_url,
            before_value=(before["value"] if before is not None else None),
            after_value=(after["value"] if after is not None else None),
            before_checked=(before["checked"] if before is not None else None),
            after_checked=(after["checked"] if after is not None else None),
            before_selected=(before["selected"] if before is not None else None),
            after_selected=(after["selected"] if after is not None else None),
            before_scroll=(before_page["scroll_x"], before_page["scroll_y"]),
            after_scroll=(after_page["scroll_x"], after_page["scroll_y"]),
            before_visible=(before["visible"] if before is not None else None),
            after_visible=(after["visible"] if after is not None else None),
            before_hovered=(before["hovered"] if before is not None else None),
            after_hovered=(after["hovered"] if after is not None else None),
            source_moved=source_moved,
            target_changed=target_changed,
            dom_changed=dom_changed,
        )
        return BackendActionOutcome(
            executed_method=f"legacy-{action.kind.value}",
            snapshot=self._snapshot(interactive_elements=interactive_elements),
            evidence=evidence,
            document_changed=document_changed,
        )

    def _validate_action_parameters(self, action: BackendAction) -> dict[str, Any]:
        values = dict(action.parameters)
        allowed = {
            ActionKind.CLICK: {"button", "click_count"},
            ActionKind.TYPE: {"text", "clear"},
            ActionKind.KEY: {"key", "modifiers"},
            ActionKind.SCROLL: {"delta_x", "delta_y"},
            ActionKind.SELECT: {"value"},
            ActionKind.CHECK: {"checked"},
            ActionKind.HOVER: set(),
            ActionKind.DRAG: set(),
        }[action.kind]
        if any(not isinstance(key, str) for key in values) or set(values) - allowed:
            self._invalid_action_parameters(action.kind)
        if action.kind is ActionKind.CLICK:
            button = values.get("button", "left")
            count = values.get("click_count", 1)
            if button not in {"left", "middle", "right"} or (
                isinstance(count, bool)
                or not isinstance(count, int)
                or not 1 <= count <= 2
            ):
                self._invalid_action_parameters(action.kind)
            return {"button": button, "click_count": count}
        if action.kind is ActionKind.TYPE:
            text = values.get("text")
            clear = values.get("clear", False)
            if (
                not isinstance(text, str)
                or len(text) > 100_000
                or not isinstance(clear, bool)
            ):
                self._invalid_action_parameters(action.kind)
            return {"text": text, "clear": clear}
        if action.kind is ActionKind.KEY:
            key = values.get("key")
            modifiers = values.get("modifiers", ())
            modifier_bits = {"Alt": 1, "Control": 2, "Meta": 4, "Shift": 8}
            if (
                not isinstance(key, str)
                or not 1 <= len(key) <= 64
                or not isinstance(modifiers, (list, tuple))
                or len(modifiers) > 4
                or any(not isinstance(item, str) for item in modifiers)
                or len(modifiers) != len(set(modifiers))
                or any(item not in modifier_bits for item in modifiers)
            ):
                self._invalid_action_parameters(action.kind)
            return {
                "key": key,
                "modifier_mask": sum(modifier_bits[item] for item in modifiers),
            }
        if action.kind is ActionKind.SCROLL:
            if not values or not any(values.get(name, 0) for name in values):
                self._invalid_action_parameters(action.kind)
            result: dict[str, Any] = {}
            for name in ("delta_x", "delta_y"):
                value = values.get(name, 0)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or not -1_000_000 <= value <= 1_000_000
                ):
                    self._invalid_action_parameters(action.kind)
                result[name] = value
            return result
        if action.kind is ActionKind.SELECT:
            value = values.get("value")
            if not isinstance(value, str) or len(value) > 10_000:
                self._invalid_action_parameters(action.kind)
            return {"value": value}
        if action.kind is ActionKind.CHECK:
            checked = values.get("checked")
            if not isinstance(checked, bool):
                self._invalid_action_parameters(action.kind)
            return {"checked": checked}
        return {}

    @staticmethod
    def _element_effect_state(state: Mapping[str, Any]) -> tuple[object, ...]:
        return (
            state["x"],
            state["y"],
            state["width"],
            state["height"],
            state["value"],
            state["checked"],
            state["selected"],
            state["visible"],
        )

    def _invalid_action_parameters(self, kind: ActionKind) -> NoReturn:
        raise TermuinatorError(
            ErrorCode.INVALID_REQUEST,
            f"Legacy {kind.value} parameters are invalid",
        )

    def _require_actionable_target(
        self, state: Mapping[str, Any] | None
    ) -> None:
        if state is None:
            raise TermuinatorError(
                ErrorCode.TARGET_NOT_FOUND,
                "The observed browser target is no longer connected",
                retryable=True,
                details={"backend": self.backend.value},
            )
        if (
            not state["visible"]
            or not state["enabled"]
            or state["width"] <= 0
            or state["height"] <= 0
        ):
            raise TermuinatorError(
                ErrorCode.TARGET_NOT_FOUND,
                "The observed browser target is not actionable",
                retryable=True,
                details={"backend": self.backend.value},
            )

    async def _page_state(self, pilot: object) -> Mapping[str, Any]:
        try:
            payload = await pilot.evaluate(  # type: ignore[attr-defined]
                page_state_script(self._dom_registry_key)
            )
            return normalize_page_state(payload)
        except TermuinatorError:
            raise
        except Exception as exc:
            raise TermuinatorError(
                ErrorCode.BACKEND_CRASHED,
                "Inherited browser page-state probe failed",
                retryable=True,
                details={"backend": self.backend.value, "capability": "act"},
            ) from exc

    async def _mutate_element(self, pilot: object, script: str) -> None:
        try:
            payload = await pilot.evaluate(script)  # type: ignore[attr-defined]
            normalize_mutation_result(payload)
        except TermuinatorError:
            raise
        except Exception as exc:
            raise TermuinatorError(
                ErrorCode.BACKEND_CRASHED,
                "Inherited browser element mutation failed",
                retryable=True,
                details={"backend": self.backend.value, "capability": "act"},
            ) from exc

    async def _run_action_call(
        self,
        operation: str,
        deadline: float,
        call: Callable[[], Any],
    ) -> Any:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TermuinatorError(
                ErrorCode.TIMEOUT,
                "Inherited browser action timed out",
                retryable=True,
                details={"backend": self.backend.value, "operation": operation},
            )
        try:
            return await asyncio.wait_for(call(), timeout=remaining)
        except TermuinatorError:
            raise
        except TimeoutError as exc:
            raise TermuinatorError(
                ErrorCode.TIMEOUT,
                "Inherited browser action timed out",
                retryable=True,
                details={"backend": self.backend.value, "operation": operation},
            ) from exc
        except Exception as exc:
            raise TermuinatorError(
                ErrorCode.BACKEND_CRASHED,
                "Inherited browser action failed",
                retryable=True,
                details={"backend": self.backend.value, "operation": operation},
            ) from exc

    async def wait(
        self, condition: Mapping[str, Any], timeout_ms: int
    ) -> Mapping[str, Any]:
        self._unsupported("wait")

    async def tabs(
        self,
        operation: str,
        *,
        backend_tab_id: str | None = None,
        url: str | None = None,
    ) -> BackendTabsResult:
        self._unsupported("tabs")

    async def screenshot(
        self, mode: str, backend_node_id: str | None = None
    ) -> BackendArtifactPayload:
        if mode == "element" or (
            mode == "full" and self.backend is Backend.FIREFOX
        ):
            self._unsupported("screenshot")
        if mode not in {"viewport", "full"} or backend_node_id is not None:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Screenshot mode or private target handle is invalid",
                details={"backend": self.backend.value},
            )
        pilot = self._require_pilot()
        try:
            data = await pilot.screenshot(  # type: ignore[attr-defined]
                None,
                full_page=mode == "full",
            )
        except TermuinatorError:
            raise
        except Exception as exc:
            raise TermuinatorError(
                ErrorCode.BACKEND_CRASHED,
                "Inherited browser screenshot failed",
                retryable=True,
                details={"backend": self.backend.value},
            ) from exc
        try:
            return BackendArtifactPayload(data=data, mime_type="image/png")
        except (TypeError, ValueError) as exc:
            raise TermuinatorError(
                ErrorCode.BACKEND_CRASHED,
                "Inherited browser returned invalid screenshot bytes",
                retryable=True,
                details={"backend": self.backend.value},
            ) from exc

    async def downloads(
        self, operation: str, backend_download_id: str | None = None
    ) -> BackendDownloadsResult:
        self._unsupported("downloads")

    async def devtools(
        self, query: BackendDevtoolsQuery
    ) -> BackendDevtoolsResult:
        if not isinstance(query, BackendDevtoolsQuery):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Developer query must use the typed backend contract",
            )
        pilot = self._require_pilot()
        try:
            payload = await pilot.evaluate(  # type: ignore[attr-defined]
                devtools_script(self._dom_registry_key, query)
            )
            return normalize_devtools_result(query.query, payload)
        except TermuinatorError:
            raise
        except Exception as exc:
            raise TermuinatorError(
                ErrorCode.BACKEND_CRASHED,
                "Inherited browser Developer probe failed",
                retryable=True,
                details={
                    "backend": self.backend.value,
                    "capability": "devtools",
                    "query": query.query,
                },
            ) from exc
