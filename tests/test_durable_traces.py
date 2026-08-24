"""Durable, project-scoped, secret-free action trace storage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import stat
import tempfile
import unittest

from src.termuinator.contracts import ErrorCode, PageRevision, RiskClass, TraceRecord
from src.termuinator.core.durable_traces import DurableTraceRecorder
from src.termuinator.errors import TermuinatorError


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class DurableTraceRecorderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "state"
        self.root.mkdir(mode=0o700)
        self.clock = _Clock()
        self.active_sessions = {"session_trace1"}

    def _store(
        self,
        *,
        digest: str = "a" * 64,
        retention_seconds: int = 60,
        quota_bytes: int = 1024 * 1024,
    ) -> DurableTraceRecorder:
        return DurableTraceRecorder(
            root=self.root,
            owner_project_digest=digest,
            authorize_session=lambda value: value in self.active_sessions,
            retention_seconds=retention_seconds,
            quota_bytes=quota_bytes,
            now=self.clock,
        )

    def _record(
        self,
        suffix: str,
        *,
        action_kind: str = "click",
        diagnostics_id: str | None = None,
    ) -> TraceRecord:
        return TraceRecord(
            trace_id=f"trace_abcdefgh{suffix}",
            step_id=f"step_abcdefgh{suffix}",
            action_kind=action_kind,
            risk=RiskClass.R1,
            page_revision=PageRevision("epoch_trace", int(suffix)),
            permission="session_allow",
            verification_passed=True,
            started_at=self.clock().isoformat(),
            duration_ms=15,
            diagnostics_id=diagnostics_id,
        )

    def test_restart_safe_list_get_and_private_modes(self) -> None:
        store = self._store()
        first = self._record("1")
        second = self._record("2")
        store.append(session_id="session_trace1", record=first)
        store.append(session_id="session_trace1", record=second)
        store.append(session_id="session_trace1", record=second)

        restarted = self._store()
        records, truncated = restarted.list_page(
            session_id="session_trace1",
            limit=1,
        )

        self.assertEqual(records, (second,))
        self.assertTrue(truncated)
        self.assertEqual(
            restarted.get(
                session_id="session_trace1",
                trace_id=first.trace_id,
            ),
            first,
        )
        directory = self.root / "traces" / ("a" * 64)
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        for path in directory.iterdir():
            self.assertEqual(stat.S_IMODE(path.lstat().st_mode), 0o600)

    def test_trace_id_conflict_and_authority_fail_closed(self) -> None:
        store = self._store()
        record = self._record("1")
        store.append(session_id="session_trace1", record=record)

        with self.assertRaises(TermuinatorError) as conflict:
            store.append(
                session_id="session_trace1",
                record=self._record("1", action_kind="type"),
            )
        self.assertEqual(conflict.exception.code, ErrorCode.INTERNAL_ERROR)

        with self.assertRaises(TermuinatorError) as wrong_session:
            store.list_page(session_id="session_wrong1", limit=1000)
        self.assertEqual(wrong_session.exception.code, ErrorCode.OWNERSHIP_DENIED)

        isolated = self._store(digest="b" * 64)
        with self.assertRaises(TermuinatorError) as other_project:
            isolated.get(
                session_id="session_trace1",
                trace_id=record.trace_id,
            )
        self.assertEqual(other_project.exception.code, ErrorCode.TARGET_NOT_FOUND)

    def test_retention_and_quota_remove_oldest_records(self) -> None:
        expiring = self._store(retention_seconds=10)
        expired = self._record("1")
        expiring.append(session_id="session_trace1", record=expired)
        self.clock.advance(11)
        with self.assertRaises(TermuinatorError) as missing:
            expiring.get(
                session_id="session_trace1",
                trace_id=expired.trace_id,
            )
        self.assertEqual(missing.exception.code, ErrorCode.TARGET_NOT_FOUND)

        quota = self._store(quota_bytes=850)
        second = self._record("2")
        third = self._record("3")
        quota.append(session_id="session_trace1", record=second)
        self.clock.advance(1)
        quota.append(session_id="session_trace1", record=third)
        records, _truncated = quota.list_page(
            session_id="session_trace1",
            limit=1000,
        )
        self.assertEqual(records[-1], third)
        self.assertLessEqual(len(records), 2)

    def test_tampered_or_symlinked_record_never_returns(self) -> None:
        store = self._store()
        record = self._record("1")
        store.append(session_id="session_trace1", record=record)
        directory = self.root / "traces" / ("a" * 64)
        path = directory / f"{record.trace_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["record"]["permission"] = "always_allow"
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.chmod(0o600)

        with self.assertRaises(TermuinatorError) as tampered:
            store.get(
                session_id="session_trace1",
                trace_id=record.trace_id,
            )
        self.assertEqual(tampered.exception.code, ErrorCode.INTERNAL_ERROR)

        path.unlink()
        target = self.root / "outside"
        target.write_text("outside", encoding="utf-8")
        path.symlink_to(target)
        with self.assertRaises(TermuinatorError) as symlinked:
            store.get(
                session_id="session_trace1",
                trace_id=record.trace_id,
            )
        self.assertEqual(symlinked.exception.code, ErrorCode.INTERNAL_ERROR)


if __name__ == "__main__":
    unittest.main()
