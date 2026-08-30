"""Small fail-closed WebDriver BiDi client for native Firefox."""

from __future__ import annotations

import asyncio
import itertools
import json
import math
import re
from typing import Any
from urllib.parse import urlsplit


_ENDPOINT_OUTPUT_RE = re.compile(
    rb"\AWebDriver BiDi listening on "
    rb"ws://127\.0\.0\.1:([0-9]{1,5})\r?\n?\Z"
)
_ENDPOINT_RE = re.compile(
    r"\Aws://127\.0\.0\.1:([0-9]{1,5})/session\Z"
)
_MAX_MESSAGE_BYTES = 1024 * 1024
_MAX_UNSOLICITED_MESSAGES = 64


class FirefoxBidiError(RuntimeError):
    """A fixed-value failure that does not expose remote protocol data."""

    def __init__(self) -> None:
        super().__init__("Firefox BiDi protocol failed")


def _valid_port(value: str) -> bool:
    try:
        port = int(value, 10)
    except ValueError:
        return False
    return 1 <= port <= 65_535


def parse_firefox_bidi_endpoint(line: bytes | str) -> str | None:
    """Return only the exact loopback session endpoint Firefox announced."""

    raw = line.encode("utf-8", errors="replace") if isinstance(line, str) else line
    if not isinstance(raw, bytes):
        return None
    match = _ENDPOINT_OUTPUT_RE.fullmatch(raw)
    if match is None:
        return None
    port = match.group(1).decode("ascii")
    if not _valid_port(port):
        return None
    return f"ws://127.0.0.1:{port}/session"


def _validate_endpoint(endpoint: str) -> None:
    match = _ENDPOINT_RE.fullmatch(endpoint) if isinstance(endpoint, str) else None
    if match is None or not _valid_port(match.group(1)):
        raise ValueError("Firefox BiDi endpoint must be an assigned loopback port")


def _validate_timeout(timeout: float) -> float:
    try:
        value = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("Firefox BiDi timeout must be positive") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Firefox BiDi timeout must be positive")
    return value


def _validate_http_url(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 8_192:
        raise FirefoxBidiError()
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise FirefoxBidiError() from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or any(char <= " " or char == "\x7f" for char in value)
    ):
        raise FirefoxBidiError()
    return value


class FirefoxBidiClient:
    """Sequential BiDi transport for one owned top-level browsing context."""

    def __init__(self, endpoint: str, *, connector=None) -> None:
        _validate_endpoint(endpoint)
        self._endpoint = endpoint
        self._connector = connector
        self._socket = None
        self._session_id: str | None = None
        self._context_id: str | None = None
        self._ids = itertools.count(1)
        self._command_lock = asyncio.Lock()

    async def connect(self, *, timeout: float = 5) -> "FirefoxBidiClient":
        timeout = _validate_timeout(timeout)
        if self._socket is not None:
            raise FirefoxBidiError()
        connector = self._connector
        if connector is None:
            from websockets.asyncio.client import connect as connector

        try:
            self._socket = await connector(
                self._endpoint,
                open_timeout=timeout,
                max_size=_MAX_MESSAGE_BYTES,
            )
            session = await self._command(
                "session.new",
                {"capabilities": {"alwaysMatch": {}}},
                timeout=timeout,
            )
            session_id = session.get("sessionId")
            if (
                not isinstance(session_id, str)
                or not session_id
                or len(session_id) > 256
            ):
                raise FirefoxBidiError()
            self._session_id = session_id

            tree = await self._command(
                "browsingContext.getTree",
                {"maxDepth": 0},
                timeout=timeout,
            )
            contexts = tree.get("contexts")
            if not isinstance(contexts, list) or len(contexts) != 1:
                raise FirefoxBidiError()
            context = contexts[0]
            context_id = context.get("context") if isinstance(context, dict) else None
            if (
                not isinstance(context_id, str)
                or not context_id
                or len(context_id) > 256
            ):
                raise FirefoxBidiError()
            self._context_id = context_id
        except (asyncio.CancelledError, TimeoutError, FirefoxBidiError):
            raise
        except Exception as exc:
            raise FirefoxBidiError() from exc
        return self

    async def _command(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        timeout = _validate_timeout(timeout)
        socket = self._socket
        if socket is None:
            raise FirefoxBidiError()
        request_id = next(self._ids)
        payload = json.dumps(
            {"id": request_id, "method": method, "params": params},
            separators=(",", ":"),
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        async with self._command_lock:
            try:
                await asyncio.wait_for(
                    socket.send(payload),
                    timeout=max(deadline - loop.time(), 0.001),
                )
                for _ in range(_MAX_UNSOLICITED_MESSAGES):
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise TimeoutError("Firefox BiDi command timed out")
                    raw = await asyncio.wait_for(socket.recv(), timeout=remaining)
                    if not isinstance(raw, (str, bytes)):
                        raise FirefoxBidiError()
                    if isinstance(raw, bytes) and len(raw) > _MAX_MESSAGE_BYTES:
                        raise FirefoxBidiError()
                    if isinstance(raw, str) and len(raw.encode("utf-8")) > _MAX_MESSAGE_BYTES:
                        raise FirefoxBidiError()
                    try:
                        message = json.loads(raw)
                    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                        raise FirefoxBidiError() from exc
                    if not isinstance(message, dict):
                        raise FirefoxBidiError()
                    response_id = message.get("id")
                    if type(response_id) is not int or response_id != request_id:
                        if message.get("type") == "event" and "id" not in message:
                            continue
                        raise FirefoxBidiError()
                    if message.get("type") != "success":
                        raise FirefoxBidiError()
                    result = message.get("result")
                    if not isinstance(result, dict):
                        raise FirefoxBidiError()
                    return result
                raise FirefoxBidiError()
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                raise TimeoutError("Firefox BiDi command timed out") from None
            except (TimeoutError, FirefoxBidiError):
                raise
            except Exception as exc:
                raise FirefoxBidiError() from exc

    async def navigate(self, url: str, *, timeout: float) -> dict[str, str]:
        requested_url = _validate_http_url(url)
        timeout = _validate_timeout(timeout)
        context_id = self._context_id
        if context_id is None:
            raise FirefoxBidiError()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        navigation = await self._command(
            "browsingContext.navigate",
            {
                "context": context_id,
                "url": requested_url,
                "wait": "complete",
            },
            timeout=max(deadline - loop.time(), 0.001),
        )
        final_url = _validate_http_url(navigation.get("url"))

        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError("Firefox BiDi command timed out")
        evaluation = await self._command(
            "script.evaluate",
            {
                "expression": "document.title",
                "target": {"context": context_id},
                "awaitPromise": False,
            },
            timeout=remaining,
        )
        remote_value = evaluation.get("result")
        title = remote_value.get("value") if isinstance(remote_value, dict) else None
        if (
            not isinstance(remote_value, dict)
            or remote_value.get("type") != "string"
            or not isinstance(title, str)
            or len(title) > 4_096
        ):
            raise FirefoxBidiError()
        return {"url": final_url, "title": title}

    async def close(self) -> None:
        socket = self._socket
        if socket is None:
            return
        cancelled = False
        try:
            if self._session_id is not None:
                try:
                    await self._command("session.end", {}, timeout=2)
                except asyncio.CancelledError:
                    cancelled = True
                except Exception:
                    pass
        finally:
            self._session_id = None
            self._context_id = None
            self._socket = None
            try:
                await asyncio.wait_for(socket.close(), timeout=2)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                pass
        if cancelled:
            raise asyncio.CancelledError
