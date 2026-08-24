"""Local host-control CLI and defensive client tests."""

from __future__ import annotations

import asyncio
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest

from src.termuinator.host_control import HostControlRouter, UnixHostControlServer
from src.termuinator.host_control_cli import (
    build_parser,
    main,
    request_from_args,
    send_control_request,
)


class _Service:
    async def local_takeover_start(self, session_id: str) -> dict[str, object]:
        return {"session_id": session_id, "state": "user_takeover_active"}


class HostControlCliTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.xdg_data = Path(self.temporary.name) / "data"
        self.socket_path = self.xdg_data / "termuinator" / "runtime" / "control.sock"
        self.server = UnixHostControlServer(
            path=self.socket_path,
            router=HostControlRouter(_Service()),
        )

    async def asyncTearDown(self) -> None:
        await self.server.close()

    def test_parser_builds_only_closed_host_requests(self) -> None:
        parser = build_parser()
        cases = (
            (
                ["permission", "session_abcdefgh", "https://example.com", "session_allow"],
                "permission_record",
            ),
            (
                ["confirmation", "session_abcdefgh", "confirmation_abcdefgh", "deny"],
                "confirmation_decide",
            ),
            (
                [
                    "developer-mode",
                    "session_abcdefgh",
                    "https://example.com",
                    "enable",
                ],
                "developer_mode_set",
            ),
            (["takeover-start", "session_abcdefgh"], "takeover_start"),
            (["takeover-resume", "session_abcdefgh"], "takeover_resume"),
        )
        for arguments, operation in cases:
            with self.subTest(arguments=arguments):
                request = request_from_args(parser.parse_args(arguments))
                self.assertEqual(request["version"], 1)
                self.assertEqual(request["operation"], operation)
                if operation == "developer_mode_set":
                    self.assertTrue(request["enabled"])

    async def test_client_and_cli_round_trip_the_owner_private_socket(self) -> None:
        await self.server.start()
        request = {
            "version": 1,
            "operation": "takeover_start",
            "session_id": "session_abcdefgh",
        }
        direct = await asyncio.to_thread(
            send_control_request,
            self.socket_path,
            request,
        )
        output = StringIO()
        exit_code = await asyncio.to_thread(
            main,
            ["takeover-start", "session_abcdefgh"],
            environ={
                "HOME": self.temporary.name,
                "XDG_DATA_HOME": str(self.xdg_data),
            },
            stdout=output,
        )

        self.assertTrue(direct["ok"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue()), direct)

    async def test_client_refuses_non_private_or_non_socket_paths(self) -> None:
        await self.server.start()
        os.chmod(self.socket_path, 0o666)
        with self.assertRaises(ValueError):
            await asyncio.to_thread(
                send_control_request,
                self.socket_path,
                {
                    "version": 1,
                    "operation": "takeover_start",
                    "session_id": "session_abcdefgh",
                },
            )
        os.chmod(self.socket_path, 0o600)

        await self.server.close()
        self.socket_path.write_text("not-a-socket", encoding="utf-8")
        with self.assertRaises(ValueError):
            await asyncio.to_thread(
                send_control_request,
                self.socket_path,
                {
                    "version": 1,
                    "operation": "takeover_start",
                    "session_id": "session_abcdefgh",
                },
            )

    def test_packaging_exposes_the_host_control_command(self) -> None:
        pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'tbp-control = "src.termuinator.host_control_cli:main"',
            pyproject,
        )


if __name__ == "__main__":
    unittest.main()
