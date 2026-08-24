"""Resolved backend dispatch and service-owned causal verification."""

from __future__ import annotations

import secrets
from typing import Protocol

from ..backends.base import BackendAction, BackendActionOutcome
from ..contracts import (
    ActionKind,
    ActionRequest,
    ActionResult,
    ActionStatus,
    ErrorCode,
    PageRevision,
    RiskClass,
    Verification,
)
from ..errors import TermuinatorError
from .element_refs import ElementBinding
from .observation import ObservationEngine


class BackendActionPort(Protocol):
    async def act(self, action: BackendAction) -> BackendActionOutcome:
        ...


class ActionExecutor:
    """Resolve refs, dispatch private handles, and verify observed effects."""

    async def execute(
        self,
        *,
        request: ActionRequest,
        backend: BackendActionPort,
        observation: ObservationEngine,
        target_binding: ElementBinding | None = None,
        destination_binding: ElementBinding | None = None,
        effective_risk: RiskClass | None = None,
    ) -> ActionResult:
        before = observation.last_observation
        if before is None:
            raise TermuinatorError(
                ErrorCode.STALE_OBSERVATION,
                "An action requires a prior page observation",
            )
        observation.require_context(
            session_id=request.session_id,
            tab_id=request.tab_id,
            page_id=request.page_id,
            expected_revision=request.expected_page_revision,
        )

        risk = effective_risk or request.risk
        if not isinstance(risk, RiskClass):
            raise TypeError("effective_risk must be a RiskClass")
        binding = target_binding
        if request.target_ref is not None:
            if binding is None:
                binding = observation.resolve_ref(
                    ref=request.target_ref,
                    expected_revision=request.expected_page_revision,
                    risk=risk,
                )
            elif binding.ref != request.target_ref:
                raise TermuinatorError(
                    ErrorCode.TARGET_NOT_FOUND,
                    "The resolved action target does not match target_ref",
                )
        elif binding is not None:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "An action without target_ref cannot receive a resolved target",
            )
        destination = destination_binding
        if request.kind is ActionKind.DRAG:
            destination_ref = request.parameters["destination_ref"]
            if destination is None:
                destination = observation.resolve_ref(
                    ref=destination_ref,
                    expected_revision=request.expected_page_revision,
                    risk=risk,
                )
            elif destination.ref != destination_ref:
                raise TermuinatorError(
                    ErrorCode.TARGET_NOT_FOUND,
                    "The resolved drag destination does not match destination_ref",
                )
        elif destination is not None:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Only drag can receive a resolved destination",
            )

        parameters = dict(request.parameters)
        parameters.pop("destination_ref", None)
        outcome = await backend.act(
            BackendAction(
                kind=request.kind,
                backend_node_id=(binding.backend_node_id if binding else None),
                destination_backend_node_id=(
                    destination.backend_node_id if destination else None
                ),
                parameters=parameters,
                timeout_ms=request.timeout_ms,
            )
        )
        if not isinstance(outcome, BackendActionOutcome):
            raise TermuinatorError(
                ErrorCode.BACKEND_CRASHED,
                "Backend returned an invalid action outcome",
                retryable=True,
            )

        after = observation.capture(
            outcome.snapshot,
            document_changed=outcome.document_changed,
            dom_changed=outcome.evidence.dom_changed,
        )
        verification = self._verify(
            request=request,
            binding=binding,
            outcome=outcome,
            before_url=before.url,
            after_revision=after.page_revision,
            observed_at=after.timestamp,
        )
        succeeded = any(item.passed and item.causal for item in verification)
        changed_url = self._changed_url(
            before.url,
            outcome.evidence.before_url,
            outcome.evidence.after_url,
            outcome.snapshot.url,
        )
        return ActionResult(
            status=(ActionStatus.SUCCEEDED if succeeded else ActionStatus.FAILED),
            before_revision=before.page_revision,
            after_revision=after.page_revision,
            executed_method=outcome.executed_method,
            verification=verification,
            changed_url=changed_url,
            changed_elements=(
                (request.target_ref,)
                if outcome.evidence.dom_changed and request.target_ref is not None
                else ()
            ),
            download=outcome.evidence.download,
            diagnostics_id=outcome.diagnostics_id,
            revalidated=False,
        )

    def _verify(
        self,
        *,
        request: ActionRequest,
        binding: ElementBinding | None,
        outcome: BackendActionOutcome,
        before_url: str,
        after_revision: PageRevision,
        observed_at: str,
    ) -> tuple[Verification, ...]:
        evidence = outcome.evidence
        sensitive = bool(
            binding is not None
            and binding.candidate.type.lower() in {"password", "otp", "secret"}
        )

        if request.kind is ActionKind.TYPE:
            expected = request.parameters["text"]
            passed = bool(
                evidence.target_event_dispatched and evidence.after_value == expected
            )
            return (
                self._item(
                    request=request,
                    kind="input_value",
                    passed=passed,
                    causal=passed,
                    expected=self._value_summary(expected, sensitive),
                    actual=self._value_summary(evidence.after_value, sensitive),
                    after_revision=after_revision,
                    observed_at=observed_at,
                ),
            )

        if request.kind is ActionKind.SELECT:
            expected = request.parameters["value"]
            passed = bool(
                evidence.target_event_dispatched and evidence.after_selected == expected
            )
            return (
                self._item(
                    request=request,
                    kind="selected_value",
                    passed=passed,
                    causal=passed,
                    expected=f"selected value {expected!r}",
                    actual=f"selected value {evidence.after_selected!r}",
                    after_revision=after_revision,
                    observed_at=observed_at,
                ),
            )

        if request.kind is ActionKind.CHECK:
            expected = request.parameters["checked"]
            passed = bool(
                evidence.target_event_dispatched and evidence.after_checked is expected
            )
            return (
                self._item(
                    request=request,
                    kind="checked_state",
                    passed=passed,
                    causal=passed,
                    expected=f"checked={expected}",
                    actual=f"checked={evidence.after_checked}",
                    after_revision=after_revision,
                    observed_at=observed_at,
                ),
            )

        if request.kind is ActionKind.SCROLL:
            passed = bool(
                evidence.target_event_dispatched
                and evidence.before_scroll is not None
                and evidence.after_scroll is not None
                and evidence.before_scroll != evidence.after_scroll
            )
            return (
                self._item(
                    request=request,
                    kind="scroll_position",
                    passed=passed,
                    causal=passed,
                    expected="scroll position changes",
                    actual=f"{evidence.before_scroll!r} -> {evidence.after_scroll!r}",
                    after_revision=after_revision,
                    observed_at=observed_at,
                ),
            )

        if request.kind is ActionKind.HOVER:
            passed = bool(
                evidence.target_event_dispatched
                and (
                    evidence.after_hovered is True
                    or (
                        evidence.before_visible is not None
                        and evidence.after_visible != evidence.before_visible
                    )
                )
            )
            return (
                self._item(
                    request=request,
                    kind="visibility",
                    passed=passed,
                    causal=passed,
                    expected="hover or visible state changes",
                    actual=(
                        f"hovered={evidence.after_hovered}, "
                        f"visible={evidence.after_visible}"
                    ),
                    after_revision=after_revision,
                    observed_at=observed_at,
                ),
            )

        if request.kind is ActionKind.DRAG:
            passed = bool(
                evidence.target_event_dispatched
                and (
                    evidence.source_moved
                    or evidence.target_changed
                    or evidence.dom_changed
                )
            )
            return (
                self._item(
                    request=request,
                    kind="dom_fingerprint",
                    passed=passed,
                    causal=passed,
                    expected="source or destination state changes",
                    actual=(
                        f"source_moved={evidence.source_moved}, "
                        f"target_changed={evidence.target_changed}, "
                        f"dom_changed={evidence.dom_changed}"
                    ),
                    after_revision=after_revision,
                    observed_at=observed_at,
                ),
            )

        return (
            self._event_effect_verification(
                request=request,
                outcome=outcome,
                before_url=before_url,
                after_revision=after_revision,
                observed_at=observed_at,
            ),
        )

    def _event_effect_verification(
        self,
        *,
        request: ActionRequest,
        outcome: BackendActionOutcome,
        before_url: str,
        after_revision: PageRevision,
        observed_at: str,
    ) -> Verification:
        evidence = outcome.evidence
        after_url = evidence.after_url or outcome.snapshot.url
        url_changed = (evidence.before_url or before_url) != after_url
        if evidence.target_event_dispatched and url_changed:
            kind, passed, actual = "url_change", True, after_url
        elif evidence.target_event_dispatched and evidence.dialog_opened:
            kind, passed, actual = "dialog", True, "dialog opened"
        elif evidence.target_event_dispatched and evidence.download is not None:
            kind, passed, actual = "download", True, "download started"
        elif evidence.target_event_dispatched and (
            evidence.before_visible is not None
            and evidence.before_visible != evidence.after_visible
        ):
            kind, passed, actual = (
                "visibility",
                True,
                f"visible={evidence.after_visible}",
            )
        elif evidence.target_event_dispatched and evidence.dom_changed:
            kind, passed, actual = "dom_fingerprint", True, "DOM changed"
        elif evidence.target_event_dispatched and (
            evidence.before_value is not None
            and evidence.before_value != evidence.after_value
        ):
            kind, passed, actual = "input_value", True, "value changed"
        else:
            kind = "target_dispatch"
            passed = evidence.target_event_dispatched
            actual = "event dispatched" if passed else "event was not dispatched"
        causal = passed and kind != "target_dispatch"
        return self._item(
            request=request,
            kind=kind,
            passed=passed,
            causal=causal,
            expected="a causally observed page effect",
            actual=actual,
            after_revision=after_revision,
            observed_at=observed_at,
        )

    @staticmethod
    def _changed_url(
        fallback_before: str,
        before: str | None,
        after: str | None,
        fallback_after: str,
    ) -> str | None:
        before_value = before or fallback_before
        after_value = after or fallback_after
        return after_value if before_value != after_value else None

    @staticmethod
    def _value_summary(value: object, sensitive: bool) -> str:
        if value is None:
            return "value is unavailable"
        if sensitive:
            return f"redacted value length={len(str(value))}"
        return f"value={value!r}"

    @staticmethod
    def _item(
        *,
        request: ActionRequest,
        kind: str,
        passed: bool,
        causal: bool,
        expected: str,
        actual: str,
        after_revision: PageRevision,
        observed_at: str,
    ) -> Verification:
        return Verification(
            verification_id="verification_" + secrets.token_urlsafe(18),
            action_id=request.action_id,
            kind=kind,
            target_ref=request.target_ref,
            passed=passed,
            causal=causal,
            expected_summary=expected,
            actual_summary=actual,
            observed_revision=after_revision,
            observed_at=observed_at,
        )


__all__ = ["ActionExecutor", "BackendActionPort"]
