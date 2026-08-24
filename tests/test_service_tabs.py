"""Typed tab lifecycle with service-owned public page identities."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.termuinator.backends.fake import FakeBackend
from src.termuinator.backends import BackendPageSnapshot
from src.termuinator.contracts import (
    Backend,
    ErrorCode,
    PageRevision,
    Tab,
    TabsResult,
    Viewport,
    to_wire,
)
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


class TabContractTests(unittest.TestCase):
    def test_tab_result_matches_the_frozen_wire_shape(self) -> None:
        tab = Tab(
            tab_id="tab_abcdefgh",
            page_id="page_abcdefgh",
            url="https://example.com/",
            title="Example",
            active=True,
            page_revision=PageRevision("epoch_tabs", 1),
        )
        result = TabsResult(
            operation="list",
            tabs=(tab,),
            active_tab_id=tab.tab_id,
            observation=None,
        )

        self.assertEqual(
            set(to_wire(tab)),
            {"tab_id", "page_id", "url", "title", "active", "page_revision"},
        )
        self.assertEqual(
            set(to_wire(result)),
            {"operation", "tabs", "active_tab_id", "observation"},
        )

    def test_tab_result_rejects_ambiguous_active_identity(self) -> None:
        tab = Tab(
            tab_id="tab_abcdefgh",
            page_id="page_abcdefgh",
            url="about:blank",
            title="",
            active=False,
            page_revision=PageRevision("epoch_tabs", 0),
        )
        with self.assertRaises(ValueError):
            TabsResult(
                operation="list",
                tabs=(tab,),
                active_tab_id=tab.tab_id,
                observation=None,
            )


class BrowserServiceTabsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.backend = FakeBackend(
            Backend.CHROMIUM,
            snapshot=BackendPageSnapshot(
                url="https://example.com/start",
                title="Start",
                ready_state="complete",
                viewport=Viewport(width=1280, height=720),
                text="initial tab",
            ),
            tabs_supported=True,
        )
        self.service = BrowserService(
            data_root=Path(self.temporary.name) / "data",
            owner_scope="transport-owner",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={Backend.CHROMIUM: lambda: self.backend},
            session_lock=_RecordingSessionLock(),
        )

    async def _start_and_observe(self) -> tuple[str, object]:
        started = await self.service.session_start(
            project_id="project-tabs",
            viewport=Viewport(width=1280, height=720),
        )
        status = started.status
        assert status.active_tab_id is not None
        assert status.active_page_id is not None
        assert status.page_revision is not None
        observation = await self.service.observe(
            session_id=started.session_id,
            tab_id=status.active_tab_id,
            page_id=status.active_page_id,
            expected_revision=status.page_revision,
            include_screenshot=False,
            include_accessibility=False,
            text_limit=1_000,
        )
        return started.session_id, observation

    async def test_list_open_switch_close_preserve_private_backend_handles(self) -> None:
        session_id, initial = await self._start_and_observe()

        listed = await self.service.tabs(
            session_id=session_id,
            operation="list",
        )
        self.assertEqual(len(listed.tabs), 1)
        self.assertEqual(listed.active_tab_id, initial.tab_id)
        self.assertEqual(listed.tabs[0].page_id, initial.page_id)
        self.assertEqual(listed.tabs[0].page_revision, initial.page_revision)
        self.assertNotIn("backend-tab", repr(to_wire(listed)))

        opened = await self.service.tabs(
            session_id=session_id,
            operation="open",
            url="https://example.com/second",
        )
        self.assertEqual(opened.operation, "open")
        self.assertEqual(len(opened.tabs), 2)
        self.assertNotEqual(opened.active_tab_id, initial.tab_id)
        self.assertIsNotNone(opened.observation)
        assert opened.observation is not None
        second_tab_id = opened.active_tab_id
        self.assertEqual(opened.observation.tab_id, second_tab_id)
        self.assertEqual(opened.observation.url, "https://example.com/second")

        with self.assertRaises(TermuinatorError) as inactive:
            await self.service.observe(
                session_id=session_id,
                tab_id=initial.tab_id,
                page_id=initial.page_id,
                expected_revision=initial.page_revision,
                include_screenshot=False,
                include_accessibility=False,
                text_limit=100,
            )
        self.assertEqual(inactive.exception.code, ErrorCode.STALE_OBSERVATION)

        switched = await self.service.tabs(
            session_id=session_id,
            operation="switch",
            tab_id=initial.tab_id,
        )
        self.assertEqual(switched.active_tab_id, initial.tab_id)
        self.assertIsNotNone(switched.observation)
        assert switched.observation is not None
        self.assertEqual(switched.observation.page_id, initial.page_id)

        assert second_tab_id is not None
        closed = await self.service.tabs(
            session_id=session_id,
            operation="close",
            tab_id=second_tab_id,
        )
        self.assertEqual(closed.operation, "close")
        self.assertEqual(tuple(tab.tab_id for tab in closed.tabs), (initial.tab_id,))
        self.assertEqual(closed.active_tab_id, initial.tab_id)

    async def test_unknown_tab_last_close_and_invalid_open_fail_before_dispatch(self) -> None:
        session_id, initial = await self._start_and_observe()
        await self.service.tabs(session_id=session_id, operation="list")
        baseline_calls = len(self.backend.tab_calls)

        invalid_cases = (
            {"operation": "switch", "tab_id": "tab_unknown_abcdefgh"},
            {"operation": "close", "tab_id": initial.tab_id},
            {"operation": "open", "url": "javascript:alert(1)"},
        )
        for case in invalid_cases:
            with self.assertRaises(TermuinatorError) as invalid:
                await self.service.tabs(session_id=session_id, **case)
            self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)

        self.assertEqual(len(self.backend.tab_calls), baseline_calls)

    async def test_popup_inventory_is_discovered_as_a_new_public_tab(self) -> None:
        session_id, initial = await self._start_and_observe()
        await self.service.tabs(session_id=session_id, operation="list")
        private_handle = self.backend.inject_popup(
            BackendPageSnapshot(
                url="https://example.com/oauth/callback",
                title="OAuth consent",
                ready_state="complete",
                viewport=Viewport(width=1280, height=720),
                text="Consent",
            )
        )

        discovered = await self.service.tabs(
            session_id=session_id,
            operation="list",
        )
        self.assertEqual(len(discovered.tabs), 2)
        self.assertNotEqual(discovered.active_tab_id, initial.tab_id)
        self.assertNotIn(private_handle, repr(to_wire(discovered)))
        active = next(tab for tab in discovered.tabs if tab.active)
        observation = await self.service.observe(
            session_id=session_id,
            tab_id=active.tab_id,
            page_id=active.page_id,
            expected_revision=active.page_revision,
            include_screenshot=False,
            include_accessibility=False,
            text_limit=1_000,
        )
        self.assertEqual(observation.url, "https://example.com/oauth/callback")
        self.assertEqual(observation.tab_id, active.tab_id)

    async def test_unconfigured_backend_is_explicitly_unsupported(self) -> None:
        backend = FakeBackend(Backend.CHROMIUM)
        service = BrowserService(
            data_root=Path(self.temporary.name) / "unsupported-data",
            owner_scope="transport-owner",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={Backend.CHROMIUM: lambda: backend},
            session_lock=_RecordingSessionLock(),
        )
        started = await service.session_start(project_id="project-no-tabs")

        with self.assertRaises(TermuinatorError) as unsupported:
            await service.tabs(
                session_id=started.session_id,
                operation="list",
            )
        self.assertEqual(
            unsupported.exception.code,
            ErrorCode.UNSUPPORTED_CAPABILITY,
        )


if __name__ == "__main__":
    unittest.main()
