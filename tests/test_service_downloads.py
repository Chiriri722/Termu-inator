"""Typed download lifecycle and artifact publication tests."""

from __future__ import annotations

import base64
from pathlib import Path
import tempfile
import unittest

from src.termuinator.backends import BackendDownloadSnapshot, BackendPageSnapshot
from src.termuinator.backends.fake import FakeBackend
from src.termuinator.contracts import (
    Backend,
    Download,
    DownloadsResult,
    ErrorCode,
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


class DownloadContractTests(unittest.TestCase):
    def test_download_result_matches_the_frozen_wire_shape(self) -> None:
        download = Download(
            download_id="download_abcdefgh",
            state="completed",
            filename="report.pdf",
            mime_type="application/pdf",
            size_bytes=4,
            artifact_uri="artifact://sha256/" + "a" * 64,
            reason_code=None,
        )
        result = DownloadsResult(operation="wait", downloads=(download,))

        self.assertEqual(
            set(to_wire(download)),
            {
                "download_id",
                "state",
                "filename",
                "mime_type",
                "size_bytes",
                "artifact_uri",
                "reason_code",
            },
        )
        self.assertEqual(set(to_wire(result)), {"operation", "downloads"})

    def test_wait_result_requires_exactly_one_download(self) -> None:
        for downloads in ((),):
            with self.assertRaises(ValueError):
                DownloadsResult(operation="wait", downloads=downloads)

    def test_backend_snapshot_rejects_paths_and_completed_without_bytes(self) -> None:
        invalid = (
            lambda: BackendDownloadSnapshot(
                backend_download_id="private-download",
                state="started",
                filename="../secret.txt",
            ),
            lambda: BackendDownloadSnapshot(
                backend_download_id="private-download",
                state="completed",
                filename="report.pdf",
                mime_type="application/pdf",
                size_bytes=4,
            ),
        )
        for factory in invalid:
            with self.assertRaises(ValueError):
                factory()


class BrowserServiceDownloadsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.payload = b"%PDF-test-download"
        private_id = "private-download-secret"
        self.backend = FakeBackend(
            Backend.CHROMIUM,
            snapshot=BackendPageSnapshot(
                url="https://example.com/download",
                title="Download",
                ready_state="complete",
                viewport=Viewport(width=1280, height=720),
            ),
            download_sequences={
                private_id: (
                    BackendDownloadSnapshot(
                        backend_download_id=private_id,
                        state="started",
                        filename="report.pdf",
                    ),
                    BackendDownloadSnapshot(
                        backend_download_id=private_id,
                        state="completed",
                        filename="report.pdf",
                        mime_type="application/pdf",
                        size_bytes=len(self.payload),
                        data=self.payload,
                    ),
                )
            },
        )
        self.service = BrowserService(
            data_root=Path(self.temporary.name) / "data",
            owner_scope="transport-owner",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={Backend.CHROMIUM: lambda: self.backend},
            session_lock=_RecordingSessionLock(),
            max_artifact_chunk_bytes=4,
        )

    async def _start(self) -> str:
        started = await self.service.session_start(project_id="project-downloads")
        return started.session_id

    async def test_list_wait_publish_and_reuse_artifact_without_handle_leak(self) -> None:
        session_id = await self._start()

        listed = await self.service.downloads(
            session_id=session_id,
            operation="list",
        )
        self.assertEqual(listed.operation, "list")
        self.assertEqual(len(listed.downloads), 1)
        started = listed.downloads[0]
        self.assertEqual(started.state, "started")
        self.assertIsNone(started.artifact_uri)
        self.assertNotIn("private-download-secret", repr(to_wire(listed)))

        waited = await self.service.downloads(
            session_id=session_id,
            operation="wait",
            download_id=started.download_id,
        )
        completed = waited.downloads[0]
        self.assertEqual(completed.download_id, started.download_id)
        self.assertEqual(completed.state, "completed")
        self.assertEqual(completed.size_bytes, len(self.payload))
        self.assertEqual(completed.mime_type, "application/pdf")
        self.assertIsNotNone(completed.artifact_uri)

        chunks: list[bytes] = []
        offset = 0
        while True:
            chunk = await self.service.artifact_read(
                session_id=session_id,
                uri=completed.artifact_uri,
                offset=offset,
                limit=4,
            )
            chunks.append(base64.b64decode(chunk.data_base64))
            offset = chunk.next_offset
            if chunk.eof:
                break
        self.assertEqual(b"".join(chunks), self.payload)

        relisted = await self.service.downloads(
            session_id=session_id,
            operation="list",
        )
        self.assertEqual(relisted.downloads[0].download_id, started.download_id)
        self.assertEqual(relisted.downloads[0].artifact_uri, completed.artifact_uri)
        self.assertEqual(
            self.backend.download_calls,
            [
                ("list", None),
                ("wait", "private-download-secret"),
                ("list", None),
            ],
        )

    async def test_unknown_public_id_fails_before_backend_dispatch(self) -> None:
        session_id = await self._start()
        await self.service.downloads(session_id=session_id, operation="list")
        before = tuple(self.backend.download_calls)

        with self.assertRaises(TermuinatorError) as invalid:
            await self.service.downloads(
                session_id=session_id,
                operation="wait",
                download_id="download_unknown_abcdefgh",
            )

        self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)
        self.assertEqual(tuple(self.backend.download_calls), before)

    async def test_invalid_union_and_unconfigured_backend_fail_structured(self) -> None:
        session_id = await self._start()
        invalid_cases = (
            {"operation": "list", "download_id": "download_abcdefgh"},
            {"operation": "wait"},
            {"operation": "delete"},
        )
        for values in invalid_cases:
            with self.assertRaises(TermuinatorError) as invalid:
                await self.service.downloads(session_id=session_id, **values)
            self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)
        self.assertEqual(self.backend.download_calls, [])

        backend = FakeBackend(Backend.CHROMIUM)
        service = BrowserService(
            data_root=Path(self.temporary.name) / "unsupported-data",
            owner_scope="transport-owner",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={Backend.CHROMIUM: lambda: backend},
            session_lock=_RecordingSessionLock(),
        )
        started = await service.session_start(project_id="project-no-downloads")
        with self.assertRaises(TermuinatorError) as unsupported:
            await service.downloads(
                session_id=started.session_id,
                operation="list",
            )
        self.assertEqual(
            unsupported.exception.code,
            ErrorCode.UNSUPPORTED_CAPABILITY,
        )

    async def test_completed_download_bytes_are_immutable(self) -> None:
        first = b"first-terminal-payload"
        second = b"other-terminal-payload"
        self.assertEqual(len(first), len(second))
        private_id = "private-download-tampered"
        backend = FakeBackend(
            Backend.CHROMIUM,
            download_sequences={
                private_id: (
                    BackendDownloadSnapshot(
                        backend_download_id=private_id,
                        state="completed",
                        filename="stable.bin",
                        mime_type="application/octet-stream",
                        size_bytes=len(first),
                        data=first,
                    ),
                    BackendDownloadSnapshot(
                        backend_download_id=private_id,
                        state="completed",
                        filename="stable.bin",
                        mime_type="application/octet-stream",
                        size_bytes=len(second),
                        data=second,
                    ),
                )
            },
        )
        service = BrowserService(
            data_root=Path(self.temporary.name) / "tamper-data",
            owner_scope="transport-owner",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={Backend.CHROMIUM: lambda: backend},
            session_lock=_RecordingSessionLock(),
        )
        started = await service.session_start(project_id="project-tamper")
        listed = await service.downloads(
            session_id=started.session_id,
            operation="list",
        )

        with self.assertRaises(TermuinatorError) as tampered:
            await service.downloads(
                session_id=started.session_id,
                operation="wait",
                download_id=listed.downloads[0].download_id,
            )

        self.assertEqual(tampered.exception.code, ErrorCode.INTERNAL_ERROR)


if __name__ == "__main__":
    unittest.main()
