"""Tests for the fail-closed dependency-free runtime configuration."""

from __future__ import annotations

import importlib.util
import importlib
from dataclasses import fields
import json
from pathlib import Path
import tempfile
import unittest

from src.termuinator.config import RuntimeConfig, load_runtime_config
from src.termuinator.contracts import Backend


class RuntimeConfigTests(unittest.TestCase):
    def _load(self, **kwargs: object) -> RuntimeConfig:
        try:
            return load_runtime_config(**kwargs)
        except NotImplementedError as exc:
            self.fail(str(exc))

    @staticmethod
    def _write_config(path: Path, payload: dict[str, object], mode: int = 0o600) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.chmod(mode)

    def test_runtime_config_module_exists(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("src.termuinator.config"))

    def test_runtime_config_api_is_explicit_and_bounded(self) -> None:
        module = importlib.import_module("src.termuinator.config")
        model = getattr(module, "RuntimeConfig", None)
        loader = getattr(module, "load_runtime_config", None)
        self.assertIsNotNone(model)
        self.assertTrue(callable(loader))
        self.assertEqual(
            {item.name for item in fields(model)},
            {
                "data_root",
                "default_backend",
                "profile_schema_version",
                "artifact_retention_seconds",
                "artifact_quota_bytes",
                "trace_retention_seconds",
                "trace_quota_bytes",
                "max_artifact_chunk_bytes",
            },
        )

    def test_defaults_are_safe_and_termux_portable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._load(environ={"HOME": temp_dir})

        self.assertEqual(
            config.data_root, Path(temp_dir) / ".local" / "share" / "termuinator"
        )
        self.assertEqual(config.default_backend, Backend.CHROMIUM)
        self.assertEqual(config.profile_schema_version, "v1")
        self.assertEqual(config.artifact_retention_seconds, 86_400)
        self.assertEqual(config.artifact_quota_bytes, 500 * 1024 * 1024)
        self.assertEqual(config.trace_retention_seconds, 7 * 86_400)
        self.assertEqual(config.trace_quota_bytes, 100 * 1024 * 1024)
        self.assertEqual(config.max_artifact_chunk_bytes, 512 * 1024)

    def test_secure_json_file_can_override_static_resource_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            data_root = root / "data"
            self._write_config(
                config_path,
                {
                    "data_root": str(data_root),
                    "default_backend": "firefox",
                    "profile_schema_version": "v1",
                    "artifact_retention_seconds": 3_600,
                    "artifact_quota_bytes": 10 * 1024 * 1024,
                    "trace_retention_seconds": 7_200,
                    "trace_quota_bytes": 5 * 1024 * 1024,
                    "max_artifact_chunk_bytes": 64 * 1024,
                },
            )
            config = self._load(path=config_path, environ={"HOME": temp_dir})

        self.assertEqual(config.data_root, data_root)
        self.assertEqual(config.default_backend, Backend.FIREFOX)
        self.assertEqual(config.artifact_retention_seconds, 3_600)
        self.assertEqual(config.max_artifact_chunk_bytes, 64 * 1024)

    def test_unknown_or_authority_enabling_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            self._write_config(config_path, {"developer_mode_enabled": True})
            with self.assertRaisesRegex(ValueError, "unknown"):
                load_runtime_config(path=config_path, environ={"HOME": temp_dir})

    def test_config_file_must_be_private_and_regular(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            self._write_config(config_path, {}, mode=0o644)
            with self.assertRaisesRegex(ValueError, "0600"):
                load_runtime_config(path=config_path, environ={"HOME": temp_dir})

    def test_numeric_limits_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            self._write_config(
                config_path, {"max_artifact_chunk_bytes": 512 * 1024 + 1}
            )
            with self.assertRaisesRegex(ValueError, "max_artifact_chunk_bytes"):
                load_runtime_config(path=config_path, environ={"HOME": temp_dir})


if __name__ == "__main__":
    unittest.main()
