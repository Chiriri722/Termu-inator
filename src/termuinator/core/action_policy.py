"""Server-owned action risk classification and safe previews."""

from __future__ import annotations

from dataclasses import dataclass
import re

from ..contracts import ActionKind, ActionRequest, ErrorCode, RiskClass
from ..errors import TermuinatorError
from .element_refs import ElementBinding
from .permissions import canonical_origin


_RISK_RANK = {
    RiskClass.R0: 0,
    RiskClass.R1: 1,
    RiskClass.R2: 2,
    RiskClass.R3: 3,
    RiskClass.R4: 4,
    RiskClass.DEVELOPER: 5,
}
_CONSEQUENTIAL_INTENT = re.compile(
    r"(?:\b(?:submit|send|purchase|buy|pay|checkout|delete|remove|"
    r"publish|post|confirm|grant|allow|permission|place\s+order)\b|"
    r"제출|전송|구매|결제|삭제|게시|승인|권한)",
    re.IGNORECASE,
)
_SENSITIVE_INTENT = re.compile(
    r"(?:\b(?:password|passcode|otp|one[- ]time|verification\s+code)\b|"
    r"비밀번호|인증번호|일회용)",
    re.IGNORECASE,
)
_SENSITIVE_TYPES = frozenset({"password", "otp", "one-time-code", "file"})


@dataclass(frozen=True)
class ActionRiskAssessment:
    risk: RiskClass
    requires_confirmation: bool
    requires_takeover: bool
    reason_code: str
    preview: str

    def __post_init__(self) -> None:
        if not isinstance(self.risk, RiskClass):
            raise ValueError("assessment risk must be a RiskClass")
        if not isinstance(self.requires_confirmation, bool) or not isinstance(
            self.requires_takeover,
            bool,
        ):
            raise ValueError("assessment gates must be booleans")
        if self.requires_confirmation and self.requires_takeover:
            raise ValueError("an action cannot require confirmation and takeover together")
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", self.reason_code):
            raise ValueError("assessment reason_code is invalid")
        if not isinstance(self.preview, str) or not 1 <= len(self.preview) <= 4096:
            raise ValueError("assessment preview is invalid")


class ActionRiskClassifier:
    """Raise server risk from untrusted semantics; never lower its minimum."""

    def assess(
        self,
        *,
        request: ActionRequest,
        target: ElementBinding | None,
        destination: ElementBinding | None,
        origin: str,
    ) -> ActionRiskAssessment:
        if not isinstance(request, ActionRequest):
            raise TypeError("request must be an ActionRequest")
        normalized_origin = canonical_origin(origin)
        self._validate_bindings(request, target, destination)

        candidates = tuple(
            binding.candidate
            for binding in (target, destination)
            if binding is not None
        )
        sensitive = bool(
            request.kind is ActionKind.TYPE
            and any(
                candidate.type.casefold().strip() in _SENSITIVE_TYPES
                or _SENSITIVE_INTENT.search(candidate.accessible_name)
                for candidate in candidates
            )
        )
        if sensitive:
            return ActionRiskAssessment(
                risk=self._raise(request.risk, RiskClass.R3),
                requires_confirmation=False,
                requires_takeover=True,
                reason_code="confidential_takeover",
                preview=(
                    "Confidential local takeover is required for a sensitive "
                    f"field at {normalized_origin}"
                ),
            )

        submit_control = any(
            candidate.type.casefold().strip() == "submit" for candidate in candidates
        )
        consequential_label = any(
            _CONSEQUENTIAL_INTENT.search(
                " ".join(
                    (
                        candidate.role,
                        candidate.accessible_name,
                        candidate.tag,
                        candidate.type,
                    )
                )
            )
            for candidate in candidates
        )
        enter_key = bool(
            request.kind is ActionKind.KEY
            and request.parameters.get("key") in {"Enter", "NumpadEnter"}
        )
        if submit_control or consequential_label or enter_key:
            label = self._target_label(target, destination)
            return ActionRiskAssessment(
                risk=self._raise(request.risk, RiskClass.R4),
                requires_confirmation=True,
                requires_takeover=False,
                reason_code=(
                    "submit_or_consequential_effect"
                    if not enter_key
                    else "enter_may_submit"
                ),
                preview=(
                    f"Confirm {request.kind.value} on untrusted page target "
                    f"{label!r} at {normalized_origin}"
                ),
            )

        return ActionRiskAssessment(
            risk=request.risk,
            requires_confirmation=False,
            requires_takeover=False,
            reason_code="action_minimum",
            preview=f"{request.kind.value} at {normalized_origin}",
        )

    @staticmethod
    def _validate_bindings(
        request: ActionRequest,
        target: ElementBinding | None,
        destination: ElementBinding | None,
    ) -> None:
        if request.target_ref is not None and (
            target is None or target.ref != request.target_ref
        ):
            raise TermuinatorError(
                ErrorCode.TARGET_NOT_FOUND,
                "The action target ref is not present in the current observation",
            )
        if request.target_ref is None and target is not None:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "An unrequested action target cannot affect risk classification",
            )
        if request.kind is ActionKind.DRAG:
            destination_ref = request.parameters["destination_ref"]
            if destination is None or destination.ref != destination_ref:
                raise TermuinatorError(
                    ErrorCode.TARGET_NOT_FOUND,
                    "The drag destination ref is not present in the current observation",
                )
        elif destination is not None:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Only drag actions can supply a destination",
            )

    @staticmethod
    def _raise(minimum: RiskClass, candidate: RiskClass) -> RiskClass:
        return candidate if _RISK_RANK[candidate] > _RISK_RANK[minimum] else minimum

    @staticmethod
    def _target_label(
        target: ElementBinding | None,
        destination: ElementBinding | None,
    ) -> str:
        parts: list[str] = []
        for binding in (target, destination):
            if binding is None:
                continue
            candidate = binding.candidate
            value = candidate.accessible_name or candidate.role or candidate.tag
            value = " ".join(value.split())[:160]
            if value:
                parts.append(value)
        return " -> ".join(parts) if parts else "page-level action"


__all__ = ["ActionRiskAssessment", "ActionRiskClassifier"]
