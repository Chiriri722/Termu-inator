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
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import zlib

from src import client

from scripts.benchmark_device import (
    BenchmarkAuthorityError,
    BenchmarkConfig,
    benchmark_backend,
    file_check,
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
                socket_path=root / ".tbp/daemon.sock",
                pidfile=root / ".tbp/daemon.pid",
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
                patch.dict(os.environ, {"HOME": str(root)}),
                patch.object(client, "SOCKET_PATH", str(config.socket_path)),
                patch.object(client, "PID_PATH", str(config.pidfile)),
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
                            "valid_png": True,
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


class BenchmarkQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "h"
        self.home.mkdir(mode=0o700)
        self.env = patch.dict(os.environ, {"HOME": str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.config = BenchmarkConfig(
            project_root=ROOT, tbp=Path(sys.executable), wheel=self.root / "wheel",
            canonical_manifest=self.root / "manifest", output=self.home / "results",
            socket_path=self.home / ".tbp/daemon.sock", pidfile=self.home / ".tbp/daemon.pid",
            url="http://127.0.0.1/forms", backends=("firefox",), cold_samples=1,
            status_samples=1, text_samples=1, screenshot_samples=1, settle_seconds=0,
            network_kind="fixture", tailscale_termux_state="unchanged",
        )
        for manager in (
            patch.object(client, "SOCKET_PATH", str(self.config.socket_path)),
            patch.object(client, "PID_PATH", str(self.config.pidfile)),
        ):
            manager.start()
            self.addCleanup(manager.stop)

    @staticmethod
    def png() -> bytes:
        def chunk(kind: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + kind + data
                    + struct.pack(">I", zlib.crc32(kind + data)))
        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
                + chunk(b"IEND", b""))

    def backend_result(self) -> dict:
        return {
            "backend": "firefox", "cold_start_stats": stats([10.0], 0),
            "warm_start": {"returncode": 0, "socket_ready_verified": True},
            "page_load": {"response": {"success": True, "data": {}}, "error": None},
            "operations": {name: stats([10.0], 0)
                           for name in ("status", "text", "screenshot")},
            "screenshots": [{"valid_png": True, "png_signature": True, "bytes": 69}],
            "operation_errors": {name: [] for name in ("status", "text", "screenshot")},
        }

    def run_report(self, backend: dict, *, clean: bool = True):
        with (
            patch("scripts.benchmark_device.authorize_benchmark", return_value={"commit": "a"}),
            patch("scripts.benchmark_device.environment", return_value={"python": "3.14"}),
            patch("scripts.benchmark_device.benchmark_backend", new_callable=AsyncMock,
                  return_value=backend),
            patch("scripts.benchmark_device.stop_daemon", return_value={
                "socket_absent_after_stop": clean, "pidfile_absent_after_stop": clean}),
        ):
            return asyncio.run(run_benchmark(self.config))

    def test_output_outside_isolated_home_is_rejected_before_creation(self) -> None:
        outside = self.root / "old-output"
        with self.assertRaisesRegex(BenchmarkAuthorityError, "outside benchmark HOME"):
            prepare_benchmark_output(outside)
        self.assertFalse(outside.exists())

    def test_output_symlink_escape_is_rejected(self) -> None:
        (self.home / "escape").symlink_to(self.root, target_is_directory=True)
        outside = self.home / "escape" / "old-output"
        with self.assertRaises(BenchmarkAuthorityError):
            prepare_benchmark_output(outside)
        self.assertFalse(outside.exists())

    def test_complete_samples_and_targets_publish_pass(self) -> None:
        raw, summary_path, summary = self.run_report(self.backend_result())
        self.assertEqual(summary.get("quality", {}).get("status"), "PASS")
        self.assertEqual(json.loads(raw.read_text())["quality"], summary["quality"])
        self.assertEqual(summary_path.stat().st_mode & 0o777, 0o600)

    def test_operation_failure_publishes_failed_quality_not_success(self) -> None:
        backend = self.backend_result()
        backend["operations"]["screenshot"] = stats([], 1)
        backend["screenshots"] = []
        _, _, summary = self.run_report(backend)
        self.assertEqual(summary.get("quality", {}).get("status"), "FAIL")

    def test_missing_success_samples_fail_even_with_zero_errors(self) -> None:
        backend = self.backend_result()
        backend["operations"]["text"] = stats([], 0)
        _, _, summary = self.run_report(backend)
        self.assertEqual(summary.get("quality", {}).get("status"), "FAIL")

    def test_latency_budget_failure_is_not_pass(self) -> None:
        backend = self.backend_result()
        backend["operations"]["status"] = stats([301.0], 0)
        _, _, summary = self.run_report(backend)
        self.assertEqual(summary.get("quality", {}).get("status"), "FAIL")

    def test_nan_latency_is_not_pass(self) -> None:
        backend = self.backend_result()
        backend["operations"]["status"]["median_ms"] = float("nan")
        _, _, summary = self.run_report(backend)
        self.assertEqual(summary.get("quality", {}).get("status"), "FAIL")

    def test_cleanup_failure_is_not_pass(self) -> None:
        _, _, summary = self.run_report(self.backend_result(), clean=False)
        self.assertEqual(summary.get("quality", {}).get("status"), "FAIL")

    def test_cli_quality_failure_exits_one_and_keeps_summary(self) -> None:
        with (
            patch("scripts.benchmark_device.parse_args", return_value=self.config),
            patch("scripts.benchmark_device.run_benchmark", new_callable=AsyncMock,
                  return_value=(self.home / "raw", self.home / "summary",
                                {"quality": {"status": "FAIL"}})),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(main([]), 1)
        self.assertIn('"FAIL"', output.getvalue())

    def test_missing_or_malformed_png_is_not_valid(self) -> None:
        path = self.home / "shot.png"
        for data in (None, b"\x89PNG\r\n\x1a\n", self.png()[:-1], self.png() + b"junk"):
            with self.subTest(data=data):
                if data is not None:
                    path.write_bytes(data)
                    path.chmod(0o600)
                self.assertIs(file_check(path).get("valid_png"), False)

    def test_private_complete_png_has_dimensions_and_hash(self) -> None:
        path = self.home / "shot.png"
        path.write_bytes(self.png())
        path.chmod(0o600)
        result = file_check(path)
        self.assertIs(result.get("valid_png"), True)
        self.assertEqual((result.get("width"), result.get("height")), (1, 1))
        self.assertEqual(result.get("sha256"), hashlib.sha256(self.png()).hexdigest())

    def test_symlink_png_is_rejected_without_reading_target(self) -> None:
        target = self.home / "target.png"
        target.write_bytes(self.png())
        target.chmod(0o600)
        path = self.home / "shot.png"
        path.symlink_to(target)
        self.assertIs(file_check(path).get("valid_png"), False)

    def test_read_access_time_change_does_not_invalidate_png(self) -> None:
        path = self.home / "shot.png"
        path.write_bytes(self.png())
        path.chmod(0o600)
        original = os.fstat

        def changed_atime(fd):
            value = original(fd)
            fields = {name: getattr(value, name) for name in dir(value)
                      if name.startswith("st_")}
            fields["st_atime"] += 1
            return SimpleNamespace(**fields)

        with patch("scripts.benchmark_device.os.fstat", side_effect=changed_atime):
            self.assertIs(file_check(path).get("valid_png"), True)

    def test_corrupt_crc_and_public_mode_are_rejected(self) -> None:
        path = self.home / "shot.png"
        damaged = bytearray(self.png())
        damaged[-1] ^= 1
        for data, mode in ((damaged, 0o600), (self.png(), 0o644)):
            with self.subTest(mode=mode):
                path.write_bytes(data)
                path.chmod(mode)
                self.assertIs(file_check(path).get("valid_png"), False)

    def test_valid_crc_does_not_hide_invalid_compressed_image(self) -> None:
        data = bytearray(self.png())
        size = struct.unpack_from(">I", data, 33)[0]
        data[41] = 0  # Break the zlib header, then repair the enclosing PNG CRC.
        struct.pack_into(">I", data, 41 + size, zlib.crc32(data[37:41 + size]))
        path = self.home / "shot.png"
        path.write_bytes(data)
        path.chmod(0o600)
        self.assertIs(file_check(path).get("valid_png"), False)

    def test_daemon_screenshot_handler_accepts_correct_isolated_layout(self) -> None:
        from src.daemon import _handle_screenshot
        from src._utils import validate_path
        output = self.home / "results"
        prepare_benchmark_output(output)
        screenshot = output / "shot.png"

        async def capture(path, **_kwargs):
            Path(path).write_bytes(self.png())
            Path(path).chmod(0o600)

        daemon = SimpleNamespace(
            pilot=SimpleNamespace(screenshot=capture,
                                  _session=SimpleNamespace(_dismiss_popup=AsyncMock())),
            _cursor_pos=None,
        )
        response = asyncio.run(_handle_screenshot(daemon, {"path": str(screenshot)}))
        self.assertEqual(response["path"], validate_path(str(screenshot)))
        self.assertIs(file_check(screenshot).get("valid_png"), True)

    def test_page_and_artifact_failures_close_quality(self) -> None:
        for defect in ("page", "artifact", "warm", "cold"):
            with self.subTest(defect=defect):
                backend = self.backend_result()
                if defect == "page":
                    backend["page_load"]["error"] = "private /path?secret=token"
                elif defect == "artifact":
                    backend["screenshots"][0]["valid_png"] = False
                elif defect == "warm":
                    backend["warm_start"]["returncode"] = 1
                else:
                    backend["cold_start_stats"] = stats([], 1)
                # Each report keeps its own non-reusable output identity.
                from dataclasses import replace
                self.config = replace(self.config, output=self.home / defect)
                _, _, summary = self.run_report(backend)
                self.assertEqual(summary["quality"]["status"], "FAIL")
                self.assertNotIn("secret", json.dumps(summary))

    def test_success_response_without_png_counts_as_error(self) -> None:
        ps = {"requested_command": ["ps"], "requested_returncode": 0,
              "requested_stdout": "", "requested_stderr": "", "effective_command": ["ps"],
              "effective_returncode": 0, "effective_stdout": "", "effective_stderr": ""}
        with (
            patch("scripts.benchmark_device.start_daemon", return_value={
                "returncode": 0, "socket_ready_verified": True,
                "start_to_socket_ready_ms": 1.0}),
            patch("scripts.benchmark_device.stop_daemon", return_value={
                "socket_absent_after_stop": True, "pidfile_absent_after_stop": True}),
            patch("scripts.benchmark_device.ps_snapshot", return_value=ps),
            patch("scripts.benchmark_device.measured_command", new_callable=AsyncMock,
                  return_value=(1.0, {"success": True}, None)),
        ):
            result = asyncio.run(benchmark_backend(self.config, "firefox"))
        self.assertEqual(result["operations"]["screenshot"]["success_count"], 0)
        self.assertEqual(result["operations"]["screenshot"]["error_count"], 1)


if __name__ == "__main__":
    unittest.main()
