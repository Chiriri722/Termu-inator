"""Service-owned opaque element-reference registry."""

from __future__ import annotations

from dataclasses import dataclass
import secrets

from ..backends.base import RawInteractiveElement
from ..contracts import (
    ErrorCode,
    InteractiveElement,
    PageRevision,
    RevisionDecision,
    RiskClass,
    classify_revision,
)
from ..errors import TermuinatorError


@dataclass(frozen=True)
class ElementBinding:
    ref: str
    backend_node_id: str
    semantic_fingerprint: str
    revision: PageRevision
    candidate: RawInteractiveElement


class ElementRefRegistry:
    """Map backend handles to unguessable refs within one document epoch."""

    def __init__(self, *, document_epoch: str) -> None:
        PageRevision(document_epoch, 0)
        self._document_epoch = document_epoch
        self._by_ref: dict[str, ElementBinding] = {}
        self._by_handle: dict[str, str] = {}

    def issue(
        self,
        candidates: tuple[RawInteractiveElement, ...],
        *,
        revision: PageRevision,
    ) -> tuple[InteractiveElement, ...]:
        if revision.document_epoch != self._document_epoch:
            raise ValueError("revision does not match the registry document epoch")
        handles = [candidate.backend_node_id for candidate in candidates]
        if len(handles) != len(set(handles)):
            raise ValueError("backend snapshot contains duplicate node handles")

        seen = set(handles)
        for handle, ref in tuple(self._by_handle.items()):
            if handle not in seen:
                self._by_handle.pop(handle, None)
                self._by_ref.pop(ref, None)

        result: list[InteractiveElement] = []
        for candidate in candidates:
            fingerprint = candidate.semantic_fingerprint()
            existing_ref = self._by_handle.get(candidate.backend_node_id)
            existing = self._by_ref.get(existing_ref) if existing_ref else None
            if existing is not None and existing.semantic_fingerprint != fingerprint:
                self._by_ref.pop(existing.ref, None)
                self._by_handle.pop(candidate.backend_node_id, None)
                existing = None

            ref = existing.ref if existing is not None else self._new_ref()
            binding = ElementBinding(
                ref=ref,
                backend_node_id=candidate.backend_node_id,
                semantic_fingerprint=fingerprint,
                revision=revision,
                candidate=candidate,
            )
            self._by_ref[ref] = binding
            self._by_handle[candidate.backend_node_id] = ref
            result.append(candidate.to_public(ref))
        return tuple(result)

    def resolve(
        self,
        *,
        ref: str,
        expected_revision: PageRevision,
        current_revision: PageRevision,
        risk: RiskClass,
        fingerprint_matches: bool,
    ) -> ElementBinding:
        binding = self._by_ref.get(ref)
        if binding is None:
            raise TermuinatorError(
                ErrorCode.TARGET_NOT_FOUND,
                "Element reference is not present in the current document",
                details={"ref": ref},
            )
        if (
            expected_revision.document_epoch != self._document_epoch
            or current_revision.document_epoch != self._document_epoch
        ):
            raise TermuinatorError(
                ErrorCode.STALE_OBSERVATION,
                "Element reference belongs to a different document epoch",
            )
        decision = classify_revision(
            expected_revision,
            current_revision,
            risk,
            fingerprint_matches=fingerprint_matches,
        )
        if decision is RevisionDecision.STALE or (
            decision is RevisionDecision.REVALIDATE and not fingerprint_matches
        ):
            raise TermuinatorError(
                ErrorCode.STALE_OBSERVATION,
                "Element reference requires a fresh observation",
                details={
                    "expected_revision": str(expected_revision),
                    "current_revision": str(current_revision),
                },
            )
        return binding

    def rotate(self, document_epoch: str) -> None:
        PageRevision(document_epoch, 0)
        self._document_epoch = document_epoch
        self._by_ref.clear()
        self._by_handle.clear()

    def ref_for_handle(self, backend_node_id: str) -> str | None:
        """Return an existing public ref without minting new authority."""

        if not isinstance(backend_node_id, str):
            raise TypeError("backend_node_id must be a string")
        return self._by_handle.get(backend_node_id)

    @staticmethod
    def _new_ref() -> str:
        return "ref_" + secrets.token_urlsafe(24)


__all__ = ["ElementBinding", "ElementRefRegistry"]
