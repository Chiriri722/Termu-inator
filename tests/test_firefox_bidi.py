"""Fail-closed WebDriver BiDi contracts for the native Firefox backend."""

from __future__ import annotations

import asyncio
from collections import deque
import importlib
import json
import unittest


def _load_bidi(testcase: unittest.TestCase):
    try:
        return importlib.import_module("src.firefox_bidi")
    except ModuleNotFoundError:
        testcase.fail("Firefox BiDi transport is not implemented")


class _Socket:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = deque(
            json.dumps(response, separators=(",", ":"))
            for response in responses
        )
        self.sent: list[dict] = []
        self.closed = False

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    async def recv(self) -> str:
        if self.responses:
            return self.responses.popleft()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def close(self) -> None:
        self.closed = True


class FirefoxBidiTests(unittest.IsolatedAsyncioTestCase):
    def test_endpoint_parser_accepts_only_firefox_loopback_output(self) -> None:
        bidi = _load_bidi(self)
        parse = bidi.parse_firefox_bidi_endpoint

        self.assertEqual(
            parse(
                b"WebDriver BiDi listening on "
                b"ws://127.0.0.1:46249\n"
            ),
            "ws://127.0.0.1:46249/session",
        )
        for unsafe in (
            b"prefix WebDriver BiDi listening on ws://127.0.0.1:9222",
            b"WebDriver BiDi listening on ws://0.0.0.0:9222",
            b"WebDriver BiDi listening on ws://localhost:9222",
            b"WebDriver BiDi listening on ws://127.0.0.1:0",
            b"WebDriver BiDi listening on ws://127.0.0.1:70000",
            b"WebDriver BiDi listening on ws://127.0.0.1:9222/private",
        ):
            with self.subTest(unsafe=unsafe):
                self.assertIsNone(parse(unsafe))

    async def test_client_returns_verified_redirect_metadata(self) -> None:
        bidi = _load_bidi(self)
        socket = _Socket(
            [
                {
                    "id": 1,
                    "type": "success",
                    "result": {
                        "sessionId": "session-1",
                        "capabilities": {},
                    },
                },
                {
                    "id": 2,
                    "type": "success",
                    "result": {
                        "contexts": [
                            {
                                "context": "context-1",
                                "url": "about:blank",
                                "children": [],
                            }
                        ]
                    },
                },
                {
                    "type": "event",
                    "method": "browsingContext.load",
                    "params": {},
                },
                {
                    "id": 3,
                    "type": "success",
                    "result": {
                        "navigation": "navigation-1",
                        "url": "http://127.0.0.1:43123/forms?redirected=1",
                    },
                },
                {
                    "id": 4,
                    "type": "success",
                    "result": {
                        "realm": "realm-1",
                        "result": {"type": "string", "value": "Forms"},
                    },
                },
                {"id": 5, "type": "success", "result": {}},
            ]
        )
        connection: list[tuple[str, dict]] = []

        async def connector(endpoint: str, **kwargs):
            connection.append((endpoint, kwargs))
            return socket

        client = bidi.FirefoxBidiClient(
            "ws://127.0.0.1:46249/session",
            connector=connector,
        )
        await client.connect(timeout=5)
        metadata = await client.navigate(
            "http://127.0.0.1:43123/forms",
            timeout=45,
        )
        await client.close()

        self.assertEqual(
            metadata,
            {
                "url": "http://127.0.0.1:43123/forms?redirected=1",
                "title": "Forms",
            },
        )
        self.assertEqual(
            connection,
            [
                (
                    "ws://127.0.0.1:46249/session",
                    {"open_timeout": 5, "max_size": 1024 * 1024},
                )
            ],
        )
        self.assertEqual(
            [request["method"] for request in socket.sent],
            [
                "session.new",
                "browsingContext.getTree",
                "browsingContext.navigate",
                "script.evaluate",
                "session.end",
            ],
        )
        self.assertEqual(
            socket.sent[2]["params"],
            {
                "context": "context-1",
                "url": "http://127.0.0.1:43123/forms",
                "wait": "complete",
            },
        )
        self.assertEqual(
            socket.sent[3]["params"],
            {
                "expression": "document.title",
                "target": {"context": "context-1"},
                "awaitPromise": False,
            },
        )
        self.assertTrue(socket.closed)

    async def test_remote_error_is_bounded_and_does_not_leak(self) -> None:
        bidi = _load_bidi(self)
        private_error = "private remote response detail"
        socket = _Socket(
            [
                {
                    "id": 1,
                    "type": "error",
                    "error": "session not created",
                    "message": private_error,
                }
            ]
        )

        async def connector(_endpoint: str, **_kwargs):
            return socket

        client = bidi.FirefoxBidiClient(
            "ws://127.0.0.1:46249/session",
            connector=connector,
        )
        with self.assertRaises(bidi.FirefoxBidiError) as caught:
            await client.connect(timeout=5)
        await client.close()

        self.assertNotIn(private_error, str(caught.exception))
        self.assertTrue(socket.closed)

    async def test_boolean_response_id_is_rejected(self) -> None:
        bidi = _load_bidi(self)
        socket = _Socket(
            [
                {
                    "id": True,
                    "type": "success",
                    "result": {"sessionId": "session-1"},
                },
                {
                    "id": 2,
                    "type": "success",
                    "result": {
                        "contexts": [
                            {"context": "context-1", "url": "about:blank"}
                        ]
                    },
                },
                {"id": 3, "type": "success", "result": {}},
            ]
        )

        async def connector(_endpoint: str, **_kwargs):
            return socket

        client = bidi.FirefoxBidiClient(
            "ws://127.0.0.1:46249/session",
            connector=connector,
        )
        try:
            with self.assertRaises(bidi.FirefoxBidiError):
                await client.connect(timeout=5)
        finally:
            await client.close()
        self.assertTrue(socket.closed)

    async def test_duplicate_connect_is_rejected_before_connector_call(self) -> None:
        bidi = _load_bidi(self)
        socket = _Socket(
            [
                {
                    "id": 1,
                    "type": "success",
                    "result": {"sessionId": "session-1"},
                },
                {
                    "id": 2,
                    "type": "success",
                    "result": {
                        "contexts": [
                            {"context": "context-1", "url": "about:blank"}
                        ]
                    },
                },
                {"id": 3, "type": "success", "result": {}},
            ]
        )
        calls = 0

        async def connector(_endpoint: str, **_kwargs):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise AssertionError("connector must not be called twice")
            return socket

        client = bidi.FirefoxBidiClient(
            "ws://127.0.0.1:46249/session",
            connector=connector,
        )
        await client.connect(timeout=5)
        with self.assertRaises(bidi.FirefoxBidiError):
            await client.connect(timeout=5)
        await client.close()

        self.assertEqual(calls, 1)
        self.assertTrue(socket.closed)

    async def test_navigation_timeout_is_fixed_and_socket_can_close(self) -> None:
        bidi = _load_bidi(self)
        socket = _Socket(
            [
                {
                    "id": 1,
                    "type": "success",
                    "result": {"sessionId": "session-1"},
                },
                {
                    "id": 2,
                    "type": "success",
                    "result": {
                        "contexts": [
                            {"context": "context-1", "url": "about:blank"}
                        ]
                    },
                },
            ]
        )

        async def connector(_endpoint: str, **_kwargs):
            return socket

        client = bidi.FirefoxBidiClient(
            "ws://127.0.0.1:46249/session",
            connector=connector,
        )
        await client.connect(timeout=5)
        with self.assertRaises(TimeoutError) as caught:
            await client.navigate("https://example.com", timeout=0.001)
        self.assertEqual(str(caught.exception), "Firefox BiDi command timed out")

        socket.responses.append(
            json.dumps(
                {"id": 4, "type": "success", "result": {}},
                separators=(",", ":"),
            )
        )
        await client.close()
        self.assertTrue(socket.closed)

    async def test_close_preserves_cancellation_after_socket_cleanup(self) -> None:
        bidi = _load_bidi(self)

        class _CancelledEndSocket(_Socket):
            async def recv(self) -> str:
                if self.sent and self.sent[-1]["method"] == "session.end":
                    raise asyncio.CancelledError()
                return await super().recv()

        socket = _CancelledEndSocket(
            [
                {
                    "id": 1,
                    "type": "success",
                    "result": {"sessionId": "session-1"},
                },
                {
                    "id": 2,
                    "type": "success",
                    "result": {
                        "contexts": [
                            {"context": "context-1", "url": "about:blank"}
                        ]
                    },
                },
            ]
        )

        async def connector(_endpoint: str, **_kwargs):
            return socket

        client = bidi.FirefoxBidiClient(
            "ws://127.0.0.1:46249/session",
            connector=connector,
        )
        await client.connect(timeout=5)

        with self.assertRaises(asyncio.CancelledError):
            await client.close()
        self.assertTrue(socket.closed)

    async def test_invalid_remote_metadata_is_rejected_without_value(self) -> None:
        bidi = _load_bidi(self)
        private_url = "javascript:private-device-value"
        socket = _Socket(
            [
                {
                    "id": 1,
                    "type": "success",
                    "result": {"sessionId": "session-1"},
                },
                {
                    "id": 2,
                    "type": "success",
                    "result": {
                        "contexts": [
                            {"context": "context-1", "url": "about:blank"}
                        ]
                    },
                },
                {
                    "id": 3,
                    "type": "success",
                    "result": {"navigation": "nav", "url": private_url},
                },
            ]
        )

        async def connector(_endpoint: str, **_kwargs):
            return socket

        client = bidi.FirefoxBidiClient(
            "ws://127.0.0.1:46249/session",
            connector=connector,
        )
        await client.connect(timeout=5)
        with self.assertRaises(bidi.FirefoxBidiError) as caught:
            await client.navigate("https://example.com", timeout=5)

        self.assertNotIn(private_url, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
