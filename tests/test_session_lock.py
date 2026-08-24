"""Tests for the process-scoped single-session lease."""

from __future__ import annotations

import json
from pathlib import Path
import stat
import tempfile
import unittest

from src.termuinator.contracts import ErrorCode
from src.termuinator.core.sessions import ProcessSessionLock
from src.termuinator.errors import TermuinatorError


class ProcessSessionLockTests(unittest.TestCase):
    def test_kernel_lease_is_private_exclusive_and_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "runtime" / "session.lock"
            first = ProcessSessionLock(
                lock_path=lock_path,
                owner_scope="private-owner-name",
            )
            second = ProcessSessionLock(
                lock_path=lock_path,
                owner_scope="other-owner",
            )

            first.acquire()
            metadata = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode), 0o600)
            self.assertNotIn("private-owner-name", lock_path.read_text(encoding="utf-8"))
            self.assertRegex(metadata["owner_digest"], r"^[0-9a-f]{64}$")

            with self.assertRaises(TermuinatorError) as busy:
                second.acquire()
            self.assertEqual(busy.exception.code, ErrorCode.SESSION_BUSY)

            first.release()
            second.acquire()
            second.release()

    def test_lock_path_refuses_symbolic_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "target.lock"
            target.write_text("do not follow", encoding="utf-8")
            target.chmod(0o600)
            lock_path = root / "session.lock"
            lock_path.symlink_to(target)
            lock = ProcessSessionLock(lock_path=lock_path, owner_scope="owner")

            with self.assertRaises(TermuinatorError) as invalid:
                lock.acquire()
            self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)
            self.assertEqual(target.read_text(encoding="utf-8"), "do not follow")


if __name__ == "__main__":
    unittest.main()
