"""Durable content-addressed artifact storage tests."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import stat
import tempfile
import unittest

from src.termuinator.contracts import ErrorCode
from src.termuinator.core.durable_artifacts import DurableArtifactStore
from src.termuinator.errors import TermuinatorError


class DurableArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.current = datetime(2026, 8, 24, 18, 0, tzinfo=timezone.utc)

    def _store(
        self,
        root: Path,
        *,
        owner_project_digest: str = "a" * 64,
        quota_bytes: int = 1024,
        retention_seconds: int = 120,
    ) -> DurableArtifactStore:
        return DurableArtifactStore(
            root=root,
            owner_project_digest=owner_project_digest,
            authorize_session=lambda session_id: session_id == "session_artifacts1",
            retention_seconds=retention_seconds,
            quota_bytes=quota_bytes,
            max_chunk_bytes=4,
            now=lambda: self.current,
        )

    def test_restart_safe_range_read_and_private_modes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = self._store(root).put(
                session_id="session_artifacts1",
                data=b"abcdefgh",
                mime_type="text/plain",
            )

            restarted = self._store(root)
            first = restarted.read(
                session_id="session_artifacts1",
                uri=artifact.uri,
                offset=0,
                limit=4,
            )
            second = restarted.read(
                session_id="session_artifacts1",
                uri=artifact.uri,
                offset=first.next_offset,
                limit=4,
            )

            self.assertEqual(base64.b64decode(first.data_base64), b"abcd")
            self.assertFalse(first.eof)
            self.assertEqual(base64.b64decode(second.data_base64), b"efgh")
            self.assertTrue(second.eof)
            files = [path for path in root.rglob("*") if path.is_file()]
            self.assertTrue(any(path.suffix == ".bin" for path in files))
            self.assertTrue(any(path.suffix == ".json" for path in files))
            self.assertTrue(
                all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in files)
            )
            directories = [path for path in root.rglob("*") if path.is_dir()]
            self.assertTrue(
                all(stat.S_IMODE(path.stat().st_mode) == 0o700 for path in directories)
            )

    def test_uri_is_not_authority_across_session_or_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = self._store(root).put(
                session_id="session_artifacts1",
                data=b"private",
                mime_type="application/octet-stream",
            )

            with self.assertRaises(TermuinatorError) as owner:
                self._store(root).read(
                    session_id="session_other000",
                    uri=artifact.uri,
                    offset=0,
                    limit=4,
                )
            self.assertEqual(owner.exception.code, ErrorCode.OWNERSHIP_DENIED)

            with self.assertRaises(TermuinatorError) as project:
                self._store(root, owner_project_digest="b" * 64).read(
                    session_id="session_artifacts1",
                    uri=artifact.uri,
                    offset=0,
                    limit=4,
                )
            self.assertEqual(project.exception.code, ErrorCode.ARTIFACT_NOT_FOUND)

    def test_expiry_and_lru_quota_remove_only_inactive_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root, quota_bytes=6)
            first = store.put(
                session_id="session_artifacts1",
                data=b"aaa",
                mime_type="text/plain",
            )
            self.current += timedelta(seconds=1)
            second = store.put(
                session_id="session_artifacts1",
                data=b"bbb",
                mime_type="text/plain",
            )
            self.current += timedelta(seconds=1)
            store.read(
                session_id="session_artifacts1",
                uri=first.uri,
                offset=0,
                limit=1,
            )
            self.current += timedelta(seconds=1)
            third = store.put(
                session_id="session_artifacts1",
                data=b"ccc",
                mime_type="text/plain",
            )

            store.read(
                session_id="session_artifacts1",
                uri=first.uri,
                offset=0,
                limit=1,
            )
            store.read(
                session_id="session_artifacts1",
                uri=third.uri,
                offset=0,
                limit=1,
            )
            with self.assertRaises(TermuinatorError) as evicted:
                store.read(
                    session_id="session_artifacts1",
                    uri=second.uri,
                    offset=0,
                    limit=1,
                )
            self.assertEqual(evicted.exception.code, ErrorCode.ARTIFACT_NOT_FOUND)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root, retention_seconds=2)
            artifact = store.put(
                session_id="session_artifacts1",
                data=b"expires",
                mime_type="text/plain",
            )
            self.current += timedelta(seconds=3)

            with self.assertRaises(TermuinatorError) as expired:
                store.read(
                    session_id="session_artifacts1",
                    uri=artifact.uri,
                    offset=0,
                    limit=1,
                )

            self.assertEqual(expired.exception.code, ErrorCode.ARTIFACT_NOT_FOUND)
            self.assertFalse(any(path.suffix == ".bin" for path in root.rglob("*")))

    def test_tampered_or_symlinked_content_fails_before_bytes_return(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root)
            artifact = store.put(
                session_id="session_artifacts1",
                data=b"original",
                mime_type="text/plain",
            )
            data_path = next(root.rglob("*.bin"))
            data_path.write_bytes(b"tampered")

            with self.assertRaises(TermuinatorError) as tampered:
                store.read(
                    session_id="session_artifacts1",
                    uri=artifact.uri,
                    offset=0,
                    limit=4,
                )
            self.assertEqual(tampered.exception.code, ErrorCode.INTERNAL_ERROR)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root)
            artifact = store.put(
                session_id="session_artifacts1",
                data=b"original",
                mime_type="text/plain",
            )
            data_path = next(root.rglob("*.bin"))
            victim = root / "victim.bin"
            victim.write_bytes(b"victim")
            data_path.unlink()
            os.symlink(victim, data_path)

            with self.assertRaises(TermuinatorError) as unsafe:
                store.read(
                    session_id="session_artifacts1",
                    uri=artifact.uri,
                    offset=0,
                    limit=4,
                )
            self.assertEqual(unsafe.exception.code, ErrorCode.INTERNAL_ERROR)
            self.assertEqual(victim.read_bytes(), b"victim")


if __name__ == "__main__":
    unittest.main()
