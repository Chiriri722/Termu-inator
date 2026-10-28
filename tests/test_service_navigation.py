"""Typed navigation with page preconditions and origin permission gates."""

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from src.termuinator.backends import BackendPageSnapshot
from src.termuinator.backends.fake import FakeBackend
from src.termuinator.contracts import (
    Backend,
    ErrorCode,
    PermissionPolicy,
    SessionState,
    Viewport,
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


class BrowserServiceNavigationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.viewport = Viewport(width=1280, height=720)
        self.allowed_url = "https://allowed.example/page"
        self.allowed_snapshot = BackendPageSnapshot(
            url=self.allowed_url,
            title="Allowed",
            ready_state="complete",
            viewport=self.viewport,
            text="Allowed fixture",
        )
        self.permissions: InMemoryPermissionEngine | None = None

    def _service(
        self,
        navigation_results: dict[tuple[str, str | None], BackendPageSnapshot],
    ) -> tuple[BrowserService, FakeBackend]:
        backend = FakeBackend(
            Backend.CHROMIUM,
            snapshot=BackendPageSnapshot(
                url="about:blank",
                title="",
                ready_state="complete",
                viewport=self.viewport,
            ),
            navigation_results=navigation_results,
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

    async def _start_and_observe(
        self,
        service: BrowserService,
    ) -> tuple[str, object]:
        started = await service.session_start(
            project_id="project-navigation",
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
            text_limit=100,
        )
        return started.session_id, observation

    async def test_allowed_goto_rotates_page_identity_and_returns_observation(self) -> None:
        service, backend = self._service(
            {("goto", self.allowed_url): self.allowed_snapshot}
        )
        session_id, before = await self._start_and_observe(service)
        assert self.permissions is not None
        self.permissions.record(
            origin="https://allowed.example",
            policy=PermissionPolicy.SESSION_ALLOW,
            session_id=session_id,
        )

        after = await service.navigate(
            session_id=session_id,
            tab_id=before.tab_id,
            page_id=before.page_id,
            expected_revision=before.page_revision,
            operation="goto",
            url=self.allowed_url,
            timeout_ms=12_000,
        )

        self.assertEqual(after.url, self.allowed_url)
        self.assertNotEqual(after.page_id, before.page_id)
        self.assertNotEqual(after.page_revision, before.page_revision)
        self.assertEqual(
            backend.navigation_calls,
            [("goto", self.allowed_url, 12_000)],
        )

    async def test_backend_navigation_timeout_remains_a_typed_timeout(self) -> None:
        service, backend = self._service(
            {("goto", self.allowed_url): self.allowed_snapshot}
        )
        session_id, before = await self._start_and_observe(service)
        assert self.permissions is not None
        self.permissions.record(
            origin="https://allowed.example",
            policy=PermissionPolicy.SESSION_ALLOW,
            session_id=session_id,
        )
        backend.navigate = AsyncMock(
            side_effect=TimeoutError("private backend timeout detail")
        )

        with self.assertRaises(TermuinatorError) as timed_out:
            await service.navigate(
                session_id=session_id,
                tab_id=before.tab_id,
                page_id=before.page_id,
                expected_revision=before.page_revision,
                operation="goto",
                url=self.allowed_url,
                timeout_ms=12_000,
            )

        self.assertEqual(timed_out.exception.code, ErrorCode.TIMEOUT)
        self.assertNotIn(
            "private backend timeout detail",
            str(timed_out.exception),
        )

    async def test_ask_and_block_are_rejected_before_backend_dispatch(self) -> None:
        for policy, expected_code in (
            (None, ErrorCode.PERMISSION_REQUIRED),
            (PermissionPolicy.BLOCK, ErrorCode.PERMISSION_DENIED),
        ):
            service, backend = self._service(
                {("goto", self.allowed_url): self.allowed_snapshot}
            )
            session_id, before = await self._start_and_observe(service)
            assert self.permissions is not None
            if policy is not None:
                self.permissions.record(
                    origin="https://allowed.example",
                    policy=policy,
                )

            with self.assertRaises(TermuinatorError) as denied:
                await service.navigate(
                    session_id=session_id,
                    tab_id=before.tab_id,
                    page_id=before.page_id,
                    expected_revision=before.page_revision,
                    operation="goto",
                    url=self.allowed_url,
                    timeout_ms=30_000,
                )
            self.assertEqual(denied.exception.code, expected_code)
            self.assertEqual(backend.navigation_calls, [])
            self.assertEqual((await service.session_status(session_id)).state, SessionState.ACTIVE)

    async def test_post_dispatch_failures_preserve_error_and_quarantine_old_context(self) -> None:
        for failure in (RuntimeError("PRIVATE dispatch failure"), TimeoutError("PRIVATE timeout"),
                        TermuinatorError(ErrorCode.BACKEND_CRASHED, "Probe failed"),
                        asyncio.CancelledError(), None):
            with self.subTest(failure=type(failure).__name__):
                service, backend = self._service({("goto", self.allowed_url): self.allowed_snapshot})
                try:
                    session_id, before = await self._start_and_observe(service)
                    self.permissions.record(origin="https://allowed.example", policy=PermissionPolicy.SESSION_ALLOW, session_id=session_id)
                    original_navigate = backend.navigate

                    async def incomplete_navigation(*args):
                        await original_navigate(*args)
                        if failure is not None:
                            raise failure
                        return None

                    backend.navigate = incomplete_navigation
                    with self.assertRaises((TermuinatorError, asyncio.CancelledError)) as caught:
                        await service.navigate(session_id=session_id, tab_id=before.tab_id, page_id=before.page_id,
                            expected_revision=before.page_revision, operation="goto", url=self.allowed_url)
                    if isinstance(failure, (asyncio.CancelledError, TermuinatorError)):
                        self.assertIs(caught.exception, failure)
                    else:
                        self.assertEqual(caught.exception.code, ErrorCode.TIMEOUT if isinstance(failure, TimeoutError) else ErrorCode.BACKEND_CRASHED)
                    self.assertEqual((await service.session_status(session_id)).state, SessionState.USER_TAKEOVER_REQUIRED)
                    self.assertEqual((await service.shared_view_snapshot()).confidential, True)
                    with self.assertRaises(TermuinatorError) as blocked:
                        await service.observe(session_id=session_id, tab_id=before.tab_id, page_id=before.page_id,
                            expected_revision=before.page_revision, include_screenshot=True, include_accessibility=True, text_limit=1000)
                    self.assertEqual(blocked.exception.code, ErrorCode.SESSION_PAUSED)
                finally:
                    await service.close()

    async def test_owner_resume_cannot_bypass_permission_for_unapproved_redirect(self) -> None:
        redirected = BackendPageSnapshot(url="https://other.example/private", title="Private", ready_state="complete", viewport=self.viewport)
        service, backend = self._service({("goto", self.allowed_url): redirected})
        try:
            session_id, before = await self._start_and_observe(service)
            self.permissions.record(origin="https://allowed.example", policy=PermissionPolicy.SESSION_ALLOW, session_id=session_id)
            with self.assertRaises(TermuinatorError):
                await service.navigate(session_id=session_id, tab_id=before.tab_id, page_id=before.page_id,
                    expected_revision=before.page_revision, operation="goto", url=self.allowed_url)
            await service.local_takeover_start(session_id)
            with self.assertRaises(TermuinatorError) as denied:
                await service.local_takeover_resume(session_id)
            self.assertEqual(denied.exception.code, ErrorCode.PERMISSION_REQUIRED)
            self.assertEqual((await service.session_status(session_id)).state, SessionState.USER_TAKEOVER_ACTIVE)
            await service.local_permission_record(session_id=session_id, origin="https://other.example", policy=PermissionPolicy.SESSION_ALLOW)
            resumed = await service.local_takeover_resume(session_id)
            self.assertEqual(resumed.url, redirected.url)
            self.assertEqual((await service.session_status(session_id)).state, SessionState.ACTIVE)
        finally:
            await service.close()

    async def test_unapproved_redirect_rotates_identity_and_pauses_without_page_data(self) -> None:
        requested = "https://allowed.example/redirect"
        redirected = BackendPageSnapshot(
            url="https://other.example/private",
            title="Unexpected origin",
            ready_state="complete",
            viewport=self.viewport,
            text="must not be returned",
        )
        service, backend = self._service({("goto", requested): redirected})
        session_id, before = await self._start_and_observe(service)
        assert self.permissions is not None
        self.permissions.record(
            origin="https://allowed.example",
            policy=PermissionPolicy.SESSION_ALLOW,
            session_id=session_id,
        )

        with self.assertRaises(TermuinatorError) as redirected_error:
            await service.navigate(
                session_id=session_id,
                tab_id=before.tab_id,
                page_id=before.page_id,
                expected_revision=before.page_revision,
                operation="goto",
                url=requested,
                timeout_ms=30_000,
            )

        self.assertEqual(
            redirected_error.exception.code,
            ErrorCode.PERMISSION_REQUIRED,
        )
        self.assertNotIn("must not be returned", str(redirected_error.exception))
        self.assertEqual(len(backend.navigation_calls), 1)
        status = await service.session_status(session_id)
        self.assertEqual(status.state, SessionState.USER_TAKEOVER_REQUIRED)
        self.assertEqual(status.url, "")
        self.assertEqual(status.title, "")
        self.assertNotEqual(status.active_page_id, before.page_id)

    async def test_invalid_union_and_stale_context_fail_before_dispatch(self) -> None:
        service, backend = self._service(
            {("goto", self.allowed_url): self.allowed_snapshot}
        )
        session_id, before = await self._start_and_observe(service)

        invalid_cases = (
            {"operation": "goto", "url": None, "timeout_ms": 30_000},
            {"operation": "reload", "url": self.allowed_url, "timeout_ms": 30_000},
            {"operation": "delete", "url": None, "timeout_ms": 30_000},
            {"operation": "goto", "url": self.allowed_url, "timeout_ms": True},
        )
        for case in invalid_cases:
            with self.assertRaises(TermuinatorError) as invalid:
                await service.navigate(
                    session_id=session_id,
                    tab_id=before.tab_id,
                    page_id=before.page_id,
                    expected_revision=before.page_revision,
                    **case,
                )
            self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)

        with self.assertRaises(TermuinatorError) as stale:
            await service.navigate(
                session_id=session_id,
                tab_id=before.tab_id,
                page_id="page_wrong_abcdefgh",
                expected_revision=before.page_revision,
                operation="goto",
                url=self.allowed_url,
                timeout_ms=30_000,
            )
        self.assertEqual(stale.exception.code, ErrorCode.STALE_OBSERVATION)
        self.assertEqual(backend.navigation_calls, [])


if __name__ == "__main__":
    unittest.main()
