"""Tests for service-owned stable interactive element references."""

from __future__ import annotations

import math
import unittest

from src.termuinator.backends import RawInteractiveElement
from src.termuinator.contracts import (
    Bounds,
    ErrorCode,
    PageRevision,
    RiskClass,
)
from src.termuinator.core.element_refs import ElementRefRegistry
from src.termuinator.errors import TermuinatorError


class ElementRefRegistryTests(unittest.TestCase):
    def _candidate(self, *, name: str = "Continue") -> RawInteractiveElement:
        return RawInteractiveElement(
            backend_node_id="backend-node-42",
            role="button",
            accessible_name=name,
            text=name,
            tag="button",
            bounds=Bounds(x=10, y=20, width=100, height=40),
            visible=True,
            enabled=True,
            frame_path=("frame-main",),
            shadow_path=("shadow-host",),
        )

    def test_bounds_reject_non_finite_or_negative_size(self) -> None:
        with self.assertRaises(ValueError):
            Bounds(x=math.nan, y=0, width=10, height=10)
        with self.assertRaises(ValueError):
            Bounds(x=0, y=0, width=-1, height=10)

    def test_refs_are_service_owned_stable_and_backend_handles_do_not_leak(self) -> None:
        registry = ElementRefRegistry(document_epoch="epoch_12345678")
        revision = PageRevision("epoch_12345678", 0)

        first = registry.issue((self._candidate(),), revision=revision)
        second = registry.issue((self._candidate(),), revision=revision)

        self.assertEqual(first[0].ref, second[0].ref)
        self.assertTrue(first[0].ref.startswith("ref_"))
        self.assertNotIn("backend-node-42", first[0].ref)
        self.assertEqual(first[0].frame_path, ("frame-main",))
        self.assertEqual(first[0].shadow_path, ("shadow-host",))
        binding = registry.resolve(
            ref=first[0].ref,
            expected_revision=revision,
            current_revision=revision,
            risk=RiskClass.R2,
            fingerprint_matches=False,
        )
        self.assertEqual(binding.backend_node_id, "backend-node-42")

    def test_changed_semantics_and_document_rotation_invalidate_old_refs(self) -> None:
        registry = ElementRefRegistry(document_epoch="epoch_12345678")
        revision = PageRevision("epoch_12345678", 0)
        original = registry.issue((self._candidate(),), revision=revision)[0]
        changed = registry.issue(
            (self._candidate(name="Delete account"),),
            revision=PageRevision("epoch_12345678", 1),
        )[0]

        self.assertNotEqual(original.ref, changed.ref)
        with self.assertRaises(TermuinatorError) as stale_target:
            registry.resolve(
                ref=original.ref,
                expected_revision=revision,
                current_revision=PageRevision("epoch_12345678", 1),
                risk=RiskClass.R4,
                fingerprint_matches=False,
            )
        self.assertEqual(stale_target.exception.code, ErrorCode.TARGET_NOT_FOUND)

        registry.rotate("epoch_abcdefgh")
        with self.assertRaises(TermuinatorError) as rotated:
            registry.resolve(
                ref=changed.ref,
                expected_revision=PageRevision("epoch_12345678", 1),
                current_revision=PageRevision("epoch_abcdefgh", 0),
                risk=RiskClass.R1,
                fingerprint_matches=True,
            )
        self.assertEqual(rotated.exception.code, ErrorCode.TARGET_NOT_FOUND)

    def test_same_semantics_with_replaced_backend_node_mints_a_new_ref(self) -> None:
        registry = ElementRefRegistry(document_epoch="epoch_12345678")
        first_revision = PageRevision("epoch_12345678", 0)
        first = registry.issue((self._candidate(),), revision=first_revision)[0]
        replacement = RawInteractiveElement(
            backend_node_id="backend-node-replacement",
            role="button",
            accessible_name="Continue",
            text="Continue",
            tag="button",
            bounds=Bounds(x=10, y=20, width=100, height=40),
            visible=True,
            enabled=True,
            frame_path=("frame-main",),
            shadow_path=("shadow-host",),
        )
        second_revision = PageRevision("epoch_12345678", 1)

        second = registry.issue((replacement,), revision=second_revision)[0]

        self.assertNotEqual(first.ref, second.ref)
        with self.assertRaises(TermuinatorError) as stale:
            registry.resolve(
                ref=first.ref,
                expected_revision=first_revision,
                current_revision=second_revision,
                risk=RiskClass.R1,
                fingerprint_matches=True,
            )
        self.assertEqual(stale.exception.code, ErrorCode.TARGET_NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
