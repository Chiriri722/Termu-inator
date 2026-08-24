"""Loopback-only static shared view over the trusted browser service."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from typing import Protocol

from .contracts import (
    Backend,
    Challenge,
    ChallengeKind,
    ChallengeState,
    PageRevision,
    SessionState,
    TraceRecord,
    to_wire,
)
from .core.redaction import redact_sensitive_text, redact_url_metadata
from .errors import TermuinatorError


_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{7,127}$")
_ARTIFACT_URI = re.compile(r"^artifact://sha256/[0-9a-f]{64}$")
_MAX_HEADER_BYTES = 16 * 1024
_MAX_SCREENSHOT_BYTES = 8 * 1024 * 1024
_REFRESH_INTERVAL_MS = 2_000
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})


@dataclass(frozen=True)
class SharedViewState:
    """Private local-view state; artifact identifiers never cross HTTP."""

    generated_at: str
    session_id: str | None
    state: str
    backend: Backend | None
    running: bool
    active_tab_id: str | None
    page_revision: PageRevision | None
    url: str
    title: str
    ready_state: str
    freshness_ms: int
    screenshot_artifact_uri: str | None
    pending_permissions: tuple[Challenge, ...]
    pending_confirmations: tuple[Challenge, ...]
    recent_traces: tuple[TraceRecord, ...]
    traces_truncated: bool
    confidential: bool

    def __post_init__(self) -> None:
        generated = datetime.fromisoformat(self.generated_at.replace("Z", "+00:00"))
        if generated.tzinfo is None:
            raise ValueError("shared-view generated_at must include a timezone")
        valid_states = {"idle", *(item.value for item in SessionState)}
        if self.state not in valid_states:
            raise ValueError("shared-view state is invalid")
        if self.session_id is not None and not _ID.fullmatch(self.session_id):
            raise ValueError("shared-view session_id is invalid")
        if self.backend is not None and not isinstance(self.backend, Backend):
            raise ValueError("shared-view backend is invalid")
        if not isinstance(self.running, bool) or not isinstance(self.confidential, bool):
            raise ValueError("shared-view flags must be booleans")
        if self.active_tab_id is not None and not _ID.fullmatch(self.active_tab_id):
            raise ValueError("shared-view tab identifier is invalid")
        if self.page_revision is not None and not isinstance(
            self.page_revision, PageRevision
        ):
            raise ValueError("shared-view page revision is invalid")
        for name, value, maximum in (
            ("url", self.url, 8_192),
            ("title", self.title, 4_096),
            ("ready_state", self.ready_state, 64),
        ):
            if not isinstance(value, str) or len(value) > maximum:
                raise ValueError(f"shared-view {name} is invalid or unbounded")
        if (
            isinstance(self.freshness_ms, bool)
            or not isinstance(self.freshness_ms, int)
            or not 0 <= self.freshness_ms <= 86_400_000
        ):
            raise ValueError("shared-view freshness is invalid")
        if self.screenshot_artifact_uri is not None and not _ARTIFACT_URI.fullmatch(
            self.screenshot_artifact_uri
        ):
            raise ValueError("shared-view screenshot URI is invalid")
        if len(self.pending_permissions) > 16 or any(
            not isinstance(item, Challenge)
            or item.kind is not ChallengeKind.PERMISSION
            or item.state is not ChallengeState.PENDING
            for item in self.pending_permissions
        ):
            raise ValueError("shared-view pending permissions are invalid")
        if len(self.pending_confirmations) > 16 or any(
            not isinstance(item, Challenge)
            or item.kind is not ChallengeKind.CONFIRMATION
            or item.state is not ChallengeState.PENDING
            for item in self.pending_confirmations
        ):
            raise ValueError("shared-view pending confirmations are invalid")
        if len(self.recent_traces) > 20 or any(
            not isinstance(item, TraceRecord) for item in self.recent_traces
        ):
            raise ValueError("shared-view recent traces are invalid or unbounded")
        if not isinstance(self.traces_truncated, bool):
            raise ValueError("shared-view trace truncation flag is invalid")
        if self.state == "idle" and any(
            value is not None for value in (self.session_id, self.backend)
        ):
            raise ValueError("idle shared view cannot identify a session")
        if self.confidential and (
            self.url
            or self.title
            or self.active_tab_id is not None
            or self.page_revision is not None
            or self.screenshot_artifact_uri is not None
            or self.pending_permissions
            or self.pending_confirmations
            or self.recent_traces
        ):
            raise ValueError("confidential shared view contains page data")


@dataclass(frozen=True)
class SharedViewArtifact:
    data: bytes
    mime_type: str

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or not 1 <= len(self.data) <= _MAX_SCREENSHOT_BYTES:
            raise ValueError("shared-view screenshot is empty or exceeds 8 MiB")
        if self.mime_type == "image/png":
            valid = self.data.startswith(b"\x89PNG\r\n\x1a\n")
        elif self.mime_type == "image/webp":
            valid = (
                len(self.data) >= 12
                and self.data.startswith(b"RIFF")
                and self.data[8:12] == b"WEBP"
            )
        else:
            valid = False
        if not valid:
            raise ValueError("shared-view screenshot MIME or signature is invalid")

    @property
    def etag(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


class SharedViewProvider(Protocol):
    async def shared_view_snapshot(self) -> SharedViewState: ...

    async def shared_view_screenshot(self) -> SharedViewArtifact: ...


_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Termu-inator Shared View</title>
  <link rel="stylesheet" href="/app.css">
</head>
<body>
  <main>
    <h1>Termu-inator Shared View</h1>
    <p id="indicator">Connecting to the local browser runtime…</p>
    <dl>
      <dt>Backend</dt><dd id="backend">—</dd>
      <dt>Tab</dt><dd id="tab">—</dd>
      <dt>URL</dt><dd id="url">—</dd>
      <dt>Title</dt><dd id="title">—</dd>
    </dl>
    <img id="screenshot" alt="Current cached browser screenshot" hidden>
    <section><h2>Pending confirmations</h2><ul id="confirmations"></ul></section>
    <section><h2>Recent action trace</h2><ul id="traces"></ul></section>
  </main>
  <script src="/app.js" defer></script>
</body>
</html>
""".encode("utf-8")

_CSS = b"""body{font:16px system-ui,sans-serif;margin:0;background:#111827;color:#f9fafb}main{max-width:1100px;margin:auto;padding:24px}dl{display:grid;grid-template-columns:max-content 1fr;gap:8px 16px}dd{margin:0;overflow-wrap:anywhere}img{display:block;max-width:100%;max-height:65vh;margin:24px 0;border:1px solid #374151}section{border-top:1px solid #374151;margin-top:20px}#indicator{padding:10px;background:#1f2937}ul{padding-left:24px}
"""

_JS = br"""'use strict';
const get=id=>document.getElementById(id);
const write=(id,value)=>{get(id).textContent=value??'\u2014';};
const list=(id,items,render)=>{const root=get(id);root.replaceChildren(...items.map(item=>{const node=document.createElement('li');node.textContent=render(item);return node;}));};
async function refresh(){
  try{
    const response=await fetch('/api/state',{cache:'no-store',credentials:'omit'});
    if(!response.ok)throw new Error('state unavailable');
    const data=await response.json();const session=data.session;
    write('indicator',data.confidential?'Confidential local takeover in progress':session.state);
    write('backend',session.backend);write('tab',session.active_tab_id);write('url',session.url);write('title',session.title);
    list('confirmations',data.pending.confirmations,item=>item.preview);
    list('traces',data.recent_traces,item=>`${item.action_kind} \u00b7 ${item.verification_passed?'verified':'failed'}`);
    const image=get('screenshot');
    if(data.screenshot_url){image.hidden=false;image.removeAttribute('src');image.src=data.screenshot_url;}else{image.hidden=true;image.removeAttribute('src');}
  }catch(_error){write('indicator','Shared view unavailable');get('screenshot').hidden=true;}
}
refresh();setInterval(refresh,2000);
"""


class SharedViewServer:
    """A minimal GET/HEAD-only HTTP server restricted to literal loopback."""

    def __init__(
        self,
        *,
        provider: SharedViewProvider,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        if host not in _LOOPBACK_HOSTS:
            raise ValueError("shared view must bind to a literal loopback address")
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65_535:
            raise ValueError("shared-view port is invalid")
        if not callable(getattr(provider, "shared_view_snapshot", None)) or not callable(
            getattr(provider, "shared_view_screenshot", None)
        ):
            raise TypeError("shared-view provider is invalid")
        self._provider = provider
        self._host = host
        self._requested_port = port
        self._server: asyncio.AbstractServer | None = None
        self._writers: set[asyncio.StreamWriter] = set()

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("shared view is not running")
        return int(self._server.sockets[0].getsockname()[1])

    @property
    def url(self) -> str:
        authority = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{authority}:{self.port}/"

    async def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("shared view is already running")
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self._host,
            port=self._requested_port,
            limit=_MAX_HEADER_BYTES + 1,
        )

    async def close(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.close()
            await server.wait_closed()
        writers = tuple(self._writers)
        for writer in writers:
            writer.close()
        if writers:
            await asyncio.gather(
                *(writer.wait_closed() for writer in writers),
                return_exceptions=True,
            )
        self._writers.clear()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._writers.add(writer)
        try:
            try:
                raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5.0)
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
                await self._respond(writer, 400, b"Bad Request\n", "text/plain; charset=utf-8")
                return
            if len(raw) > _MAX_HEADER_BYTES:
                await self._respond(writer, 431, b"Request Header Fields Too Large\n", "text/plain; charset=utf-8")
                return
            try:
                method, target, version, headers = self._parse_request(raw)
            except ValueError:
                await self._respond(writer, 400, b"Bad Request\n", "text/plain; charset=utf-8")
                return
            if not self._host_allowed(headers.get("host")):
                await self._respond(writer, 421, b"Misdirected Request\n", "text/plain; charset=utf-8")
                return
            if method not in {"GET", "HEAD"}:
                await self._respond(
                    writer,
                    405,
                    b"Method Not Allowed\n",
                    "text/plain; charset=utf-8",
                    method=method,
                    extra_headers={"Allow": "GET, HEAD"},
                )
                return
            if version not in {"HTTP/1.0", "HTTP/1.1"}:
                await self._respond(writer, 505, b"HTTP Version Not Supported\n", "text/plain; charset=utf-8", method=method)
                return
            await self._route(writer, method=method, target=target)
        except Exception:
            if not writer.is_closing():
                await self._respond(
                    writer,
                    500,
                    b"Shared View Unavailable\n",
                    "text/plain; charset=utf-8",
                )
        finally:
            self._writers.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    @staticmethod
    def _parse_request(raw: bytes) -> tuple[str, str, str, dict[str, str]]:
        try:
            lines = raw[:-4].decode("ascii").split("\r\n")
            method, target, version = lines[0].split(" ")
        except (UnicodeDecodeError, ValueError, IndexError) as exc:
            raise ValueError("invalid request line") from exc
        if not target.startswith("/") or "\x00" in target or len(target) > 2_048:
            raise ValueError("invalid request target")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" not in line:
                raise ValueError("invalid header")
            name, value = line.split(":", 1)
            key = name.strip().lower()
            if not key or key in headers:
                raise ValueError("duplicate or empty header")
            headers[key] = value.strip()
        if "transfer-encoding" in headers or headers.get("content-length", "0") != "0":
            raise ValueError("request bodies are not accepted")
        return method, target, version, headers

    def _host_allowed(self, host: str | None) -> bool:
        if host is None:
            return False
        authority = f"[{self.host}]" if ":" in self.host else self.host
        return host in {f"{authority}:{self.port}", f"localhost:{self.port}"}

    async def _route(
        self,
        writer: asyncio.StreamWriter,
        *,
        method: str,
        target: str,
    ) -> None:
        if target == "/":
            await self._respond(writer, 200, _HTML, "text/html; charset=utf-8", method=method)
            return
        if target == "/app.css":
            await self._respond(writer, 200, _CSS, "text/css; charset=utf-8", method=method)
            return
        if target == "/app.js":
            await self._respond(writer, 200, _JS, "text/javascript; charset=utf-8", method=method)
            return
        if target == "/api/state":
            state = await self._provider.shared_view_snapshot()
            if not isinstance(state, SharedViewState):
                raise TypeError("shared-view provider returned an invalid state")
            body = json.dumps(
                self._state_payload(state),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            await self._respond(writer, 200, body, "application/json; charset=utf-8", method=method)
            return
        if target == "/screenshot/current":
            try:
                artifact = await self._provider.shared_view_screenshot()
            except TermuinatorError:
                await self._respond(writer, 404, b"Screenshot Unavailable\n", "text/plain; charset=utf-8", method=method)
                return
            if not isinstance(artifact, SharedViewArtifact):
                raise TypeError("shared-view provider returned an invalid screenshot")
            await self._respond(
                writer,
                200,
                artifact.data,
                artifact.mime_type,
                method=method,
                extra_headers={"ETag": f'"sha256-{artifact.etag}"'},
            )
            return
        await self._respond(writer, 404, b"Not Found\n", "text/plain; charset=utf-8", method=method)

    @staticmethod
    def _state_payload(state: SharedViewState) -> dict[str, object]:
        def challenges(values: tuple[Challenge, ...]) -> list[dict[str, object]]:
            return [
                {
                    "kind": value.kind.value,
                    "state": value.state.value,
                    "preview": redact_sensitive_text(value.preview),
                    "expires_at": value.expires_at,
                }
                for value in values
            ]

        return {
            "version": 1,
            "refresh_interval_ms": _REFRESH_INTERVAL_MS,
            "generated_at": state.generated_at,
            "confidential": state.confidential,
            "session": {
                "session_id": state.session_id,
                "state": state.state,
                "backend": state.backend.value if state.backend is not None else None,
                "running": state.running,
                "active_tab_id": state.active_tab_id,
                "page_revision": (
                    str(state.page_revision) if state.page_revision is not None else None
                ),
                "url": redact_url_metadata(state.url),
                "title": redact_sensitive_text(state.title),
                "ready_state": state.ready_state,
                "freshness_ms": state.freshness_ms,
            },
            "screenshot_url": (
                "/screenshot/current"
                if state.screenshot_artifact_uri is not None and not state.confidential
                else None
            ),
            "pending": {
                "permissions": challenges(state.pending_permissions),
                "confirmations": challenges(state.pending_confirmations),
            },
            "recent_traces": [to_wire(item) for item in state.recent_traces],
            "traces_truncated": state.traces_truncated,
        }

    @staticmethod
    async def _respond(
        writer: asyncio.StreamWriter,
        status: int,
        body: bytes,
        content_type: str,
        *,
        method: str = "GET",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        reasons = {
            200: "OK",
            400: "Bad Request",
            404: "Not Found",
            405: "Method Not Allowed",
            421: "Misdirected Request",
            431: "Request Header Fields Too Large",
            500: "Internal Server Error",
            505: "HTTP Version Not Supported",
        }
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "Connection": "close",
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'self'; img-src 'self'; style-src 'self'; "
                "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'none'"
            ),
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        }
        if extra_headers:
            headers.update(extra_headers)
        encoded_headers = "".join(f"{name}: {value}\r\n" for name, value in headers.items())
        writer.write(
            f"HTTP/1.1 {status} {reasons[status]}\r\n{encoded_headers}\r\n".encode(
                "ascii"
            )
        )
        if method != "HEAD":
            writer.write(body)
        await writer.drain()


__all__ = [
    "SharedViewArtifact",
    "SharedViewProvider",
    "SharedViewServer",
    "SharedViewState",
]
