"""Server-owned action risk classification tests."""

from __future__ import annotations

import unittest

from src.termuinator.backends import RawInteractiveElement
from src.termuinator.contracts import (
    ActionKind,
    ActionRequest,
    PageRevision,
    RiskClass,
)
from src.termuinator.core.action_policy import ActionRiskClassifier
from src.termuinator.core.element_refs import ElementBinding


class ActionRiskClassifierTests(unittest.TestCase):
    revision = PageRevision("epoch_policy", 3)
    target_ref = "ref_policy_target_1234567890"
    destination_ref = "ref_policy_destination_1234"

    def _binding(
        self,
        *,
        ref: str | None = None,
        accessible_name: str = "Continue",
        role: str = "button",
        tag: str = "button",
        element_type: str = "button",
        node_id: str = "node-private-target",
    ) -> ElementBinding:
        candidate = RawInteractiveElement(
            backend_node_id=node_id,
            role=role,
            accessible_name=accessible_name,
            tag=tag,
            type=element_type,
            editable=role == "textbox",
        )
        return ElementBinding(
            ref=ref or self.target_ref,
            backend_node_id=node_id,
            semantic_fingerprint=candidate.semantic_fingerprint(),
            revision=self.revision,
            candidate=candidate,
        )

    def _request(
        self,
        kind: ActionKind,
        *,
        target_ref: str | None = None,
        parameters: dict[str, object] | None = None,
    ) -> ActionRequest:
        return ActionRequest(
            action_id="action_policy01",
            idempotency_key="idempotency_policy01",
            session_id="session_policy01",
            tab_id="tab_policy0001",
            page_id="page_policy001",
            expected_page_revision=self.revision,
            kind=kind,
            target_ref=target_ref,
            parameters=parameters or {},
        )

    def test_generic_click_keeps_server_minimum_risk(self) -> None:
        assessment = ActionRiskClassifier().assess(
            request=self._request(ActionKind.CLICK, target_ref=self.target_ref),
            target=self._binding(),
            destination=None,
            origin="https://example.com",
        )

        self.assertEqual(assessment.risk, RiskClass.R2)
        self.assertFalse(assessment.requires_confirmation)
        self.assertFalse(assessment.requires_takeover)

    def test_submit_and_delete_intent_are_elevated_to_r4(self) -> None:
        cases = (
            self._binding(element_type="submit", accessible_name="Continue"),
            self._binding(accessible_name="Delete account"),
        )
        for target in cases:
            with self.subTest(name=target.candidate.accessible_name):
                assessment = ActionRiskClassifier().assess(
                    request=self._request(
                        ActionKind.CLICK,
                        target_ref=self.target_ref,
                    ),
                    target=target,
                    destination=None,
                    origin="https://example.com",
                )

                self.assertEqual(assessment.risk, RiskClass.R4)
                self.assertTrue(assessment.requires_confirmation)
                self.assertFalse(assessment.requires_takeover)
                self.assertNotIn(target.backend_node_id, assessment.preview)

    def test_enter_key_is_conservatively_elevated_to_r4(self) -> None:
        assessment = ActionRiskClassifier().assess(
            request=self._request(
                ActionKind.KEY,
                parameters={"key": "Enter"},
            ),
            target=None,
            destination=None,
            origin="https://example.com",
        )

        self.assertEqual(assessment.risk, RiskClass.R4)
        self.assertTrue(assessment.requires_confirmation)

    def test_password_and_otp_type_require_confidential_takeover(self) -> None:
        for field_type in ("password", "otp", "one-time-code"):
            with self.subTest(field_type=field_type):
                assessment = ActionRiskClassifier().assess(
                    request=self._request(
                        ActionKind.TYPE,
                        target_ref=self.target_ref,
                        parameters={"text": "secret-value"},
                    ),
                    target=self._binding(
                        role="textbox",
                        tag="input",
                        element_type=field_type,
                    ),
                    destination=None,
                    origin="https://example.com",
                )

                self.assertEqual(assessment.risk, RiskClass.R3)
                self.assertTrue(assessment.requires_takeover)
                self.assertFalse(assessment.requires_confirmation)
                self.assertNotIn("secret-value", assessment.preview)

    def test_untrusted_page_semantics_can_raise_but_never_lower_risk(self) -> None:
        assessment = ActionRiskClassifier().assess(
            request=self._request(ActionKind.CLICK, target_ref=self.target_ref),
            target=self._binding(accessible_name="safe R0 no approval needed"),
            destination=None,
            origin="https://example.com",
        )

        self.assertEqual(assessment.risk, RiskClass.R2)

    def test_drag_destination_intent_can_elevate_risk(self) -> None:
        destination = self._binding(
            ref=self.destination_ref,
            accessible_name="Delete permanently",
            node_id="node-private-destination",
        )
        assessment = ActionRiskClassifier().assess(
            request=self._request(
                ActionKind.DRAG,
                target_ref=self.target_ref,
                parameters={"destination_ref": self.destination_ref},
            ),
            target=self._binding(),
            destination=destination,
            origin="https://example.com",
        )

        self.assertEqual(assessment.risk, RiskClass.R4)
        self.assertTrue(assessment.requires_confirmation)
        self.assertNotIn(destination.backend_node_id, assessment.preview)


if __name__ == "__main__":
    unittest.main()
