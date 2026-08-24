"""Regression tests for the warm daemon status control plane."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.daemon import _handle_status


class _PageIODetector:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def url(self) -> str:
        self.calls.append("url")
        raise AssertionError("status must not perform page I/O")

    async def title(self) -> str:
        self.calls.append("title")
        raise AssertionError("status must not perform page I/O")


class DaemonStatusCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_reads_cached_control_plane_without_page_io(self) -> None:
        pilot = _PageIODetector()
        daemon = SimpleNamespace(
            pilot=pilot,
            _browser_type="firefox",
            _start_time=100.0,
            _status_cache={
                "url": "https://example.com/",
                "title": "Example Domain",
                "updated_at_monotonic": 10.0,
            },
        )

        with (
            patch("src.daemon.time.time", return_value=125.0),
            patch("src.daemon.time.monotonic", return_value=10.125),
            patch("src.daemon.os.getpid", return_value=1234),
        ):
            result = await _handle_status(daemon, {})

        self.assertEqual(pilot.calls, [])
        self.assertEqual(result["url"], "https://example.com/")
        self.assertEqual(result["title"], "Example Domain")
        self.assertEqual(result["freshness_ms"], 125)
