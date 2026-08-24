"""Closed local host-control protocol routing tests."""

from __future__ import annotations

import unittest

from src.termuinator.contracts import ErrorCode, PermissionPolicy
from src.termuinator.errors import TermuinatorError
from src.termuinator.host_control import HostControlRouter


class _RecordingService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.error: TermuinatorError | None = None

    async def _record(self, name: str, **values: object) -> dict[str, object]:
        self.calls.append((name, values))
        if self.error is not None:
            raise self.error
        return {"operation": name, **values}

    async def local_permission_record(self, **values: object) -> dict[str, object]:
        return await self._record("permission_record", **values)

    async def local_confirmation_decide(self, **values: object) -> dict[str, object]:
        return await self._record("confirmation_decide", **values)

    async def local_developer_mode_set(self, **values: object) -> dict[str, object]:
        return await self._record("developer_mode_set", **values)

    async def local_takeover_start(self, session_id: str) -> dict[str, object]:
        return await self._record("takeover_start", session_id=session_id)

    async def local_takeover_resume(self, session_id: str) -> dict[str, object]:
        return await self._record("takeover_resume", session_id=session_id)


class HostControlRouterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = _RecordingService()
        self.router = HostControlRouter(self.service)

    async def test_exact_operations_decode_into_service_owned_types(self) -> None:
        permission = await self.router.dispatch(
            {
                "version": 1,
                "operation": "permission_record",
                "session_id": "session_abcdefgh",
                "origin": "https://example.com/path",
                "policy": "session_allow",
            }
        )
        confirmation = await self.router.dispatch(
            {
                "version": 1,
                "operation": "confirmation_decide",
                "session_id": "session_abcdefgh",
                "decision": "approve",
                "confirmation_id": "confirmation_abcdefgh",
            }
        )
        takeover_start = await self.router.dispatch(
            {
                "version": 1,
                "operation": "takeover_start",
                "session_id": "session_abcdefgh",
            }
        )
        takeover_resume = await self.router.dispatch(
            {
                "version": 1,
                "operation": "takeover_resume",
                "session_id": "session_abcdefgh",
            }
        )

        self.assertTrue(permission["ok"])
        self.assertTrue(confirmation["ok"])
        self.assertTrue(takeover_start["ok"])
        self.assertTrue(takeover_resume["ok"])
        self.assertEqual(
            self.service.calls,
            [
                (
                    "permission_record",
                    {
                        "session_id": "session_abcdefgh",
                        "origin": "https://example.com/path",
                        "policy": PermissionPolicy.SESSION_ALLOW,
                    },
                ),
                (
                    "confirmation_decide",
                    {
                        "session_id": "session_abcdefgh",
                        "operation": "approve",
                        "confirmation_id": "confirmation_abcdefgh",
                    },
                ),
                ("takeover_start", {"session_id": "session_abcdefgh"}),
                ("takeover_resume", {"session_id": "session_abcdefgh"}),
            ],
        )

    async def test_request_version_shape_and_closed_unions_fail_before_service(self) -> None:
        invalid_requests: tuple[object, ...] = (
            [],
            {1: "non-string-key"},
            {"version": True, "operation": "takeover_start", "session_id": "session_abcdefgh"},
            {"version": 2, "operation": "takeover_start", "session_id": "session_abcdefgh"},
            {"version": 1, "operation": "unknown", "session_id": "session_abcdefgh"},
            {
                "version": 1,
                "operation": "takeover_start",
                "session_id": "session_abcdefgh",
                "extra": "smuggled",
            },
            {
                "version": 1,
                "operation": "permission_record",
                "session_id": "session_abcdefgh",
                "origin": "https://example.com",
                "policy": "ask",
            },
            {
                "version": 1,
                "operation": "permission_record",
                "session_id": "session_abcdefgh",
                "origin": "https://example.com",
                "policy": [],
            },
            {
                "version": 1,
                "operation": "confirmation_decide",
                "session_id": "session_abcdefgh",
                "decision": "status",
                "confirmation_id": "confirmation_abcdefgh",
            },
            {
                "version": 1,
                "operation": "confirmation_decide",
                "session_id": "session_abcdefgh",
                "decision": [],
                "confirmation_id": "confirmation_abcdefgh",
            },
        )
        for request in invalid_requests:
            with self.subTest(request=request):
                with self.assertRaises(TermuinatorError) as invalid:
                    await self.router.dispatch(request)
                self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)
        self.assertEqual(self.service.calls, [])

    async def test_developer_mode_set_is_an_exact_local_only_union(self) -> None:
        enabled = await self.router.dispatch(
            {
                "version": 1,
                "operation": "developer_mode_set",
                "session_id": "session_abcdefgh",
                "origin": "https://example.com",
                "enabled": True,
            }
        )

        self.assertTrue(enabled["ok"])
        self.assertEqual(
            self.service.calls,
            [
                (
                    "developer_mode_set",
                    {
                        "session_id": "session_abcdefgh",
                        "origin": "https://example.com",
                        "enabled": True,
                    },
                )
            ],
        )

        invalid_requests = (
            {
                "version": 1,
                "operation": "developer_mode_set",
                "session_id": "session_abcdefgh",
                "origin": "https://example.com",
                "enabled": "true",
            },
            {
                "version": 1,
                "operation": "developer_mode_set",
                "session_id": "session_abcdefgh",
                "origin": "https://example.com",
                "enabled": False,
                "extra": "smuggled",
            },
        )
        before = tuple(self.service.calls)
        for request in invalid_requests:
            with self.assertRaises(TermuinatorError) as invalid:
                await self.router.dispatch(request)
            self.assertEqual(invalid.exception.code, ErrorCode.INVALID_REQUEST)
        self.assertEqual(tuple(self.service.calls), before)

    async def test_errors_use_the_shared_stable_envelope(self) -> None:
        self.service.error = TermuinatorError(
            ErrorCode.PERMISSION_DENIED,
            "Local decision was denied",
            details={"reason_code": "host_denied"},
        )
        with self.assertRaises(TermuinatorError) as denied:
            await self.router.dispatch(
                {
                    "version": 1,
                    "operation": "takeover_start",
                    "session_id": "session_abcdefgh",
                }
            )

        self.assertEqual(
            self.router.error_payload(denied.exception),
            {
                "ok": False,
                "error": {
                    "code": "permission_denied",
                    "message": "Local decision was denied",
                    "retryable": False,
                    "details": {"reason_code": "host_denied"},
                    "diagnostics_id": None,
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
