"""Service-owned observation identity, revision, and ref state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import secrets
from typing import Callable

from ..backends.base import BackendPageSnapshot
from ..contracts import (
    Challenge,
    ChallengeKind,
    ChallengeState,
    Dialog,
    ErrorCode,
    Observation,
    PageRevision,
    RiskClass,
    Viewport,
)
from ..errors import TermuinatorError
from .element_refs import ElementBinding, ElementRefRegistry
from .permissions import canonical_origin


_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{7,127}$")
_SENSITIVE_FIELD_PATTERN = re.compile(
    r"(?:\b(?:password|passcode|otp|one[- ]time|verification\s+code)\b)",
    re.IGNORECASE,
)
_SENSITIVE_FIELD_TYPES = frozenset({"password", "otp", "one-time-code"})


class ObservationEngine:
    """Mint public page identity around backend-owned raw snapshots."""

    def __init__(
        self,
        *,
        session_id: str,
        capability_revision: str,
        default_viewport: Viewport | None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not _ID_PATTERN.fullmatch(session_id):
            raise ValueError("session_id must be an opaque wire identifier")
        if not isinstance(capability_revision, str) or not capability_revision:
            raise ValueError("capability_revision must not be empty")
        if default_viewport is not None and not isinstance(default_viewport, Viewport):
            raise ValueError("default_viewport must be a Viewport or None")
        self._session_id = session_id
        self._capability_revision = capability_revision
        self._default_viewport = default_viewport
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._tab_id = self._new_id("tab")
        self._page_id = self._new_id("page")
        self._revision = PageRevision(self._new_epoch(), 0)
        self._sequence = 0
        self._last_observation: Observation | None = None
        self._dialogs: dict[str, Dialog] = {}
        self._handoff_challenge: Challenge | None = None
        self._sensitive_suppressed_epoch: str | None = None
        self._refs = ElementRefRegistry(
            document_epoch=self._revision.document_epoch
        )

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def tab_id(self) -> str:
        return self._tab_id

    @property
    def page_id(self) -> str:
        return self._page_id

    @property
    def revision(self) -> PageRevision:
        return self._revision

    @property
    def last_observation(self) -> Observation | None:
        return self._last_observation

    def capture(
        self,
        snapshot: BackendPageSnapshot,
        *,
        document_changed: bool = False,
        dom_changed: bool = False,
        screenshot_artifact_uri: str | None = None,
        suppress_sensitive_handoff: bool = False,
    ) -> Observation:
        if not isinstance(snapshot, BackendPageSnapshot):
            raise TypeError("capture requires BackendPageSnapshot")
        if document_changed and dom_changed:
            raise ValueError("document_changed and dom_changed are mutually exclusive")
        if not isinstance(suppress_sensitive_handoff, bool):
            raise ValueError("suppress_sensitive_handoff must be a boolean")
        if document_changed:
            self._page_id = self._new_id("page")
            self._revision = PageRevision(self._new_epoch(), 0)
            self._refs.rotate(self._revision.document_epoch)
            self._dialogs.clear()
            self._handoff_challenge = None
            self._sensitive_suppressed_epoch = None
        elif dom_changed:
            self._revision = PageRevision(
                self._revision.document_epoch,
                self._revision.mutation_counter + 1,
            )

        viewport = snapshot.viewport or self._default_viewport
        if viewport is None:
            raise TermuinatorError(
                ErrorCode.INTERNAL_ERROR,
                "Backend did not provide a resolved viewport",
            )
        interactive = self._refs.issue(
            snapshot.interactive_elements,
            revision=self._revision,
        )
        observed_at = self._now()
        if observed_at.tzinfo is None:
            raise ValueError("observation clock must return a timezone-aware datetime")
        origin = (
            canonical_origin(snapshot.url)
            if snapshot.url.startswith(("http://", "https://"))
            else "null"
        )
        if suppress_sensitive_handoff:
            self._sensitive_suppressed_epoch = self._revision.document_epoch
            self._handoff_challenge = None
        dialogs = self._capture_dialogs(snapshot)
        challenges = self._capture_sensitive_handoff(
            snapshot,
            observed_at=observed_at,
        )
        observation = Observation(
            session_id=self._session_id,
            page_id=self._page_id,
            tab_id=self._tab_id,
            sequence=self._sequence,
            page_revision=self._revision,
            url=snapshot.url,
            origin=origin,
            title=snapshot.title,
            ready_state=snapshot.ready_state,
            viewport=viewport,
            timestamp=observed_at.isoformat(),
            capability_revision=self._capability_revision,
            text=snapshot.text,
            text_truncated=snapshot.text_truncated,
            accessibility=snapshot.accessibility,
            interactive_elements=interactive,
            dialogs=dialogs,
            challenges=challenges,
            screenshot_artifact_uri=screenshot_artifact_uri,
        )
        self._last_observation = observation
        self._sequence += 1
        return observation

    def _capture_dialogs(
        self,
        snapshot: BackendPageSnapshot,
    ) -> tuple[Dialog, ...]:
        seen: set[str] = set()
        emitted: list[Dialog] = []
        for raw in snapshot.dialogs:
            seen.add(raw.backend_dialog_id)
            previous = self._dialogs.get(raw.backend_dialog_id)
            dialog = Dialog(
                dialog_id=(
                    previous.dialog_id
                    if previous is not None
                    else self._new_id("dialog")
                ),
                kind=raw.kind,
                message=raw.message,
                open=raw.open,
            )
            emitted.append(dialog)
            if raw.open:
                self._dialogs[raw.backend_dialog_id] = dialog
            else:
                self._dialogs.pop(raw.backend_dialog_id, None)

        for backend_dialog_id, previous in tuple(self._dialogs.items()):
            if backend_dialog_id in seen:
                continue
            emitted.append(
                Dialog(
                    dialog_id=previous.dialog_id,
                    kind=previous.kind,
                    message=previous.message,
                    open=False,
                )
            )
            del self._dialogs[backend_dialog_id]
        if len(emitted) > 64:
            raise TermuinatorError(
                ErrorCode.INTERNAL_ERROR,
                "Dialog lifecycle delta exceeds the public observation bound",
            )
        return tuple(emitted)

    def _capture_sensitive_handoff(
        self,
        snapshot: BackendPageSnapshot,
        *,
        observed_at: datetime,
    ) -> tuple[Challenge, ...]:
        sensitive = any(
            raw.type.lower() in _SENSITIVE_FIELD_TYPES
            or _SENSITIVE_FIELD_PATTERN.search(raw.accessible_name) is not None
            for raw in snapshot.interactive_elements
            if raw.editable or raw.role in {"textbox", "searchbox", "combobox"}
        )
        if (
            not sensitive
            or self._sensitive_suppressed_epoch == self._revision.document_epoch
        ):
            self._handoff_challenge = None
            return ()
        if self._handoff_challenge is None:
            self._handoff_challenge = Challenge(
                challenge_id=self._new_id("takeover"),
                kind=ChallengeKind.USER_TAKEOVER,
                state=ChallengeState.PENDING,
                preview=(
                    "Sensitive credential or one-time-code input detected; "
                    "continue through confidential local takeover."
                ),
                expires_at=(observed_at + timedelta(minutes=10)).isoformat(),
            )
        return (self._handoff_challenge,)

    def resolve_ref(
        self,
        *,
        ref: str,
        expected_revision: PageRevision,
        risk: RiskClass,
        fingerprint_matches: bool = False,
    ) -> ElementBinding:
        return self._refs.resolve(
            ref=ref,
            expected_revision=expected_revision,
            current_revision=self._revision,
            risk=risk,
            fingerprint_matches=fingerprint_matches,
        )

    def ref_for_backend_node(self, backend_node_id: str) -> str | None:
        """Resolve only handles already exposed by the current observation."""

        return self._refs.ref_for_handle(backend_node_id)

    def require_context(
        self,
        *,
        session_id: str,
        tab_id: str,
        page_id: str,
        expected_revision: PageRevision,
    ) -> PageRevision:
        if session_id != self._session_id:
            raise TermuinatorError(
                ErrorCode.SESSION_NOT_FOUND,
                "Browser session was not found",
            )
        if (
            tab_id != self._tab_id
            or page_id != self._page_id
            or expected_revision != self._revision
        ):
            raise TermuinatorError(
                ErrorCode.STALE_OBSERVATION,
                "Page context no longer matches the active observation",
                details={"current_revision": str(self._revision)},
            )
        return self._revision

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{secrets.token_urlsafe(18)}"

    @staticmethod
    def _new_epoch() -> str:
        return "epoch_" + secrets.token_urlsafe(18)


__all__ = ["ObservationEngine"]
