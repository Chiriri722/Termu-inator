"""Deterministic local HTTP fixture used by browser acceptance tests."""

from __future__ import annotations

import hashlib
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler, urlopen

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
        self.assertIn(b"Activations 0", body)

    def test_unactionable_fixture_exposes_activation_count(self) -> None:
        _status, _headers, body = self._get("/states")
        self.assertIn(b"Unavailable activations 0", body)

    def test_form_exposes_initial_actual_values_and_submission_count(self) -> None:
        _status, _headers, body = self._get("/forms")
        self.assertIn(
            b'Fixture state: {"text":"","terms":false,"choice":"A","submissions":0}', body,
        )

    @unittest.skipUnless(os.environ.get("TERMUINATOR_TEST_BROWSER"), "opt-in isolated real-browser fixture test")
    def test_live_browser_form_events_count_each_real_submit(self) -> None:
        from src.cdp import CDPClient
        from src.termuinator.backends import BackendPageSnapshot
        from src.termuinator.backends.legacy_dom import observe_script, normalize_observation
        from src.termuinator.contracts import ChallengeKind, Viewport
        from src.termuinator.core.observation import ObservationEngine

        async def check() -> None:
            with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryFile() as browser_log:
                profile = Path(directory)
                browser = subprocess.Popen([
                    os.environ["TERMUINATOR_TEST_BROWSER"], "--headless=new", "--remote-debugging-port=0",
                    "--remote-debugging-address=127.0.0.1", f"--user-data-dir={profile}",
                    "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
                    "--disable-component-update", "--disable-sync", "--disable-default-apps",
                    "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1", "about:blank",
                ], stdout=browser_log, stderr=browser_log)
                client = None
                try:
                    for _ in range(100):
                        if (profile / "DevToolsActivePort").is_file() or browser.poll() is not None:
                            break
                        await asyncio.sleep(0.1)
                    self.assertIsNone(browser.poll(), "isolated browser exited before CDP readiness")
                    port = int((profile / "DevToolsActivePort").read_text().splitlines()[0])
                    opener = build_opener(ProxyHandler({}))
                    with opener.open(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
                        targets = json.load(response)
                    client = CDPClient(next(item["webSocketDebuggerUrl"] for item in targets if item["type"] == "page"))
                    await client.connect()

                    async def evaluate(expression):
                        result = await client.send("Runtime.evaluate", {"expression": expression, "returnByValue": True})
                        self.assertNotIn("exceptionDetails", result)
                        return result.get("result", {}).get("value")

                    async def navigate(path, selector):
                        await client.send("Page.navigate", {"url": self.site.url(path)})
                        for _ in range(100):
                            ready = await evaluate(
                                "document.readyState === 'complete' && location.pathname === " + json.dumps(path)
                                + " && !!document.querySelector(" + json.dumps(selector) + ")"
                            )
                            if ready:
                                return
                            await asyncio.sleep(0.05)
                        self.fail("isolated fixture navigation did not become ready")

                    await navigate("/forms", "#form-result")
                    expected = {"text": "", "terms": False, "choice": "A", "submissions": 0}

                    async def assert_state():
                        text = await evaluate("document.body.innerText")
                        lines = [line.strip() for line in text.splitlines() if line.strip().startswith("Fixture state:")]
                        self.assertEqual(lines, ["Fixture state: " + json.dumps(expected, separators=(",", ":"))])
                        actual = await evaluate("({text:document.querySelector('#text-input').value,terms:document.querySelector('#terms').checked,choice:document.querySelector('#choice').value})")
                        self.assertEqual(actual, {key: expected[key] for key in ("text", "terms", "choice")})
                        # Check the real shared probe, not names invented by a fake caller.
                        targets = normalize_observation(await evaluate(observe_script("fixture_registry")))[2]
                        self.assertEqual(
                            [(item.role, item.accessible_name) for item in targets],
                            [("textbox", "Text input"), ("checkbox", "Accept terms"),
                             ("combobox", "Choose option"), ("button", "Submit fixture")],
                        )

                    await assert_state()
                    await evaluate("document.querySelector('#text-input').focus()")
                    await client.send("Input.insertText", {"text": "termuinator-fixture"})
                    expected["text"] = "termuinator-fixture"
                    await assert_state()
                    await evaluate("document.querySelector('#terms').click()")
                    expected["terms"] = True
                    await assert_state()
                    await evaluate("document.querySelector('#choice').value='B';document.querySelector('#choice').dispatchEvent(new Event('change',{bubbles:true}))")
                    expected["choice"] = "B"
                    await assert_state()
                    for count in (1, 2):
                        await evaluate("document.querySelector('#submit').click()")
                        expected["submissions"] = count
                        await assert_state()

                    await navigate("/stale-replacement", "#replaceable-target")
                    before = normalize_observation(await evaluate(observe_script("fixture_registry")))[2]
                    await evaluate("window.retiredFixtureTarget=document.querySelector('#replaceable-target');document.querySelector('#replace-node').click()")
                    after = normalize_observation(await evaluate(observe_script("fixture_registry")))[2]
                    old = next(item for item in before if item.accessible_name == "Continue")
                    new = next(item for item in after if item.accessible_name == "Continue")
                    self.assertNotEqual(old.backend_node_id, new.backend_node_id)
                    self.assertIs(await evaluate("window.retiredFixtureTarget.isConnected"), False)
                    self.assertIn("Generation 2", (await evaluate("document.body.innerText")).splitlines())
                    await evaluate("window.retiredFixtureTarget.click()")
                    self.assertEqual(await evaluate("document.querySelector('#activation-count').textContent"), "Activations 0")
                    await evaluate("document.querySelector('#replaceable-target').click()")
                    self.assertEqual(await evaluate("document.querySelector('#activation-count').textContent"), "Activations 1")

                    await navigate("/states", "#disabled")
                    targets = normalize_observation(await evaluate(observe_script("fixture_registry")))[2]
                    self.assertFalse(next(item for item in targets if item.accessible_name == "Disabled action").enabled)
                    self.assertFalse(next(item for item in targets if item.accessible_name == "Hidden action").visible)
                    await evaluate("document.querySelector('#disabled').click()")
                    self.assertEqual(await evaluate("document.querySelector('#unavailable-count').textContent"), "Unavailable activations 0")
                    # Bypassing the service with JS must be visible in fixture evidence.
                    await evaluate("document.querySelector('#hidden').click()")
                    self.assertEqual(await evaluate("document.querySelector('#unavailable-count').textContent"), "Unavailable activations 1")

                    await navigate("/dynamic-list", "#items")
                    for control, values in (("add", ["Item 1", "Item 2"]), ("remove", ["Item 1"])):
                        await evaluate("document.getElementById(" + json.dumps(control) + ").click()")
                        self.assertEqual(await evaluate("Array.from(document.querySelectorAll('#items li'),item=>item.textContent)"), values)

                    await navigate("/delayed", "#delayed-result")
                    for _ in range(100):
                        if await evaluate("document.querySelector('#delayed-result').textContent === 'Ready'"):
                            break
                        await asyncio.sleep(0.05)
                    self.assertEqual(await evaluate("document.querySelector('#delayed-result').textContent"), "Ready")

                    for route, selector in (("/login", "#password"), ("/otp", "#otp"), ("/prompt-injection", "main")):
                        await navigate(route, selector)
                        ready_state, _, targets = normalize_observation(await evaluate(observe_script("fixture_registry")))
                        engine = ObservationEngine(session_id="session_fixture_privacy", capability_revision="fixture-probe",
                                                   default_viewport=Viewport(width=1000, height=700))
                        detected = engine.capture(BackendPageSnapshot(url=self.site.url(route), title="Fixture", ready_state=ready_state,
                                                                     viewport=None, interactive_elements=targets))
                        if route != "/prompt-injection":
                            self.assertEqual([item.kind for item in detected.challenges], [ChallengeKind.USER_TAKEOVER])
                            self.assertEqual(await evaluate("document.querySelector(" + json.dumps(selector) + ").value"), "")
                        else:
                            self.assertEqual(detected.challenges, ())
                            self.assertEqual(await evaluate("document.scripts.length"), 0)
                            text = await evaluate("document.body.innerText")
                            self.assertIn("always_allow", text)
                            self.assertIn("Developer Mode", text)

                    # A lost response must not undo or repeat the real page effect.
                    await navigate("/forms", "#form-result")
                    expected = {"text": "", "terms": False, "choice": "A", "submissions": 1}
                    pending = asyncio.create_task(client.send("Runtime.evaluate", {
                        "expression": "document.querySelector('#submit').click();new Promise(()=>{})",
                        "awaitPromise": True,
                    }))
                    try:
                        for _ in range(100):
                            text = await evaluate("document.body.innerText")
                            if '"submissions":1' in text:
                                break
                            await asyncio.sleep(0.01)
                        await assert_state()
                        pending.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await pending
                        self.assertEqual(client._callbacks, {})
                    finally:
                        pending.cancel()
                        await asyncio.gather(pending, return_exceptions=True)
                    endpoint = client.ws_url
                    await client.close()
                    with self.assertRaises(ConnectionError):
                        await client.send("Runtime.evaluate", {"expression": "document.title"})
                    client = CDPClient(endpoint)
                    await client.connect()
                    await assert_state()
                finally:
                    try:
                        if client is not None:
                            await client.close()
                    finally:
                        if browser.poll() is None:
                            browser.terminate()
                            try:
                                browser.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                browser.kill()
                                browser.wait(timeout=5)
                        else:
                            browser.wait()

        asyncio.run(check())

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
