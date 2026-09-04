"""Tests for the portable on-device benchmark and privacy boundary."""

from __future__ import annotations

import asyncio
import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from scripts.benchmark_device import (
    BenchmarkAuthorityError,
    BenchmarkConfig,
    _current_benchmark_identity,
    load_canonical_manifest,
    main,
    parse_args,
    prepare_benchmark_output,
    run_benchmark,
    sanitize_report,
    stats,
    validate_benchmark_authority,
)


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


class CanonicalAuthorityTests(unittest.TestCase):
    @staticmethod
    def _manifest() -> dict[str, object]:
        return {
            "status": "PASS",
            "benchmark_allowed": True,
            "source": {
                "commit": "a" * 40,
                "clean_worktree": True,
            },
            "environment": {
                "python": "3.14.6",
                "kernel_release": "16",
                "python_sys_platform": "android",
                "platform_system": "Android",
                "native_cryptography": "50.0.0",
                "mcp": "1.29.0",
                "websockets": "17.0.1",
                "termux_browser_pilot": "0.1.0a1",
                "wheel_sha256": "b" * 64,
                "source_tree_sha256": "c" * 64,
                "installed_source_tree_sha256": "c" * 64,
            },
            "device": {
                "status": "PASS",
                "benchmark_allowed": True,
                "backends": [
                    {"backend": "chromium", "status": "PASS"},
                    {"backend": "firefox", "status": "PASS"},
                ],
                "stdio": {
                    "interactive": {"stderr_bytes": 0},
                    "observer_restart": {"stderr_bytes": 0},
                },
            },
        }

    @staticmethod
    def _identity() -> dict[str, str]:
        return {
            "python": "3.14.6",
            "kernel_release": "16",
            "python_sys_platform": "android",
            "platform_system": "Android",
            "native_cryptography": "50.0.0",
            "mcp": "1.29.0",
            "websockets": "17.0.1",
            "termux_browser_pilot": "0.1.0a1",
            "wheel_sha256": "b" * 64,
            "source_tree_sha256": "c" * 64,
            "installed_source_tree_sha256": "c" * 64,
        }

    def test_native_cryptography_drift_closes_benchmark_gate(self) -> None:
        identity = self._identity()
        identity["native_cryptography"] = "50.0.1"

        with self.assertRaisesRegex(
            BenchmarkAuthorityError,
            "native_cryptography differs from canonical manifest",
        ):
            validate_benchmark_authority(
                self._manifest(),
                current_identity=identity,
                current_commit="a" * 40,
                clean_worktree=True,
            )

    def test_exact_canonical_environment_authorizes_benchmark(self) -> None:
        summary = validate_benchmark_authority(
            self._manifest(),
            current_identity=self._identity(),
            current_commit="a" * 40,
            clean_worktree=True,
        )

        self.assertEqual(summary["commit"], "a" * 40)
        self.assertEqual(summary["native_cryptography"], "50.0.0")
        self.assertTrue(summary["environment_match_verified"])

    def test_failed_backend_cannot_authorize_benchmark(self) -> None:
        manifest = self._manifest()
        manifest["device"]["backends"][1]["status"] = "FAIL"

        with self.assertRaisesRegex(
            BenchmarkAuthorityError,
            "canonical backend status does not authorize benchmark",
        ):
            validate_benchmark_authority(
                manifest,
                current_identity=self._identity(),
                current_commit="a" * 40,
                clean_worktree=True,
            )

    def test_android_runtime_drift_closes_benchmark_gate(self) -> None:
        identity = self._identity()
        identity["platform_system"] = "Linux"

        with self.assertRaisesRegex(
            BenchmarkAuthorityError,
            "platform_system differs from canonical manifest",
        ):
            validate_benchmark_authority(
                self._manifest(),
                current_identity=identity,
                current_commit="a" * 40,
                clean_worktree=True,
            )

    def test_manifest_loader_requires_matching_private_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "final-verify-manifest.json"
            manifest_path.write_text(
                json.dumps(self._manifest(), sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest_path.chmod(0o600)
            digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            checksum_path = root / "final-verify-manifest.sha256"
            checksum_path.write_text(
                f"{digest}  final-verify-manifest.json\n",
                encoding="ascii",
            )
            checksum_path.chmod(0o600)

            manifest, observed = load_canonical_manifest(manifest_path)
            self.assertEqual(manifest["status"], "PASS")
            self.assertEqual(observed, digest)

            tampered = copy.deepcopy(self._manifest())
            tampered["status"] = "FAIL"
            manifest_path.write_text(
                json.dumps(tampered, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                BenchmarkAuthorityError,
                "canonical manifest checksum differs",
            ):
                load_canonical_manifest(manifest_path)

    def test_manifest_loader_rejects_non_private_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "evidence"
            root.mkdir(mode=0o755)
            root.chmod(0o755)
            manifest_path = root / "final-verify-manifest.json"
            manifest_path.write_text(
                json.dumps(self._manifest(), sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest_path.chmod(0o600)
            digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            checksum_path = root / "final-verify-manifest.sha256"
            checksum_path.write_text(
                f"{digest}  final-verify-manifest.json\n",
                encoding="ascii",
            )
            checksum_path.chmod(0o600)

            with self.assertRaisesRegex(
                BenchmarkAuthorityError,
                "canonical manifest parent is not owner-private",
            ):
                load_canonical_manifest(manifest_path)

    def test_cli_requires_canonical_manifest(self) -> None:
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parse_args(
                    [
                        "--project-root",
                        str(ROOT),
                        "--tbp",
                        sys.executable,
                    ]
                )

    def test_invalid_authority_stops_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "final-verify-manifest.json"
            manifest_path.write_text("{}\n", encoding="utf-8")
            manifest_path.chmod(0o600)
            checksum_path = root / "final-verify-manifest.sha256"
            checksum_path.write_text(
                f"{'0' * 64}  final-verify-manifest.json\n",
                encoding="ascii",
            )
            checksum_path.chmod(0o600)
            output = root / "benchmark"
            config = BenchmarkConfig(
                project_root=ROOT,
                tbp=Path(sys.executable),
                wheel=manifest_path,
                canonical_manifest=manifest_path,
                output=output,
                socket_path=root / "daemon.sock",
                pidfile=root / "daemon.pid",
                url="https://example.com",
                backends=("firefox", "chromium"),
                cold_samples=1,
                status_samples=1,
                text_samples=1,
                screenshot_samples=1,
                settle_seconds=0,
                network_kind="test",
                tailscale_termux_state="test",
            )

            with self.assertRaisesRegex(
                BenchmarkAuthorityError,
                "canonical manifest checksum differs",
            ):
                asyncio.run(run_benchmark(config))
            self.assertFalse(output.exists())

    def test_existing_output_identity_is_never_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "benchmark-output"
            output.mkdir(mode=0o700)

            with self.assertRaisesRegex(
                BenchmarkAuthorityError,
                "benchmark output identity already exists",
            ):
                prepare_benchmark_output(output)

    def test_cli_preserves_manifest_symlink_for_fail_closed_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wheel = root / "candidate.whl"
            wheel.write_bytes(b"wheel")
            target = root / "final-verify-manifest.json"
            target.write_text("{}\n", encoding="utf-8")
            link_root = root / "linked"
            link_root.mkdir()
            manifest_link = link_root / "final-verify-manifest.json"
            manifest_link.symlink_to(target)

            config = parse_args(
                [
                    "--project-root",
                    str(ROOT),
                    "--tbp",
                    sys.executable,
                    "--wheel",
                    str(wheel),
                    "--canonical-manifest",
                    str(manifest_link),
                ]
            )

            self.assertTrue(config.canonical_manifest.is_symlink())

    def test_cli_reports_bounded_authority_failure_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wheel = root / "candidate.whl"
            wheel.write_bytes(b"wheel")
            manifest_path = root / "final-verify-manifest.json"
            manifest_path.write_text("{}\n", encoding="utf-8")
            manifest_path.chmod(0o600)
            checksum_path = root / "final-verify-manifest.sha256"
            checksum_path.write_text(
                f"{'0' * 64}  final-verify-manifest.json\n",
                encoding="ascii",
            )
            checksum_path.chmod(0o600)
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(
                    [
                        "--project-root",
                        str(ROOT),
                        "--tbp",
                        sys.executable,
                        "--wheel",
                        str(wheel),
                        "--canonical-manifest",
                        str(manifest_path),
                        "--output",
                        str(root / "benchmark"),
                    ]
                )

            self.assertEqual(result, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(
                stderr.getvalue(),
                "benchmark_authority_error=canonical manifest checksum differs\n",
            )
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_current_identity_ignores_checkout_egg_info(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wheel = root / "candidate.whl"
            wheel.write_bytes(b"wheel")
            prefix = root / "prefix"
            crypto_file = prefix / "lib" / "cryptography" / "__init__.py"
            crypto_file.parent.mkdir(parents=True)
            crypto_file.write_text("", encoding="utf-8")
            config = BenchmarkConfig(
                project_root=ROOT,
                tbp=Path(sys.prefix) / "bin" / "tbp",
                wheel=wheel,
                canonical_manifest=root / "final-verify-manifest.json",
                output=root / "benchmark",
                socket_path=root / "daemon.sock",
                pidfile=root / "daemon.pid",
                url="https://example.com",
                backends=("firefox", "chromium"),
                cold_samples=1,
                status_samples=1,
                text_samples=1,
                screenshot_samples=1,
                settle_seconds=0,
                network_kind="test",
                tailscale_termux_state="test",
            )
            versions = {
                "termux-browser-pilot": "0.1.0a1",
                "cryptography": "50.0.1",
                "mcp": "1.29.0",
                "websockets": "17.0.1",
            }

            def runtime_distribution(name: str):
                return SimpleNamespace(
                    version=versions[name],
                    entry_points=[],
                    read_text=lambda _name: "{}",
                )

            def inherited_version(name: str) -> str:
                if name != "cryptography":
                    raise AssertionError("unscoped version lookup")
                return versions[name]

            with (
                patch.dict(os.environ, {"PREFIX": str(prefix)}),
                patch(
                    "scripts.benchmark_device.importlib_metadata.distribution",
                    side_effect=AssertionError("unscoped distribution lookup"),
                ),
                patch(
                    "scripts.benchmark_device.importlib_metadata.version",
                    side_effect=inherited_version,
                ),
                patch(
                    "scripts.final_verify._runtime_distribution",
                    side_effect=runtime_distribution,
                ),
                patch("scripts.final_verify.validate_wheel_provenance"),
                patch(
                    "scripts.final_verify.validate_wheel_source_binding",
                    return_value={"source_tree_sha256": "a" * 64},
                ),
                patch(
                    "scripts.final_verify.validate_installed_source_binding",
                    return_value={"installed_source_tree_sha256": "b" * 64},
                ),
                patch("scripts.final_verify.validate_android_termux_identity"),
                patch(
                    "scripts.benchmark_device.importlib_util.find_spec",
                    return_value=SimpleNamespace(origin=str(crypto_file)),
                ),
            ):
                identity = _current_benchmark_identity(config)

            self.assertEqual(identity["termux_browser_pilot"], "0.1.0a1")
            self.assertEqual(identity["native_cryptography"], "50.0.1")
            self.assertEqual(identity["mcp"], "1.29.0")
            self.assertEqual(identity["websockets"], "17.0.1")

    def test_runtime_drift_during_measurement_rejects_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = BenchmarkConfig(
                project_root=ROOT,
                tbp=Path(sys.executable),
                wheel=root / "candidate.whl",
                canonical_manifest=root / "final-verify-manifest.json",
                output=root / "benchmark",
                socket_path=root / "daemon.sock",
                pidfile=root / "daemon.pid",
                url="https://example.com",
                backends=("firefox",),
                cold_samples=1,
                status_samples=1,
                text_samples=1,
                screenshot_samples=1,
                settle_seconds=0,
                network_kind="test",
                tailscale_termux_state="test",
            )

            with (
                patch(
                    "scripts.benchmark_device.authorize_benchmark",
                    side_effect=[{"commit": "a" * 40}, {"commit": "b" * 40}],
                ),
                patch(
                    "scripts.benchmark_device.environment",
                    return_value={"python": "3.14.7"},
                ),
                patch(
                    "scripts.benchmark_device.benchmark_backend",
                    new_callable=AsyncMock,
                    return_value={"backend": "firefox"},
                ),
                patch("scripts.benchmark_device.stop_daemon"),
            ):
                with self.assertRaisesRegex(
                    BenchmarkAuthorityError,
                    "benchmark environment changed during measurement",
                ):
                    asyncio.run(run_benchmark(config))

            self.assertTrue(config.output.is_dir())
            self.assertFalse((config.output / "baseline-report.json").exists())
            self.assertFalse((config.output / "baseline-summary.json").exists())


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
                "canonical_authority": {
                    "commit": "a" * 40,
                    "manifest_sha256": "d" * 64,
                    "native_cryptography": "50.0.1",
                    "environment_match_verified": True,
                },
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
        self.assertEqual(
            summary["environment"]["canonical_authority"],
            raw["environment"]["canonical_authority"],
        )

    def test_script_has_no_device_specific_absolute_path(self) -> None:
        source = (ROOT / "scripts" / "benchmark_device.py").read_text(encoding="utf-8")
        self.assertNotIn("/data/data/com.termux", source)
        self.assertNotIn('HOME / "src" / "Termu-inator"', source)


if __name__ == "__main__":
    unittest.main()
