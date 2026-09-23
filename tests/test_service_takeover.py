"""Local-only user takeover transitions for confidential browser input."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from src.termuinator.backends import (
    BackendActionEvidence,
    BackendActionOutcome,
    BackendArtifactPayload,
    BackendPageSnapshot,
    RawInteractiveElement,
)
from src.termuinator.backends.fake import FakeBackend
from src.termuinator.contracts import (
    ActionKind,
    ActionRequest,
    Backend,
    Bounds,
    ErrorCode,
    PermissionPolicy,
    SessionState,
    Viewport,
    WaitTextCondition,
)
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


class _FailingResumeBackend(FakeBackend):
    fail_observe = False

    async def observe(
        self,
        *,
        include_screenshot: bool,
        include_accessibility: bool,
        text_limit: int,
    ) -> BackendPageSnapshot:
        if self.fail_observe:
            raise RuntimeError("local resume probe failed")
        return await super().observe(
            include_screenshot=include_screenshot,
            include_accessibility=include_accessibility,
            text_limit=text_limit,
        )


class BrowserServiceTakeoverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.viewport = Viewport(width=1280, height=720)
        self.permissions: InMemoryPermissionEngine | None = None

    @staticmethod
    def _snapshot() -> BackendPageSnapshot:
        return BackendPageSnapshot(
            url="https://example.com/login",
            title="Login",
            ready_state="complete",
            viewport=Viewport(width=1280, height=720),
            text="Password secret should not be collected during resume",
            accessibility=({"role": "textbox", "value": "secret"},),
            screenshot=BackendArtifactPayload(
                data=b"\x89PNG\r\n\x1a\ntakeover-boundary",
                mime_type="image/png",
            ),
            interactive_elements=(
                RawInteractiveElement(
                    backend_node_id="private-password-node",
                    role="textbox",
                    accessible_name="Password",
                    tag="input",
                    type="password",
                    bounds=Bounds(x=10, y=20, width=200, height=40),
                    editable=True,
                ),
            ),
        )

    def _service(
        self,
        *,
        failing_resume: bool = False,
        initial_snapshot: BackendPageSnapshot | None = None,
    ) -> tuple[BrowserService, FakeBackend]:
        snapshot = self._snapshot()
        outcome = BackendActionOutcome(
            executed_method="dom-input",
            snapshot=snapshot,
            evidence=BackendActionEvidence(
                target_event_dispatched=True,
                before_value="",
                after_value="redacted",
                dom_changed=True,
            ),
        )
        backend_type = _FailingResumeBackend if failing_resume else FakeBackend
        backend = backend_type(
            Backend.CHROMIUM,
            snapshot=initial_snapshot or snapshot,
            action_outcome=outcome,
            navigation_results={("goto", snapshot.url): snapshot},
            tabs_supported=True,
        )

        def permission_factory(project_id: str) -> InMemoryPermissionEngine:
            self.permissions = InMemoryPermissionEngine(project_id=project_id)
            return self.permissions

        service = BrowserService(
            data_root=Path(self.temporary.name) / "data",
            owner_scope="transport-owner",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={Backend.CHROMIUM: lambda: backend},
            session_lock=_RecordingSessionLock(),
            permission_factory=permission_factory,
        )
        return service, backend

    async def test_first_sensitive_response_is_not_published_by_any_capture_path(self) -> None:
        sensitive = self._snapshot()
        normal = replace(sensitive, text="Ready", accessibility=(), interactive_elements=(
            RawInteractiveElement(backend_node_id="private-continue", role="button", accessible_name="Continue",
                                  tag="button", type="button", bounds=Bounds(x=10, y=20, width=120, height=40)),
        ))
        for operation in ("observe", "navigate", "wait", "tabs", "act"):
            with self.subTest(operation=operation):
                service, backend = self._service(initial_snapshot=normal)
                session_id, before = await self._start_and_observe(service, expect_takeover=False)
                context = {"session_id": session_id, "tab_id": before.tab_id, "page_id": before.page_id,
                           "expected_revision": before.page_revision}
                backend._snapshot = sensitive
                request = ActionRequest(
                    action_id="action_transition" + operation, idempotency_key="idem_transition" + operation,
                    session_id=session_id, tab_id=before.tab_id, page_id=before.page_id,
                    expected_page_revision=before.page_revision, kind=ActionKind.CLICK,
                    target_ref=before.interactive_elements[0].ref, parameters={},
                )
                with self.assertRaises(TermuinatorError) as paused:
                    if operation == "observe":
                        await service.observe(**context, include_screenshot=True, include_accessibility=True, text_limit=1000)
                    elif operation == "navigate":
                        await service.navigate(**context, operation="goto", url=sensitive.url)
                    elif operation == "wait":
                        await service.wait(**context, condition=WaitTextCondition(kind="text", text="secret", present=True), timeout_ms=100)
                    elif operation == "tabs":
                        backend._tab_snapshots[backend._active_backend_tab_id] = sensitive
                        await service.tabs(session_id=session_id, operation="switch", tab_id=before.tab_id)
                    else:
                        await service.act(request)
                self.assertEqual(paused.exception.code, ErrorCode.SESSION_PAUSED)
                self.assertNotIn("secret", str(paused.exception))
                self.assertEqual((await service.session_status(session_id)).state, SessionState.USER_TAKEOVER_REQUIRED)
                if operation == "act":
                    await service.local_takeover_start(session_id)
                    await service.local_takeover_resume(session_id)
                    await service.act(request)
                    self.assertEqual(len(backend.action_calls), 1, "hidden terminal action must not be replayed")
                await service.session_stop(session_id)

    async def _start_and_observe(
        self,
        service: BrowserService,
        *,
        expect_takeover: bool = True,
    ) -> tuple[str, object]:
        started = await service.session_start(
            project_id="project-takeover",
            viewport=self.viewport,
        )
        status = started.status
        assert status.active_tab_id is not None
        assert status.active_page_id is not None
        assert status.page_revision is not None
        attempt = service.observe(
            session_id=started.session_id,
            tab_id=status.active_tab_id,
            page_id=status.active_page_id,
            expected_revision=status.page_revision,
            include_screenshot=False,
            include_accessibility=False,
            text_limit=1_000,
        )
        if expect_takeover:
            with self.assertRaises(TermuinatorError) as paused:
                await attempt
            self.assertEqual(paused.exception.code, ErrorCode.SESSION_PAUSED)
            # Internal identity is used only to probe subsequent blocked calls;
            # the first confidential observation was not returned to the caller.
            observation = service._active.observation.last_observation
        else:
            observation = await attempt
        assert self.permissions is not None
        self.permissions.record(
            origin="https://example.com",
            policy=PermissionPolicy.SESSION_ALLOW,
            session_id=started.session_id,
        )
        return started.session_id, observation

    @staticmethod
    def _request(
        *,
        session_id: str,
        observation: object,
        suffix: str,
    ) -> ActionRequest:
        return ActionRequest(
            action_id=f"action_takeover{suffix}",
            idempotency_key=f"idempotency_takeover{suffix}",
            session_id=session_id,
            tab_id=observation.tab_id,
            page_id=observation.page_id,
            expected_page_revision=observation.page_revision,
            kind=ActionKind.TYPE,
            target_ref=observation.interactive_elements[0].ref,
            parameters={"text": "never-log-this"},
        )

    async def _require_takeover(
        self,
        service: BrowserService,
        session_id: str,
        observation: object,
    ) -> None:
        request = self._request(
            session_id=session_id,
            observation=observation,
            suffix="1",
        )
        with self.assertRaises(TermuinatorError) as paused:
            await service.act(request)
        self.assertEqual(paused.exception.code, ErrorCode.SESSION_PAUSED)

    async def test_local_resume_rotates_page_and_keeps_mcp_actions_paused(self) -> None:
        service, backend = self._service()
        session_id, before = await self._start_and_observe(service)
        await self._require_takeover(service, session_id, before)
        self.assertEqual(backend.action_calls, [])

        active = await service.local_takeover_start(session_id)
        self.assertEqual(active.state, SessionState.USER_TAKEOVER_ACTIVE)

        with self.assertRaises(TermuinatorError) as still_paused:
            await service.act(
                self._request(
                    session_id=session_id,
                    observation=before,
                    suffix="2",
                )
            )
        self.assertEqual(still_paused.exception.code, ErrorCode.SESSION_PAUSED)
        self.assertEqual(backend.action_calls, [])

        resumed = await service.local_takeover_resume(session_id)
        self.assertNotEqual(resumed.page_id, before.page_id)
        self.assertNotEqual(resumed.page_revision, before.page_revision)
        self.assertEqual(resumed.text, "")
        self.assertEqual(resumed.accessibility, ())
        self.assertIsNone(resumed.screenshot_artifact_uri)
        status = await service.session_status(session_id)
        self.assertEqual(status.state, SessionState.ACTIVE)

        with self.assertRaises(TermuinatorError) as stale:
            await service.act(
                self._request(
                    session_id=session_id,
                    observation=before,
                    suffix="3",
                )
            )
        self.assertEqual(stale.exception.code, ErrorCode.STALE_OBSERVATION)
        self.assertEqual(backend.action_calls, [])

    async def test_invalid_local_takeover_transitions_fail_closed(self) -> None:
        service, _backend = self._service()
        session_id, before = await self._start_and_observe(service)

        with self.assertRaises(TermuinatorError) as invalid:
            await service.local_takeover_resume(session_id)
        self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)

        await self._require_takeover(service, session_id, before)
        await service.local_takeover_start(session_id)
        with self.assertRaises(TermuinatorError) as duplicate_start:
            await service.local_takeover_start(session_id)
        self.assertEqual(duplicate_start.exception.code, ErrorCode.INVALID_REQUEST)

        await service.local_takeover_resume(session_id)
        with self.assertRaises(TermuinatorError) as duplicate_resume:
            await service.local_takeover_resume(session_id)
        self.assertEqual(duplicate_resume.exception.code, ErrorCode.INVALID_REQUEST)

    async def test_failed_resume_remains_under_local_user_control(self) -> None:
        service, backend = self._service(failing_resume=True)
        session_id, before = await self._start_and_observe(service)
        await self._require_takeover(service, session_id, before)
        await service.local_takeover_start(session_id)
        assert isinstance(backend, _FailingResumeBackend)
        backend.fail_observe = True

        with self.assertRaises(TermuinatorError) as failed:
            await service.local_takeover_resume(session_id)

        self.assertEqual(failed.exception.code, ErrorCode.BACKEND_CRASHED)
        status = await service.session_status(session_id)
        self.assertEqual(status.state, SessionState.USER_TAKEOVER_ACTIVE)
        self.assertEqual(backend.action_calls, [])

    async def test_confidential_states_block_remote_reads_and_redact_status(self) -> None:
        service, backend = self._service()
        started = await service.session_start(
            project_id="project-takeover",
            viewport=self.viewport,
        )
        status = started.status
        assert status.active_tab_id is not None
        assert status.active_page_id is not None
        assert status.page_revision is not None
        artifact = await service.screenshot(
            session_id=started.session_id,
            tab_id=status.active_tab_id,
            page_id=status.active_page_id,
            expected_revision=status.page_revision,
            mode="viewport",
        )
        with self.assertRaises(TermuinatorError) as first_paused:
            await service.observe(
                session_id=started.session_id,
                tab_id=status.active_tab_id,
                page_id=status.active_page_id,
                expected_revision=status.page_revision,
                include_screenshot=False,
                include_accessibility=False,
                text_limit=1_000,
            )
        self.assertEqual(first_paused.exception.code, ErrorCode.SESSION_PAUSED)
        before = service._active.observation.last_observation
        session_id = started.session_id
        await self._require_takeover(service, session_id, before)

        for expected_state in (
            SessionState.USER_TAKEOVER_REQUIRED,
            SessionState.USER_TAKEOVER_ACTIVE,
        ):
            if expected_state is SessionState.USER_TAKEOVER_ACTIVE:
                await service.local_takeover_start(session_id)
            status = await service.session_status(session_id)
            self.assertEqual(status.state, expected_state)
            self.assertEqual(status.url, "")
            self.assertEqual(status.title, "")
            self.assertEqual(status.ready_state, "takeover")
            self.assertIsNotNone(status.active_page_id)
            self.assertIsNotNone(status.active_tab_id)
            self.assertIsNotNone(status.page_revision)

            attempts = (
                service.navigate(
                    session_id=session_id,
                    tab_id=before.tab_id,
                    page_id=before.page_id,
                    expected_revision=before.page_revision,
                    operation="reload",
                ),
                service.observe(
                    session_id=session_id,
                    tab_id=before.tab_id,
                    page_id=before.page_id,
                    expected_revision=before.page_revision,
                    include_screenshot=False,
                    include_accessibility=False,
                    text_limit=1_000,
                ),
                service.screenshot(
                    session_id=session_id,
                    tab_id=before.tab_id,
                    page_id=before.page_id,
                    expected_revision=before.page_revision,
                    mode="viewport",
                ),
                service.artifact_read(
                    session_id=session_id,
                    uri=artifact.uri,
                    offset=0,
                    limit=8,
                ),
                service.permissions(
                    session_id=session_id,
                    operation="list",
                ),
                service.trace(
                    session_id=session_id,
                    operation="list",
                ),
                service.wait(
                    session_id=session_id,
                    tab_id=before.tab_id,
                    page_id=before.page_id,
                    expected_revision=before.page_revision,
                    condition=WaitTextCondition(
                        kind="text",
                        text="secret",
                        present=True,
                    ),
                    timeout_ms=1,
                ),
                service.tabs(
                    session_id=session_id,
                    operation="list",
                ),
                service.downloads(
                    session_id=session_id,
                    operation="list",
                ),
                service.devtools(
                    session_id=session_id,
                    tab_id=before.tab_id,
                    page_id=before.page_id,
                    expected_revision=before.page_revision,
                    query="console",
                    parameters={},
                ),
            )
            for attempt in attempts:
                with self.assertRaises(TermuinatorError) as paused:
                    await attempt
                self.assertEqual(paused.exception.code, ErrorCode.SESSION_PAUSED)

        self.assertEqual(backend.screenshot_calls, [("viewport", None)])
        self.assertEqual(backend.navigation_calls, [])
        self.assertEqual(backend.tab_calls, [])
        self.assertEqual(backend.download_calls, [])
        self.assertEqual(backend.devtools_calls, [])
        resumed = await service.local_takeover_resume(session_id)
        resumed_status = await service.session_status(session_id)
        self.assertEqual(resumed_status.state, SessionState.ACTIVE)
        self.assertEqual(resumed_status.url, "https://example.com/login")
        self.assertEqual(resumed_status.title, "Login")
        self.assertNotEqual(resumed.page_id, before.page_id)
        chunk = await service.artifact_read(
            session_id=session_id,
            uri=artifact.uri,
            offset=0,
            limit=8,
        )
        self.assertTrue(chunk.data_base64)


if __name__ == "__main__":
    unittest.main()
