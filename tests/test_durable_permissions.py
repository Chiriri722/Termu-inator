"""Durable origin permission policy tests."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from src.termuinator.contracts import ErrorCode, PermissionPolicy
from src.termuinator.core.durable_permissions import DurablePermissionEngine
from src.termuinator.errors import TermuinatorError


class DurablePermissionEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 24, 17, 0, tzinfo=timezone.utc)

    def _engine(self, root: Path) -> DurablePermissionEngine:
        return DurablePermissionEngine(
            root=root,
            owner_scope="owner-secret-alpha",
            project_id="project-secret-alpha",
            now=lambda: self.now,
        )

    def test_persistent_allow_and_block_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = self._engine(root)
            self.assertEqual(
                engine.evaluate(
                    url="https://example.com/page",
                    session_id="session_permissions1",
                ),
                PermissionPolicy.ASK,
            )
            engine.record(
                origin="https://EXAMPLE.com:443/path",
                policy=PermissionPolicy.ALWAYS_ALLOW,
            )
            engine.record(
                origin="https://blocked.example",
                policy=PermissionPolicy.BLOCK,
            )

            restarted = self._engine(root)
            self.assertEqual(
                restarted.evaluate(
                    url="https://example.com/other",
                    session_id="session_permissions2",
                ),
                PermissionPolicy.ALWAYS_ALLOW,
            )
            self.assertEqual(
                restarted.evaluate(
                    url="https://blocked.example/path",
                    session_id="session_permissions2",
                ),
                PermissionPolicy.BLOCK,
            )
            decisions = restarted.list(session_id="session_permissions2")
            self.assertEqual(
                {item.origin: item.policy for item in decisions},
                {
                    "https://blocked.example": PermissionPolicy.BLOCK,
                    "https://example.com": PermissionPolicy.ALWAYS_ALLOW,
                },
            )

            records = list(root.rglob("*.json"))
            self.assertEqual(len(records), 1)
            self.assertEqual(stat.S_IMODE(records[0].stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(records[0].parent.stat().st_mode), 0o700)
            serialized = records[0].read_text(encoding="utf-8")
            self.assertNotIn("owner-secret-alpha", serialized)
            self.assertNotIn("project-secret-alpha", serialized)

    def test_session_allow_is_memory_only_and_clearable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = self._engine(root)
            engine.record(
                origin="https://session.example",
                policy=PermissionPolicy.SESSION_ALLOW,
                session_id="session_permissions1",
            )
            self.assertEqual(
                engine.evaluate(
                    url="https://session.example",
                    session_id="session_permissions1",
                ),
                PermissionPolicy.SESSION_ALLOW,
            )
            engine.clear_session("session_permissions1")
            self.assertEqual(
                engine.evaluate(
                    url="https://session.example",
                    session_id="session_permissions1",
                ),
                PermissionPolicy.ASK,
            )
            self.assertEqual(
                self._engine(root).evaluate(
                    url="https://session.example",
                    session_id="session_permissions1",
                ),
                PermissionPolicy.ASK,
            )

    def test_two_engine_instances_merge_updates_without_lost_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self._engine(root)
            second = self._engine(root)
            first.record(
                origin="https://one.example",
                policy=PermissionPolicy.ALWAYS_ALLOW,
            )
            second.record(
                origin="https://two.example",
                policy=PermissionPolicy.BLOCK,
            )

            origins = {item.origin for item in first.list()}

            self.assertEqual(
                origins,
                {"https://one.example", "https://two.example"},
            )

    def test_symlink_or_corrupt_record_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = self._engine(root)
            engine.record(
                origin="https://example.com",
                policy=PermissionPolicy.ALWAYS_ALLOW,
            )
            record = next(root.rglob("*.json"))
            victim = root / "victim.json"
            victim.write_text('{"safe": true}\n', encoding="utf-8")
            record.unlink()
            os.symlink(victim, record)

            with self.assertRaises(TermuinatorError) as unsafe:
                engine.evaluate(
                    url="https://example.com",
                    session_id="session_permissions1",
                )

            self.assertEqual(unsafe.exception.code, ErrorCode.INTERNAL_ERROR)
            self.assertEqual(victim.read_text(encoding="utf-8"), '{"safe": true}\n')

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = self._engine(root)
            engine.record(
                origin="https://example.com",
                policy=PermissionPolicy.ALWAYS_ALLOW,
            )
            record = next(root.rglob("*.json"))
            payload = json.loads(record.read_text(encoding="utf-8"))
            payload["decisions"][0]["policy"] = []
            record.write_text(json.dumps(payload) + "\n", encoding="utf-8")

            with self.assertRaises(TermuinatorError) as corrupt:
                engine.list()

            self.assertEqual(corrupt.exception.code, ErrorCode.INTERNAL_ERROR)


if __name__ == "__main__":
    unittest.main()
