"""Fake backend capability claims must match configured behavior."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.termuinator.backends import (
    BackendActionEvidence,
    BackendActionOutcome,
    BackendPageSnapshot,
)
from src.termuinator.backends.fake import FakeBackend
from src.termuinator.contracts import Backend, CapabilityStatus, Viewport


class FakeBackendCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_unconfigured_operations_are_not_advertised_as_supported(self) -> None:
        backend = FakeBackend(Backend.CHROMIUM)
        with tempfile.TemporaryDirectory() as directory:
            capabilities = await backend.start(
                Path(directory),
                Viewport(width=1280, height=720),
            )
        records = {item.capability_id: item for item in capabilities.capabilities}

        self.assertEqual(records["observe"].status, CapabilityStatus.SUPPORTED)
        self.assertEqual(records["cached_status"].status, CapabilityStatus.SUPPORTED)
        self.assertEqual(records["navigate"].status, CapabilityStatus.UNSUPPORTED)
        self.assertEqual(records["act"].status, CapabilityStatus.UNSUPPORTED)
        self.assertIsNotNone(records["navigate"].reason_code)
        self.assertIsNotNone(records["act"].reason_code)

    async def test_configured_action_is_advertised_as_supported(self) -> None:
        snapshot = BackendPageSnapshot(
            url="https://example.com",
            title="Example",
            ready_state="complete",
            viewport=Viewport(width=1280, height=720),
        )
        backend = FakeBackend(
            Backend.CHROMIUM,
            action_outcome=BackendActionOutcome(
                executed_method="fake-action",
                snapshot=snapshot,
                evidence=BackendActionEvidence(target_event_dispatched=True),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            capabilities = await backend.start(
                Path(directory),
                Viewport(width=1280, height=720),
            )
        records = {item.capability_id: item for item in capabilities.capabilities}

        self.assertEqual(records["act"].status, CapabilityStatus.SUPPORTED)
        self.assertIsNone(records["act"].reason_code)


if __name__ == "__main__":
    unittest.main()
