"""Server-held one-shot confirmation boundary tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from src.termuinator.contracts import (
    Challenge,
    ChallengeKind,
    ChallengeState,
    ErrorCode,
    PageRevision,
    to_wire,
)
from src.termuinator.core.confirmations import ConfirmationEngine
from src.termuinator.errors import TermuinatorError


class ConfirmationEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.current = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)
        self.engine = ConfirmationEngine(
            owner_scope="owner-alpha",
            project_id="project-alpha",
            now=lambda: self.current,
        )
        self.context = {
            "session_id": "session_confirm1",
            "origin": "https://example.com",
            "page_revision": PageRevision("epoch_confirm", 4),
            "action_digest": "a" * 64,
            "idempotency_key": "idempotency_confirm1",
            "preview": "Submit the Example form",
        }

    def test_prepare_returns_only_non_secret_public_challenge(self) -> None:
        challenge = self.engine.prepare(**self.context)

        self.assertIsInstance(challenge, Challenge)
        self.assertEqual(challenge.kind, ChallengeKind.CONFIRMATION)
        self.assertEqual(challenge.state, ChallengeState.PENDING)
        self.assertEqual(challenge.preview, self.context["preview"])
        self.assertEqual(
            self.engine.prepare(**self.context).challenge_id,
            challenge.challenge_id,
        )
        wire = to_wire(challenge)
        self.assertEqual(
            set(wire),
            {"challenge_id", "kind", "state", "preview", "expires_at"},
        )
        self.assertNotIn("nonce", repr(wire).lower())
        self.assertNotIn("proof", repr(wire).lower())

    def test_identifier_is_not_authority_and_approval_is_consumed_once(self) -> None:
        challenge = self.engine.prepare(**self.context)

        with self.assertRaises(TermuinatorError) as pending:
            self.engine.consume(challenge.challenge_id, **self.context)
        self.assertEqual(pending.exception.code, ErrorCode.CONFIRMATION_REQUIRED)

        approved = self.engine.approve(challenge.challenge_id)
        self.assertEqual(approved.state, ChallengeState.APPROVED)
        consumed = self.engine.consume(challenge.challenge_id, **self.context)
        self.assertEqual(consumed.state, ChallengeState.CONSUMED)

        with self.assertRaises(TermuinatorError) as replay:
            self.engine.consume(challenge.challenge_id, **self.context)
        self.assertEqual(replay.exception.code, ErrorCode.CONFIRMATION_REQUIRED)

    def test_revision_origin_payload_or_key_change_invalidates_approval(self) -> None:
        cases = (
            ("page_revision", PageRevision("epoch_confirm", 5)),
            ("origin", "https://other.example"),
            ("action_digest", "b" * 64),
            ("idempotency_key", "idempotency_confirm2"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                engine = ConfirmationEngine(
                    owner_scope="owner-alpha",
                    project_id="project-alpha",
                    now=lambda: self.current,
                )
                challenge = engine.prepare(**self.context)
                engine.approve(challenge.challenge_id)
                changed = dict(self.context)
                changed[field] = value

                with self.assertRaises(TermuinatorError) as stale:
                    engine.consume(challenge.challenge_id, **changed)

                self.assertEqual(
                    stale.exception.code,
                    ErrorCode.CONFIRMATION_REQUIRED,
                )
                self.assertEqual(
                    engine.status(challenge.challenge_id).state,
                    ChallengeState.EXPIRED,
                )

    def test_expired_approval_cannot_be_consumed(self) -> None:
        challenge = self.engine.prepare(**self.context)
        self.engine.approve(challenge.challenge_id)
        self.current += timedelta(seconds=121)

        with self.assertRaises(TermuinatorError) as expired:
            self.engine.consume(challenge.challenge_id, **self.context)

        self.assertEqual(expired.exception.code, ErrorCode.CONFIRMATION_REQUIRED)
        self.assertEqual(
            self.engine.status(challenge.challenge_id).state,
            ChallengeState.EXPIRED,
        )

    def test_different_owner_scope_cannot_approve_or_consume(self) -> None:
        challenge = self.engine.prepare(**self.context)
        other = ConfirmationEngine(
            owner_scope="owner-beta",
            project_id="project-alpha",
            now=lambda: self.current,
        )

        with self.assertRaises(TermuinatorError) as hidden:
            other.approve(challenge.challenge_id)

        self.assertEqual(hidden.exception.code, ErrorCode.CONFIRMATION_REQUIRED)

    def test_denial_is_terminal_for_that_challenge(self) -> None:
        challenge = self.engine.prepare(**self.context)
        denied = self.engine.deny(challenge.challenge_id)
        self.assertEqual(denied.state, ChallengeState.DENIED)

        with self.assertRaises(TermuinatorError) as blocked:
            self.engine.consume(challenge.challenge_id, **self.context)

        self.assertEqual(blocked.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_pending_list_is_bounded_value_only_and_refreshes_expiry(self) -> None:
        first = self.engine.prepare(**self.context)
        second_context = dict(self.context)
        second_context.update(
            action_digest="b" * 64,
            idempotency_key="idempotency_confirm2",
            preview="Publish the Example form",
        )
        second = self.engine.prepare(**second_context)
        self.engine.approve(first.challenge_id)

        pending = self.engine.list_pending(limit=8)

        self.assertEqual(pending, (second,))
        self.assertNotIn("nonce", repr(pending).lower())
        self.assertNotIn("proof", repr(pending).lower())

        self.current += timedelta(seconds=121)
        self.assertEqual(self.engine.list_pending(limit=8), ())

        with self.assertRaises(TermuinatorError) as invalid:
            self.engine.list_pending(limit=0)
        self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)


if __name__ == "__main__":
    unittest.main()
