"""Owner-private Unix socket transport for local host control."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from src.termuinator.contracts import ErrorCode
from src.termuinator.errors import TermuinatorError
from src.termuinator.host_control import HostControlRouter, UnixHostControlServer


class _RecordingService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.error: Exception | None = None

    async def local_takeover_start(self, session_id: str) -> dict[str, object]:
        self.calls.append(session_id)
        if self.error is not None:
            raise self.error
        return {"session_id": session_id, "state": "user_takeover_active"}


class UnixHostControlServerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.socket_path = self.root / "runtime" / "control.sock"
        self.service = _RecordingService()
        self.server = UnixHostControlServer(
            path=self.socket_path,
            router=HostControlRouter(self.service),
        )

    async def asyncTearDown(self) -> None:
        await self.server.close()

    async def _request_bytes(self, payload: bytes) -> dict[str, object]:
        reader, writer = await asyncio.open_unix_connection(self.socket_path)
        writer.write(payload)
        await writer.drain()
        try:
            response = await asyncio.wait_for(reader.readline(), timeout=2)
        finally:
            writer.close()
            await writer.wait_closed()
        return json.loads(response)

    async def _request(self, payload: object) -> dict[str, object]:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        return await self._request_bytes(encoded)

    async def test_socket_is_owner_private_and_round_trips_one_request(self) -> None:
        await self.server.start()
        metadata = os.lstat(self.socket_path)
        parent_metadata = os.lstat(self.socket_path.parent)

        self.assertTrue(stat.S_ISSOCK(metadata.st_mode))
        self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o600)
        self.assertEqual(metadata.st_uid, os.getuid())
        self.assertTrue(stat.S_ISDIR(parent_metadata.st_mode))
        self.assertEqual(stat.S_IMODE(parent_metadata.st_mode) & 0o077, 0)

        response = await self._request(
            {
                "version": 1,
                "operation": "takeover_start",
                "session_id": "session_abcdefgh",
            }
        )

        self.assertEqual(response["ok"], True)
        self.assertEqual(
            response["result"],
            {
                "session_id": "session_abcdefgh",
                "state": "user_takeover_active",
            },
        )
        self.assertEqual(self.service.calls, ["session_abcdefgh"])

    async def test_invalid_oversized_and_internal_failures_are_structured(self) -> None:
        await self.server.start()

        malformed = await self._request_bytes(b"not-json\n")
        oversized = await self._request_bytes(b'"' + b"x" * (65 * 1024) + b'"\n')
        self.service.error = RuntimeError("never-expose-local-secret")
        internal = await self._request(
            {
                "version": 1,
                "operation": "takeover_start",
                "session_id": "session_abcdefgh",
            }
        )

        self.assertEqual(malformed["error"]["code"], ErrorCode.INVALID_REQUEST.value)
        self.assertEqual(oversized["error"]["code"], ErrorCode.INVALID_REQUEST.value)
        self.assertEqual(internal["error"]["code"], ErrorCode.INTERNAL_ERROR.value)
        self.assertNotIn("never-expose-local-secret", json.dumps(internal))

    async def test_existing_file_or_symlink_is_never_overwritten(self) -> None:
        self.socket_path.parent.mkdir(mode=0o700)
        self.socket_path.write_text("do-not-overwrite", encoding="utf-8")
        with self.assertRaises(ValueError):
            await self.server.start()
        self.assertEqual(self.socket_path.read_text(encoding="utf-8"), "do-not-overwrite")

        self.socket_path.unlink()
        target = self.root / "target"
        target.write_text("target", encoding="utf-8")
        self.socket_path.symlink_to(target)
        with self.assertRaises(ValueError):
            await self.server.start()
        self.assertTrue(self.socket_path.is_symlink())
        self.assertEqual(target.read_text(encoding="utf-8"), "target")

    async def test_close_does_not_unlink_a_replacement_path(self) -> None:
        await self.server.start()
        moved = self.root / "original.sock"
        self.socket_path.rename(moved)
        self.socket_path.write_text("replacement", encoding="utf-8")

        await self.server.close()

        self.assertEqual(self.socket_path.read_text(encoding="utf-8"), "replacement")
        self.assertTrue(moved.exists())


if __name__ == "__main__":
    unittest.main()
