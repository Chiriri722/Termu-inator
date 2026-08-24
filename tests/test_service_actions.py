"""BrowserService action policy, idempotency, and confirmation integration."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
import unittest

from src.termuinator.backends import (
    BackendActionEvidence,
    BackendActionOutcome,
    BackendPageSnapshot,
    RawInteractiveElement,
)
from src.termuinator.backends.fake import FakeBackend
from src.termuinator.contracts import (
    ActionKind,
    ActionRequest,
    ActionStatus,
    Backend,
    Bounds,
    ErrorCode,
    PageRevision,
    PermissionPolicy,
    SessionState,
    TraceExportResult,
    TraceRecordsResult,
    Viewport,
    to_wire,
)
from src.termuinator.core.confirmations import ConfirmationEngine
from src.termuinator.core.permissions import InMemoryPermissionEngine
from src.termuinator.core.service import BrowserService
from src.termuinator.errors import TermuinatorError


class _RecordingSessionLock:
    def __init__(self) -> None:
        self.held = False

    def acquire(self) -> None:
        if self.held:
            raise AssertionError("test lock acquired twice")
        self.held = True

    def release(self) -> None:
        self.held = False


class BrowserServiceActionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data_root = Path(self.temporary.name) / "data"
        self.viewport = Viewport(width=1280, height=720)
        self.permissions: InMemoryPermissionEngine | None = None
        self.confirmations: ConfirmationEngine | None = None

    @staticmethod
    def _snapshot(
        *,
        accessible_name: str = "Name",
        role: str = "textbox",
        element_type: str = "text",
    ) -> BackendPageSnapshot:
        return BackendPageSnapshot(
            url="https://example.com/form",
            title="Form",
            ready_state="complete",
            viewport=Viewport(width=1280, height=720),
            interactive_elements=(
                RawInteractiveElement(
                    backend_node_id="node-service-target",
                    role=role,
                    accessible_name=accessible_name,
                    tag="input" if role == "textbox" else "button",
                    type=element_type,
                    bounds=Bounds(x=10, y=20, width=200, height=40),
                    editable=role == "textbox",
                ),
            ),
        )

    def _service(
        self,
        *,
        snapshot: BackendPageSnapshot,
        outcome: BackendActionOutcome | None = None,
        action_error: Exception | None = None,
    ) -> tuple[BrowserService, FakeBackend]:
        backend = FakeBackend(
            Backend.CHROMIUM,
            snapshot=snapshot,
            action_outcome=outcome,
            action_error=action_error,
        )

        def permission_factory(project_id: str) -> InMemoryPermissionEngine:
            self.permissions = InMemoryPermissionEngine(project_id=project_id)
            return self.permissions

        def confirmation_factory(project_id: str) -> ConfirmationEngine:
            self.confirmations = ConfirmationEngine(
                owner_scope="transport-owner",
                project_id=project_id,
            )
            return self.confirmations

        return (
            BrowserService(
                data_root=self.data_root,
                owner_scope="transport-owner",
                default_backend=Backend.CHROMIUM,
                profile_schema_version="v1",
                backend_factories={Backend.CHROMIUM: lambda: backend},
                session_lock=_RecordingSessionLock(),
                permission_factory=permission_factory,
                confirmation_factory=confirmation_factory,
            ),
            backend,
        )

    async def _start_and_observe(
        self,
        service: BrowserService,
    ) -> tuple[str, object]:
        started = await service.session_start(
            project_id="project-actions",
            viewport=self.viewport,
        )
        status = started.status
        observation = await service.observe(
            session_id=started.session_id,
            tab_id=status.active_tab_id,
            page_id=status.active_page_id,
            expected_revision=PageRevision.parse(str(status.page_revision)),
            include_screenshot=False,
            include_accessibility=False,
            text_limit=1_000,
        )
        return started.session_id, observation

    @staticmethod
    def _request(
        *,
        session_id: str,
        observation: object,
        kind: ActionKind,
        parameters: dict[str, object],
        confirmation_id: str | None = None,
    ) -> ActionRequest:
        return ActionRequest(
            action_id="action_service1",
            idempotency_key="idempotency_service1",
            session_id=session_id,
            tab_id=observation.tab_id,
            page_id=observation.page_id,
            expected_page_revision=observation.page_revision,
            kind=kind,
            target_ref=observation.interactive_elements[0].ref,
            parameters=parameters,
            confirmation_id=confirmation_id,
        )

    def _allow(self, session_id: str) -> None:
        assert self.permissions is not None
        self.permissions.record(
            origin="https://example.com",
            policy=PermissionPolicy.SESSION_ALLOW,
            session_id=session_id,
        )

    async def test_permission_then_terminal_replay_dispatches_once(self) -> None:
        snapshot = self._snapshot()
        outcome = BackendActionOutcome(
            executed_method="dom-input",
            snapshot=snapshot,
            evidence=BackendActionEvidence(
                target_event_dispatched=True,
                before_value="",
                after_value="hello",
                dom_changed=True,
            ),
        )
        service, backend = self._service(snapshot=snapshot, outcome=outcome)
        session_id, observation = await self._start_and_observe(service)
        request = self._request(
            session_id=session_id,
            observation=observation,
            kind=ActionKind.TYPE,
            parameters={"text": "hello"},
        )

        with self.assertRaises(TermuinatorError) as permission:
            await service.act(request)
        self.assertEqual(permission.exception.code, ErrorCode.PERMISSION_REQUIRED)
        self.assertEqual(backend.action_calls, [])

        self._allow(session_id)
        result = await service.act(request)
        replay = await service.act(request)

        self.assertEqual(result.status, ActionStatus.SUCCEEDED)
        self.assertEqual(replay, result)
        self.assertEqual(len(backend.action_calls), 1)

    async def test_r4_confirmation_dispatches_exactly_once(self) -> None:
        snapshot = self._snapshot(
            accessible_name="Submit order",
            role="button",
            element_type="submit",
        )
        outcome = BackendActionOutcome(
            executed_method="dom-click",
            snapshot=snapshot,
            evidence=BackendActionEvidence(
                target_event_dispatched=True,
                dom_changed=True,
            ),
        )
        service, backend = self._service(snapshot=snapshot, outcome=outcome)
        session_id, observation = await self._start_and_observe(service)
        self._allow(session_id)
        request = self._request(
            session_id=session_id,
            observation=observation,
            kind=ActionKind.CLICK,
            parameters={},
        )

        with self.assertRaises(TermuinatorError) as required:
            await service.act(request)
        self.assertEqual(required.exception.code, ErrorCode.CONFIRMATION_REQUIRED)
        self.assertEqual(backend.action_calls, [])
        confirmation_id = required.exception.details["challenge"]["challenge_id"]
        assert self.confirmations is not None
        self.confirmations.approve(confirmation_id)
        confirmed = self._request(
            session_id=session_id,
            observation=observation,
            kind=ActionKind.CLICK,
            parameters={},
            confirmation_id=confirmation_id,
        )

        result = await service.act(confirmed)
        replay = await service.act(confirmed)

        self.assertEqual(result.status, ActionStatus.SUCCEEDED)
        self.assertEqual(replay, result)
        self.assertEqual(len(backend.action_calls), 1)

    async def test_sensitive_type_pauses_for_takeover_without_dispatch(self) -> None:
        snapshot = self._snapshot(element_type="password")
        service, backend = self._service(snapshot=snapshot)
        session_id, observation = await self._start_and_observe(service)
        self._allow(session_id)
        request = self._request(
            session_id=session_id,
            observation=observation,
            kind=ActionKind.TYPE,
            parameters={"text": "never-log-this"},
        )

        with self.assertRaises(TermuinatorError) as paused:
            await service.act(request)

        self.assertEqual(paused.exception.code, ErrorCode.SESSION_PAUSED)
        self.assertNotIn("never-log-this", repr(paused.exception.details))
        self.assertEqual(backend.action_calls, [])
        status = await service.session_status(session_id)
        self.assertEqual(status.state, SessionState.USER_TAKEOVER_REQUIRED)

    async def test_backend_exception_after_dispatch_is_outcome_unknown(self) -> None:
        snapshot = self._snapshot()
        service, backend = self._service(
            snapshot=snapshot,
            action_error=RuntimeError("backend exploded"),
        )
        session_id, observation = await self._start_and_observe(service)
        self._allow(session_id)
        request = self._request(
            session_id=session_id,
            observation=observation,
            kind=ActionKind.TYPE,
            parameters={"text": "hello"},
        )

        with self.assertRaises(TermuinatorError) as first:
            await service.act(request)
        with self.assertRaises(TermuinatorError) as replay:
            await service.act(request)

        self.assertEqual(first.exception.code, ErrorCode.OUTCOME_UNKNOWN)
        self.assertEqual(replay.exception.code, ErrorCode.OUTCOME_UNKNOWN)
        self.assertEqual(len(backend.action_calls), 1)

    async def test_trace_persistence_failure_after_dispatch_is_outcome_unknown(self) -> None:
        snapshot = self._snapshot()
        outcome = BackendActionOutcome(
            executed_method="dom-input",
            snapshot=snapshot,
            evidence=BackendActionEvidence(
                target_event_dispatched=True,
                before_value="",
                after_value="hello",
                dom_changed=True,
            ),
        )
        service, backend = self._service(snapshot=snapshot, outcome=outcome)
        session_id, observation = await self._start_and_observe(service)
        self._allow(session_id)
        trace_parent = self.data_root / "state" / "traces"
        trace_parent.write_text("unsafe trace namespace", encoding="utf-8")
        request = self._request(
            session_id=session_id,
            observation=observation,
            kind=ActionKind.TYPE,
            parameters={"text": "hello"},
        )

        with self.assertRaises(TermuinatorError) as first:
            await service.act(request)
        with self.assertRaises(TermuinatorError) as replay:
            await service.act(request)

        self.assertEqual(first.exception.code, ErrorCode.OUTCOME_UNKNOWN)
        self.assertEqual(replay.exception.code, ErrorCode.OUTCOME_UNKNOWN)
        self.assertNotIn("unsafe trace namespace", str(first.exception))
        self.assertEqual(len(backend.action_calls), 1)

    async def test_trace_operations_fail_closed_on_invalid_union_or_session(self) -> None:
        service, _backend = self._service(snapshot=self._snapshot())
        started = await service.session_start(
            project_id="project-actions",
            viewport=self.viewport,
        )

        invalid_calls = (
            service.trace(
                session_id=started.session_id,
                operation="list",
                trace_id="trace_abcdefgh",
            ),
            service.trace(
                session_id=started.session_id,
                operation="get",
            ),
            service.trace(
                session_id=started.session_id,
                operation="delete",
            ),
        )
        for call in invalid_calls:
            with self.assertRaises(TermuinatorError) as invalid:
                await call
            self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)

        with self.assertRaises(TermuinatorError) as foreign:
            await service.trace(
                session_id="session_foreign1",
                operation="list",
            )
        self.assertEqual(foreign.exception.code, ErrorCode.SESSION_NOT_FOUND)

    async def test_successful_action_writes_one_durable_secret_free_trace(self) -> None:
        secret = "do-not-store-this-value"
        snapshot = self._snapshot()
        outcome = BackendActionOutcome(
            executed_method="dom-input",
            snapshot=snapshot,
            evidence=BackendActionEvidence(
                target_event_dispatched=True,
                before_value="",
                after_value=secret,
                dom_changed=True,
            ),
        )
        service, backend = self._service(snapshot=snapshot, outcome=outcome)
        session_id, observation = await self._start_and_observe(service)
        self._allow(session_id)
        request = self._request(
            session_id=session_id,
            observation=observation,
            kind=ActionKind.TYPE,
            parameters={"text": secret},
        )

        result = await service.act(request)
        replay = await service.act(request)
        listed = await service.trace(
            session_id=session_id,
            operation="list",
        )

        self.assertEqual(replay, result)
        self.assertIsInstance(listed, TraceRecordsResult)
        self.assertEqual(len(listed.traces), 1)
        self.assertFalse(listed.truncated)
        trace = listed.traces[0]
        self.assertEqual(trace.action_kind, "type")
        self.assertEqual(trace.risk.value, "R2")
        self.assertEqual(trace.page_revision, observation.page_revision)
        self.assertEqual(trace.permission, "session_allow")
        self.assertTrue(trace.verification_passed)
        self.assertGreaterEqual(trace.duration_ms, 0)
        trace_wire = json.dumps(to_wire(listed))
        self.assertNotIn(secret, trace_wire)
        self.assertNotIn("node-service-target", trace_wire)
        self.assertNotIn("https://example.com", trace_wire)

        fetched = await service.trace(
            session_id=session_id,
            operation="get",
            trace_id=trace.trace_id,
        )
        self.assertIsInstance(fetched, TraceRecordsResult)
        self.assertEqual(fetched.traces, (trace,))

        exported = await service.trace(
            session_id=session_id,
            operation="export",
            trace_id=trace.trace_id,
        )
        self.assertIsInstance(exported, TraceExportResult)
        chunk = await service.artifact_read(
            session_id=session_id,
            uri=exported.artifact.uri,
            offset=0,
            limit=512 * 1024,
        )
        export_bytes = base64.b64decode(chunk.data_base64)
        self.assertNotIn(secret.encode("utf-8"), export_bytes)
        self.assertNotIn(b"node-service-target", export_bytes)
        self.assertEqual(json.loads(export_bytes)["trace"]["trace_id"], trace.trace_id)
        self.assertEqual(len(backend.action_calls), 1)

        await service.session_stop(session_id)
        restarted = await service.session_start(
            project_id="project-actions",
            viewport=self.viewport,
        )
        after_restart = await service.trace(
            session_id=restarted.session_id,
            operation="list",
        )
        self.assertEqual(after_restart.traces, (trace,))


if __name__ == "__main__":
    unittest.main()
