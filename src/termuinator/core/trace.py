"""Closed typed trace recorder boundary."""

from __future__ import annotations

from typing import Callable, Protocol

from ..contracts import ErrorCode, TraceRecord
from ..errors import TermuinatorError


class TraceRecorder(Protocol):
    def append(self, *, session_id: str, record: TraceRecord) -> None:
        ...

    def list(self, *, session_id: str, limit: int) -> tuple[TraceRecord, ...]:
        ...


class InMemoryTraceRecorder:
    """Bounded recorder used by core tests before durable trace storage."""

    def __init__(
        self,
        *,
        authorize_session: Callable[[str], bool],
        max_records: int = 1_000,
    ) -> None:
        if not 1 <= max_records <= 10_000:
            raise ValueError("max_records must be between 1 and 10000")
        self._authorize_session = authorize_session
        self._max_records = max_records
        self._records: dict[str, list[TraceRecord]] = {}

    def append(self, *, session_id: str, record: TraceRecord) -> None:
        self._authorize(session_id)
        if not isinstance(record, TraceRecord):
            raise TypeError("trace recorder accepts only TraceRecord values")
        records = self._records.setdefault(session_id, [])
        records.append(record)
        del records[: max(0, len(records) - self._max_records)]

    def list(self, *, session_id: str, limit: int) -> tuple[TraceRecord, ...]:
        self._authorize(session_id)
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1_000
        ):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "trace list limit must be between 1 and 1000",
            )
        return tuple(self._records.get(session_id, ())[-limit:])

    def clear_session(self, session_id: str) -> None:
        self._records.pop(session_id, None)

    def _authorize(self, session_id: str) -> None:
        if not isinstance(session_id, str) or not self._authorize_session(session_id):
            raise TermuinatorError(
                ErrorCode.OWNERSHIP_DENIED,
                "The active session does not own this trace namespace",
            )


__all__ = ["InMemoryTraceRecorder", "TraceRecorder"]
