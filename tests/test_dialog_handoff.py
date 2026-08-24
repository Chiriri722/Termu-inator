"""Dialog lifecycle and sensitive sign-in handoff signals."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from src.termuinator.backends import (
    BackendDialogSnapshot,
    BackendPageSnapshot,
    RawInteractiveElement,
)
from src.termuinator.backends.fake import FakeBackend
from src.termuinator.contracts import (
    Backend,
    ChallengeKind,
    ChallengeState,
    Dialog,
    ErrorCode,
    SessionState,
    Viewport,
    to_wire,
)
from src.termuinator.core.observation import ObservationEngine
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


class DialogContractAndLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.viewport = Viewport(width=1280, height=720)
        self.engine = ObservationEngine(
            session_id="session_dialogs",
            capability_revision="fake-v1",
            default_viewport=self.viewport,
        )

    def _snapshot(
        self,
        dialogs: tuple[BackendDialogSnapshot, ...],
    ) -> BackendPageSnapshot:
        return BackendPageSnapshot(
            url="https://example.com/dialogs",
            title="Dialogs",
            ready_state="complete",
            viewport=self.viewport,
            dialogs=dialogs,
        )

    def test_dialog_identity_is_stable_and_close_is_emitted_once(self) -> None:
        raw = BackendDialogSnapshot(
            backend_dialog_id="private-dialog-1",
            kind="confirm",
            message="Continue?",
            open=True,
        )
        first = self.engine.capture(self._snapshot((raw,)))
        second = self.engine.capture(self._snapshot((raw,)))
        closed = self.engine.capture(self._snapshot(()))
        settled = self.engine.capture(self._snapshot(()))

        self.assertEqual(len(first.dialogs), 1)
        self.assertIsInstance(first.dialogs[0], Dialog)
        self.assertEqual(first.dialogs[0].dialog_id, second.dialogs[0].dialog_id)
        self.assertTrue(first.dialogs[0].open)
        self.assertEqual(closed.dialogs[0].dialog_id, first.dialogs[0].dialog_id)
        self.assertFalse(closed.dialogs[0].open)
        self.assertEqual(settled.dialogs, ())
        self.assertNotIn("private-dialog-1", repr(to_wire(first)))


class SensitiveHandoffServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.viewport = Viewport(width=1280, height=720)

    def _service(
        self,
        snapshot: BackendPageSnapshot,
    ) -> tuple[BrowserService, FakeBackend]:
        backend = FakeBackend(Backend.CHROMIUM, snapshot=snapshot)
        service = BrowserService(
            data_root=Path(self.temporary.name) / "data",
            owner_scope="transport-owner",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={Backend.CHROMIUM: lambda: backend},
            session_lock=_RecordingSessionLock(),
        )
        return service, backend

    async def _observe(
        self,
        service: BrowserService,
    ) -> tuple[str, object]:
        started = await service.session_start(
            project_id="project-handoff",
            viewport=self.viewport,
        )
        status = started.status
        assert status.active_tab_id is not None
        assert status.active_page_id is not None
        assert status.page_revision is not None
        observation = await service.observe(
            session_id=started.session_id,
            tab_id=status.active_tab_id,
            page_id=status.active_page_id,
            expected_revision=status.page_revision,
            include_screenshot=False,
            include_accessibility=False,
            text_limit=1_000,
        )
        return started.session_id, observation

    async def test_password_or_otp_field_pauses_remote_control_without_value_capture(self) -> None:
        snapshot = BackendPageSnapshot(
            url="https://example.com/login",
            title="Sign in",
            ready_state="complete",
            viewport=self.viewport,
            text="Sign in",
            interactive_elements=(
                RawInteractiveElement(
                    backend_node_id="private-password-node",
                    role="textbox",
                    accessible_name="Password",
                    tag="input",
                    type="password",
                    editable=True,
                ),
            ),
        )
        service, backend = self._service(snapshot)
        session_id, observation = await self._observe(service)

        self.assertEqual(len(observation.challenges), 1)
        challenge = observation.challenges[0]
        self.assertEqual(challenge.kind, ChallengeKind.USER_TAKEOVER)
        self.assertEqual(challenge.state, ChallengeState.PENDING)
        self.assertNotIn("private-password-node", repr(to_wire(challenge)))
        status = await service.session_status(session_id)
        self.assertEqual(status.state, SessionState.USER_TAKEOVER_REQUIRED)

        with self.assertRaises(TermuinatorError) as paused:
            await service.tabs(session_id=session_id, operation="list")
        self.assertEqual(paused.exception.code, ErrorCode.SESSION_PAUSED)
        self.assertEqual(backend.tab_calls, [])

        await service.local_takeover_start(session_id)
        resumed = await service.local_takeover_resume(session_id)
        self.assertEqual(resumed.challenges, ())
        self.assertEqual(
            (await service.session_status(session_id)).state,
            SessionState.ACTIVE,
        )

    async def test_open_dialog_requires_local_takeover_until_it_is_closed(self) -> None:
        snapshot = BackendPageSnapshot(
            url="https://example.com/dialogs",
            title="Dialogs",
            ready_state="complete",
            viewport=self.viewport,
            dialogs=(
                BackendDialogSnapshot(
                    backend_dialog_id="private-dialog-1",
                    kind="alert",
                    message="Review this message",
                    open=True,
                ),
            ),
        )
        service, backend = self._service(snapshot)
        session_id, observation = await self._observe(service)
        self.assertTrue(observation.dialogs[0].open)
        self.assertEqual(
            (await service.session_status(session_id)).state,
            SessionState.USER_TAKEOVER_REQUIRED,
        )

        await service.local_takeover_start(session_id)
        backend._snapshot = replace(snapshot, dialogs=())
        resumed = await service.local_takeover_resume(session_id)
        self.assertFalse(any(dialog.open for dialog in resumed.dialogs))
        self.assertEqual(
            (await service.session_status(session_id)).state,
            SessionState.ACTIVE,
        )


if __name__ == "__main__":
    unittest.main()
