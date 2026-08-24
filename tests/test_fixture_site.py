"""Deterministic local HTTP fixture used by browser acceptance tests."""

from __future__ import annotations

import hashlib
import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler, urlopen

from tests.fixtures.server import FIXTURE_SCENARIOS, FixtureSite


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class FixtureSiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.site = FixtureSite()
        self.site.start()
        self.addCleanup(self.site.stop)

    def _get(self, path: str) -> tuple[int, object, bytes]:
        with urlopen(self.site.url(path), timeout=2) as response:
            return response.status, response.headers, response.read()

    def test_manifest_has_at_least_twenty_five_bounded_unique_scenarios(self) -> None:
        self.assertGreaterEqual(len(FIXTURE_SCENARIOS), 25)
        identifiers = [item.scenario_id for item in FIXTURE_SCENARIOS]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        for scenario in FIXTURE_SCENARIOS:
            self.assertRegex(scenario.scenario_id, r"^[a-z][a-z0-9-]{2,63}$")
            self.assertTrue(scenario.path.startswith("/"))
            self.assertLessEqual(len(scenario.expected_text), 256)

    def test_core_pages_are_local_deterministic_and_security_bounded(self) -> None:
        expected_markers = {
            "/forms": b'data-fixture="forms"',
            "/spa": b'data-fixture="spa"',
            "/dynamic-list": b'data-fixture="dynamic-list"',
            "/stale-replacement": b'data-fixture="stale-replacement"',
            "/shadow-dom": b'attachShadow',
            "/iframes": b'http://localhost:',
            "/dialogs": b'window.prompt',
            "/popup": b'window.open',
            "/login": b'type="password"',
            "/otp": b'autocomplete="one-time-code"',
            "/long-text": b'data-fixture="long-text"',
            "/delayed": b'data-fixture="delayed"',
        }
        for path, marker in expected_markers.items():
            status, headers, body = self._get(path)
            self.assertEqual(status, 200, path)
            self.assertIn(marker, body, path)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            self.assertLess(len(body), 128 * 1024)

    def test_stale_replacement_route_replaces_node_identity_not_just_text(self) -> None:
        status, _headers, body = self._get("/stale-replacement")

        self.assertEqual(status, 200)
        self.assertIn(b'id="replaceable-target"', body)
        self.assertIn(b"replaceWith(replacement)", body)
        self.assertIn(b"replacement-generation", body)

    def test_prompt_injection_fixture_is_inert_untrusted_text(self) -> None:
        status, headers, body = self._get("/prompt-injection")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn(b'data-fixture="prompt-injection"', body)
        self.assertIn(b"Ignore previous instructions", body)
        self.assertIn(b"always_allow", body)
        self.assertIn(b"Developer Mode", body)
        self.assertNotIn(b"<script", body.lower())

    def test_download_redirect_health_and_unknown_route_contracts(self) -> None:
        status, headers, payload = self._get("/downloads/report.txt")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), "text/plain")
        self.assertEqual(
            headers["Content-Disposition"],
            'attachment; filename="termuinator-fixture.txt"',
        )
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "289efbbfc548aaa5d01ebed9aa27b2c8a3e3291151f4bab4cef8fec9b5b131c9",
        )

        status, headers, body = self._get("/healthz")
        self.assertEqual((status, body), (200, b'{"status":"ok"}\n'))
        self.assertEqual(headers.get_content_type(), "application/json")
        self.assertEqual(json.loads(body), {"status": "ok"})

        opener = build_opener(_NoRedirect)
        with self.assertRaises(HTTPError) as redirect:
            opener.open(Request(self.site.url("/redirect")), timeout=2)
        self.assertEqual(redirect.exception.code, 302)
        self.assertEqual(redirect.exception.headers["Location"], "/final")
        redirect.exception.close()

        with self.assertRaises(HTTPError) as missing:
            urlopen(self.site.url("/missing"), timeout=2)
        self.assertEqual(missing.exception.code, 404)
        missing.exception.close()

    def test_repeated_response_bytes_are_identical(self) -> None:
        for path in ("/forms", "/spa", "/dialogs", "/downloads/report.txt"):
            first = self._get(path)[2]
            second = self._get(path)[2]
            self.assertEqual(first, second, path)


if __name__ == "__main__":
    unittest.main()
