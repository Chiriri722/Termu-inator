"""Adversarial contract-freeze gates derived from the Phase 2 review."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
import unittest

from src.termuinator import contracts
from src.termuinator import schema as schema_module


def _contains_external_contract_ref(value: object) -> bool:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("contracts.schema.json"):
            return True
        return any(_contains_external_contract_ref(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_external_contract_ref(item) for item in value)
    return False


class ManifestFreezeTests(unittest.TestCase):
    def test_manifest_has_unambiguous_version_and_count_fields(self) -> None:
        manifest = schema_module.build_tool_manifest()
        self.assertTrue(manifest["$schema"].endswith("tool-manifest.schema.json"))
        self.assertTrue(manifest["$id"].endswith("tool-manifest.json"))
        self.assertEqual(manifest["manifest_version"], "1.0")
        self.assertEqual(manifest["contract_version"], "1.0")
        self.assertEqual(manifest["backend_protocol_version"], "1.0")
        self.assertEqual(manifest["mcp_protocol_version"], "2025-11-25")
        self.assertEqual(manifest["default_tool_count"], 14)
        self.assertEqual(manifest["max_tool_count"], 16)
        self.assertNotIn("default_tool_limit", manifest)
        manifest_schema = schema_module.build_manifest_schema()
        self.assertEqual(
            manifest_schema["$schema"],
            "https://json-schema.org/draft/2020-12/schema",
        )

    def test_every_public_output_is_strictly_defined(self) -> None:
        generic = []
        for tool in schema_module.build_tool_manifest()["tools"]:
            if tool["output_schema"] == {"type": "object"}:
                generic.append(tool["name"])
        self.assertEqual(generic, [])

    def test_internal_manifest_generates_actual_self_contained_mcp_tools(self) -> None:
        build_mcp_tools = getattr(schema_module, "build_mcp_tools", None)
        self.assertIsNotNone(build_mcp_tools)
        tools = build_mcp_tools()
        self.assertEqual(len(tools), 14)
        for tool in tools:
            self.assertEqual(
                set(tool),
                {"name", "description", "inputSchema", "outputSchema", "annotations"},
            )
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertEqual(tool["outputSchema"]["type"], "object")
            self.assertFalse(_contains_external_contract_ref(tool))

    def test_browser_act_advertises_durable_idempotency(self) -> None:
        tools = {tool["name"]: tool for tool in schema_module.build_mcp_tools()}
        self.assertTrue(tools["browser_act"]["annotations"]["idempotentHint"])

    def test_every_page_sensitive_input_has_full_revision_preconditions(self) -> None:
        manifest = {
            tool["name"]: tool["input_schema"]
            for tool in schema_module.build_tool_manifest()["tools"]
        }
        action = schema_module.build_contract_schema()["$defs"]["ActionRequest"]
        page_sensitive = {
            "browser_navigate": manifest["browser_navigate"]["oneOf"],
            "browser_observe": [manifest["browser_observe"]],
            "browser_act": action["oneOf"],
            "browser_wait": [manifest["browser_wait"]],
            "browser_screenshot": manifest["browser_screenshot"]["oneOf"],
            "browser_devtools": manifest["browser_devtools"]["oneOf"],
        }
        expected = {"session_id", "tab_id", "page_id", "expected_page_revision"}
        for tool_name, branches in page_sensitive.items():
            for branch in branches:
                with self.subTest(tool=tool_name):
                    self.assertTrue(expected <= set(branch["required"]))


class ActionAndErrorFreezeTests(unittest.TestCase):
    def test_action_schema_is_a_closed_discriminated_union(self) -> None:
        action = schema_module.build_contract_schema()["$defs"]["ActionRequest"]
        self.assertEqual(action["type"], "object")
        self.assertEqual(len(action["oneOf"]), 8)
        kinds = []
        for branch in action["oneOf"]:
            kinds.extend(branch["properties"]["kind"]["enum"])
            self.assertFalse(branch["additionalProperties"])
            self.assertFalse(branch["properties"]["parameters"]["additionalProperties"])
            self.assertNotIn("risk_context", branch["properties"])
            self.assertNotIn("confirmation_token", branch["properties"])
            self.assertIn("confirmation_id", branch["properties"])
        self.assertEqual(sorted(kinds), sorted(kind.value for kind in contracts.ActionKind))

    def test_action_request_model_matches_every_frozen_branch(self) -> None:
        action = schema_module.build_contract_schema()["$defs"]["ActionRequest"]
        model_fields = {item.name for item in fields(contracts.ActionRequest)}
        for branch in action["oneOf"]:
            self.assertEqual(model_fields, set(branch["properties"]))

    def test_domain_errors_and_terminal_action_status_do_not_overlap(self) -> None:
        action_status = schema_module.build_contract_schema()["$defs"]["ActionResult"]
        self.assertEqual(
            action_status["properties"]["status"]["enum"], ["succeeded", "failed"]
        )
        codes = {code.value for code in contracts.ErrorCode}
        for required in (
            "permission_denied",
            "session_paused",
            "ownership_denied",
            "idempotency_conflict",
            "outcome_unknown",
        ):
            self.assertIn(required, codes)

    def test_error_retryability_is_code_owned(self) -> None:
        mapping = contracts.ERROR_RETRYABLE
        self.assertEqual(set(mapping), set(contracts.ErrorCode))
        self.assertFalse(mapping[contracts.ErrorCode.OUTCOME_UNKNOWN])
        self.assertTrue(mapping[contracts.ErrorCode.SESSION_BUSY])
        with self.assertRaisesRegex(ValueError, "retryable"):
            contracts.ErrorEnvelope(
                code=contracts.ErrorCode.OUTCOME_UNKNOWN,
                message="The action may have executed",
                retryable=True,
            )

    def test_action_identifiers_follow_the_public_wire_pattern(self) -> None:
        with self.assertRaisesRegex(ValueError, "action_id"):
            contracts.ActionRequest(
                action_id="short",
                idempotency_key="idem_0001",
                session_id="session_01",
                tab_id="tab_00001",
                page_id="page_0001",
                expected_page_revision=contracts.PageRevision("doc_a1", 0),
                kind=contracts.ActionKind.SCROLL,
                parameters={"delta_y": 1},
            )

    def test_confirmation_identifier_follows_the_public_wire_pattern(self) -> None:
        with self.assertRaisesRegex(ValueError, "confirmation_id"):
            contracts.ActionRequest(
                action_id="action_01",
                idempotency_key="idem_0001",
                session_id="session_01",
                tab_id="tab_00001",
                page_id="page_0001",
                expected_page_revision=contracts.PageRevision("doc_a1", 0),
                kind=contracts.ActionKind.SCROLL,
                parameters={"delta_y": 1},
                confirmation_id="short",
            )

    def test_action_parameter_values_match_the_closed_union(self) -> None:
        invalid = (
            (contracts.ActionKind.CLICK, {"button": 1}, "button"),
            (contracts.ActionKind.TYPE, {"text": 123}, "text"),
            (contracts.ActionKind.KEY, {"key": "Enter", "modifiers": ["Hyper"]}, "modifier"),
            (contracts.ActionKind.SCROLL, {"delta_y": True}, "delta"),
            (contracts.ActionKind.SELECT, {"value": 1}, "value"),
            (contracts.ActionKind.CHECK, {"checked": "yes"}, "checked"),
        )
        for kind, parameters, message in invalid:
            with self.subTest(kind=kind.value), self.assertRaisesRegex(ValueError, message):
                contracts.ActionRequest(
                    action_id="action_01",
                    idempotency_key="idem_0001",
                    session_id="session_01",
                    tab_id="tab_00001",
                    page_id="page_0001",
                    expected_page_revision=contracts.PageRevision("doc_a1", 0),
                    kind=kind,
                    target_ref=(
                        "ref_0123456789abcdef"
                        if kind in contracts.TARGET_ACTIONS
                        else None
                    ),
                    parameters=parameters,
                )


class CapabilityAndLifecycleFreezeTests(unittest.TestCase):
    def test_session_models_match_the_frozen_wire_shapes(self) -> None:
        definitions = schema_module.build_contract_schema()["$defs"]
        for name in ("SessionStartResult", "SessionStatus", "SessionStopResult"):
            model = getattr(contracts, name, None)
            with self.subTest(model=name):
                self.assertIsNotNone(model)
                self.assertEqual(
                    {item.name for item in fields(model)},
                    set(definitions[name]["properties"]),
                )

    def test_verification_model_matches_the_frozen_wire_shape(self) -> None:
        definition = schema_module.build_contract_schema()["$defs"]["Verification"]
        self.assertEqual(
            {item.name for item in fields(contracts.Verification)},
            set(definition["properties"]),
        )

    def test_action_result_model_matches_the_frozen_wire_shape(self) -> None:
        definition = schema_module.build_contract_schema()["$defs"]["ActionResult"]
        self.assertEqual(
            {item.name for item in fields(contracts.ActionResult)},
            set(definition["properties"]),
        )

    def test_capability_limits_have_a_typed_wire_model(self) -> None:
        limit_model = getattr(contracts, "CapabilityLimit", None)
        self.assertIsNotNone(limit_model)
        definition = schema_module.build_contract_schema()["$defs"]["CapabilityLimit"]
        self.assertEqual(
            {item.name for item in fields(limit_model)},
            set(definition["properties"]),
        )

    def test_capability_limit_rejects_non_wire_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "name"):
            contracts.CapabilityLimit(name="Not Valid", value=True)
        with self.assertRaisesRegex(ValueError, "value"):
            contracts.CapabilityLimit(name="max_items", value={"nested": True})

    def test_verification_rejects_unknown_evidence_kind(self) -> None:
        with self.assertRaisesRegex(ValueError, "kind"):
            contracts.Verification(
                verification_id="verify_01",
                action_id="action_01",
                kind="invented",
                target_ref=None,
                passed=True,
                causal=True,
                expected_summary="expected",
                actual_summary="actual",
                observed_revision=contracts.PageRevision("doc_a1", 1),
                observed_at=datetime.now(timezone.utc).isoformat(),
            )

    def test_success_requires_passed_causal_verification(self) -> None:
        noncausal = contracts.Verification(
            verification_id="verify_01",
            action_id="action_01",
            kind="target_dispatch",
            target_ref=None,
            passed=True,
            causal=False,
            expected_summary="dispatch",
            actual_summary="dispatched",
            observed_revision=contracts.PageRevision("doc_a1", 1),
            observed_at=datetime.now(timezone.utc).isoformat(),
        )
        with self.assertRaisesRegex(ValueError, "causal"):
            contracts.ActionResult(
                status=contracts.ActionStatus.SUCCEEDED,
                before_revision=contracts.PageRevision("doc_a1", 0),
                after_revision=contracts.PageRevision("doc_a1", 1),
                executed_method="fake.click",
                verification=(noncausal,),
            )

    def test_capabilities_use_versioned_fidelity_records_not_booleans(self) -> None:
        definition = schema_module.build_contract_schema()["$defs"]["CapabilitySet"]
        self.assertNotIn("features", definition["properties"])
        self.assertIn("revision", definition["properties"])
        record = definition["properties"]["capabilities"]["items"]
        self.assertEqual(record["$ref"], "#/$defs/CapabilityRecord")
        states = schema_module.build_contract_schema()["$defs"]["CapabilityRecord"][
            "properties"
        ]["status"]["enum"]
        self.assertEqual(
            states, ["supported", "emulated", "partial", "unsupported", "broken"]
        )

    def test_artifact_identity_and_lifetime_are_runtime_invariants(self) -> None:
        now = datetime.now(timezone.utc)
        digest = "a" * 64
        valid = contracts.Artifact(
            uri=f"artifact://sha256/{digest}",
            sha256=digest,
            size_bytes=10,
            mime_type="image/png",
            created_at=now.isoformat(),
            expires_at=(now + timedelta(hours=1)).isoformat(),
        )
        with self.assertRaisesRegex(ValueError, "match"):
            replace(valid, sha256="b" * 64)
        with self.assertRaisesRegex(ValueError, "after"):
            replace(valid, expires_at=(now - timedelta(seconds=1)).isoformat())

    def test_permission_records_cannot_represent_persisted_ask_or_session_allow(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.assertRaisesRegex(ValueError, "ask"):
            contracts.PermissionDecision(
                project_id="project-a",
                origin="https://example.com",
                policy=contracts.PermissionPolicy.ASK,
                created_at=now,
                persistent=True,
            )
        with self.assertRaisesRegex(ValueError, "session_id"):
            contracts.PermissionDecision(
                project_id="project-a",
                origin="https://example.com",
                policy=contracts.PermissionPolicy.SESSION_ALLOW,
                created_at=now,
                persistent=False,
            )
        with self.assertRaisesRegex(ValueError, "memory-only"):
            contracts.PermissionDecision(
                project_id="project-a",
                origin="https://example.com",
                policy=contracts.PermissionPolicy.SESSION_ALLOW,
                created_at=now,
                session_id="session-a",
                persistent=True,
            )

    def test_observation_references_one_capability_revision(self) -> None:
        observation = schema_module.build_contract_schema()["$defs"]["Observation"]
        self.assertNotIn("capability_flags", observation["properties"])
        self.assertIn("capability_revision", observation["properties"])
        self.assertIn("text", observation["properties"])
        self.assertIn("text_truncated", observation["properties"])
        self.assertIn("accessibility", observation["properties"])


if __name__ == "__main__":
    unittest.main()
