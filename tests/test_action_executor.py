"""Tests for ref resolution, backend dispatch, and causal verification."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest

from src.termuinator.backends import (
    BackendAction,
    BackendActionEvidence,
    BackendActionOutcome,
    BackendPageSnapshot,
    RawInteractiveElement,
)
from src.termuinator.contracts import (
    ActionKind,
    ActionRequest,
    ActionStatus,
    Bounds,
    ErrorCode,
    Viewport,
)
from src.termuinator.core.actions import ActionExecutor
from src.termuinator.core.observation import ObservationEngine
from src.termuinator.errors import TermuinatorError


class _RecordingActionBackend:
    def __init__(self, outcome: BackendActionOutcome) -> None:
        self.outcome = outcome
        self.calls: list[BackendAction] = []

    async def act(self, action: BackendAction) -> BackendActionOutcome:
        self.calls.append(action)
        return self.outcome


class ActionExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 24, 14, 0, tzinfo=timezone.utc)
        self.engine = ObservationEngine(
            session_id="session_12345678",
            capability_revision="fake-v1",
            default_viewport=Viewport(width=1280, height=720),
            now=lambda: self.now,
        )

    @staticmethod
    def _snapshot(
        *,
        role: str = "textbox",
        element_type: str = "password",
        url: str = "https://example.com/form",
    ) -> BackendPageSnapshot:
        return BackendPageSnapshot(
            url=url,
            title="Form",
            ready_state="complete",
            viewport=Viewport(width=1280, height=720),
            interactive_elements=(
                RawInteractiveElement(
                    backend_node_id="node-secret-input",
                    role=role,
                    accessible_name="Secret",
                    tag="input" if role == "textbox" else "button",
                    type=element_type,
                    bounds=Bounds(x=10, y=20, width=200, height=40),
                    editable=role == "textbox",
                ),
            ),
        )

    @staticmethod
    def _drag_snapshot() -> BackendPageSnapshot:
        return BackendPageSnapshot(
            url="https://example.com/board",
            title="Board",
            ready_state="complete",
            viewport=Viewport(width=1280, height=720),
            interactive_elements=(
                RawInteractiveElement(
                    backend_node_id="node-drag-source",
                    role="button",
                    accessible_name="Source",
                    tag="button",
                    type="button",
                    bounds=Bounds(x=10, y=20, width=100, height=40),
                ),
                RawInteractiveElement(
                    backend_node_id="node-drag-destination",
                    role="button",
                    accessible_name="Destination",
                    tag="button",
                    type="button",
                    bounds=Bounds(x=300, y=20, width=100, height=40),
                ),
            ),
        )

    async def test_type_uses_private_handle_and_service_verifies_redacted_value(self) -> None:
        before = self.engine.capture(self._snapshot())
        secret = "not-for-traces"
        outcome = BackendActionOutcome(
            executed_method="dom-input",
            snapshot=self._snapshot(),
            evidence=BackendActionEvidence(
                target_event_dispatched=True,
                before_value="",
                after_value=secret,
                dom_changed=True,
            ),
        )
        backend = _RecordingActionBackend(outcome)
        request = ActionRequest(
            action_id="action_12345678",
            idempotency_key="idempotency_12345678",
            session_id=before.session_id,
            tab_id=before.tab_id,
            page_id=before.page_id,
            expected_page_revision=before.page_revision,
            kind=ActionKind.TYPE,
            target_ref=before.interactive_elements[0].ref,
            parameters={"text": secret, "clear": True},
        )

        result = await ActionExecutor().execute(
            request=request,
            backend=backend,
            observation=self.engine,
        )

        self.assertEqual(result.status, ActionStatus.SUCCEEDED)
        self.assertEqual(backend.calls[0].backend_node_id, "node-secret-input")
        self.assertNotEqual(backend.calls[0].backend_node_id, request.target_ref)
        summaries = " ".join(
            item.expected_summary + item.actual_summary
            for item in result.verification
        )
        self.assertNotIn(secret, summaries)
        self.assertTrue(result.verification[0].causal)
        self.assertEqual(result.after_revision.mutation_counter, 1)

    async def test_unverified_click_is_failed_not_succeeded(self) -> None:
        before = self.engine.capture(
            self._snapshot(role="button", element_type="button")
        )
        backend = _RecordingActionBackend(
            BackendActionOutcome(
                executed_method="dom-click",
                snapshot=self._snapshot(role="button", element_type="button"),
                evidence=BackendActionEvidence(target_event_dispatched=True),
            )
        )
        request = ActionRequest(
            action_id="action_abcdefgh",
            idempotency_key="idempotency_abcdefgh",
            session_id=before.session_id,
            tab_id=before.tab_id,
            page_id=before.page_id,
            expected_page_revision=before.page_revision,
            kind=ActionKind.CLICK,
            target_ref=before.interactive_elements[0].ref,
        )

        result = await ActionExecutor().execute(
            request=request,
            backend=backend,
            observation=self.engine,
        )

        self.assertEqual(result.status, ActionStatus.FAILED)
        self.assertFalse(any(item.causal for item in result.verification))

    async def test_stale_revision_is_rejected_before_backend_dispatch(self) -> None:
        before = self.engine.capture(self._snapshot())
        self.engine.capture(self._snapshot(), dom_changed=True)
        backend = _RecordingActionBackend(
            BackendActionOutcome(
                executed_method="dom-input",
                snapshot=self._snapshot(),
                evidence=BackendActionEvidence(
                    target_event_dispatched=True,
                    after_value="new",
                ),
            )
        )
        request = ActionRequest(
            action_id="action_stale000",
            idempotency_key="idempotency_stale000",
            session_id=before.session_id,
            tab_id=before.tab_id,
            page_id=before.page_id,
            expected_page_revision=before.page_revision,
            kind=ActionKind.TYPE,
            target_ref=before.interactive_elements[0].ref,
            parameters={"text": "new"},
        )

        with self.assertRaises(TermuinatorError) as stale:
            await ActionExecutor().execute(
                request=request,
                backend=backend,
                observation=self.engine,
            )
        self.assertEqual(stale.exception.code, ErrorCode.STALE_OBSERVATION)
        self.assertEqual(backend.calls, [])

    async def test_stale_ref_at_current_revision_is_rejected_before_dispatch(self) -> None:
        before = self.engine.capture(self._snapshot())
        current = self.engine.capture(
            self._snapshot(role="button", element_type="button"),
            dom_changed=True,
        )
        backend = _RecordingActionBackend(
            BackendActionOutcome(
                executed_method="dom-click",
                snapshot=self._snapshot(role="button", element_type="button"),
                evidence=BackendActionEvidence(target_event_dispatched=True),
            )
        )
        request = ActionRequest(
            action_id="action_staleref",
            idempotency_key="idempotency_staleref",
            session_id=current.session_id,
            tab_id=current.tab_id,
            page_id=current.page_id,
            expected_page_revision=current.page_revision,
            kind=ActionKind.CLICK,
            target_ref=before.interactive_elements[0].ref,
        )

        with self.assertRaises(TermuinatorError) as stale:
            await ActionExecutor().execute(
                request=request,
                backend=backend,
                observation=self.engine,
            )
        self.assertEqual(stale.exception.code, ErrorCode.TARGET_NOT_FOUND)
        self.assertEqual(backend.calls, [])

    async def test_drag_resolves_source_and_destination_handles(self) -> None:
        snapshot = self._drag_snapshot()
        before = self.engine.capture(snapshot)
        backend = _RecordingActionBackend(
            BackendActionOutcome(
                executed_method="dom-drag",
                snapshot=snapshot,
                evidence=BackendActionEvidence(
                    target_event_dispatched=True,
                    source_moved=True,
                ),
            )
        )
        request = ActionRequest(
            action_id="action_drag1234",
            idempotency_key="idempotency_drag1234",
            session_id=before.session_id,
            tab_id=before.tab_id,
            page_id=before.page_id,
            expected_page_revision=before.page_revision,
            kind=ActionKind.DRAG,
            target_ref=before.interactive_elements[0].ref,
            parameters={"destination_ref": before.interactive_elements[1].ref},
        )

        result = await ActionExecutor().execute(
            request=request,
            backend=backend,
            observation=self.engine,
        )

        self.assertEqual(result.status, ActionStatus.SUCCEEDED)
        self.assertEqual(backend.calls[0].backend_node_id, "node-drag-source")
        self.assertEqual(
            backend.calls[0].destination_backend_node_id,
            "node-drag-destination",
        )
        self.assertNotIn("destination_ref", backend.calls[0].parameters)
        self.assertEqual(result.verification[0].kind, "dom_fingerprint")

    async def test_click_promotes_url_and_download_effects(self) -> None:
        cases = (
            (
                BackendActionOutcome(
                    executed_method="dom-click",
                    snapshot=self._snapshot(
                        role="button",
                        element_type="button",
                        url="https://example.com/success",
                    ),
                    evidence=BackendActionEvidence(
                        target_event_dispatched=True,
                        before_url="https://example.com/form",
                        after_url="https://example.com/success",
                    ),
                ),
                "url_change",
            ),
            (
                BackendActionOutcome(
                    executed_method="dom-click",
                    snapshot=self._snapshot(role="button", element_type="button"),
                    evidence=BackendActionEvidence(
                        target_event_dispatched=True,
                        download={"artifact_uri": "artifact://sha256/" + "a" * 64},
                    ),
                ),
                "download",
            ),
        )
        for index, (outcome, expected_kind) in enumerate(cases):
            with self.subTest(kind=expected_kind):
                engine = ObservationEngine(
                    session_id=f"session_effect{index}",
                    capability_revision="fake-v1",
                    default_viewport=Viewport(width=1280, height=720),
                    now=lambda: self.now,
                )
                before = engine.capture(
                    self._snapshot(role="button", element_type="button")
                )
                request = ActionRequest(
                    action_id=f"action_effect{index}",
                    idempotency_key=f"idempotency_effect{index}",
                    session_id=before.session_id,
                    tab_id=before.tab_id,
                    page_id=before.page_id,
                    expected_page_revision=before.page_revision,
                    kind=ActionKind.CLICK,
                    target_ref=before.interactive_elements[0].ref,
                )

                result = await ActionExecutor().execute(
                    request=request,
                    backend=_RecordingActionBackend(outcome),
                    observation=engine,
                )

                self.assertEqual(result.status, ActionStatus.SUCCEEDED)
                self.assertEqual(result.verification[0].kind, expected_kind)

    async def test_every_closed_action_kind_has_effect_specific_verification(self) -> None:
        cases = (
            (
                ActionKind.SELECT,
                {"value": "kr"},
                BackendActionEvidence(
                    target_event_dispatched=True,
                    before_selected="us",
                    after_selected="kr",
                ),
                "selected_value",
                True,
            ),
            (
                ActionKind.CHECK,
                {"checked": True},
                BackendActionEvidence(
                    target_event_dispatched=True,
                    before_checked=False,
                    after_checked=True,
                ),
                "checked_state",
                True,
            ),
            (
                ActionKind.SCROLL,
                {"delta_y": 400},
                BackendActionEvidence(
                    target_event_dispatched=True,
                    before_scroll=(0, 0),
                    after_scroll=(0, 400),
                ),
                "scroll_position",
                False,
            ),
            (
                ActionKind.HOVER,
                {},
                BackendActionEvidence(
                    target_event_dispatched=True,
                    before_hovered=False,
                    after_hovered=True,
                ),
                "visibility",
                True,
            ),
            (
                ActionKind.KEY,
                {"key": "Enter"},
                BackendActionEvidence(
                    target_event_dispatched=True,
                    dialog_opened=True,
                ),
                "dialog",
                False,
            ),
        )
        for index, (kind, parameters, evidence, expected_kind, needs_target) in enumerate(cases):
            with self.subTest(kind=kind.value):
                engine = ObservationEngine(
                    session_id=f"session_case{index:02d}",
                    capability_revision="fake-v1",
                    default_viewport=Viewport(width=1280, height=720),
                    now=lambda: self.now,
                )
                before = engine.capture(self._snapshot(role="button", element_type="button"))
                target_ref = before.interactive_elements[0].ref if needs_target else None
                request = ActionRequest(
                    action_id=f"action_case{index:02d}",
                    idempotency_key=f"idempotency_case{index:02d}",
                    session_id=before.session_id,
                    tab_id=before.tab_id,
                    page_id=before.page_id,
                    expected_page_revision=before.page_revision,
                    kind=kind,
                    target_ref=target_ref,
                    parameters=parameters,
                )
                backend = _RecordingActionBackend(
                    BackendActionOutcome(
                        executed_method=f"fake-{kind.value}",
                        snapshot=self._snapshot(role="button", element_type="button"),
                        evidence=evidence,
                    )
                )

                result = await ActionExecutor().execute(
                    request=request,
                    backend=backend,
                    observation=engine,
                )

                self.assertEqual(result.status, ActionStatus.SUCCEEDED)
                self.assertEqual(result.verification[0].kind, expected_kind)


if __name__ == "__main__":
    unittest.main()
