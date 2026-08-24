"""Tests for the trusted runtime composition boundary."""

from __future__ import annotations

import base64
from pathlib import Path
import tempfile
import unittest

from src.termuinator.config import RuntimeConfig
from src.termuinator.contracts import Backend, PageRevision
from src.termuinator.core.service import BrowserService
from src.termuinator.runtime import (
    CompactRuntime,
    build_legacy_browser_service,
    build_legacy_compact_runtime,
)
from src.termuinator.shared_view import SharedViewServer


class _FakePilot:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def start(self) -> None:
        self.calls.append("start")

    async def stop(self) -> None:
        self.calls.append("stop")

    async def screenshot(
        self,
        path: str | None = None,
        full_page: bool = False,
    ) -> bytes:
        self.calls.append(("screenshot", path, full_page))
        return b"\x89PNG\r\n\x1a\nruntime-image"


class RuntimeCompositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_developer_availability_is_a_trusted_explicit_option(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                data_root=Path(temp_dir) / "runtime",
                default_backend=Backend.CHROMIUM,
                profile_schema_version="v1",
                artifact_retention_seconds=120,
                artifact_quota_bytes=1024 * 1024,
                trace_retention_seconds=120,
                trace_quota_bytes=1024 * 1024,
                max_artifact_chunk_bytes=1024,
            )
            service = build_legacy_browser_service(
                config=config,
                owner_scope="transport-owner",
                pilot_factory=lambda **_: _FakePilot(),
                developer_mode_available=True,
            )

            self.assertTrue(service._developer_mode_available)

    async def test_compact_runtime_shares_one_service_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                data_root=Path(temp_dir) / "runtime",
                default_backend=Backend.CHROMIUM,
                profile_schema_version="v1",
                artifact_retention_seconds=120,
                artifact_quota_bytes=1024 * 1024,
                trace_retention_seconds=120,
                trace_quota_bytes=1024 * 1024,
                max_artifact_chunk_bytes=1024,
            )
            runtime = build_legacy_compact_runtime(
                config=config,
                owner_scope="transport-owner",
                pilot_factory=lambda **_: _FakePilot(),
            )

            self.assertIsInstance(runtime, CompactRuntime)
            self.assertIsNone(runtime.shared_view_server)
            self.assertEqual(
                runtime.host_server.path,
                config.data_root / "runtime" / "control.sock",
            )
            started = await runtime.mcp_router.dispatch(
                "browser_session_start",
                {"project_id": "project-shared-authority"},
            )
            session_id = started["session_id"]
            await runtime.host_router.dispatch(
                {
                    "version": 1,
                    "operation": "permission_record",
                    "session_id": session_id,
                    "origin": "https://example.com/path",
                    "policy": "session_allow",
                }
            )
            listed = await runtime.mcp_router.dispatch(
                "browser_permissions",
                {"session_id": session_id, "operation": "list"},
            )

            self.assertEqual(
                listed["decisions"][0]["origin"],
                "https://example.com",
            )
            self.assertEqual(
                listed["decisions"][0]["session_id"],
                session_id,
            )
            await runtime.mcp_router.dispatch(
                "browser_session_stop",
                {"session_id": session_id},
            )

    async def test_shared_view_requires_an_explicit_runtime_option(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                data_root=Path(temp_dir) / "runtime",
                default_backend=Backend.CHROMIUM,
                profile_schema_version="v1",
                artifact_retention_seconds=120,
                artifact_quota_bytes=1024 * 1024,
                trace_retention_seconds=120,
                trace_quota_bytes=1024 * 1024,
                max_artifact_chunk_bytes=1024,
            )

            runtime = build_legacy_compact_runtime(
                config=config,
                owner_scope="transport-owner",
                pilot_factory=lambda **_: _FakePilot(),
                shared_view_enabled=True,
                shared_view_port=9123,
            )

            self.assertIsInstance(runtime.shared_view_server, SharedViewServer)
            self.assertEqual(runtime.shared_view_server.host, "127.0.0.1")
            with self.assertRaises(RuntimeError):
                _ = runtime.shared_view_server.port

    async def test_config_selects_explicit_backend_and_profile_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                data_root=Path(temp_dir) / "runtime",
                default_backend=Backend.FIREFOX,
                profile_schema_version="v1",
                artifact_retention_seconds=86_400,
                artifact_quota_bytes=500 * 1024 * 1024,
                trace_retention_seconds=7 * 86_400,
                trace_quota_bytes=100 * 1024 * 1024,
                max_artifact_chunk_bytes=512 * 1024,
            )
            pilot_kwargs: list[dict[str, object]] = []
            pilots: list[_FakePilot] = []

            def pilot_factory(**kwargs: object) -> _FakePilot:
                pilot_kwargs.append(kwargs)
                pilot = _FakePilot()
                pilots.append(pilot)
                return pilot

            service = build_legacy_browser_service(
                config=config,
                owner_scope="transport-owner",
                pilot_factory=pilot_factory,
            )

            self.assertIsInstance(service, BrowserService)
            started = await service.session_start(project_id="project-a")

            self.assertEqual(started.status.backend, Backend.FIREFOX)
            self.assertEqual(pilot_kwargs[0]["browser"], "firefox")
            self.assertEqual(
                Path(str(pilot_kwargs[0]["user_data_dir"])).parts[-3:],
                ("firefox", "v1", "profile"),
            )
            await service.session_stop(started.session_id)
            self.assertEqual(pilots[0].calls, ["start", "stop"])

    async def test_runtime_screenshot_round_trip_uses_configured_chunk_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                data_root=Path(temp_dir) / "runtime",
                default_backend=Backend.CHROMIUM,
                profile_schema_version="v1",
                artifact_retention_seconds=120,
                artifact_quota_bytes=1024 * 1024,
                trace_retention_seconds=120,
                trace_quota_bytes=1024 * 1024,
                max_artifact_chunk_bytes=4,
            )
            pilot = _FakePilot()
            service = build_legacy_browser_service(
                config=config,
                owner_scope="transport-owner",
                pilot_factory=lambda **_: pilot,
            )
            started = await service.session_start(
                project_id="project-runtime-artifact"
            )
            status = started.status

            artifact = await service.screenshot(
                session_id=started.session_id,
                tab_id=status.active_tab_id,
                page_id=status.active_page_id,
                expected_revision=PageRevision.parse(str(status.page_revision)),
                mode="viewport",
            )
            chunk = await service.artifact_read(
                session_id=started.session_id,
                uri=artifact.uri,
                offset=0,
                limit=4,
            )

            self.assertEqual(base64.b64decode(chunk.data_base64), b"\x89PNG")
            self.assertFalse(chunk.eof)
            self.assertEqual(
                pilot.calls,
                ["start", ("screenshot", None, False)],
            )
            await service.session_stop(started.session_id)


if __name__ == "__main__":
    unittest.main()
