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
