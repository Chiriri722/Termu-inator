"""Structured service-layer failures for the v1 runtime."""

from __future__ import annotations

from typing import Any, Mapping

from .contracts import ERROR_RETRYABLE, ErrorCode, ErrorEnvelope


class TermuinatorError(RuntimeError):
    """An expected public failure with a stable wire error code."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool | None = None,
        details: Mapping[str, Any] | None = None,
        diagnostics_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        expected_retryable = ERROR_RETRYABLE[code]
        if retryable is not None and retryable is not expected_retryable:
            raise ValueError("retryable must be derived from the error code")
        self.retryable = expected_retryable
        self.details = dict(details or {})
        self.diagnostics_id = diagnostics_id

    def to_envelope(self) -> ErrorEnvelope:
        return ErrorEnvelope(
            code=self.code,
            message=str(self),
            retryable=self.retryable,
            details=self.details,
            diagnostics_id=self.diagnostics_id,
        )
