"""Read-only loopback shared-view security and composition tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from src.termuinator.backends import (
    BackendArtifactPayload,
    BackendPageSnapshot,
    RawInteractiveElement,
)
from src.termuinator.backends.fake import FakeBackend
from src.termuinator.contracts import (
    Backend,
    Bounds,
    Challenge,
    ChallengeKind,
    ChallengeState,
    ErrorCode,
    PageRevision,
    PermissionPolicy,
    RiskClass,
    SessionState,
    TraceRecord,
    Viewport,
)
from src.termuinator.core.service import BrowserService
from src.termuinator.errors import TermuinatorError
from src.termuinator.shared_view import (
    SharedViewArtifact,
    SharedViewServer,
    SharedViewState,
)


_PNG = b"\x89PNG\r\n\x1a\nshared-view-image"


class _SessionLock:
    def __init__(self) -> None:
        self.held = False

    def acquire(self) -> None:
        if self.held:
            raise AssertionError("test lock acquired twice")
        self.held = True

    def release(self) -> None:
        self.held = False


def _snapshot(*, sensitive: bool = False) -> BackendPageSnapshot:
    interactive = ()
    if sensitive:
        interactive = (
            RawInteractiveElement(
                backend_node_id="private-password-node",
                role="textbox",
                accessible_name="Password",
                tag="input",
                type="password",
                bounds=Bounds(x=10, y=20, width=200, height=40),
                editable=True,
            ),
        )
    return BackendPageSnapshot(
        url="https://example.com/account?token=secret#private",
        title="Private account" if sensitive else "token=secret Example dashboard",
        ready_state="complete",
        viewport=Viewport(width=1280, height=720),
        text="password secret" if sensitive else "Safe dashboard text",
        screenshot=BackendArtifactPayload(data=_PNG, mime_type="image/png"),
        interactive_elements=interactive,
    )


class SharedViewServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def _service(self, *, sensitive: bool = False) -> tuple[BrowserService, FakeBackend]:
        backend = FakeBackend(Backend.CHROMIUM, snapshot=_snapshot(sensitive=sensitive))
        service = BrowserService(
            data_root=Path(self.temporary.name) / "data",
            owner_scope="shared-view-owner",
            default_backend=Backend.CHROMIUM,
            profile_schema_version="v1",
            backend_factories={Backend.CHROMIUM: lambda: backend},
            session_lock=_SessionLock(),
        )
        return service, backend

    async def _start_and_observe(
        self,
        service: BrowserService,
    ) -> tuple[str, object]:
        started = await service.session_start(
            project_id="shared-view-project",
            viewport=Viewport(width=1280, height=720),
        )
        status = started.status
        assert status.active_tab_id is not None
        assert status.active_page_id is not None
        assert status.page_revision is not None
        observed = await service.observe(
            session_id=started.session_id,
            tab_id=status.active_tab_id,
            page_id=status.active_page_id,
            expected_revision=status.page_revision,
            include_screenshot=True,
            include_accessibility=False,
            text_limit=1_000,
        )
        return started.session_id, observed

    async def test_snapshot_and_image_use_only_cached_active_state(self) -> None:
        service, backend = self._service()
        session_id, observation = await self._start_and_observe(service)
        before = list(backend.calls)

        state = await service.shared_view_snapshot()
        image = await service.shared_view_screenshot()

        self.assertIsInstance(state, SharedViewState)
        self.assertFalse(state.confidential)
        self.assertEqual(state.session_id, session_id)
        self.assertEqual(state.state, SessionState.ACTIVE.value)
        self.assertEqual(state.backend, Backend.CHROMIUM)
        self.assertEqual(state.active_tab_id, observation.tab_id)
        self.assertEqual(state.url, "https://example.com/account?redacted")
        self.assertEqual(state.title, "token=[REDACTED] Example dashboard")
        self.assertEqual(
            state.screenshot_artifact_uri,
            observation.screenshot_artifact_uri,
        )
        self.assertEqual(state.pending_permissions, ())
        self.assertEqual(state.pending_confirmations, ())
        self.assertEqual(state.recent_traces, ())
        self.assertEqual(backend.calls, before)
        self.assertEqual(image, SharedViewArtifact(data=_PNG, mime_type="image/png"))

    async def test_idle_snapshot_is_non_secret_and_has_no_image(self) -> None:
        service, _backend = self._service()

        state = await service.shared_view_snapshot()

        self.assertEqual(state.state, "idle")
        self.assertIsNone(state.session_id)
        self.assertIsNone(state.backend)
        self.assertIsNone(state.screenshot_artifact_uri)
        with self.assertRaises(TermuinatorError) as missing:
            await service.shared_view_screenshot()
        self.assertEqual(missing.exception.code, ErrorCode.ARTIFACT_NOT_FOUND)

    async def test_pending_permission_is_visible_then_cleared_by_local_decision(self) -> None:
        service, backend = self._service()
        session_id, observation = await self._start_and_observe(service)
        before_navigation = list(backend.navigation_calls)

        with self.assertRaises(TermuinatorError) as permission:
            await service.navigate(
                session_id=session_id,
                tab_id=observation.tab_id,
                page_id=observation.page_id,
                expected_revision=observation.page_revision,
                operation="goto",
                url="https://other.example/path?token=secret#private",
            )
        self.assertEqual(permission.exception.code, ErrorCode.PERMISSION_REQUIRED)

        pending = await service.shared_view_snapshot()
        self.assertEqual(len(pending.pending_permissions), 1)
        challenge = pending.pending_permissions[0]
        self.assertEqual(challenge.kind, ChallengeKind.PERMISSION)
        self.assertEqual(challenge.state, ChallengeState.PENDING)
        self.assertIn("https://other.example", challenge.preview)
        self.assertNotIn("secret", challenge.preview)
        self.assertEqual(backend.navigation_calls, before_navigation)

        await service.local_permission_record(
            session_id=session_id,
            origin="https://other.example",
            policy=PermissionPolicy.SESSION_ALLOW,
        )
        cleared = await service.shared_view_snapshot()
        self.assertEqual(cleared.pending_permissions, ())

    async def test_takeover_hides_page_challenges_traces_and_screenshot(self) -> None:
        service, _backend = self._service(sensitive=True)
        _session_id, _observation = await self._start_and_observe(service)

        state = await service.shared_view_snapshot()

        self.assertTrue(state.confidential)
        self.assertEqual(state.state, SessionState.USER_TAKEOVER_REQUIRED.value)
        self.assertEqual(state.url, "")
        self.assertEqual(state.title, "")
        self.assertIsNone(state.active_tab_id)
        self.assertIsNone(state.page_revision)
        self.assertIsNone(state.screenshot_artifact_uri)
        self.assertEqual(state.pending_permissions, ())
        self.assertEqual(state.pending_confirmations, ())
        self.assertEqual(state.recent_traces, ())
        with self.assertRaises(TermuinatorError) as paused:
            await service.shared_view_screenshot()
        self.assertEqual(paused.exception.code, ErrorCode.SESSION_PAUSED)


class _Provider:
    def __init__(self, state: SharedViewState) -> None:
        self.state = state
        self.snapshot_calls = 0
        self.screenshot_calls = 0

    async def shared_view_snapshot(self) -> SharedViewState:
        self.snapshot_calls += 1
        return self.state

    async def shared_view_screenshot(self) -> SharedViewArtifact:
        self.screenshot_calls += 1
        return SharedViewArtifact(data=_PNG, mime_type="image/png")


class SharedViewHttpTests(unittest.IsolatedAsyncioTestCase):
    def _state(self) -> SharedViewState:
        now = datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc).isoformat()
        challenge = Challenge(
            challenge_id="confirmation_abcdefgh",
            kind=ChallengeKind.CONFIRMATION,
            state=ChallengeState.PENDING,
            preview="Publish the form",
            expires_at=now,
        )
        permission = Challenge(
            challenge_id="permission_abcdefgh",
            kind=ChallengeKind.PERMISSION,
            state=ChallengeState.PENDING,
            preview="Allow browser access to https://other.example",
            expires_at=None,
        )
        trace = TraceRecord(
            trace_id="trace_abcdefgh",
            step_id="step_abcdefgh",
            action_kind="click",
            risk=RiskClass.R2,
            page_revision=PageRevision("epoch_shared", 3),
            permission="session_allow",
            verification_passed=True,
            started_at=now,
            duration_ms=25,
        )
        return SharedViewState(
            generated_at=now,
            session_id="session_abcdefgh",
            state=SessionState.ACTIVE.value,
            backend=Backend.CHROMIUM,
            running=True,
            active_tab_id="tab_abcdefgh",
            page_revision=PageRevision("epoch_shared", 3),
            url="https://user:password@example.com/dashboard?token=secret#private",
            title="token=secret Dashboard",
            ready_state="complete",
            freshness_ms=5,
            screenshot_artifact_uri=(
                "artifact://sha256/" + hashlib.sha256(_PNG).hexdigest()
            ),
            pending_permissions=(permission,),
            pending_confirmations=(challenge,),
            recent_traces=(trace,),
            traces_truncated=False,
            confidential=False,
        )

    async def _request(
        self,
        server: SharedViewServer,
        *,
        method: str = "GET",
        target: str = "/",
        host: str | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        reader, writer = await asyncio.open_connection(server.host, server.port)
        authority = host or f"{server.host}:{server.port}"
        writer.write(
            (
                f"{method} {target} HTTP/1.1\r\n"
                f"Host: {authority}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
        )
        await writer.drain()
        raw = await reader.read()
        writer.close()
        await writer.wait_closed()
        head, body = raw.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        status = int(lines[0].split(" ", 2)[1])
        headers = {
            name.lower(): value.strip()
            for name, value in (line.split(":", 1) for line in lines[1:])
        }
        return status, headers, body

    async def test_server_is_loopback_only(self) -> None:
        provider = _Provider(self._state())
        with self.assertRaises(ValueError):
            SharedViewServer(provider=provider, host="0.0.0.0")

    async def test_read_only_api_has_security_headers_and_no_private_uri(self) -> None:
        provider = _Provider(self._state())
        server = SharedViewServer(provider=provider)
        await server.start()
        self.addAsyncCleanup(server.close)

        status, headers, body = await self._request(server, target="/api/state")
        payload = json.loads(body)

        self.assertEqual(status, 200)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(headers["x-frame-options"], "DENY")
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", headers["content-security-policy"])
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["refresh_interval_ms"], 2_000)
        self.assertEqual(payload["screenshot_url"], "/screenshot/current")
        self.assertNotIn("artifact://", body.decode("utf-8"))
        self.assertNotIn("nonce", body.decode("utf-8").lower())
        self.assertNotIn("proof", body.decode("utf-8").lower())
        self.assertNotIn("confirmation_abcdefgh", body.decode("utf-8"))
        self.assertNotIn("permission_abcdefgh", body.decode("utf-8"))
        self.assertNotIn("secret", body.decode("utf-8").lower())
        self.assertNotIn("password", body.decode("utf-8").lower())
        self.assertEqual(
            payload["session"]["url"],
            "https://example.com/dashboard?redacted",
        )
        self.assertEqual(payload["session"]["title"], "token=[REDACTED] Dashboard")
        self.assertEqual(len(payload["pending"]["permissions"]), 1)
        self.assertEqual(len(payload["pending"]["confirmations"]), 1)
        self.assertEqual(provider.snapshot_calls, 1)

    async def test_static_page_has_no_mutation_controls_and_image_is_bounded(self) -> None:
        provider = _Provider(self._state())
        server = SharedViewServer(provider=provider)
        await server.start()
        self.addAsyncCleanup(server.close)

        page_status, _headers, page = await self._request(server)
        image_status, image_headers, image = await self._request(
            server,
            target="/screenshot/current",
        )
        post_status, post_headers, _post_body = await self._request(
            server,
            method="POST",
            target="/api/state",
        )

        lowered = page.decode("utf-8").lower()
        self.assertEqual(page_status, 200)
        self.assertNotIn("<button", lowered)
        self.assertNotIn("<form", lowered)
        self.assertNotIn("approve", lowered)
        self.assertNotIn("resume", lowered)
        self.assertEqual(image_status, 200)
        self.assertEqual(image_headers["content-type"], "image/png")
        self.assertEqual(image, _PNG)
        self.assertEqual(post_status, 405)
        self.assertEqual(post_headers["allow"], "GET, HEAD")

    async def test_host_header_mismatch_is_rejected(self) -> None:
        provider = _Provider(self._state())
        server = SharedViewServer(provider=provider)
        await server.start()
        self.addAsyncCleanup(server.close)

        status, _headers, body = await self._request(
            server,
            target="/api/state",
            host="attacker.example",
        )

        self.assertEqual(status, 421)
        self.assertNotIn(b"Dashboard", body)
        self.assertEqual(provider.snapshot_calls, 0)


if __name__ == "__main__":
    unittest.main()
