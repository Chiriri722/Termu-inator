"""Contract and snapshot tests for the compact Termu-inator v1 surface."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import unittest

from src.termuinator.contracts import (
    ActionKind,
    ActionRequest,
    Backend,
    ErrorCode,
    ErrorEnvelope,
    PageRevision,
    RiskClass,
    RevisionDecision,
    classify_revision,
)
from src.termuinator.schema import (
    PUBLIC_TOOL_NAMES,
    build_contract_schema,
    build_manifest_schema,
    build_tool_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas" / "v1"


class ToolSurfaceTests(unittest.TestCase):
    def test_default_surface_is_exactly_fourteen_tools(self) -> None:
        self.assertEqual(
            PUBLIC_TOOL_NAMES,
            (
                "browser_session_start",
                "browser_session_status",
                "browser_session_stop",
                "browser_navigate",
                "browser_observe",
                "browser_act",
                "browser_wait",
                "browser_tabs",
                "browser_screenshot",
                "browser_downloads",
                "browser_artifact_read",
                "browser_permissions",
                "browser_devtools",
                "browser_trace",
            ),
        )
        self.assertEqual(len(PUBLIC_TOOL_NAMES), len(set(PUBLIC_TOOL_NAMES)))
        self.assertLessEqual(len(PUBLIC_TOOL_NAMES), 16)
        self.assertFalse(any("eval" in name or "upload" in name for name in PUBLIC_TOOL_NAMES))

    def test_manifest_locks_safe_defaults(self) -> None:
        manifest = build_tool_manifest()
        by_name = {tool["name"]: tool for tool in manifest["tools"]}
        start_schema = by_name["browser_session_start"]["input_schema"]
        self.assertEqual(start_schema["properties"]["backend"]["default"], "chromium")
        self.assertIn("project_id", start_schema["required"])

        artifact_schema = by_name["browser_artifact_read"]["input_schema"]
        self.assertEqual(artifact_schema["properties"]["limit"]["maximum"], 524288)

        permission_schema = by_name["browser_permissions"]["input_schema"]
        permission_operations = sorted(
            {
                operation
                for branch in permission_schema["oneOf"]
                for operation in branch["properties"]["operation"]["enum"]
            }
        )
        self.assertEqual(permission_operations, ["list", "status"])

        self.assertTrue(by_name["browser_devtools"]["developer_mode_required"])

    def test_artifact_reads_are_bound_to_the_active_session(self) -> None:
        manifest = build_tool_manifest()
        by_name = {tool["name"]: tool for tool in manifest["tools"]}
        artifact_schema = by_name["browser_artifact_read"]["input_schema"]

        self.assertIn("session_id", artifact_schema["properties"])
        self.assertIn("session_id", artifact_schema["required"])

    def test_multiplexed_tools_encode_operation_specific_requirements(self) -> None:
        manifest = build_tool_manifest()
        by_name = {tool["name"]: tool for tool in manifest["tools"]}

        expected = {
            "browser_navigate": {"goto": "url"},
            "browser_tabs": {"open": "url", "switch": "tab_id", "close": "tab_id"},
            "browser_screenshot": {"element": "target_ref"},
            "browser_permissions": {"status": "challenge_id"},
            "browser_trace": {"get": "trace_id", "export": "trace_id"},
        }
        for tool_name, requirements in expected.items():
            branches = by_name[tool_name]["input_schema"]["oneOf"]
            for operation, required_field in requirements.items():
                matching = [
                    branch
                    for branch in branches
                    if operation in branch["properties"][
                        "operation" if tool_name != "browser_screenshot" else "mode"
                    ]["enum"]
                ]
                self.assertEqual(len(matching), 1, (tool_name, operation))
                self.assertIn(required_field, matching[0]["required"])


class RevisionContractTests(unittest.TestCase):
    def test_page_revision_round_trip(self) -> None:
        revision = PageRevision(document_epoch="doc_a1", mutation_counter=42)
        self.assertEqual(str(revision), "doc_a1:42")
        self.assertEqual(PageRevision.parse(str(revision)), revision)

    def test_document_change_is_always_stale(self) -> None:
        before = PageRevision("doc_a1", 2)
        after = PageRevision("doc_b2", 0)
        for risk in RiskClass:
            self.assertEqual(
                classify_revision(before, after, risk, fingerprint_matches=True),
                RevisionDecision.STALE,
            )

    def test_only_low_risk_dom_change_can_be_revalidated(self) -> None:
        before = PageRevision("doc_a1", 2)
        after = PageRevision("doc_a1", 3)
        self.assertEqual(
            classify_revision(before, after, RiskClass.R1, fingerprint_matches=True),
            RevisionDecision.REVALIDATE,
        )
        self.assertEqual(
            classify_revision(before, after, RiskClass.R2, fingerprint_matches=True),
            RevisionDecision.STALE,
        )
        self.assertEqual(
            classify_revision(before, after, RiskClass.R0, fingerprint_matches=False),
            RevisionDecision.STALE,
        )


class ModelValidationTests(unittest.TestCase):
    def test_target_action_requires_observation_ref(self) -> None:
        with self.assertRaisesRegex(ValueError, "target_ref"):
            ActionRequest(
                action_id="action_01",
                idempotency_key="idem_0001",
                session_id="session_1",
                tab_id="tab_00001",
                page_id="page_0001",
                expected_page_revision=PageRevision("doc_a1", 0),
                kind=ActionKind.CLICK,
            )

    def test_non_target_scroll_is_valid(self) -> None:
        request = ActionRequest(
            action_id="action_01",
            idempotency_key="idem_0001",
            session_id="session_1",
            tab_id="tab_00001",
            page_id="page_0001",
            expected_page_revision=PageRevision("doc_a1", 0),
            kind=ActionKind.SCROLL,
            parameters={"delta_y": 500},
        )
        self.assertEqual(request.risk, RiskClass.R1)

    def test_caller_context_cannot_lower_server_owned_risk(self) -> None:
        with self.assertRaisesRegex(TypeError, "risk_context"):
            ActionRequest(
                action_id="action_01",
                idempotency_key="idem_0001",
                session_id="session_1",
                tab_id="tab_00001",
                page_id="page_0001",
                expected_page_revision=PageRevision("doc_a1", 0),
                kind=ActionKind.CLICK,
                target_ref="ref_0123456789abcdef",
                risk_context={"risk_class": "R0"},
            )

    def test_target_ref_requirement_is_in_the_public_schema(self) -> None:
        action_schema = build_contract_schema()["$defs"]["ActionRequest"]
        branches = {
            branch["properties"]["kind"]["enum"][0]: branch
            for branch in action_schema["oneOf"]
        }
        target_kinds = {"click", "type", "select", "check", "hover", "drag"}
        self.assertEqual(target_kinds, target_kinds & branches.keys())
        for kind in target_kinds:
            self.assertIn("target_ref", branches[kind]["required"])
            self.assertEqual(
                branches[kind]["properties"]["target_ref"]["type"], "string"
            )

    def test_error_envelope_is_stable_and_serializable(self) -> None:
        error = ErrorEnvelope(
            code=ErrorCode.UNSUPPORTED_CAPABILITY,
            message="Firefox does not expose network response bodies",
            retryable=False,
            details={"backend": Backend.FIREFOX.value},
            diagnostics_id="diag_1",
        )
        payload = asdict(error)
        payload["code"] = error.code.value
        self.assertEqual(payload["code"], "unsupported_capability")
        json.dumps(payload)


class ContractSnapshotTests(unittest.TestCase):
    def test_contract_schema_snapshot(self) -> None:
        expected = json.loads((SCHEMAS / "contracts.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(build_contract_schema(), expected)

    def test_tool_manifest_snapshot(self) -> None:
        expected = json.loads((SCHEMAS / "tool-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(build_tool_manifest(), expected)

    def test_tool_manifest_schema_snapshot(self) -> None:
        expected = json.loads(
            (SCHEMAS / "tool-manifest.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(build_manifest_schema(), expected)

    def test_rfc_documents_lock_all_approved_boundaries(self) -> None:
        architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        contracts = (ROOT / "docs" / "tool-contracts.md").read_text(encoding="utf-8")
        security = (ROOT / "docs" / "security-model.md").read_text(encoding="utf-8")
        combined = "\n".join((architecture, contracts, security))
        for expected in (
            "Chromium is the default backend",
            "single active session",
            "project-scoped persistent profiles",
            "120 seconds",
            "512 KiB",
            "read-only shared view",
            "raw eval",
            "untrusted input",
            "v0.x",
            "MCP Tool Execution",
            "server-held",
            "outcome_unknown",
            "before following every redirect",
            "user_takeover_active",
            "profiles/<backend>/v1/profile",
            "Cache-Control: no-store",
            "inputSchema",
            "Form elicitation",
        ):
            self.assertIn(expected, combined)

    def test_backend_target_and_legacy_lifetime_are_explicit(self) -> None:
        capabilities = (ROOT / "docs" / "backend-capabilities.md").read_text(
            encoding="utf-8"
        )
        migration = (ROOT / "docs" / "migration-from-tbp.md").read_text(
            encoding="utf-8"
        )
        for expected in (
            "default_backend: chromium",
            "automatic fallback: forbidden",
            "unsupported_capability",
        ):
            self.assertIn(expected, capabilities)
        for expected in (
            "v0.1",
            "v0.2",
            "v0.3",
            "--legacy",
            "separate v1 migration",
        ):
            self.assertIn(expected, migration)


if __name__ == "__main__":
    unittest.main()
