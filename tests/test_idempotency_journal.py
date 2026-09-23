"""Crash-safe action idempotency journal contracts."""

from __future__ import annotations

import os
from pathlib import Path
import json
import selectors
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping
import unittest

from src.termuinator.contracts import (
    ActionKind,
    ActionRequest,
    ActionResult,
    ActionStatus,
    ErrorCode,
    PageRevision,
    Verification,
)
from src.termuinator.core.idempotency import (
    DurableActionJournal,
    JournalState,
    canonical_action_digest,
)
from src.termuinator.core.sessions import ProcessSessionLock
from src.termuinator.errors import TermuinatorError


class DurableActionJournalTests(unittest.TestCase):
    @staticmethod
    def _request(
        *,
        text: str = "hello",
        action_id: str = "action_journal1",
        idempotency_key: str = "idempotency_journal1",
        confirmation_id: str | None = None,
    ) -> ActionRequest:
        return ActionRequest(
            action_id=action_id,
            idempotency_key=idempotency_key,
            session_id="session_journal1",
            tab_id="tab_journal0001",
            page_id="page_journal001",
            expected_page_revision=PageRevision("epoch_journal", 2),
            kind=ActionKind.TYPE,
            target_ref="ref_journal_target_1234567890",
            parameters={"text": text, "clear": True},
            timeout_ms=12_000,
            confirmation_id=confirmation_id,
        )

    @staticmethod
    def _result(
        *,
        download: Mapping[str, Any] | None = None,
    ) -> ActionResult:
        before = PageRevision("epoch_journal", 2)
        after = PageRevision("epoch_journal", 3)
        return ActionResult(
            status=ActionStatus.SUCCEEDED,
            before_revision=before,
            after_revision=after,
            executed_method="dom-input",
            verification=(
                Verification(
                    verification_id="verification_journal1",
                    action_id="action_journal1",
                    kind="input_value",
                    target_ref="ref_journal_target_1234567890",
                    passed=True,
                    causal=True,
                    expected_summary="redacted value length=5",
                    actual_summary="redacted value length=5",
                    observed_revision=after,
                    observed_at="2026-08-24T15:00:00+00:00",
                ),
            ),
            download=download,
        )

    def _journal(self, root: Path) -> DurableActionJournal:
        return DurableActionJournal(
            root=root,
            owner_scope="owner-secret-alpha",
            project_id="project-secret-alpha",
        )

    def test_digest_tracks_effect_but_not_retry_or_confirmation_handles(self) -> None:
        original = self._request()
        retry = self._request(
            action_id="action_journal2",
            confirmation_id="confirmation_journal1",
        )

        self.assertEqual(
            canonical_action_digest(original),
            canonical_action_digest(retry),
        )
        self.assertNotEqual(
            canonical_action_digest(original),
            canonical_action_digest(self._request(text="changed")),
        )

    def test_terminal_result_replays_after_process_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self._request()
            journal = self._journal(root)

            claim = journal.reserve(request)
            self.assertEqual(claim.state, JournalState.RESERVED)
            self.assertIsNone(claim.result)
            journal.mark_dispatched(request)
            journal.record_terminal(request, self._result())

            restarted = self._journal(root)
            replay = restarted.reserve(
                self._request(action_id="action_retry01")
            )
            self.assertEqual(replay.state, JournalState.TERMINAL)
            self.assertEqual(replay.result, self._result())

            records = list(root.rglob("*.json"))
            self.assertEqual(len(records), 1)
            self.assertEqual(stat.S_IMODE(records[0].stat().st_mode), 0o600)
            self.assertEqual(
                stat.S_IMODE(records[0].parent.stat().st_mode),
                0o700,
            )
            serialized = records[0].read_text(encoding="utf-8")
            self.assertNotIn("owner-secret-alpha", serialized)
            self.assertNotIn("project-secret-alpha", serialized)
            self.assertNotIn(request.idempotency_key, serialized)

    def test_same_key_with_changed_effect_is_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = self._journal(Path(directory))
            journal.reserve(self._request())

            with self.assertRaises(TermuinatorError) as conflict:
                journal.reserve(self._request(text="different"))

            self.assertEqual(
                conflict.exception.code,
                ErrorCode.IDEMPOTENCY_CONFLICT,
            )
            self.assertFalse(conflict.exception.retryable)

    def test_recovered_dispatched_record_is_outcome_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self._request()
            journal = self._journal(root)
            journal.reserve(request)
            journal.mark_dispatched(request)

            with self.assertRaises(TermuinatorError) as unknown:
                self._journal(root).reserve(request)

            self.assertEqual(unknown.exception.code, ErrorCode.OUTCOME_UNKNOWN)
            self.assertFalse(unknown.exception.retryable)

    def test_waiting_confirmation_survives_restart_without_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self._request()
            journal = self._journal(root)
            journal.reserve(request)
            journal.mark_waiting_confirmation(request)

            resumed = self._journal(root).reserve(request)

            self.assertEqual(resumed.state, JournalState.WAITING_CONFIRMATION)
            self.assertIsNone(resumed.result)

    def test_actual_writer_exit_preserves_journal_and_releases_its_lease(self) -> None:
        script = r"""
import os, pathlib, sys
sys.path.insert(0, sys.argv[1])
from tests.test_idempotency_journal import DurableActionJournalTests
from src.termuinator.core.sessions import ProcessSessionLock
root = pathlib.Path(sys.argv[2])
lease = ProcessSessionLock(lock_path=root / 'session.lock', owner_scope='writer-owner')
lease.acquire()
case = DurableActionJournalTests()
request = case._request()
journal = case._journal(root)
journal.reserve(request)
journal.mark_dispatched(request)
descriptor = os.open(root / 'effect', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    os.write(descriptor, b'one synthetic effect\n')
    os.fsync(descriptor)
finally:
    os.close(descriptor)
if sys.argv[3] == 'terminal':
    journal.record_terminal(request, case._result())
print('READY', flush=True)
sys.stdin.buffer.read()
"""
        for phase in ("dispatched", "terminal"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with subprocess.Popen(
                    [sys.executable, "-I", "-B", "-c", script,
                     str(Path(__file__).resolve().parents[1]), str(root), phase],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                ) as child:
                    lock_path = root / "session.lock"
                    lease = ProcessSessionLock(
                        lock_path=lock_path, owner_scope="recovery-owner",
                    )
                    try:
                        with selectors.DefaultSelector() as selector:
                            selector.register(child.stdout, selectors.EVENT_READ)
                            self.assertTrue(
                                selector.select(timeout=5),
                                "journal writer did not reach its interruption point",
                            )
                        self.assertEqual(child.stdout.readline(), b"READY\n")
                        self.assertEqual(json.loads(lock_path.read_text())["pid"], child.pid)
                        lock_inode = lock_path.stat().st_ino
                        with self.assertRaises(TermuinatorError) as busy:
                            lease.acquire()
                        self.assertEqual(busy.exception.code, ErrorCode.SESSION_BUSY)
                        child.kill()  # Only this owned child; no PID/name census.
                        self.assertLess(child.wait(timeout=5), 0)
                        self.assertEqual(child.stderr.read(), b"")
                        self.assertEqual(lock_path.stat().st_ino, lock_inode)
                        lease.acquire()
                        lease.release()
                        recovered = self._journal(root)
                        if phase == "dispatched":
                            with self.assertRaises(TermuinatorError) as unknown:
                                recovered.reserve(self._request())
                            self.assertEqual(
                                unknown.exception.code, ErrorCode.OUTCOME_UNKNOWN,
                            )
                            self.assertFalse(unknown.exception.retryable)
                        else:
                            claim = recovered.reserve(self._request())
                            self.assertEqual(claim.state, JournalState.TERMINAL)
                            self.assertEqual(claim.result, self._result())
                        self.assertEqual(
                            (root / "effect").read_bytes(), b"one synthetic effect\n",
                        )
                    finally:
                        lease.release()
                        if child.poll() is None:
                            child.kill()
                        child.wait(timeout=5)

    def test_terminal_before_dispatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = self._journal(Path(directory))
            request = self._request()
            journal.reserve(request)

            with self.assertRaises(TermuinatorError) as invalid:
                journal.record_terminal(request, self._result())

            self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)

    def test_record_symlink_is_never_followed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self._request()
            journal = self._journal(root)
            journal.reserve(request)
            record = next(root.rglob("*.json"))
            victim = root / "victim.json"
            victim.write_text('{"safe": true}\n', encoding="utf-8")
            record.unlink()
            os.symlink(victim, record)

            with self.assertRaises(TermuinatorError) as unsafe:
                journal.reserve(request)

            self.assertEqual(unsafe.exception.code, ErrorCode.INTERNAL_ERROR)
            self.assertEqual(victim.read_text(encoding="utf-8"), '{"safe": true}\n')

    def test_type_confused_stored_download_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self._request()
            journal = self._journal(root)
            journal.reserve(request)
            journal.mark_dispatched(request)
            journal.record_terminal(
                request,
                self._result(
                    download={
                        "download_id": "download_journal1",
                        "state": "completed",
                        "filename": "result.txt",
                        "mime_type": "text/plain",
                        "size_bytes": 12,
                        "artifact_uri": "artifact://sha256/" + "a" * 64,
                        "reason_code": None,
                    }
                ),
            )
            record = next(root.rglob("*.json"))
            payload = json.loads(record.read_text(encoding="utf-8"))
            payload["result"]["download"]["state"] = []
            record.write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(TermuinatorError) as corrupt:
                self._journal(root).reserve(request)

            self.assertEqual(corrupt.exception.code, ErrorCode.INTERNAL_ERROR)

    def test_non_directory_journal_parent_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "idempotency").write_text("not a directory\n", encoding="utf-8")

            with self.assertRaises(TermuinatorError) as unsafe:
                self._journal(root).reserve(self._request())

            self.assertEqual(unsafe.exception.code, ErrorCode.INTERNAL_ERROR)


if __name__ == "__main__":
    unittest.main()
