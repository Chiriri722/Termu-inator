"""Compact MCP v1 routing and schema-projection tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from src.termuinator.contracts import (
    ActionKind,
    ActionRequest,
    Artifact,
    ArtifactChunk,
    Download,
    DownloadsResult,
    ConsoleEntry,
    DevtoolsResult,
    ErrorCode,
    PageRevision,
    PermissionsResult,
    RiskClass,
    Tab,
    TabsResult,
    TraceExportResult,
    TraceRecord,
    TraceRecordsResult,
    WaitDownloadCondition,
    WaitNavigationCondition,
    WaitRefStateCondition,
    WaitResult,
    WaitTextCondition,
    WaitUrlCondition,
)
from src.termuinator.errors import TermuinatorError
from src.termuinator.mcp_v1 import CompactV1Router, compact_tool_definitions
from src.termuinator.schema import PUBLIC_TOOL_NAMES, build_mcp_tools


def _artifact() -> Artifact:
    created = datetime(2026, 8, 24, tzinfo=timezone.utc)
    digest = "a" * 64
    return Artifact(
        uri=f"artifact://sha256/{digest}",
        sha256=digest,
        size_bytes=4,
        mime_type="image/png",
        created_at=created.isoformat(),
        expires_at=(created + timedelta(minutes=2)).isoformat(),
    )


class _Service:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def artifact_read(self, **kwargs: object) -> ArtifactChunk:
        self.calls.append(("artifact_read", kwargs))
        return ArtifactChunk(
            uri=str(kwargs["uri"]),
            offset=int(kwargs["offset"]),
            next_offset=int(kwargs["offset"]) + 4,
            eof=True,
            data_base64="aW1hZw==",
        )

    async def navigate(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("navigate", kwargs))
        return {
            "operation": kwargs["operation"],
            "url": kwargs.get("url"),
        }

    async def screenshot(self, **kwargs: object) -> Artifact:
        self.calls.append(("screenshot", kwargs))
        return _artifact()

    async def act(self, request: ActionRequest) -> ActionRequest:
        self.calls.append(("act", {"request": request}))
        return request

    async def permissions(self, **kwargs: object) -> PermissionsResult:
        self.calls.append(("permissions", kwargs))
        return PermissionsResult(
            operation="list",
            decisions=(),
            challenge=None,
        )

    async def trace(self, **kwargs: object) -> object:
        self.calls.append(("trace", kwargs))
        operation = str(kwargs["operation"])
        if operation == "export":
            return TraceExportResult(operation="export", artifact=_artifact())
        record = TraceRecord(
            trace_id="trace_abcdefgh",
            step_id="step_abcdefgh",
            action_kind="click",
            risk=RiskClass.R2,
            page_revision=PageRevision("epoch_abc", 2),
            permission="session_allow",
            verification_passed=True,
            started_at="2026-08-24T00:00:00+00:00",
            duration_ms=12,
        )
        return TraceRecordsResult(
            operation=operation,
            traces=(record,),
            truncated=False,
        )

    async def wait(self, **kwargs: object) -> WaitResult:
        self.calls.append(("wait", kwargs))
        condition = kwargs["condition"]
        return WaitResult(
            condition_kind=condition.kind,
            satisfied=True,
            elapsed_ms=0,
            observation=None,
            download=None,
        )

    async def tabs(self, **kwargs: object) -> TabsResult:
        self.calls.append(("tabs", kwargs))
        operation = str(kwargs["operation"])
        tab = Tab(
            tab_id="tab_abcdefgh",
            page_id="page_abcdefgh",
            url=str(kwargs.get("url") or "https://example.com/"),
            title="Example",
            active=True,
            page_revision=PageRevision("epoch_tabs", 1),
        )
        return TabsResult(
            operation=operation,
            tabs=(tab,),
            active_tab_id=tab.tab_id,
            observation=None,
        )

    async def downloads(self, **kwargs: object) -> DownloadsResult:
        self.calls.append(("downloads", kwargs))
        download_id = str(kwargs.get("download_id") or "download_abcdefgh")
        return DownloadsResult(
            operation=str(kwargs["operation"]),
            downloads=(
                Download(
                    download_id=download_id,
                    state="completed",
                    filename="report.pdf",
                    mime_type="application/pdf",
                    size_bytes=4,
                    artifact_uri="artifact://sha256/" + "b" * 64,
                    reason_code=None,
                ),
            ),
        )

    async def devtools(self, **kwargs: object) -> DevtoolsResult:
        self.calls.append(("devtools", kwargs))
        return DevtoolsResult(
            query=str(kwargs["query"]),
            entries=(
                ConsoleEntry(
                    level="info",
                    message="ready",
                    timestamp="2026-08-24T00:00:00+00:00",
                ),
            ),
            truncated=False,
        )


class CompactV1TransportTests(unittest.IsolatedAsyncioTestCase):
    def test_tool_projection_is_exactly_the_reviewed_self_contained_surface(self) -> None:
        definitions = compact_tool_definitions()

        self.assertEqual(definitions, build_mcp_tools())
        self.assertEqual(
            tuple(tool["name"] for tool in definitions),
            PUBLIC_TOOL_NAMES,
        )
        self.assertEqual(len(definitions), 14)
        serialized = repr(definitions)
        self.assertNotIn("contracts.schema.json", serialized)
        self.assertNotIn('"$ref"', serialized)

    async def test_artifact_read_uses_schema_defaults_and_active_session(self) -> None:
        service = _Service()
        router = CompactV1Router(service)
        uri = "artifact://sha256/" + "a" * 64

        result = await router.dispatch(
            "browser_artifact_read",
            {"session_id": "session_abcdefgh", "uri": uri},
        )

        self.assertEqual(
            service.calls,
            [
                (
                    "artifact_read",
                    {
                        "session_id": "session_abcdefgh",
                        "uri": uri,
                        "offset": 0,
                        "limit": 512 * 1024,
                    },
                )
            ],
        )
        self.assertEqual(result["data_base64"], "aW1hZw==")
        self.assertTrue(result["eof"])

    async def test_screenshot_and_act_decode_page_revision_and_closed_action(self) -> None:
        service = _Service()
        router = CompactV1Router(service)

        screenshot = await router.dispatch(
            "browser_screenshot",
            {
                "session_id": "session_abcdefgh",
                "tab_id": "tab_abcdefgh",
                "page_id": "page_abcdefgh",
                "expected_page_revision": "epoch_abc:2",
            },
        )
        acted = await router.dispatch(
            "browser_act",
            {
                "action_id": "action_abcdefgh",
                "idempotency_key": "key_abcdefgh",
                "session_id": "session_abcdefgh",
                "tab_id": "tab_abcdefgh",
                "page_id": "page_abcdefgh",
                "expected_page_revision": "epoch_abc:2",
                "kind": "key",
                "target_ref": None,
                "parameters": {"key": "Enter", "modifiers": []},
                "timeout_ms": 30000,
                "confirmation_id": None,
            },
        )

        self.assertEqual(screenshot["mime_type"], "image/png")
        screenshot_call = service.calls[0][1]
        self.assertEqual(screenshot_call["mode"], "viewport")
        self.assertEqual(
            screenshot_call["expected_revision"],
            PageRevision("epoch_abc", 2),
        )
        request = service.calls[1][1]["request"]
        self.assertIsInstance(request, ActionRequest)
        self.assertEqual(request.kind, ActionKind.KEY)
        self.assertEqual(acted["expected_page_revision"], "epoch_abc:2")

    async def test_navigate_transport_decodes_the_exact_operation_union(self) -> None:
        service = _Service()
        router = CompactV1Router(service)
        base = {
            "session_id": "session_abcdefgh",
            "tab_id": "tab_abcdefgh",
            "page_id": "page_abcdefgh",
            "expected_page_revision": "epoch_abc:2",
        }

        goto = await router.dispatch(
            "browser_navigate",
            {
                **base,
                "operation": "goto",
                "url": "https://example.com/new",
                "timeout_ms": 250,
            },
        )
        reload = await router.dispatch(
            "browser_navigate",
            {**base, "operation": "reload"},
        )

        self.assertEqual(goto["operation"], "goto")
        self.assertEqual(reload["operation"], "reload")
        self.assertEqual(
            service.calls,
            [
                (
                    "navigate",
                    {
                        "session_id": "session_abcdefgh",
                        "tab_id": "tab_abcdefgh",
                        "page_id": "page_abcdefgh",
                        "expected_revision": PageRevision("epoch_abc", 2),
                        "operation": "goto",
                        "url": "https://example.com/new",
                        "timeout_ms": 250,
                    },
                ),
                (
                    "navigate",
                    {
                        "session_id": "session_abcdefgh",
                        "tab_id": "tab_abcdefgh",
                        "page_id": "page_abcdefgh",
                        "expected_revision": PageRevision("epoch_abc", 2),
                        "operation": "reload",
                        "url": None,
                        "timeout_ms": 30_000,
                    },
                ),
            ],
        )

        invalid_arguments = (
            {**base, "operation": "goto"},
            {**base, "operation": "goto", "url": "javascript:alert(1)"},
            {**base, "operation": "reload", "url": "https://example.com"},
            {**base, "operation": "delete"},
            {**base, "operation": "back", "timeout_ms": True},
        )
        for arguments in invalid_arguments:
            with self.assertRaises(TermuinatorError) as invalid:
                await router.dispatch("browser_navigate", arguments)
            self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)

    async def test_invalid_wire_values_and_unknown_tools_fail_structured(self) -> None:
        router = CompactV1Router(_Service())

        with self.assertRaises(TermuinatorError) as invalid:
            await router.dispatch(
                "browser_artifact_read",
                {
                    "session_id": "session_abcdefgh",
                    "uri": "artifact://sha256/" + "a" * 64,
                    "offset": True,
                },
            )
        self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)

        with self.assertRaises(TermuinatorError) as unknown:
            await router.dispatch(
                "browser_raw_cdp",
                {},
            )
        self.assertEqual(
            unknown.exception.code,
            ErrorCode.INVALID_REQUEST,
        )

        envelope = CompactV1Router.error_payload(unknown.exception)
        self.assertEqual(envelope["code"], "invalid_request")
        self.assertFalse(envelope["retryable"])
        self.assertEqual(envelope["details"]["capability"], "browser_raw_cdp")

    async def test_download_transport_decodes_the_exact_operation_union(self) -> None:
        service = _Service()
        router = CompactV1Router(service)

        listed = await router.dispatch(
            "browser_downloads",
            {"session_id": "session_abcdefgh", "operation": "list"},
        )
        waited = await router.dispatch(
            "browser_downloads",
            {
                "session_id": "session_abcdefgh",
                "operation": "wait",
                "download_id": "download_abcdefgh",
            },
        )

        self.assertEqual(
            service.calls,
            [
                (
                    "downloads",
                    {
                        "session_id": "session_abcdefgh",
                        "operation": "list",
                        "download_id": None,
                    },
                ),
                (
                    "downloads",
                    {
                        "session_id": "session_abcdefgh",
                        "operation": "wait",
                        "download_id": "download_abcdefgh",
                    },
                ),
            ],
        )
        self.assertEqual(listed["operation"], "list")
        self.assertEqual(waited["downloads"][0]["state"], "completed")

        invalid_arguments = (
            {
                "session_id": "session_abcdefgh",
                "operation": "list",
                "download_id": "download_abcdefgh",
            },
            {"session_id": "session_abcdefgh", "operation": "wait"},
            {
                "session_id": "session_abcdefgh",
                "operation": "wait",
                "download_id": True,
            },
            {"session_id": "session_abcdefgh", "operation": "delete"},
        )
        for arguments in invalid_arguments:
            with self.assertRaises(TermuinatorError) as invalid:
                await router.dispatch("browser_downloads", arguments)
            self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)

    async def test_tabs_transport_decodes_the_exact_operation_union(self) -> None:
        service = _Service()
        router = CompactV1Router(service)
        cases = (
            (
                {"session_id": "session_abcdefgh", "operation": "list"},
                {"session_id": "session_abcdefgh", "operation": "list", "tab_id": None, "url": None},
            ),
            (
                {
                    "session_id": "session_abcdefgh",
                    "operation": "open",
                    "url": "https://example.com/new",
                },
                {
                    "session_id": "session_abcdefgh",
                    "operation": "open",
                    "tab_id": None,
                    "url": "https://example.com/new",
                },
            ),
            (
                {
                    "session_id": "session_abcdefgh",
                    "operation": "switch",
                    "tab_id": "tab_abcdefgh",
                },
                {
                    "session_id": "session_abcdefgh",
                    "operation": "switch",
                    "tab_id": "tab_abcdefgh",
                    "url": None,
                },
            ),
            (
                {
                    "session_id": "session_abcdefgh",
                    "operation": "close",
                    "tab_id": "tab_abcdefgh",
                },
                {
                    "session_id": "session_abcdefgh",
                    "operation": "close",
                    "tab_id": "tab_abcdefgh",
                    "url": None,
                },
            ),
        )
        for arguments, expected in cases:
            result = await router.dispatch("browser_tabs", arguments)
            self.assertEqual(service.calls[-1], ("tabs", expected))
            self.assertEqual(result["operation"], arguments["operation"])
            self.assertEqual(result["active_tab_id"], "tab_abcdefgh")

        invalid_arguments = (
            {
                "session_id": "session_abcdefgh",
                "operation": "list",
                "tab_id": "tab_abcdefgh",
            },
            {"session_id": "session_abcdefgh", "operation": "open"},
            {
                "session_id": "session_abcdefgh",
                "operation": "open",
                "url": True,
            },
            {"session_id": "session_abcdefgh", "operation": "switch"},
            {
                "session_id": "session_abcdefgh",
                "operation": "close",
                "tab_id": "tab_abcdefgh",
                "url": "https://example.com",
            },
            {"session_id": "session_abcdefgh", "operation": "delete"},
        )
        for arguments in invalid_arguments:
            with self.assertRaises(TermuinatorError) as invalid:
                await router.dispatch("browser_tabs", arguments)
            self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)

    async def test_devtools_transport_preserves_the_exact_read_only_union(self) -> None:
        service = _Service()
        router = CompactV1Router(service)
        base = {
            "session_id": "session_abcdefgh",
            "tab_id": "tab_abcdefgh",
            "page_id": "page_abcdefgh",
            "expected_page_revision": "epoch_abc:2",
            "query": "console",
            "parameters": {"level": "info", "limit": 10},
        }

        result = await router.dispatch("browser_devtools", base)

        self.assertEqual(result["query"], "console")
        self.assertEqual(result["entries"][0]["message"], "ready")
        self.assertEqual(
            service.calls,
            [
                (
                    "devtools",
                    {
                        "session_id": "session_abcdefgh",
                        "tab_id": "tab_abcdefgh",
                        "page_id": "page_abcdefgh",
                        "expected_revision": PageRevision("epoch_abc", 2),
                        "query": "console",
                        "parameters": {"level": "info", "limit": 10},
                    },
                )
            ],
        )

        invalid_arguments = (
            {**base, "parameters": {"body": True}},
            {**base, "query": "eval", "parameters": {"source": "1+1"}},
            {**base, "extra": "smuggled"},
            {**base, "parameters": []},
        )
        for arguments in invalid_arguments:
            with self.assertRaises(TermuinatorError) as invalid:
                await router.dispatch("browser_devtools", arguments)
            self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)

    async def test_permissions_transport_is_read_only_and_union_exact(self) -> None:
        service = _Service()
        router = CompactV1Router(service)

        result = await router.dispatch(
            "browser_permissions",
            {"session_id": "session_abcdefgh", "operation": "list"},
        )

        self.assertEqual(
            service.calls,
            [
                (
                    "permissions",
                    {
                        "session_id": "session_abcdefgh",
                        "operation": "list",
                        "challenge_id": None,
                    },
                )
            ],
        )
        self.assertEqual(
            result,
            {"operation": "list", "decisions": [], "challenge": None},
        )

        with self.assertRaises(TermuinatorError) as invalid:
            await router.dispatch(
                "browser_permissions",
                {
                    "session_id": "session_abcdefgh",
                    "operation": "grant",
                },
            )
        self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)

    async def test_trace_transport_is_exact_list_get_export_union(self) -> None:
        service = _Service()
        router = CompactV1Router(service)

        listed = await router.dispatch(
            "browser_trace",
            {"session_id": "session_abcdefgh", "operation": "list"},
        )
        fetched = await router.dispatch(
            "browser_trace",
            {
                "session_id": "session_abcdefgh",
                "operation": "get",
                "trace_id": "trace_abcdefgh",
            },
        )
        exported = await router.dispatch(
            "browser_trace",
            {
                "session_id": "session_abcdefgh",
                "operation": "export",
                "trace_id": "trace_abcdefgh",
            },
        )

        self.assertEqual(listed["operation"], "list")
        self.assertEqual(listed["traces"][0]["risk"], "R2")
        self.assertEqual(fetched["operation"], "get")
        self.assertEqual(exported["operation"], "export")
        self.assertEqual(
            service.calls,
            [
                (
                    "trace",
                    {
                        "session_id": "session_abcdefgh",
                        "operation": "list",
                        "trace_id": None,
                    },
                ),
                (
                    "trace",
                    {
                        "session_id": "session_abcdefgh",
                        "operation": "get",
                        "trace_id": "trace_abcdefgh",
                    },
                ),
                (
                    "trace",
                    {
                        "session_id": "session_abcdefgh",
                        "operation": "export",
                        "trace_id": "trace_abcdefgh",
                    },
                ),
            ],
        )

        invalid_arguments = (
            {
                "session_id": "session_abcdefgh",
                "operation": "list",
                "trace_id": "trace_abcdefgh",
            },
            {"session_id": "session_abcdefgh", "operation": "get"},
            {"session_id": "session_abcdefgh", "operation": "delete"},
            {
                "session_id": "session_abcdefgh",
                "operation": "get",
                "trace_id": "trace_abcdefgh",
                "unexpected": True,
            },
        )
        for arguments in invalid_arguments:
            with self.assertRaises(TermuinatorError) as invalid:
                await router.dispatch("browser_trace", arguments)
            self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)

    async def test_wait_transport_decodes_all_closed_condition_branches(self) -> None:
        service = _Service()
        router = CompactV1Router(service)
        base = {
            "session_id": "session_abcdefgh",
            "tab_id": "tab_abcdefgh",
            "page_id": "page_abcdefgh",
            "expected_page_revision": "epoch_abc:2",
        }
        cases = (
            (
                {"kind": "url", "url": "https://example.com/ready"},
                WaitUrlCondition,
            ),
            ({"kind": "text", "text": "ready"}, WaitTextCondition),
            (
                {
                    "kind": "ref_state",
                    "target_ref": "ref_abcdefghijklmnop",
                    "state": "visible",
                },
                WaitRefStateCondition,
            ),
            (
                {"kind": "navigation", "from_revision": "epoch_abc:2"},
                WaitNavigationCondition,
            ),
            (
                {"kind": "download", "download_id": "download_abcdefgh"},
                WaitDownloadCondition,
            ),
        )

        for condition, expected_type in cases:
            result = await router.dispatch(
                "browser_wait",
                {**base, "condition": condition, "timeout_ms": 250},
            )
            call = service.calls[-1]
            self.assertEqual(call[0], "wait")
            self.assertIsInstance(call[1]["condition"], expected_type)
            self.assertEqual(call[1]["timeout_ms"], 250)
            self.assertEqual(result["condition_kind"], condition["kind"])

        text_condition = service.calls[1][1]["condition"]
        self.assertTrue(text_condition.present)
        navigation_condition = service.calls[3][1]["condition"]
        self.assertEqual(
            navigation_condition.from_revision,
            PageRevision("epoch_abc", 2),
        )

        invalid_conditions = (
            {"kind": "text", "text": "ready", "unexpected": True},
            {"kind": "url"},
            {"kind": "ref_state", "target_ref": "ref_abcdefghijklmnop"},
            {"kind": "navigation", "from_revision": True},
            {"kind": "download", "download_id": "download_abcdefgh", "url": "x"},
            {"kind": "unknown"},
        )
        for condition in invalid_conditions:
            with self.assertRaises(TermuinatorError) as invalid:
                await router.dispatch(
                    "browser_wait",
                    {**base, "condition": condition},
                )
            self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)

        with self.assertRaises(TermuinatorError) as outer_extra:
            await router.dispatch(
                "browser_wait",
                {
                    **base,
                    "condition": {"kind": "text", "text": "ready"},
                    "unexpected": True,
                },
            )
        self.assertEqual(outer_extra.exception.code, ErrorCode.INVALID_REQUEST)


if __name__ == "__main__":
    unittest.main()
