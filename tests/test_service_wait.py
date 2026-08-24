"""Typed browser wait contracts and backend-neutral service polling."""

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import time
import unittest

from src.termuinator.backends import (
    BackendDownloadSnapshot,
    BackendDownloadsResult,
    BackendPageSnapshot,
    RawInteractiveElement,
)
from src.termuinator.backends.fake import FakeBackend
from src.termuinator.contracts import (
    Backend,
    Bounds,
    Download,
    ErrorCode,
    PageRevision,
    Viewport,
    WaitDownloadCondition,
    WaitNavigationCondition,
    WaitRefStateCondition,
    WaitResult,
    WaitTextCondition,
    WaitUrlCondition,
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


class _SequenceBackend(FakeBackend):
    def __init__(self, snapshots: tuple[BackendPageSnapshot, ...]) -> None:
        if not snapshots:
            raise ValueError("sequence backend requires at least one snapshot")
        super().__init__(Backend.CHROMIUM, snapshot=snapshots[0])
        self._sequence = list(snapshots)

    async def observe(
        self,
        *,
        include_screenshot: bool,
        include_accessibility: bool,
        text_limit: int,
    ) -> BackendPageSnapshot:
        if self._sequence:
            self._snapshot = self._sequence.pop(0)
        return await super().observe(
            include_screenshot=include_screenshot,
            include_accessibility=include_accessibility,
            text_limit=text_limit,
        )


class _SlowSequenceBackend(_SequenceBackend):
    async def observe(
        self,
        *,
        include_screenshot: bool,
        include_accessibility: bool,
        text_limit: int,
    ) -> BackendPageSnapshot:
        if self.calls.count("observe") >= 1:
            await asyncio.sleep(0.05)
        return await super().observe(
            include_screenshot=include_screenshot,
            include_accessibility=include_accessibility,
            text_limit=text_limit,
        )


class _SlowDownloadBackend(FakeBackend):
    async def downloads(
        self,
        operation: str,
        backend_download_id: str | None = None,
    ) -> BackendDownloadsResult:
        if operation == "wait":
            await asyncio.sleep(0.05)
        return await super().downloads(operation, backend_download_id)


class WaitContractTests(unittest.TestCase):
    def test_condition_union_and_result_match_frozen_wire_shapes(self) -> None:
        revision = PageRevision("epoch_wait", 2)
        conditions = (
            (
                WaitUrlCondition(kind="url", url="https://example.com/ready"),
                {"kind", "url"},
            ),
            (
                WaitTextCondition(kind="text", text="ready", present=False),
                {"kind", "text", "present"},
            ),
            (
                WaitRefStateCondition(
                    kind="ref_state",
                    target_ref="ref_abcdefghijklmnop",
                    state="visible",
                ),
                {"kind", "target_ref", "state"},
            ),
            (
                WaitNavigationCondition(
                    kind="navigation",
                    from_revision=revision,
                ),
                {"kind", "from_revision"},
            ),
            (
                WaitDownloadCondition(
                    kind="download",
                    download_id="download_abcdefgh",
                ),
                {"kind", "download_id"},
            ),
        )
        for condition, expected_fields in conditions:
            self.assertEqual(set(to_wire(condition)), expected_fields)

        download = Download(
            download_id="download_abcdefgh",
            state="completed",
            filename="report.pdf",
            mime_type="application/pdf",
            size_bytes=42,
            artifact_uri="artifact://sha256/" + "a" * 64,
            reason_code=None,
        )
        result = WaitResult(
            condition_kind="download",
            satisfied=True,
            elapsed_ms=12,
            observation=None,
            download=download,
        )
        self.assertEqual(
            set(to_wire(result)),
            {"condition_kind", "satisfied", "elapsed_ms", "observation", "download"},
        )

    def test_condition_models_reject_wrong_discriminators_and_values(self) -> None:
        invalid_factories = (
            lambda: WaitUrlCondition(kind="text", url="https://example.com"),
            lambda: WaitUrlCondition(kind="url", url="javascript:alert(1)"),
            lambda: WaitTextCondition(kind="text", text="", present=True),
            lambda: WaitTextCondition(kind="text", text="ok", present=1),
            lambda: WaitRefStateCondition(
                kind="ref_state",
                target_ref="selector:#submit",
                state="visible",
            ),
            lambda: WaitRefStateCondition(
                kind="ref_state",
                target_ref="ref_abcdefghijklmnop",
                state="focused",
            ),
            lambda: WaitNavigationCondition(
                kind="navigation",
                from_revision="epoch_wait:2",
            ),
            lambda: WaitDownloadCondition(kind="download", download_id="short"),
        )
        for factory in invalid_factories:
            with self.assertRaises(ValueError):
                factory()


class BrowserServiceWaitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.viewport = Viewport(width=1280, height=720)
        self._service_index = 0

    @staticmethod
    def _snapshot(
        *,
        url: str = "https://example.com/wait",
        text: str = "loading",
        visible: bool = False,
        enabled: bool = True,
    ) -> BackendPageSnapshot:
        return BackendPageSnapshot(
            url=url,
            title="Wait fixture",
            ready_state="complete",
            viewport=Viewport(width=1280, height=720),
            text=text,
            interactive_elements=(
                RawInteractiveElement(
                    backend_node_id="node-wait-target",
                    role="button",
                    accessible_name="Continue",
                    tag="button",
                    type="button",
                    bounds=Bounds(x=10, y=20, width=120, height=40),
                    visible=visible,
                    enabled=enabled,
                ),
            ),
        )

    def _service(
        self,
        snapshots: tuple[BackendPageSnapshot, ...],
        *,
        backend_type: type[_SequenceBackend] = _SequenceBackend,
    ) -> tuple[BrowserService, _SequenceBackend]:
        self._service_index += 1
        backend = backend_type(snapshots)
        service = BrowserService(
            data_root=(
                Path(self.temporary.name) / f"data-{self._service_index}"
            ),
            owner_scope="transport-owner",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={Backend.CHROMIUM: lambda: backend},
            session_lock=_RecordingSessionLock(),
        )
        return service, backend

    async def _start_and_observe(
        self,
        service: BrowserService,
    ) -> tuple[str, object]:
        started = await service.session_start(
            project_id="project-wait",
            viewport=self.viewport,
        )
        status = started.status
        observation = await service.observe(
            session_id=started.session_id,
            tab_id=status.active_tab_id,
            page_id=status.active_page_id,
            expected_revision=status.page_revision,
            include_screenshot=False,
            include_accessibility=False,
            text_limit=100_000,
        )
        return started.session_id, observation

    async def test_text_and_ref_state_waits_use_fresh_observations(self) -> None:
        before = self._snapshot(text="loading", visible=False)
        after = self._snapshot(text="ready", visible=True)

        text_service, text_backend = self._service((before, after))
        text_session, text_observation = await self._start_and_observe(text_service)
        text_result = await text_service.wait(
            session_id=text_session,
            tab_id=text_observation.tab_id,
            page_id=text_observation.page_id,
            expected_revision=text_observation.page_revision,
            condition=WaitTextCondition(kind="text", text="ready", present=True),
            timeout_ms=100,
        )
        self.assertTrue(text_result.satisfied)
        self.assertEqual(text_result.condition_kind, "text")
        self.assertEqual(text_result.observation.text, "ready")
        self.assertEqual(text_backend.calls.count("observe"), 2)

        ref_service, _ref_backend = self._service((before, after))
        ref_session, ref_observation = await self._start_and_observe(ref_service)
        target_ref = ref_observation.interactive_elements[0].ref
        ref_result = await ref_service.wait(
            session_id=ref_session,
            tab_id=ref_observation.tab_id,
            page_id=ref_observation.page_id,
            expected_revision=ref_observation.page_revision,
            condition=WaitRefStateCondition(
                kind="ref_state",
                target_ref=target_ref,
                state="visible",
            ),
            timeout_ms=100,
        )
        self.assertTrue(ref_result.satisfied)
        self.assertEqual(ref_result.observation.interactive_elements[0].ref, target_ref)

    async def test_url_and_navigation_waits_rotate_document_identity(self) -> None:
        before = self._snapshot(url="https://example.com/start")
        after = self._snapshot(url="https://example.com/ready", text="ready")

        navigation_service, _backend = self._service((before, after))
        session_id, observation = await self._start_and_observe(navigation_service)
        navigation = await navigation_service.wait(
            session_id=session_id,
            tab_id=observation.tab_id,
            page_id=observation.page_id,
            expected_revision=observation.page_revision,
            condition=WaitNavigationCondition(
                kind="navigation",
                from_revision=observation.page_revision,
            ),
            timeout_ms=100,
        )
        self.assertTrue(navigation.satisfied)
        self.assertNotEqual(navigation.observation.page_id, observation.page_id)
        self.assertNotEqual(
            navigation.observation.page_revision,
            observation.page_revision,
        )

        url_service, _backend = self._service((before, after))
        url_session, url_observation = await self._start_and_observe(url_service)
        url_result = await url_service.wait(
            session_id=url_session,
            tab_id=url_observation.tab_id,
            page_id=url_observation.page_id,
            expected_revision=url_observation.page_revision,
            condition=WaitUrlCondition(
                kind="url",
                url="https://example.com/ready",
            ),
            timeout_ms=100,
        )
        self.assertTrue(url_result.satisfied)
        self.assertEqual(url_result.observation.url, "https://example.com/ready")

    async def test_timeout_returns_unsatisfied_last_observation(self) -> None:
        service, backend = self._service((self._snapshot(),))
        session_id, observation = await self._start_and_observe(service)

        result = await service.wait(
            session_id=session_id,
            tab_id=observation.tab_id,
            page_id=observation.page_id,
            expected_revision=observation.page_revision,
            condition=WaitTextCondition(
                kind="text",
                text="never appears",
                present=True,
            ),
            timeout_ms=1,
        )

        self.assertFalse(result.satisfied)
        self.assertEqual(result.condition_kind, "text")
        self.assertIsNotNone(result.observation)
        self.assertLessEqual(result.elapsed_ms, 120_000)
        self.assertGreaterEqual(backend.calls.count("observe"), 2)

    async def test_timeout_cancels_a_slow_async_backend_observation(self) -> None:
        service, backend = self._service(
            (self._snapshot(),),
            backend_type=_SlowSequenceBackend,
        )
        session_id, observation = await self._start_and_observe(service)

        started = time.monotonic()
        result = await service.wait(
            session_id=session_id,
            tab_id=observation.tab_id,
            page_id=observation.page_id,
            expected_revision=observation.page_revision,
            condition=WaitTextCondition(
                kind="text",
                text="never appears",
                present=True,
            ),
            timeout_ms=1,
        )
        wall_ms = (time.monotonic() - started) * 1_000

        self.assertFalse(result.satisfied)
        self.assertLess(wall_ms, 30)
        self.assertEqual(backend.calls.count("observe"), 1)

    async def test_download_wait_uses_typed_lifecycle_without_page_polling(self) -> None:
        private_id = "private-download-wait"
        payload = b"download-wait-payload"
        backend = FakeBackend(
            Backend.CHROMIUM,
            snapshot=self._snapshot(),
            download_sequences={
                private_id: (
                    BackendDownloadSnapshot(
                        backend_download_id=private_id,
                        state="started",
                        filename="wait.txt",
                    ),
                    BackendDownloadSnapshot(
                        backend_download_id=private_id,
                        state="completed",
                        filename="wait.txt",
                        mime_type="text/plain",
                        size_bytes=len(payload),
                        data=payload,
                    ),
                )
            },
        )
        service = BrowserService(
            data_root=Path(self.temporary.name) / "download-wait-data",
            owner_scope="transport-owner",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={Backend.CHROMIUM: lambda: backend},
            session_lock=_RecordingSessionLock(),
        )
        session_id, observation = await self._start_and_observe(service)
        listed = await service.downloads(
            session_id=session_id,
            operation="list",
        )
        public_id = listed.downloads[0].download_id

        result = await service.wait(
            session_id=session_id,
            tab_id=observation.tab_id,
            page_id=observation.page_id,
            expected_revision=observation.page_revision,
            condition=WaitDownloadCondition(
                kind="download",
                download_id=public_id,
            ),
            timeout_ms=100,
        )

        self.assertTrue(result.satisfied)
        self.assertIsNone(result.observation)
        self.assertIsNotNone(result.download)
        assert result.download is not None
        self.assertEqual(result.download.download_id, public_id)
        self.assertEqual(result.download.state, "completed")
        self.assertEqual(backend.calls.count("observe"), 1)
        self.assertEqual(
            backend.download_calls,
            [("list", None), ("wait", private_id)],
        )

    async def test_download_wait_cancels_a_slow_backend_at_the_deadline(self) -> None:
        private_id = "private-download-slow"
        payload = b"eventual"
        backend = _SlowDownloadBackend(
            Backend.CHROMIUM,
            snapshot=self._snapshot(),
            download_sequences={
                private_id: (
                    BackendDownloadSnapshot(
                        backend_download_id=private_id,
                        state="started",
                        filename="slow.txt",
                    ),
                    BackendDownloadSnapshot(
                        backend_download_id=private_id,
                        state="completed",
                        filename="slow.txt",
                        mime_type="text/plain",
                        size_bytes=len(payload),
                        data=payload,
                    ),
                )
            },
        )
        service = BrowserService(
            data_root=Path(self.temporary.name) / "slow-download-data",
            owner_scope="transport-owner",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={Backend.CHROMIUM: lambda: backend},
            session_lock=_RecordingSessionLock(),
        )
        session_id, observation = await self._start_and_observe(service)
        listed = await service.downloads(
            session_id=session_id,
            operation="list",
        )

        started = time.monotonic()
        result = await service.wait(
            session_id=session_id,
            tab_id=observation.tab_id,
            page_id=observation.page_id,
            expected_revision=observation.page_revision,
            condition=WaitDownloadCondition(
                kind="download",
                download_id=listed.downloads[0].download_id,
            ),
            timeout_ms=1,
        )
        wall_ms = (time.monotonic() - started) * 1_000

        self.assertFalse(result.satisfied)
        self.assertLess(wall_ms, 30)
        self.assertIsNotNone(result.download)
        assert result.download is not None
        self.assertEqual(result.download.state, "started")
        self.assertEqual(backend.download_calls, [("list", None)])
        self.assertEqual(backend.calls.count("observe"), 1)


if __name__ == "__main__":
    unittest.main()
