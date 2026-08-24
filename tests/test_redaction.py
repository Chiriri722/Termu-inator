"""Deterministic secret and URL metadata redaction tests."""

from __future__ import annotations

import unittest

from src.termuinator.core.redaction import (
    redact_sensitive_text,
    redact_url_metadata,
)


class RedactionTests(unittest.TestCase):
    def test_common_credentials_and_jwt_are_removed(self) -> None:
        jwt = "eyJabcdefghijk.eyJabcdefghijk.signature12345"
        source = (
            "Authorization: Basic dXNlcjpwYXNz; token=abc123; "
            "api_key='key-value'; cookie=session-value; "
            f"jwt={jwt}"
        )

        redacted = redact_sensitive_text(source)

        for secret in (
            "dXNlcjpwYXNz",
            "abc123",
            "key-value",
            "session-value",
            jwt,
        ):
            self.assertNotIn(secret, redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_url_redaction_preserves_resource_path_only(self) -> None:
        redacted = redact_url_metadata(
            "https://user:pass@[2001:db8::1]:8443/api/items"
            "?token=secret&query=value#account"
        )

        self.assertEqual(
            redacted,
            "https://[2001:db8::1]:8443/api/items?redacted",
        )
        for secret in ("user", "pass", "secret", "value", "account"):
            self.assertNotIn(secret, redacted)

    def test_malformed_url_fails_closed(self) -> None:
        self.assertEqual(
            redact_url_metadata("https://example.com:invalid/path?token=secret"),
            "[REDACTED]",
        )


if __name__ == "__main__":
    unittest.main()
