"""Unit tests for the typed single-session service boundary."""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
import stat
import tempfile
import unittest

from src.termuinator.backends.fake import FakeBackend
from src.termuinator.contracts import (
    Backend,
    ErrorCode,
    Observation,
    PageRevision,
    SessionStartResult,
    SessionState,
    SessionStatus,
    SessionStopResult,
    Viewport,
)
from src.termuinator.core.service import BrowserService
from src.termuinator.errors import TermuinatorError


class _RecordingSessionLock:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.acquired = False

    def acquire(self) -> None:
        if self.acquired:
            raise AssertionError("test lock acquired twice")
        self.acquired = True
        self.calls.append("acquire")

    def release(self) -> None:
        if self.acquired:
            self.acquired = False
            self.calls.append("release")


class BrowserServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_service_requires_transport_established_owner_scope(self) -> None:
        parameter = inspect.signature(BrowserService).parameters.get("owner_scope")
        self.assertIsNotNone(parameter)
        self.assertIs(parameter.default, inspect.Parameter.empty)

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_root = Path(self.temp_dir.name) / "runtime"
        self.chromium = FakeBackend(Backend.CHROMIUM)
        self.firefox = FakeBackend(Backend.FIREFOX)
        self.session_lock = _RecordingSessionLock()
        self.service = BrowserService(
            data_root=self.data_root,
            owner_scope="test-owner",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={
                Backend.CHROMIUM: lambda: self.chromium,
                Backend.FIREFOX: lambda: self.firefox,
            },
            session_lock=self.session_lock,
        )

    async def test_default_start_uses_chromium_and_hashed_profile(self) -> None:
        project_id = "/Users/example/Private Project"
        result = await self.service.session_start(
            project_id=project_id,
            viewport=Viewport(width=1280, height=720),
        )

        digest = hashlib.sha256(
            b"termuinator-owner-project-v1\x00test-owner\x00"
            + project_id.encode("utf-8")
        ).hexdigest()
        expected_profile = (
            self.data_root
            / "projects"
            / digest
            / "profiles"
            / "chromium"
            / "v1"
            / "profile"
        )
        self.assertIsInstance(result, SessionStartResult)
        self.assertEqual(result.status.backend, Backend.CHROMIUM)
        self.assertEqual(result.status.state, SessionState.ACTIVE)
        self.assertEqual(result.status.session_id, result.session_id)
        self.assertEqual(result.capabilities.backend, Backend.CHROMIUM)
        self.assertEqual(result.status.capabilities, result.capabilities)
        self.assertEqual(self.chromium.profile_dir, expected_profile)
        self.assertNotIn("Private Project", str(self.chromium.profile_dir))
        self.assertEqual(
            stat.S_IMODE(self.chromium.profile_dir.stat().st_mode), 0o700
        )
        self.assertEqual(self.chromium.calls, ["start"])

    async def test_backends_never_share_a_browser_profile(self) -> None:
        project_id = "project-a"
        chromium = await self.service.session_start(project_id=project_id)
        await self.service.session_stop(chromium.session_id)
        firefox = await self.service.session_start(
            project_id=project_id, backend=Backend.FIREFOX
        )

        self.assertNotEqual(self.chromium.profile_dir, self.firefox.profile_dir)
        self.assertEqual(self.chromium.profile_dir.parts[-3:], ("chromium", "v1", "profile"))
        self.assertEqual(self.firefox.profile_dir.parts[-3:], ("firefox", "v1", "profile"))

    async def test_owner_scopes_never_share_a_project_profile(self) -> None:
        backend_a = FakeBackend(Backend.CHROMIUM)
        backend_b = FakeBackend(Backend.CHROMIUM)
        service_a = BrowserService(
            data_root=self.data_root,
            owner_scope="owner-a",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={Backend.CHROMIUM: lambda: backend_a},
            session_lock=_RecordingSessionLock(),
        )
        service_b = BrowserService(
            data_root=self.data_root,
            owner_scope="owner-b",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={Backend.CHROMIUM: lambda: backend_b},
            session_lock=_RecordingSessionLock(),
        )

        await service_a.session_start(project_id="same-project")
        await service_b.session_start(project_id="same-project")

        self.assertNotEqual(backend_a.profile_dir, backend_b.profile_dir)
        self.assertNotIn("owner-a", str(backend_a.profile_dir))
        self.assertNotIn("owner-b", str(backend_b.profile_dir))

    async def test_status_is_a_cached_control_plane_read(self) -> None:
        started = await self.service.session_start(project_id="project-a")
        before = list(self.chromium.calls)

        status = await self.service.session_status(started.session_id)

        self.assertIsInstance(status, SessionStatus)
        self.assertEqual(self.chromium.calls, before)
        self.assertTrue(status.running)
        self.assertEqual(status.state, SessionState.ACTIVE)
        self.assertEqual(status.backend, Backend.CHROMIUM)
        self.assertIsNotNone(status.active_page_id)
        self.assertIsNotNone(status.active_tab_id)
        self.assertIsNotNone(status.page_revision)
        self.assertRegex(status.active_page_id, r"^page_[A-Za-z0-9_-]{16,}$")
        self.assertRegex(status.active_tab_id, r"^tab_[A-Za-z0-9_-]{16,}$")
        self.assertIsInstance(status.page_revision, PageRevision)
        self.assertEqual(
            PageRevision.parse(str(status.page_revision)),
            status.page_revision,
        )
        self.assertGreaterEqual(status.freshness_ms, 0)

    async def test_second_start_fails_without_backend_takeover(self) -> None:
        await self.service.session_start(project_id="project-a")

        with self.assertRaises(TermuinatorError) as caught:
            await self.service.session_start(
                project_id="project-b", backend=Backend.FIREFOX
            )

        self.assertEqual(caught.exception.code, ErrorCode.SESSION_BUSY)
        self.assertEqual(self.chromium.calls, ["start"])
        self.assertEqual(self.firefox.calls, [])

    async def test_explicit_backend_failure_never_falls_back(self) -> None:
        failing_firefox = FakeBackend(
            Backend.FIREFOX, start_error=RuntimeError("native launch failed")
        )
        service = BrowserService(
            data_root=self.data_root,
            owner_scope="test-owner",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={
                Backend.CHROMIUM: lambda: self.chromium,
                Backend.FIREFOX: lambda: failing_firefox,
            },
            session_lock=_RecordingSessionLock(),
        )

        with self.assertRaises(TermuinatorError) as caught:
            await service.session_start(
                project_id="project-a", backend=Backend.FIREFOX
            )

        self.assertEqual(caught.exception.code, ErrorCode.BACKEND_CRASHED)
        self.assertEqual(failing_firefox.calls, ["start"])
        self.assertEqual(self.chromium.calls, [])

        recovered = await service.session_start(project_id="project-a")
        self.assertIsInstance(recovered, SessionStartResult)
        self.assertEqual(recovered.status.backend, Backend.CHROMIUM)

    async def test_wrong_session_cannot_stop_the_active_browser(self) -> None:
        started = await self.service.session_start(project_id="project-a")

        with self.assertRaises(TermuinatorError) as caught:
            await self.service.session_stop("session_wrong")

        self.assertEqual(caught.exception.code, ErrorCode.SESSION_NOT_FOUND)
        self.assertEqual(self.chromium.calls, ["start"])

        stopped = await self.service.session_stop(started.session_id)
        self.assertIsInstance(stopped, SessionStopResult)
        self.assertEqual(stopped.state, SessionState.STOPPED)
        self.assertEqual(stopped.session_id, started.session_id)
        self.assertTrue(stopped.stopped_at.endswith("+00:00"))
        self.assertEqual(self.chromium.calls, ["start", "stop"])

    async def test_empty_project_id_is_rejected_before_filesystem_use(self) -> None:
        with self.assertRaises(TermuinatorError) as caught:
            await self.service.session_start(project_id=" \t")

        self.assertEqual(caught.exception.code, ErrorCode.INVALID_REQUEST)
        self.assertFalse(self.data_root.exists())
        self.assertEqual(self.chromium.calls, [])

    async def test_process_lease_spans_session_and_releases_after_start_failure(self) -> None:
        session_lock = _RecordingSessionLock()
        failing = FakeBackend(
            Backend.CHROMIUM,
            start_error=RuntimeError("launch failed"),
        )
        service = BrowserService(
            data_root=self.data_root,
            owner_scope="test-owner",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={Backend.CHROMIUM: lambda: failing},
            session_lock=session_lock,
        )

        with self.assertRaises(TermuinatorError):
            await service.session_start(project_id="project-a")
        self.assertEqual(session_lock.calls, ["acquire", "release"])

        healthy = FakeBackend(Backend.CHROMIUM)
        recovered = BrowserService(
            data_root=self.data_root,
            owner_scope="test-owner",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={Backend.CHROMIUM: lambda: healthy},
            session_lock=session_lock,
        )
        started = await recovered.session_start(project_id="project-a")
        self.assertEqual(session_lock.calls, ["acquire", "release", "acquire"])
        await recovered.session_stop(started.session_id)
        self.assertEqual(
            session_lock.calls,
            ["acquire", "release", "acquire", "release"],
        )

    async def test_observe_checks_page_context_before_backend_io(self) -> None:
        started = await self.service.session_start(
            project_id="project-a",
            viewport=Viewport(width=1280, height=720),
        )
        status = started.status
        self.assertIsNotNone(status.active_tab_id)
        self.assertIsNotNone(status.active_page_id)
        self.assertIsNotNone(status.page_revision)

        observed = await self.service.observe(
            session_id=started.session_id,
            tab_id=status.active_tab_id,
            page_id=status.active_page_id,
            expected_revision=status.page_revision,
            include_screenshot=False,
            include_accessibility=True,
            text_limit=100,
        )
        self.assertIsInstance(observed, Observation)
        self.assertEqual(observed.session_id, started.session_id)
        self.assertEqual(observed.viewport, Viewport(width=1280, height=720))
        before = list(self.chromium.calls)

        with self.assertRaises(TermuinatorError) as stale:
            await self.service.observe(
                session_id=started.session_id,
                tab_id=status.active_tab_id,
                page_id="page_stale000",
                expected_revision=status.page_revision,
                include_screenshot=False,
                include_accessibility=True,
                text_limit=100,
            )
        self.assertEqual(stale.exception.code, ErrorCode.STALE_OBSERVATION)
        self.assertEqual(self.chromium.calls, before)


if __name__ == "__main__":
    unittest.main()
