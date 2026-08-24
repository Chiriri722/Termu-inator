"""Server-held one-shot confirmation state for consequential actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import secrets
import threading
from typing import Callable

from ..contracts import (
    Challenge,
    ChallengeKind,
    ChallengeState,
    ErrorCode,
    PageRevision,
    to_wire,
)
from ..errors import TermuinatorError
from .permissions import canonical_origin


_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{7,127}$")
_CONFIRMATION_TTL = timedelta(seconds=120)


@dataclass
class _ConfirmationRecord:
    challenge_id: str
    binding_digest: str
    preview: str
    expires_at: datetime
    nonce: bytes
    state: ChallengeState = ChallengeState.PENDING
    approval_proof: bytes | None = None

    def public(self) -> Challenge:
        return Challenge(
            challenge_id=self.challenge_id,
            kind=ChallengeKind.CONFIRMATION,
            state=self.state,
            preview=self.preview,
            expires_at=self.expires_at.isoformat(),
        )


class ConfirmationEngine:
    """Keep approval authority off the model-visible confirmation identifier."""

    def __init__(
        self,
        *,
        owner_scope: str,
        project_id: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._validate_scope(owner_scope, "owner_scope")
        self._validate_scope(project_id, "project_id")
        self._owner_scope = owner_scope
        self._project_id = project_id
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._records: dict[str, _ConfirmationRecord] = {}
        self._by_binding: dict[str, str] = {}
        self._lock = threading.RLock()

    def prepare(
        self,
        *,
        session_id: str,
        origin: str,
        page_revision: PageRevision,
        action_digest: str,
        idempotency_key: str,
        preview: str,
    ) -> Challenge:
        binding = self._binding_digest(
            session_id=session_id,
            origin=origin,
            page_revision=page_revision,
            action_digest=action_digest,
            idempotency_key=idempotency_key,
            preview=preview,
        )
        with self._lock:
            existing_id = self._by_binding.get(binding)
            if existing_id is not None:
                existing = self._records.get(existing_id)
                if existing is not None:
                    self._refresh(existing)
                    if existing.state in {
                        ChallengeState.PENDING,
                        ChallengeState.APPROVED,
                        ChallengeState.DENIED,
                    }:
                        return existing.public()

            current = self._current_time()
            record = _ConfirmationRecord(
                challenge_id="confirmation_" + secrets.token_urlsafe(24),
                binding_digest=binding,
                preview=preview,
                expires_at=current + _CONFIRMATION_TTL,
                nonce=secrets.token_bytes(32),
            )
            self._records[record.challenge_id] = record
            self._by_binding[binding] = record.challenge_id
            return record.public()

    def approve(self, confirmation_id: str) -> Challenge:
        with self._lock:
            record = self._require_record(confirmation_id)
            self._refresh(record)
            if record.state is ChallengeState.DENIED:
                raise self._denied(record)
            if record.state in {ChallengeState.EXPIRED, ChallengeState.CONSUMED}:
                raise self._required(record, "confirmation_not_usable")
            if record.state is ChallengeState.PENDING:
                record.approval_proof = hmac.new(
                    record.nonce,
                    record.binding_digest.encode("ascii"),
                    hashlib.sha256,
                ).digest()
                record.state = ChallengeState.APPROVED
            return record.public()

    def deny(self, confirmation_id: str) -> Challenge:
        with self._lock:
            record = self._require_record(confirmation_id)
            self._refresh(record)
            if record.state in {ChallengeState.EXPIRED, ChallengeState.CONSUMED}:
                raise self._required(record, "confirmation_not_usable")
            record.approval_proof = None
            record.state = ChallengeState.DENIED
            return record.public()

    def consume(
        self,
        confirmation_id: str,
        *,
        session_id: str,
        origin: str,
        page_revision: PageRevision,
        action_digest: str,
        idempotency_key: str,
        preview: str,
    ) -> Challenge:
        binding = self._binding_digest(
            session_id=session_id,
            origin=origin,
            page_revision=page_revision,
            action_digest=action_digest,
            idempotency_key=idempotency_key,
            preview=preview,
        )
        with self._lock:
            record = self._require_record(confirmation_id)
            self._refresh(record)
            if not hmac.compare_digest(record.binding_digest, binding):
                record.state = ChallengeState.EXPIRED
                record.approval_proof = None
                raise self._required(record, "confirmation_context_changed")
            if record.state is ChallengeState.DENIED:
                raise self._denied(record)
            if record.state is not ChallengeState.APPROVED:
                raise self._required(record, "confirmation_not_approved")
            expected_proof = hmac.new(
                record.nonce,
                record.binding_digest.encode("ascii"),
                hashlib.sha256,
            ).digest()
            if record.approval_proof is None or not hmac.compare_digest(
                record.approval_proof,
                expected_proof,
            ):
                raise TermuinatorError(
                    ErrorCode.INTERNAL_ERROR,
                    "Confirmation approval proof is invalid",
                )
            record.state = ChallengeState.CONSUMED
            record.approval_proof = None
            return record.public()

    def status(self, confirmation_id: str) -> Challenge:
        with self._lock:
            record = self._require_record(confirmation_id)
            self._refresh(record)
            return record.public()

    def list_pending(self, *, limit: int) -> tuple[Challenge, ...]:
        """Return a bounded newest-first public view of pending challenges."""

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 64
        ):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "confirmation pending limit must be between 1 and 64",
            )
        with self._lock:
            pending: list[Challenge] = []
            for record in reversed(tuple(self._records.values())):
                self._refresh(record)
                if record.state is ChallengeState.PENDING:
                    pending.append(record.public())
                    if len(pending) == limit:
                        break
            return tuple(pending)

    def _binding_digest(
        self,
        *,
        session_id: str,
        origin: str,
        page_revision: PageRevision,
        action_digest: str,
        idempotency_key: str,
        preview: str,
    ) -> str:
        if not isinstance(session_id, str) or not _ID.fullmatch(session_id):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Confirmation session_id is invalid",
            )
        if not isinstance(page_revision, PageRevision):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Confirmation page revision is invalid",
            )
        if not isinstance(action_digest, str) or not _DIGEST.fullmatch(action_digest):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Confirmation action digest is invalid",
            )
        if not isinstance(idempotency_key, str) or not _ID.fullmatch(idempotency_key):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Confirmation idempotency key is invalid",
            )
        if not isinstance(preview, str) or not 1 <= len(preview) <= 4096:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Confirmation preview is invalid",
            )
        payload = {
            "owner_scope": self._owner_scope,
            "project_id": self._project_id,
            "session_id": session_id,
            "origin": canonical_origin(origin),
            "page_revision": str(page_revision),
            "action_digest": action_digest,
            "idempotency_key": idempotency_key,
            "preview": preview,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(
            b"termuinator-confirmation-binding-v1\x00" + encoded
        ).hexdigest()

    def _require_record(self, confirmation_id: str) -> _ConfirmationRecord:
        if not isinstance(confirmation_id, str) or not _ID.fullmatch(confirmation_id):
            raise self._required(None, "confirmation_not_found")
        record = self._records.get(confirmation_id)
        if record is None:
            raise self._required(None, "confirmation_not_found")
        return record

    def _refresh(self, record: _ConfirmationRecord) -> None:
        if (
            record.state in {ChallengeState.PENDING, ChallengeState.APPROVED}
            and self._current_time() >= record.expires_at
        ):
            record.state = ChallengeState.EXPIRED
            record.approval_proof = None

    def _current_time(self) -> datetime:
        value = self._now()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("confirmation clock must return a timezone-aware datetime")
        return value

    @staticmethod
    def _validate_scope(value: str, name: str) -> None:
        if (
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
            or "\x00" in value
            or len(value) > 4096
        ):
            raise ValueError(f"{name} must be a non-empty canonical identifier")

    @staticmethod
    def _required(
        record: _ConfirmationRecord | None,
        reason_code: str,
    ) -> TermuinatorError:
        details = {"reason_code": reason_code}
        if record is not None:
            details["challenge"] = to_wire(record.public())
        return TermuinatorError(
            ErrorCode.CONFIRMATION_REQUIRED,
            "An exact, unexpired local confirmation is required",
            details=details,
        )

    @staticmethod
    def _denied(record: _ConfirmationRecord) -> TermuinatorError:
        return TermuinatorError(
            ErrorCode.PERMISSION_DENIED,
            "The consequential action was denied",
            details={"challenge": to_wire(record.public())},
        )


__all__ = ["ConfirmationEngine"]
