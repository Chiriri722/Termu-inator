"""Bounded request ownership across CDP cancellation and transport failure."""

import asyncio
import importlib.util
import json
from types import SimpleNamespace
import unittest


@unittest.skipUnless(
    importlib.util.find_spec("websockets") is not None,
    "requires the websockets transport dependency",
)
class CDPClientLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_timeout_includes_blocked_send(self):
        from src.cdp import CDPClient

        client = CDPClient("ws://127.0.0.1:1")
        requests = []
        futures = []

        async def stalled_send(payload):
            requests.append(json.loads(payload))
            futures.extend(client._callbacks.values())
            await asyncio.Event().wait()

        client._ws = SimpleNamespace(close_code=None, send=stalled_send)
        pending = asyncio.create_task(client.send("Runtime.evaluate", timeout=0.02))
        try:
            done, _ = await asyncio.wait({pending}, timeout=1)
            self.assertIn(pending, done, "the command deadline did not bound socket.send")
            with self.assertRaisesRegex(TimeoutError, "CDP command Runtime.evaluate timed out"):
                await pending
            self.assertEqual(len(requests), 1)
            self.assertEqual(client._callbacks, {})
            self.assertEqual(len(futures), 1)
            self.assertTrue(futures[0].cancelled())
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    async def test_send_and_reply_share_one_timeout_budget(self):
        from src.cdp import CDPClient

        client = CDPClient("ws://127.0.0.1:1")
        requests = []
        replies = []
        loop = asyncio.get_running_loop()

        async def slow_send(payload):
            request = json.loads(payload)
            requests.append(request)
            future = client._callbacks[request["id"]]

            def reply():
                if not future.done():
                    future.set_result({"id": request["id"], "result": {}})

            replies.append(loop.call_later(0.3, reply))
            await asyncio.sleep(0.15)

        client._ws = SimpleNamespace(close_code=None, send=slow_send)
        try:
            with self.assertRaisesRegex(TimeoutError, "CDP command Runtime.evaluate timed out"):
                await client.send("Runtime.evaluate", timeout=0.2)
            self.assertEqual(len(requests), 1)
            self.assertEqual(client._callbacks, {})
        finally:
            for timer in replies:
                timer.cancel()

    async def test_cancelled_reply_wait_releases_callback_without_resending(self):
        from websockets.asyncio.server import serve
        from src.cdp import CDPClient

        received = asyncio.Event()
        requests = []

        async def peer(socket):
            async for raw in socket:
                request = json.loads(raw)
                requests.append(request["method"])
                if request["method"] == "Runtime.evaluate":
                    received.set()  # Accept once, deliberately withhold the reply.
                else:
                    await socket.send(json.dumps({"id": request["id"], "result": {}}))

        async with serve(peer, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = CDPClient(f"ws://127.0.0.1:{port}")
            pending = None
            try:
                await client.connect()
                pending = asyncio.create_task(client.send("Runtime.evaluate"))
                await asyncio.wait_for(received.wait(), timeout=2)
                pending.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await pending
                self.assertEqual(client._callbacks, {})
                self.assertEqual(await client.send("Page.getFrameTree", timeout=2), {})
                self.assertEqual(requests.count("Runtime.evaluate"), 1)
            finally:
                if pending is not None:
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                await client.close()

    async def test_late_reply_after_timeout_does_not_replay_or_poison_next_command(self):
        from websockets.asyncio.server import serve
        from src.cdp import CDPClient

        release_reply = asyncio.Event()
        requests = []

        async def peer(socket):
            async for raw in socket:
                request = json.loads(raw)
                requests.append(request["method"])
                if request["method"] == "Runtime.evaluate":
                    await release_reply.wait()
                await socket.send(json.dumps({"id": request["id"], "result": {}}))

        async with serve(peer, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = CDPClient(f"ws://127.0.0.1:{port}")
            try:
                await client.connect()
                with self.assertRaisesRegex(TimeoutError, "CDP command Runtime.evaluate timed out"):
                    await client.send("Runtime.evaluate", timeout=0.02)
                self.assertEqual(client._callbacks, {})
                release_reply.set()
                self.assertEqual(await client.send("Page.getFrameTree", timeout=2), {})
                self.assertEqual(requests.count("Runtime.evaluate"), 1)
                self.assertEqual(requests.count("Page.getFrameTree"), 1)
            finally:
                release_reply.set()
                await client.close()

    async def test_send_failure_retires_its_unawaited_future(self):
        from src.cdp import CDPClient

        for failure in (ConnectionError("transport closed"), asyncio.CancelledError()):
            with self.subTest(failure=type(failure).__name__):
                client = CDPClient("ws://127.0.0.1:1")
                abandoned = []

                async def fail_send(_payload):
                    abandoned.extend(client._callbacks.values())
                    raise failure

                client._ws = SimpleNamespace(close_code=None, send=fail_send)
                with self.assertRaises(type(failure)):
                    await client.send("Runtime.evaluate")
                self.assertEqual(client._callbacks, {})
                self.assertEqual(len(abandoned), 1)
                self.assertTrue(abandoned[0].cancelled())

    async def test_cancelled_close_cleans_socket_without_swallowing_cancellation(self):
        from websockets.asyncio.server import serve
        from src.cdp import CDPClient

        async def peer(socket):
            async for raw in socket:
                request = json.loads(raw)
                await socket.send(json.dumps({"id": request["id"], "result": {}}))

        async with serve(peer, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = CDPClient(f"ws://127.0.0.1:{port}")
            closing = None
            try:
                await client.connect()
                socket = client._ws
                listener = client._listener_task
                closing = asyncio.create_task(client.close())
                # Cancel the caller while close is waiting for its cancelled listener.
                await asyncio.sleep(0)
                self.assertTrue(closing.cancel())
                with self.assertRaises(asyncio.CancelledError):
                    await closing
                self.assertTrue(listener.done())
                self.assertIsNotNone(socket.close_code)
                self.assertEqual(client._callbacks, {})
                with self.assertRaises(ConnectionError):
                    await client.send("Runtime.evaluate")
            finally:
                if closing is not None:
                    closing.cancel()
                    await asyncio.gather(closing, return_exceptions=True)
                await client.close()

    async def test_close_releases_pending_reply_without_replaying_request(self):
        from websockets.asyncio.server import serve
        from src.cdp import CDPClient

        received = asyncio.Event()
        requests = []

        async def peer(socket):
            async for raw in socket:
                request = json.loads(raw)
                requests.append(request["method"])
                if request["method"] == "Runtime.evaluate":
                    received.set()
                else:
                    await socket.send(json.dumps({"id": request["id"], "result": {}}))

        async with serve(peer, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = CDPClient(f"ws://127.0.0.1:{port}")
            pending = None
            try:
                await client.connect()
                socket = client._ws
                listener = client._listener_task
                pending = asyncio.create_task(client.send("Runtime.evaluate"))
                await asyncio.wait_for(received.wait(), timeout=2)
                await client.close()
                with self.assertRaises(ConnectionError):
                    await asyncio.wait_for(pending, timeout=2)
                self.assertEqual(client._callbacks, {})
                self.assertTrue(listener.done())
                self.assertIsNotNone(socket.close_code)
                self.assertEqual(requests.count("Runtime.evaluate"), 1)
                await client.close()
            finally:
                if pending is not None:
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                await client.close()

    async def test_close_preserves_socket_failure_for_owner_retry(self):
        from src.cdp import CDPClient

        for failure in (RuntimeError("close failed"), asyncio.CancelledError()):
            with self.subTest(failure=type(failure).__name__):
                client = CDPClient("ws://127.0.0.1:1")
                attempts = 0

                async def close_socket():
                    nonlocal attempts
                    attempts += 1
                    if attempts == 1:
                        raise failure

                socket = SimpleNamespace(close=close_socket)
                client._ws = socket
                with self.assertRaises(type(failure)) as caught:
                    await client.close()
                self.assertIs(caught.exception, failure)
                self.assertIs(client._ws, socket)
                await client.close()
                self.assertEqual(attempts, 2)

    async def test_close_does_not_hide_an_unexpected_listener_failure(self):
        from src.cdp import CDPClient

        failure = RuntimeError("listener cleanup failed")

        async def fail_listener():
            raise failure

        client = CDPClient("ws://127.0.0.1:1")
        client._listener_task = asyncio.create_task(fail_listener())
        await asyncio.gather(client._listener_task, return_exceptions=True)
        with self.assertRaises(RuntimeError) as caught:
            await client.close()
        self.assertIs(caught.exception, failure)
