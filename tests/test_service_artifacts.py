"""Screenshot publication and remote artifact read service tests."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import tempfile
import unittest

from src.termuinator.backends import (
    BackendArtifactPayload,
    BackendPageSnapshot,
    RawInteractiveElement,
)
from src.termuinator.backends.fake import FakeBackend
from src.termuinator.contracts import Backend, ErrorCode, PageRevision, Viewport
from src.termuinator.core.service import BrowserService
from src.termuinator.errors import TermuinatorError


class _SessionLock:
    def __init__(self) -> None:
        self.held = False

    def acquire(self) -> None:
        self.held = True

    def release(self) -> None:
        self.held = False


class BrowserServiceArtifactTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.viewport = Viewport(width=1280, height=720)

    def _service(
        self,
        screenshot: BackendArtifactPayload | None,
        *,
        interactive_elements: tuple[RawInteractiveElement, ...] = (),
    ) -> BrowserService:
        snapshot = BackendPageSnapshot(
            url="https://example.com",
            title="Example",
            ready_state="complete",
            viewport=self.viewport,
            interactive_elements=interactive_elements,
            screenshot=screenshot,
        )
        backend = FakeBackend(Backend.CHROMIUM, snapshot=snapshot)
        return BrowserService(
            data_root=Path(self.temporary.name) / "data",
            owner_scope="artifact-owner",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={Backend.CHROMIUM: lambda: backend},
            session_lock=_SessionLock(),
            artifact_retention_seconds=120,
            artifact_quota_bytes=1024,
            max_artifact_chunk_bytes=4,
        )

    async def test_observation_screenshot_is_published_and_chunk_readable(self) -> None:
        png = b"\x89PNG\r\n\x1a\nimage-bytes"
        service = self._service(
            BackendArtifactPayload(data=png, mime_type="image/png")
        )
        started = await service.session_start(
            project_id="project-artifacts",
            viewport=self.viewport,
        )
        status = started.status

        observation = await service.observe(
            session_id=started.session_id,
            tab_id=status.active_tab_id,
            page_id=status.active_page_id,
            expected_revision=PageRevision.parse(str(status.page_revision)),
            include_screenshot=True,
            include_accessibility=False,
            text_limit=100,
        )

        self.assertIsNotNone(observation.screenshot_artifact_uri)
        chunks: list[bytes] = []
        offset = 0
        while True:
            chunk = await service.artifact_read(
                session_id=started.session_id,
                uri=observation.screenshot_artifact_uri,
                offset=offset,
                limit=4,
            )
            chunks.append(base64.b64decode(chunk.data_base64))
            offset = chunk.next_offset
            if chunk.eof:
                break
        self.assertEqual(b"".join(chunks), png)

    async def test_requested_screenshot_without_backend_payload_fails_explicitly(self) -> None:
        service = self._service(None)
        started = await service.session_start(
            project_id="project-artifacts",
            viewport=self.viewport,
        )
        status = started.status

        with self.assertRaises(TermuinatorError) as unsupported:
            await service.observe(
                session_id=started.session_id,
                tab_id=status.active_tab_id,
                page_id=status.active_page_id,
                expected_revision=PageRevision.parse(str(status.page_revision)),
                include_screenshot=True,
                include_accessibility=False,
                text_limit=100,
            )

        self.assertEqual(
            unsupported.exception.code,
            ErrorCode.UNSUPPORTED_CAPABILITY,
        )

    async def test_standalone_png_screenshot_returns_complete_metadata(self) -> None:
        png = b"\x89PNG\r\n\x1a\nstandalone-image"
        service = self._service(
            BackendArtifactPayload(data=png, mime_type="image/png")
        )
        started = await service.session_start(
            project_id="project-artifacts",
            viewport=self.viewport,
        )
        status = started.status

        artifact = await service.screenshot(
            session_id=started.session_id,
            tab_id=status.active_tab_id,
            page_id=status.active_page_id,
            expected_revision=PageRevision.parse(str(status.page_revision)),
            mode="viewport",
        )

        digest = hashlib.sha256(png).hexdigest()
        self.assertEqual(artifact.uri, f"artifact://sha256/{digest}")
        self.assertEqual(artifact.sha256, digest)
        self.assertEqual(artifact.size_bytes, len(png))
        self.assertEqual(artifact.mime_type, "image/png")
        self.assertGreater(artifact.expires_at, artifact.created_at)

    async def test_element_webp_resolves_private_handle_and_rejects_bad_union(self) -> None:
        webp = b"RIFF\x04\x00\x00\x00WEBPdata"
        service = self._service(
            BackendArtifactPayload(data=webp, mime_type="image/webp"),
            interactive_elements=(
                RawInteractiveElement(
                    backend_node_id="private-node-1",
                    role="button",
                    accessible_name="Preview",
                ),
            ),
        )
        started = await service.session_start(
            project_id="project-artifacts",
            viewport=self.viewport,
        )
        status = started.status
        revision = PageRevision.parse(str(status.page_revision))
        observation = await service.observe(
            session_id=started.session_id,
            tab_id=status.active_tab_id,
            page_id=status.active_page_id,
            expected_revision=revision,
            include_screenshot=False,
            include_accessibility=False,
            text_limit=100,
        )
        target_ref = observation.interactive_elements[0].ref

        artifact = await service.screenshot(
            session_id=started.session_id,
            tab_id=observation.tab_id,
            page_id=observation.page_id,
            expected_revision=observation.page_revision,
            mode="element",
            target_ref=target_ref,
        )

        self.assertEqual(artifact.mime_type, "image/webp")
        backend = service._active.backend
        self.assertEqual(
            backend.screenshot_calls,
            [("element", "private-node-1")],
        )

        with self.assertRaises(TermuinatorError) as invalid_full:
            await service.screenshot(
                session_id=started.session_id,
                tab_id=observation.tab_id,
                page_id=observation.page_id,
                expected_revision=observation.page_revision,
                mode="full",
                target_ref=target_ref,
            )
        self.assertEqual(invalid_full.exception.code, ErrorCode.INVALID_REQUEST)

        with self.assertRaises(TermuinatorError) as missing_element:
            await service.screenshot(
                session_id=started.session_id,
                tab_id=observation.tab_id,
                page_id=observation.page_id,
                expected_revision=observation.page_revision,
                mode="element",
            )
        self.assertEqual(missing_element.exception.code, ErrorCode.INVALID_REQUEST)

    async def test_screenshot_rejects_stale_context_before_backend_io(self) -> None:
        service = self._service(
            BackendArtifactPayload(
                data=b"\x89PNG\r\n\x1a\nstale",
                mime_type="image/png",
            )
        )
        started = await service.session_start(
            project_id="project-artifacts",
            viewport=self.viewport,
        )
        status = started.status

        with self.assertRaises(TermuinatorError) as stale:
            await service.screenshot(
                session_id=started.session_id,
                tab_id=status.active_tab_id,
                page_id=status.active_page_id,
                expected_revision=PageRevision("epoch_stale-context", 0),
                mode="viewport",
            )

        self.assertEqual(stale.exception.code, ErrorCode.STALE_OBSERVATION)
        backend = service._active.backend
        self.assertEqual(backend.screenshot_calls, [])


if __name__ == "__main__":
    unittest.main()
