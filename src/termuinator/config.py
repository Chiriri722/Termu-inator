"""Fail-closed runtime configuration boundary for Termu-inator v1."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
from typing import Mapping

from .contracts import Backend


@dataclass(frozen=True)
class RuntimeConfig:
    data_root: Path
    default_backend: Backend
    profile_schema_version: str
    artifact_retention_seconds: int
    artifact_quota_bytes: int
    trace_retention_seconds: int
    trace_quota_bytes: int
    max_artifact_chunk_bytes: int


_CONFIG_FIELDS = frozenset(RuntimeConfig.__dataclass_fields__)


def _read_private_json(path: Path) -> dict[str, object]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("config must be an existing regular 0600 file") from exc

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise ValueError("config must be a regular 0600 file")
        if metadata.st_size > 64 * 1024:
            raise ValueError("config exceeds the 64 KiB limit")
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            descriptor = -1
            payload = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("config must contain valid UTF-8 JSON") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    if not isinstance(payload, dict):
        raise ValueError("config root must be a JSON object")
    unknown = set(payload) - _CONFIG_FIELDS
    if unknown:
        raise ValueError("config contains unknown keys: " + ", ".join(sorted(unknown)))
    return payload


def _absolute_path(value: object, field_name: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value or len(value) > 4096:
        raise ValueError(f"{field_name} must be a non-empty absolute path")
    result = Path(value)
    if not result.is_absolute() or ".." in result.parts:
        raise ValueError(f"{field_name} must be a non-empty absolute path")
    return result


def _bounded_int(
    value: object, field_name: str, *, minimum: int, maximum: int
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")
    return value


def load_runtime_config(
    path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> RuntimeConfig:
    source = os.environ if environ is None else environ
    home = _absolute_path(source.get("HOME", str(Path.home())), "HOME")
    data_base = _absolute_path(
        source.get("XDG_DATA_HOME", str(home / ".local" / "share")),
        "XDG_DATA_HOME",
    )
    values: dict[str, object] = {
        "data_root": str(data_base / "termuinator"),
        "default_backend": Backend.CHROMIUM.value,
        "profile_schema_version": "v1",
        "artifact_retention_seconds": 86_400,
        "artifact_quota_bytes": 500 * 1024 * 1024,
        "trace_retention_seconds": 7 * 86_400,
        "trace_quota_bytes": 100 * 1024 * 1024,
        "max_artifact_chunk_bytes": 512 * 1024,
    }
    if path is not None:
        values.update(_read_private_json(path))

    try:
        backend = Backend(values["default_backend"])
    except (TypeError, ValueError) as exc:
        raise ValueError("default_backend must be chromium or firefox") from exc
    if backend not in (Backend.CHROMIUM, Backend.FIREFOX):
        raise ValueError("default_backend must be chromium or firefox")
    if values["profile_schema_version"] != "v1":
        raise ValueError("profile_schema_version must be v1")

    return RuntimeConfig(
        data_root=_absolute_path(values["data_root"], "data_root"),
        default_backend=backend,
        profile_schema_version="v1",
        artifact_retention_seconds=_bounded_int(
            values["artifact_retention_seconds"],
            "artifact_retention_seconds",
            minimum=60,
            maximum=30 * 86_400,
        ),
        artifact_quota_bytes=_bounded_int(
            values["artifact_quota_bytes"],
            "artifact_quota_bytes",
            minimum=1024 * 1024,
            maximum=1024**4,
        ),
        trace_retention_seconds=_bounded_int(
            values["trace_retention_seconds"],
            "trace_retention_seconds",
            minimum=60,
            maximum=30 * 86_400,
        ),
        trace_quota_bytes=_bounded_int(
            values["trace_quota_bytes"],
            "trace_quota_bytes",
            minimum=1024 * 1024,
            maximum=1024**4,
        ),
        max_artifact_chunk_bytes=_bounded_int(
            values["max_artifact_chunk_bytes"],
            "max_artifact_chunk_bytes",
            minimum=1,
            maximum=512 * 1024,
        ),
    )
