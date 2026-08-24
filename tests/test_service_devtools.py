"""Fail-closed Developer Mode service and typed result tests."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.termuinator.backends import (
    BackendConsoleEntry,
    BackendDevtoolsResult,
    BackendDomEntry,
    BackendNetworkEntry,
    BackendPageSnapshot,
    BackendPerformanceEntry,
    BackendStyleEntry,
    RawInteractiveElement,
)
from src.termuinator.backends.fake import FakeBackend
from src.termuinator.contracts import (
    Backend,
    Bounds,
    ConsoleEntry,
    DevtoolsResult,
    DomEntry,
    ErrorCode,
    NetworkEntry,
    PerformanceEntry,
    StyleEntry,
    Viewport,
    to_wire,
)
from src.termuinator.core.service import BrowserService
from src.termuinator.errors import TermuinatorError


class _RecordingSessionLock:
    def __init__(self) -> None:
        self.held = False

    def acquire(self) -> None:
        if self.held:
            raise AssertionError("test lock acquired twice")
        self.held = True

    def release(self) -> None:
        self.held = False


class DevtoolsContractTests(unittest.TestCase):
    def test_each_result_branch_matches_the_frozen_wire_shape(self) -> None:
        timestamp = "2026-08-24T00:00:00+00:00"
        cases = (
            (
                "console",
                ConsoleEntry(level="error", message="boom", timestamp=timestamp),
                {"level", "message", "timestamp"},
            ),
            (
                "network",
                NetworkEntry(
                    request_id="request_abcdefgh",
                    method="GET",
                    url="https://example.com/api",
                    status=200,
                    resource_type="fetch",
                    started_at=timestamp,
                    duration_ms=12.5,
                ),
                {
                    "request_id",
                    "method",
                    "url",
                    "status",
                    "resource_type",
                    "started_at",
                    "duration_ms",
                },
            ),
            (
                "dom",
                DomEntry(
                    ref="ref_abcdefghijklmnop",
                    tag="button",
                    role="button",
                    name="Save",
                    text="Save",
                    bounds=Bounds(x=1, y=2, width=30, height=20),
                ),
                {"ref", "tag", "role", "name", "text", "bounds"},
            ),
            (
                "style",
                StyleEntry(name="color", value="rgb(0, 0, 0)"),
                {"name", "value"},
            ),
            (
                "performance",
                PerformanceEntry(name="domContentLoaded", value=12.5, unit="ms"),
                {"name", "value", "unit"},
            ),
        )
        for query, entry, fields in cases:
            with self.subTest(query=query):
                result = DevtoolsResult(
                    query=query,
                    entries=(entry,),
                    truncated=False,
                )
                self.assertEqual(set(to_wire(entry)), fields)
                self.assertEqual(
                    set(to_wire(result)),
                    {"query", "entries", "truncated"},
                )


class BrowserServiceDevtoolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        timestamp = "2026-08-24T00:00:00+00:00"
        self.backend = FakeBackend(
            Backend.CHROMIUM,
            snapshot=BackendPageSnapshot(
                url="https://example.com/app",
                title="App",
                ready_state="complete",
                viewport=Viewport(width=1280, height=720),
                interactive_elements=(
                    RawInteractiveElement(
                        backend_node_id="private-save-button",
                        role="button",
                        accessible_name="Save",
                        text="Save",
                        tag="button",
                        bounds=Bounds(x=1, y=2, width=30, height=20),
                    ),
                ),
            ),
            devtools_results={
                "console": BackendDevtoolsResult(
                    query="console",
                    entries=(
                        BackendConsoleEntry(
                            level="error",
                            message=(
                                "Authorization: Bearer super-secret-token; "
                                "password=hunter2"
                            ),
                            timestamp=timestamp,
                        ),
                    ),
                    truncated=False,
                ),
                "network": BackendDevtoolsResult(
                    query="network",
                    entries=(
                        BackendNetworkEntry(
                            backend_request_id="private-request-1",
                            method="GET",
                            url=(
                                "https://user:pass@example.com/api"
                                "?token=query-secret&query=visible#fragment"
                            ),
                            status=200,
                            resource_type="fetch",
                            started_at=timestamp,
                            duration_ms=12.5,
                        ),
                    ),
                    truncated=False,
                ),
                "dom": BackendDevtoolsResult(
                    query="dom",
                    entries=(
                        BackendDomEntry(
                            backend_node_id="private-save-button",
                            tag="button",
                            role="button",
                            name="Save",
                            text="Save",
                            bounds=Bounds(x=1, y=2, width=30, height=20),
                        ),
                    ),
                    truncated=False,
                ),
                "style": BackendDevtoolsResult(
                    query="style",
                    entries=(BackendStyleEntry(name="color", value="black"),),
                    truncated=False,
                ),
                "performance": BackendDevtoolsResult(
                    query="performance",
                    entries=(
                        BackendPerformanceEntry(
                            name="domContentLoaded",
                            value=12.5,
                            unit="ms",
                        ),
                    ),
                    truncated=False,
                ),
            },
        )
        self.service = self._service(self.backend, available=True, suffix="enabled")

    def _service(
        self,
        backend: FakeBackend,
        *,
        available: bool,
        suffix: str,
    ) -> BrowserService:
        return BrowserService(
            data_root=Path(self.temporary.name) / suffix,
            owner_scope="transport-owner",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={Backend.CHROMIUM: lambda: backend},
            session_lock=_RecordingSessionLock(),
            developer_mode_available=available,
        )

    async def _start_and_observe(self, service: BrowserService) -> tuple[str, object]:
        started = await service.session_start(
            project_id="project-devtools",
            viewport=Viewport(width=1280, height=720),
        )
        status = started.status
        observation = await service.observe(
            session_id=started.session_id,
            tab_id=status.active_tab_id,
            page_id=status.active_page_id,
            expected_revision=status.page_revision,
            include_screenshot=False,
            include_accessibility=False,
            text_limit=1_000,
        )
        return started.session_id, observation

    async def test_default_off_and_missing_site_grant_fail_before_backend(self) -> None:
        disabled_backend = FakeBackend(Backend.CHROMIUM)
        disabled = self._service(
            disabled_backend,
            available=False,
            suffix="disabled",
        )
        session_id, observation = await self._start_and_observe(disabled)
        with self.assertRaises(TermuinatorError) as unavailable:
            await disabled.devtools(
                session_id=session_id,
                tab_id=observation.tab_id,
                page_id=observation.page_id,
                expected_revision=observation.page_revision,
                query="console",
                parameters={},
            )
        self.assertEqual(
            unavailable.exception.code,
            ErrorCode.UNSUPPORTED_CAPABILITY,
        )
        self.assertEqual(disabled_backend.devtools_calls, [])

        session_id, observation = await self._start_and_observe(self.service)
        with self.assertRaises(TermuinatorError) as permission:
            await self.service.devtools(
                session_id=session_id,
                tab_id=observation.tab_id,
                page_id=observation.page_id,
                expected_revision=observation.page_revision,
                query="console",
                parameters={},
            )
        self.assertEqual(permission.exception.code, ErrorCode.PERMISSION_REQUIRED)
        self.assertEqual(self.backend.devtools_calls, [])

    async def test_local_origin_grant_enables_closed_read_only_queries(self) -> None:
        session_id, observation = await self._start_and_observe(self.service)
        decision = await self.service.local_developer_mode_set(
            session_id=session_id,
            origin="https://example.com/path-is-canonicalized",
            enabled=True,
        )
        self.assertTrue(decision.enabled)
        self.assertEqual(decision.origin, "https://example.com")
        target_ref = observation.interactive_elements[0].ref

        cases = (
            ("console", {"level": "error", "limit": 10}),
            ("network", {"url_filter": "/api", "limit": 10}),
            ("dom", {"target_ref": target_ref, "max_depth": 2}),
            ("style", {"target_ref": target_ref, "properties": ["color"]}),
            ("performance", {"scope": "summary"}),
        )
        results = []
        for query, parameters in cases:
            results.append(
                await self.service.devtools(
                    session_id=session_id,
                    tab_id=observation.tab_id,
                    page_id=observation.page_id,
                    expected_revision=observation.page_revision,
                    query=query,
                    parameters=parameters,
                )
            )

        self.assertEqual([item.query for item in results], [item[0] for item in cases])
        self.assertEqual(results[2].entries[0].ref, target_ref)
        serialized = repr([to_wire(item) for item in results])
        self.assertNotIn("private-save-button", serialized)
        self.assertNotIn("private-request-1", serialized)
        self.assertNotIn("super-secret-token", serialized)
        self.assertNotIn("hunter2", serialized)
        self.assertNotIn("user:pass", serialized)
        self.assertNotIn("query-secret", serialized)
        self.assertNotIn("visible", serialized)
        self.assertNotIn("#fragment", serialized)
        self.assertEqual(
            self.backend.devtools_calls[2].backend_node_id,
            "private-save-button",
        )
        self.assertEqual(
            self.backend.devtools_calls[3].backend_node_id,
            "private-save-button",
        )

        revoked = await self.service.local_developer_mode_set(
            session_id=session_id,
            origin="https://example.com",
            enabled=False,
        )
        self.assertFalse(revoked.enabled)
        with self.assertRaises(TermuinatorError) as denied:
            await self.service.devtools(
                session_id=session_id,
                tab_id=observation.tab_id,
                page_id=observation.page_id,
                expected_revision=observation.page_revision,
                query="console",
                parameters={},
            )
        self.assertEqual(denied.exception.code, ErrorCode.PERMISSION_REQUIRED)

    async def test_invalid_query_union_and_wrong_origin_grant_fail_closed(self) -> None:
        session_id, observation = await self._start_and_observe(self.service)
        with self.assertRaises(TermuinatorError) as wrong_origin:
            await self.service.local_developer_mode_set(
                session_id=session_id,
                origin="https://other.example",
                enabled=True,
            )
        self.assertEqual(wrong_origin.exception.code, ErrorCode.INVALID_REQUEST)

        await self.service.local_developer_mode_set(
            session_id=session_id,
            origin="https://example.com",
            enabled=True,
        )
        invalid_cases = (
            ("console", {"limit": True}),
            ("network", {"body": True}),
            ("dom", {"target_ref": "ref_unknown_abcdefgh", "max_depth": 2}),
            ("style", {"properties": ["color"]}),
            ("performance", {"scope": "raw-trace"}),
            ("eval", {"source": "document.cookie"}),
        )
        before = len(self.backend.devtools_calls)
        for query, parameters in invalid_cases:
            with self.subTest(query=query, parameters=parameters):
                with self.assertRaises(TermuinatorError) as invalid:
                    await self.service.devtools(
                        session_id=session_id,
                        tab_id=observation.tab_id,
                        page_id=observation.page_id,
                        expected_revision=observation.page_revision,
                        query=query,
                        parameters=parameters,
                    )
                self.assertIn(
                    invalid.exception.code,
                    {
                        ErrorCode.INVALID_REQUEST,
                        ErrorCode.STALE_OBSERVATION,
                        ErrorCode.TARGET_NOT_FOUND,
                    },
                )
        self.assertEqual(len(self.backend.devtools_calls), before)


if __name__ == "__main__":
    unittest.main()
