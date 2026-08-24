"""Tests for service-owned observation identity and revision state."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest

from src.termuinator.backends import BackendPageSnapshot, RawInteractiveElement
from src.termuinator.contracts import Bounds, ErrorCode, Viewport
from src.termuinator.core.observation import ObservationEngine
from src.termuinator.errors import TermuinatorError


class ObservationEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 24, 13, 0, tzinfo=timezone.utc)
        self.engine = ObservationEngine(
            session_id="session_12345678",
            capability_revision="fake-v1",
            default_viewport=Viewport(width=1280, height=720),
            now=lambda: self.now,
        )

    @staticmethod
    def _snapshot(*, name: str = "Continue") -> BackendPageSnapshot:
        return BackendPageSnapshot(
            url="https://example.com/path",
            title="Example Domain",
            ready_state="complete",
            viewport=None,
            text="Example Domain",
            interactive_elements=(
                RawInteractiveElement(
                    backend_node_id="node-1",
                    role="button",
                    accessible_name=name,
                    tag="button",
                    bounds=Bounds(x=10, y=20, width=100, height=40),
                ),
            ),
        )

    def test_service_mints_identity_revision_origin_and_stable_refs(self) -> None:
        first = self.engine.capture(self._snapshot())
        second = self.engine.capture(self._snapshot(), dom_changed=True)

        self.assertEqual(first.session_id, "session_12345678")
        self.assertRegex(first.page_id, r"^page_[A-Za-z0-9_-]{16,}$")
        self.assertRegex(first.tab_id, r"^tab_[A-Za-z0-9_-]{16,}$")
        self.assertEqual(first.origin, "https://example.com")
        self.assertEqual(first.viewport, Viewport(width=1280, height=720))
        self.assertEqual(first.page_revision.document_epoch, second.page_revision.document_epoch)
        self.assertEqual((first.page_revision.mutation_counter, second.page_revision.mutation_counter), (0, 1))
        self.assertEqual(second.sequence, first.sequence + 1)
        self.assertEqual(
            first.interactive_elements[0].ref,
            second.interactive_elements[0].ref,
        )

    def test_document_navigation_rotates_page_epoch_and_refs(self) -> None:
        before = self.engine.capture(self._snapshot())
        after = self.engine.capture(self._snapshot(), document_changed=True)

        self.assertEqual(before.tab_id, after.tab_id)
        self.assertNotEqual(before.page_id, after.page_id)
        self.assertNotEqual(
            before.page_revision.document_epoch,
            after.page_revision.document_epoch,
        )
        self.assertNotEqual(
            before.interactive_elements[0].ref,
            after.interactive_elements[0].ref,
        )

        with self.assertRaises(TermuinatorError) as stale:
            self.engine.require_context(
                session_id=before.session_id,
                tab_id=before.tab_id,
                page_id=before.page_id,
                expected_revision=before.page_revision,
            )
        self.assertEqual(stale.exception.code, ErrorCode.STALE_OBSERVATION)


if __name__ == "__main__":
    unittest.main()
