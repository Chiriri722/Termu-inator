"""Small deterministic redaction helpers for privileged read-only results."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit


_AUTHORIZATION = re.compile(
    r"(?i)(\bauthorization\s*:\s*(?:bearer|basic)\s+)[^\s;,]+"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|cookie|set-cookie)"
    r"(\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s;,]+)"
)
_JWT = re.compile(
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)
_REDACTED = "[REDACTED]"


def redact_sensitive_text(value: str) -> str:
    """Remove common credential forms without logging the matched value."""

    if not isinstance(value, str):
        raise TypeError("redaction input must be a string")
    redacted = _AUTHORIZATION.sub(lambda match: match.group(1) + _REDACTED, value)
    redacted = _SECRET_ASSIGNMENT.sub(
        lambda match: match.group(1) + match.group(2) + _REDACTED,
        redacted,
    )
    return _JWT.sub(_REDACTED, redacted)


def redact_url_metadata(value: str) -> str:
    """Strip URL credentials, fragment, and every query value."""

    if not isinstance(value, str):
        raise TypeError("URL redaction input must be a string")
    try:
        parsed = urlsplit(value)
    except ValueError:
        return _REDACTED
    if not parsed.scheme or not parsed.netloc:
        return value.split("#", 1)[0].split("?", 1)[0]
    hostname = parsed.hostname
    if hostname is None:
        return _REDACTED
    host = f"[{hostname}]" if ":" in hostname else hostname
    try:
        port = parsed.port
    except ValueError:
        return _REDACTED
    if port is not None:
        host = f"{host}:{port}"
    return urlunsplit(
        (
            parsed.scheme,
            host,
            parsed.path,
            "redacted" if parsed.query else "",
            "",
        )
    )


__all__ = ["redact_sensitive_text", "redact_url_metadata"]
