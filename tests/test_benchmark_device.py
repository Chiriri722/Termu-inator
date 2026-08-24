"""Tests for the portable on-device benchmark and privacy boundary."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.benchmark_device import sanitize_report, stats


ROOT = Path(__file__).resolve().parents[1]


class BenchmarkMathTests(unittest.TestCase):
    def test_stats_are_deterministic(self) -> None:
        self.assertEqual(
            stats([1.0, 2.0, 3.0], errors=1),
            {
                "raw_ms": [1.0, 2.0, 3.0],
                "min_ms": 1.0,
                "median_ms": 2.0,
                "p95_ms": 2.9,
                "max_ms": 3.0,
                "success_count": 3,
                "error_count": 1,
            },
        )


class SanitizedReportTests(unittest.TestCase):
    def test_summary_excludes_paths_pids_and_process_arguments(self) -> None:
        raw = {
            "environment": {
                "measured_at_utc": "2026-08-15T16:00:02+00:00",
                "device": {"system": "Android", "release": "16", "machine": "aarch64"},
                "python": "3.14.6",
                "termux_version": "0.118.3",
                "tbp_version": {"stdout": "tbp 0.1.0a1\n"},
                "browser_versions": {"firefox": {"result": {"stdout": "Firefox 153"}}},
                "network_kind": "controlled",
                "tailscale_termux_split_tunneling": "OFF",
                "project": "/data/data/com.termux/files/home/src/Termu-inator",
            },
            "backends": [
                {
                    "backend": "firefox",
                    "cold_start_stats": {"median_ms": 10.0, "error_count": 0},
                    "operations": {
                        "status": {"median_ms": 20.0, "error_count": 0},
                        "text": {"median_ms": 30.0, "error_count": 0},
                        "screenshot": {"median_ms": 40.0, "error_count": 0},
                    },
                    "operation_errors": {"status": [], "text": [], "screenshot": []},
                    "page_load": {
                        "latency_ms": 50.0,
                        "response": {
                            "success": True,
                            "data": {"url": "https://example.com/", "title": "Example Domain"},
                        },
                        "error": None,
                    },
                    "rss": {
                        "daemon_python": [{"pid": 1, "rss_kb": 10, "args": "secret"}],
                        "browser_processes": [{"pid": 2, "rss_kb": 20, "args": "token"}],
                        "xvfb": [{"pid": 3, "rss_kb": 30, "args": "path"}],
                        "openbox": [{"pid": 4, "rss_kb": 40, "args": "path"}],
                    },
                    "screenshots": [
                        {
                            "path": "/data/data/com.termux/files/home/private.png",
                            "bytes": 123,
                            "png_signature": True,
                        }
                    ],
                }
            ],
        }

        summary = sanitize_report(raw)
        encoded = json.dumps(summary, sort_keys=True)

        self.assertNotIn("/data/data", encoded)
        self.assertNotIn('"pid"', encoded)
        self.assertNotIn('"args"', encoded)
        self.assertEqual(summary["backends"][0]["rss_kb"]["browser"], 20)
        self.assertEqual(summary["backends"][0]["screenshots"]["bytes"], [123])
        self.assertTrue(summary["backends"][0]["screenshots"]["all_valid_png"])

    def test_script_has_no_device_specific_absolute_path(self) -> None:
        source = (ROOT / "scripts" / "benchmark_device.py").read_text(encoding="utf-8")
        self.assertNotIn("/data/data/com.termux", source)
        self.assertNotIn('HOME / "src" / "Termu-inator"', source)


if __name__ == "__main__":
    unittest.main()

