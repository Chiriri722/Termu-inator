"""Tests for typed artifact, trace, and permission core boundaries."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import unittest

from src.termuinator.contracts import (
    ArtifactChunk,
    ErrorCode,
    PageRevision,
    PermissionPolicy,
    RiskClass,
    TraceRecord,
)
from src.termuinator.core.artifacts import InMemoryArtifactStore
from src.termuinator.core.permissions import InMemoryPermissionEngine
from src.termuinator.core.trace import InMemoryTraceRecorder
from src.termuinator.errors import TermuinatorError


class CoreStorageBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
        self.active_sessions = {"session_12345678"}

    def test_artifact_chunks_are_bounded_session_authorized_and_expiring(self) -> None:
        store = InMemoryArtifactStore(
            owner_project_digest="a" * 64,
            authorize_session=lambda value: value in self.active_sessions,
            retention_seconds=60,
            quota_bytes=32,
            max_chunk_bytes=4,
            now=lambda: self.now,
        )
        artifact = store.put(
            session_id="session_12345678",
            data=b"abcdef",
            mime_type="text/plain",
        )

        chunk = store.read(
            session_id="session_12345678",
            uri=artifact.uri,
            offset=1,
            limit=4,
        )
        self.assertIsInstance(chunk, ArtifactChunk)
        self.assertEqual(base64.b64decode(chunk.data_base64), b"bcde")
        self.assertEqual((chunk.offset, chunk.next_offset, chunk.eof), (1, 5, False))

        with self.assertRaises(TermuinatorError) as unauthorized:
            store.read(
                session_id="session_other",
                uri=artifact.uri,
                offset=0,
                limit=1,
            )
        self.assertEqual(unauthorized.exception.code, ErrorCode.OWNERSHIP_DENIED)

        with self.assertRaises(TermuinatorError) as oversized:
            store.read(
                session_id="session_12345678",
                uri=artifact.uri,
                offset=0,
                limit=5,
            )
        self.assertEqual(oversized.exception.code, ErrorCode.INVALID_REQUEST)

        self.now += timedelta(seconds=61)
        with self.assertRaises(TermuinatorError) as expired:
            store.read(
                session_id="session_12345678",
                uri=artifact.uri,
                offset=0,
                limit=1,
            )
        self.assertEqual(expired.exception.code, ErrorCode.ARTIFACT_NOT_FOUND)

    def test_trace_recorder_accepts_only_closed_typed_records(self) -> None:
        recorder = InMemoryTraceRecorder(
            authorize_session=lambda value: value in self.active_sessions,
            max_records=2,
        )
        first = TraceRecord(
            trace_id="trace_12345678",
            step_id="step_12345678",
            action_kind="click",
            risk=RiskClass.R1,
            page_revision=PageRevision("epoch_12345678", 2),
            permission="session_allow",
            verification_passed=True,
            started_at=self.now.isoformat(),
            duration_ms=25,
            diagnostics_id=None,
        )
        recorder.append(session_id="session_12345678", record=first)

        self.assertEqual(
            recorder.list(session_id="session_12345678", limit=10),
            (first,),
        )
        with self.assertRaises(TypeError):
            recorder.append(  # type: ignore[arg-type]
                session_id="session_12345678",
                record={"authorization": "secret"},
            )

    def test_session_permissions_expire_and_origins_are_canonical(self) -> None:
        engine = InMemoryPermissionEngine(
            project_id="project-a",
            now=lambda: self.now,
        )
        self.assertEqual(
            engine.evaluate(
                url="https://Example.COM:443/path?q=1",
                session_id="session_12345678",
            ),
            PermissionPolicy.ASK,
        )

        decision = engine.record(
            origin="https://Example.COM:443/path?q=1",
            policy=PermissionPolicy.SESSION_ALLOW,
            session_id="session_12345678",
        )
        self.assertEqual(decision.origin, "https://example.com")
        self.assertEqual(
            engine.evaluate(
                url="https://example.com/other",
                session_id="session_12345678",
            ),
            PermissionPolicy.SESSION_ALLOW,
        )

        engine.clear_session("session_12345678")
        self.assertEqual(
            engine.evaluate(
                url="https://example.com/other",
                session_id="session_12345678",
            ),
            PermissionPolicy.ASK,
        )
        with self.assertRaises(TermuinatorError) as invalid:
            engine.evaluate(url="file:///tmp/secret", session_id="session_12345678")
        self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)

        idn = engine.record(
            origin="https://bücher.example:443/catalog",
            policy=PermissionPolicy.ALWAYS_ALLOW,
        )
        self.assertEqual(idn.origin, "https://xn--bcher-kva.example")
        self.assertEqual(
            engine.evaluate(
                url="https://xn--bcher-kva.example/checkout",
                session_id="session_12345678",
            ),
            PermissionPolicy.ALWAYS_ALLOW,
        )


if __name__ == "__main__":
    unittest.main()
