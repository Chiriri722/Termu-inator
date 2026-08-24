"""Low-level input safety regressions shared by Chromium and native Firefox."""

from __future__ import annotations

import unittest

from src.input import InputCommands


class _RecordingSession:
    def __init__(self, *, fail_during_move: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.fail_during_move = fail_during_move

    async def send(self, method: str, parameters: dict[str, object]) -> dict[str, object]:
        self.calls.append((method, parameters))
        if (
            self.fail_during_move
            and parameters.get("type") == "mouseMoved"
            and parameters.get("buttons") == 1
        ):
            raise RuntimeError("injected drag move failure")
        return {}


class InputCommandsDragTests(unittest.IsolatedAsyncioTestCase):
    async def test_drag_dispatches_bounded_path_and_releases_mouse(self) -> None:
        session = _RecordingSession()
        commands = InputCommands(session)

        await commands.drag(10, 20, 40, 50, steps=3)

        event_types = [parameters["type"] for _, parameters in session.calls]
        self.assertEqual(
            event_types,
            [
                "mouseMoved",
                "mousePressed",
                "mouseMoved",
                "mouseMoved",
                "mouseMoved",
                "mouseReleased",
            ],
        )
        self.assertEqual(session.calls[-1][1]["x"], 40)
        self.assertEqual(session.calls[-1][1]["y"], 50)
        self.assertEqual(session.calls[-1][1]["buttons"], 0)

    async def test_drag_releases_mouse_when_an_intermediate_move_fails(self) -> None:
        session = _RecordingSession(fail_during_move=True)
        commands = InputCommands(session)

        with self.assertRaisesRegex(RuntimeError, "injected drag move failure"):
            await commands.drag(10, 20, 40, 50, steps=3)

        self.assertEqual(session.calls[-1][1]["type"], "mouseReleased")
        self.assertEqual(session.calls[-1][1]["buttons"], 0)


if __name__ == "__main__":
    unittest.main()
