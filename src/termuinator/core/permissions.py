"""Origin permission policy boundary."""

from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
from typing import Callable, Protocol
from urllib.parse import urlsplit

from ..contracts import ErrorCode, PermissionDecision, PermissionPolicy
from ..errors import TermuinatorError


class PermissionEngine(Protocol):
    def evaluate(self, *, url: str, session_id: str) -> PermissionPolicy:
        ...

    def record(
        self,
        *,
        origin: str,
        policy: PermissionPolicy,
        session_id: str | None = None,
    ) -> PermissionDecision:
        ...

    def clear_session(self, session_id: str) -> None:
        ...

    def list(self, session_id: str | None = None) -> tuple[PermissionDecision, ...]:
        ...


class InMemoryPermissionEngine:
    """Deterministic engine separating persistent and session decisions."""

    def __init__(
        self,
        *,
        project_id: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        self._project_id = project_id
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._persistent: dict[str, PermissionDecision] = {}
        self._session: dict[tuple[str, str], PermissionDecision] = {}

    def evaluate(self, *, url: str, session_id: str) -> PermissionPolicy:
        if not isinstance(session_id, str) or not session_id:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "session_id is required for permission evaluation",
            )
        origin = canonical_origin(url)
        persistent = self._persistent.get(origin)
        if persistent is not None:
            return persistent.policy
        decision = self._session.get((session_id, origin))
        return decision.policy if decision is not None else PermissionPolicy.ASK

    def record(
        self,
        *,
        origin: str,
        policy: PermissionPolicy,
        session_id: str | None = None,
    ) -> PermissionDecision:
        normalized = canonical_origin(origin)
        if not isinstance(policy, PermissionPolicy) or policy is PermissionPolicy.ASK:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "ask is derived and cannot be recorded",
            )
        now = self._current_time().isoformat()
        if policy is PermissionPolicy.SESSION_ALLOW:
            if not isinstance(session_id, str) or not session_id:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "session_allow requires session_id",
                )
            decision = PermissionDecision(
                project_id=self._project_id,
                origin=normalized,
                policy=policy,
                created_at=now,
                persistent=False,
                session_id=session_id,
            )
            self._session[(session_id, normalized)] = decision
            return decision

        if session_id is not None:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "persistent permissions cannot bind session_id",
            )
        decision = PermissionDecision(
            project_id=self._project_id,
            origin=normalized,
            policy=policy,
            created_at=now,
            persistent=True,
        )
        self._persistent[normalized] = decision
        return decision

    def clear_session(self, session_id: str) -> None:
        keys = [key for key in self._session if key[0] == session_id]
        for key in keys:
            del self._session[key]

    def list(self, session_id: str | None = None) -> tuple[PermissionDecision, ...]:
        if session_id is not None and (
            not isinstance(session_id, str) or not session_id
        ):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "session_id must be non-empty when provided",
            )
        session = tuple(
            decision
            for (item_session, _), decision in self._session.items()
            if session_id is None or item_session == session_id
        )
        return tuple(
            sorted(
                tuple(self._persistent.values()) + session,
                key=lambda item: (item.origin, item.policy.value, item.session_id or ""),
            )
        )

    def _current_time(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("permission clock must return a timezone-aware datetime")
        return value


def canonical_origin(value: str) -> str:
    """Return a strict HTTP(S) origin without path, query, or fragment."""

    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 8_192
        or value != value.strip()
        or "\\" in value
        or any(character.isspace() for character in value)
    ):
        raise TermuinatorError(ErrorCode.INVALID_REQUEST, "URL is not canonical")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise TermuinatorError(ErrorCode.INVALID_REQUEST, "URL origin is invalid") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise TermuinatorError(
            ErrorCode.INVALID_REQUEST,
            "Only HTTP(S) origins are supported",
        )
    if parsed.username is not None or parsed.password is not None:
        raise TermuinatorError(
            ErrorCode.INVALID_REQUEST,
            "URL credentials are not accepted",
        )

    host = parsed.hostname.rstrip(".").lower()
    if not host:
        raise TermuinatorError(ErrorCode.INVALID_REQUEST, "URL host is empty")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "URL host is invalid",
            ) from exc
    else:
        host = f"[{address.compressed}]" if address.version == 6 else address.compressed

    default_port = 80 if scheme == "http" else 443
    port_suffix = "" if port in (None, default_port) else f":{port}"
    return f"{scheme}://{host}{port_suffix}"


__all__ = ["InMemoryPermissionEngine", "PermissionEngine", "canonical_origin"]
