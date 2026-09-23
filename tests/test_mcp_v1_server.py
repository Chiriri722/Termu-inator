"""MCP 1.29 low-level server projection tests (optional dependency)."""

from __future__ import annotations

import importlib.util
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, AsyncMock, patch


MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None


@unittest.skipUnless(MCP_AVAILABLE, "requires the pinned MCP optional dependency")
class CompactMcpServerTests(unittest.IsolatedAsyncioTestCase):
    def test_sigterm_and_stdio_eof_clean_control_socket_and_allow_restart(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            data_home = Path(root) / "data"
            environment = os.environ.copy()
            environment.pop("TERMUINATOR_CONFIG", None)
            environment["HOME"] = root
            environment["XDG_DATA_HOME"] = str(data_home)
            socket_path = data_home / "termuinator" / "runtime" / "control.sock"

            for shutdown in ("sigterm", "eof", "sigterm", "eof"):
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-B",
                        "-m",
                        "src.mcp_v1_server",
                        "--tool-profile",
                        "observer",
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=environment,
                )
                try:
                    deadline = time.monotonic() + 5
                    while not socket_path.exists() and time.monotonic() < deadline:
                        if process.poll() is not None:
                            break
                        time.sleep(0.01)
                    self.assertIsNone(process.poll())
                    self.assertTrue(socket_path.exists())

                    if shutdown == "eof":
                        process.stdin.write(json.dumps({
                            "jsonrpc": "2.0", "id": 1, "method": "initialize",
                            "params": {
                                "protocolVersion": "2025-11-25", "capabilities": {},
                                "clientInfo": {"name": "recovery-test", "version": "1"},
                            },
                        }).encode() + b"\n")
                        process.stdin.flush()
                        with selectors.DefaultSelector() as selector:
                            selector.register(process.stdout, selectors.EVENT_READ)
                            self.assertTrue(selector.select(timeout=5))
                        response = json.loads(process.stdout.readline())
                        self.assertEqual(response["id"], 1)
                        self.assertEqual(response["result"]["protocolVersion"], "2025-11-25")
                        process.stdin.write(
                            b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
                        )
                        process.stdin.close()
                        process.stdin = None
                    else:
                        process.terminate()
                    stdout, stderr = process.communicate(timeout=5)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=5)

                self.assertEqual(process.returncode, 0)
                self.assertEqual(stdout, b"")
                self.assertEqual(stderr, b"")
                self.assertFalse(socket_path.exists())

    def test_main_requires_explicit_privileged_viewer_and_tool_profile_flags(self) -> None:
        from src.mcp_v1_server import main

        runtime = object()
        with (
            patch(
                "src.mcp_v1_server.build_default_runtime",
                return_value=runtime,
            ) as build,
            patch("src.mcp_v1_server.anyio.run") as run,
        ):
            main([])
            build.assert_called_once_with(
                developer_mode_available=False,
                shared_view_enabled=False,
                shared_view_port=8765,
            )
            run.assert_called_once_with(
                ANY,
                runtime,
                "interactive",
            )

        with (
            patch(
                "src.mcp_v1_server.build_default_runtime",
                return_value=runtime,
            ) as build,
            patch("src.mcp_v1_server.anyio.run"),
        ):
            main(["--developer-mode"])
            build.assert_called_once_with(
                developer_mode_available=True,
                shared_view_enabled=False,
                shared_view_port=8765,
            )

        with (
            patch(
                "src.mcp_v1_server.build_default_runtime",
                return_value=runtime,
            ) as build,
            patch("src.mcp_v1_server.anyio.run"),
        ):
            main(["--shared-view", "--shared-view-port", "9123"])
            build.assert_called_once_with(
                developer_mode_available=False,
                shared_view_enabled=True,
                shared_view_port=9123,
            )

        with (
            patch(
                "src.mcp_v1_server.build_default_runtime",
                return_value=runtime,
            ),
            patch("src.mcp_v1_server.anyio.run") as run,
        ):
            main(["--tool-profile", "observer"])
            run.assert_called_once_with(
                ANY,
                runtime,
                "observer",
            )

    async def test_stdio_lifecycle_owns_the_local_control_socket(self) -> None:
        from src.mcp_v1_server import _run_stdio

        events: list[str] = []

        class HostServer:
            async def start(self) -> None:
                events.append("host-start")

            async def close(self) -> None:
                events.append("host-close")

        class McpServer:
            def create_initialization_options(self) -> object:
                return object()

            async def run(self, *_args: object) -> None:
                events.append("mcp-run")

        class Service:
            async def close(self) -> None:
                events.append("service-close")

        @asynccontextmanager
        async def fake_stdio():
            events.append("stdio-open")
            try:
                yield object(), object()
            finally:
                events.append("stdio-close")

        runtime = SimpleNamespace(
            host_server=HostServer(),
            shared_view_server=None,
            mcp_router=object(),
            service=Service(),
        )
        with (
            patch("src.mcp_v1_server.build_compact_server", return_value=McpServer()),
            patch("src.mcp_v1_server.stdio_server", side_effect=fake_stdio),
        ):
            await _run_stdio(runtime)

        self.assertEqual(
            events,
            [
                "host-start",
                "stdio-open",
                "mcp-run",
                "stdio-close",
                "host-close",
                "service-close",
            ],
        )

    async def test_stdio_failure_still_closes_local_control(self) -> None:
        from src.mcp_v1_server import _run_stdio

        events: list[str] = []

        class HostServer:
            async def start(self) -> None:
                events.append("host-start")

            async def close(self) -> None:
                events.append("host-close")

        class McpServer:
            def create_initialization_options(self) -> object:
                return object()

            async def run(self, *_args: object) -> None:
                events.append("mcp-run")
                raise RuntimeError("stdio failed")

        @asynccontextmanager
        async def fake_stdio():
            yield object(), object()

        runtime = SimpleNamespace(
            host_server=HostServer(),
            shared_view_server=None,
            mcp_router=object(),
        )
        runtime.service = SimpleNamespace(
            close=AsyncMock(side_effect=lambda: events.append("service-close")),
        )
        with (
            patch("src.mcp_v1_server.build_compact_server", return_value=McpServer()),
            patch("src.mcp_v1_server.stdio_server", side_effect=fake_stdio),
        ):
            with self.assertRaisesRegex(RuntimeError, "stdio failed"):
                await _run_stdio(runtime)

        self.assertEqual(events, ["host-start", "mcp-run", "host-close", "service-close"])

    async def test_stdio_lifecycle_owns_optional_shared_view(self) -> None:
        from src.mcp_v1_server import _run_stdio

        events: list[str] = []

        class HostServer:
            async def start(self) -> None:
                events.append("host-start")

            async def close(self) -> None:
                events.append("host-close")

        class ViewServer:
            url = "http://127.0.0.1:9123/"

            async def start(self) -> None:
                events.append("view-start")

            async def close(self) -> None:
                events.append("view-close")

        class McpServer:
            def create_initialization_options(self) -> object:
                return object()

            async def run(self, *_args: object) -> None:
                events.append("mcp-run")

        @asynccontextmanager
        async def fake_stdio():
            events.append("stdio-open")
            try:
                yield object(), object()
            finally:
                events.append("stdio-close")

        runtime = SimpleNamespace(
            host_server=HostServer(),
            shared_view_server=ViewServer(),
            mcp_router=object(),
            service=SimpleNamespace(
                close=AsyncMock(side_effect=lambda: events.append("service-close")),
            ),
        )
        with (
            patch("src.mcp_v1_server.build_compact_server", return_value=McpServer()),
            patch("src.mcp_v1_server.stdio_server", side_effect=fake_stdio),
            patch("builtins.print") as printed,
        ):
            await _run_stdio(runtime)

        self.assertEqual(
            events,
            [
                "host-start",
                "view-start",
                "stdio-open",
                "mcp-run",
                "stdio-close",
                "view-close",
                "host-close",
                "service-close",
            ],
        )
        self.assertIn("http://127.0.0.1:9123/", printed.call_args.args[0])

    async def test_server_lists_exact_tools_and_returns_structured_chunks(self) -> None:
        from mcp import types

        from src.mcp_v1_server import build_compact_server
        from src.termuinator.contracts import ArtifactChunk
        from src.termuinator.mcp_v1 import CompactV1Router
        from src.termuinator.schema import PUBLIC_TOOL_NAMES, build_mcp_tools

        class Service:
            async def artifact_read(self, **kwargs: object) -> ArtifactChunk:
                return ArtifactChunk(
                    uri=str(kwargs["uri"]),
                    offset=0,
                    next_offset=4,
                    eof=True,
                    data_base64="aW1hZw==",
                )

        server = build_compact_server(CompactV1Router(Service()))
        listed = await server.request_handlers[types.ListToolsRequest](
            types.ListToolsRequest()
        )
        tools = listed.root.tools

        self.assertEqual(tuple(tool.name for tool in tools), PUBLIC_TOOL_NAMES)
        expected = build_mcp_tools()
        self.assertEqual(tools[10].inputSchema, expected[10]["inputSchema"])
        self.assertEqual(tools[10].outputSchema, expected[10]["outputSchema"])

        uri = "artifact://sha256/" + "a" * 64
        called = await server.request_handlers[types.CallToolRequest](
            types.CallToolRequest(
                params=types.CallToolRequestParams(
                    name="browser_artifact_read",
                    arguments={"session_id": "session_abcdefgh", "uri": uri},
                )
            )
        )
        result = called.root
        self.assertFalse(result.isError)
        self.assertEqual(result.structuredContent["data_base64"], "aW1hZw==")

    async def test_observer_profile_hides_and_rejects_mutation_tools(self) -> None:
        from mcp import types

        from src.mcp_v1_server import build_compact_server
        from src.termuinator.mcp_v1 import CompactV1Router
        from src.termuinator.tool_profiles import resolve_tool_profile

        class Service:
            pass

        server = build_compact_server(
            CompactV1Router(Service()),
            tool_profile="observer",
        )
        listed = await server.request_handlers[types.ListToolsRequest](
            types.ListToolsRequest()
        )
        self.assertEqual(
            tuple(tool.name for tool in listed.root.tools),
            resolve_tool_profile("observer"),
        )

        called = await server.request_handlers[types.CallToolRequest](
            types.CallToolRequest(
                params=types.CallToolRequestParams(
                    name="browser_act",
                    arguments={},
                )
            )
        )
        self.assertTrue(called.root.isError)
        self.assertIn("tool_profile", called.root.content[0].text)

    async def test_expected_service_error_is_mcp_tool_execution_error(self) -> None:
        import json

        from mcp import types

        from src.mcp_v1_server import build_compact_server
        from src.termuinator.contracts import ErrorCode
        from src.termuinator.errors import TermuinatorError
        from src.termuinator.mcp_v1 import CompactV1Router

        class _UnsupportedDeveloperService:
            async def devtools(self, **_kwargs: object) -> object:
                raise TermuinatorError(
                    ErrorCode.UNSUPPORTED_CAPABILITY,
                    "Backend Developer query is unavailable",
                    details={"capability": "devtools"},
                )

        server = build_compact_server(
            CompactV1Router(_UnsupportedDeveloperService())
        )
        called = await server.request_handlers[types.CallToolRequest](
            types.CallToolRequest(
                params=types.CallToolRequestParams(
                    name="browser_devtools",
                    arguments={
                        "session_id": "session_abcdefgh",
                        "tab_id": "tab_abcdefgh",
                        "page_id": "page_abcdefgh",
                        "expected_page_revision": "epoch_abc:2",
                        "query": "console",
                        "parameters": {},
                    },
                )
            )
        )
        result = called.root

        self.assertTrue(result.isError)
        self.assertIsNone(result.structuredContent)
        self.assertEqual(len(result.content), 1)
        envelope = json.loads(result.content[0].text)
        self.assertEqual(envelope["code"], "unsupported_capability")
        self.assertEqual(envelope["details"]["capability"], "devtools")


if __name__ == "__main__":
    unittest.main()
