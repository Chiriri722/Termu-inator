"""Trusted composition helpers for the typed migration runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .backends.legacy import LegacyPilotBackend
from .config import RuntimeConfig
from .contracts import Backend
from .core.service import BackendFactory, BrowserService
from .core.sessions import ProcessSessionLock
from .host_control import HostControlRouter, UnixHostControlServer
from .mcp_v1 import CompactV1Router
from .shared_view import SharedViewServer


@dataclass(frozen=True)
class CompactRuntime:
    """Trusted composition of one service and its remote/local transports."""

    service: BrowserService
    mcp_router: CompactV1Router
    host_router: HostControlRouter
    host_server: UnixHostControlServer
    shared_view_server: SharedViewServer | None


def build_legacy_browser_service(
    *,
    config: RuntimeConfig,
    owner_scope: str,
    pilot_factory: Callable[..., object] | None = None,
    developer_mode_available: bool = False,
) -> BrowserService:
    """Compose one typed service over explicit inherited backend adapters.

    ``owner_scope`` must come from the authenticated transport.  It is kept
    outside public browser-tool arguments so page or model input cannot select
    another owner's project namespace.
    """

    def legacy_factory(backend: Backend) -> BackendFactory:
        return lambda: LegacyPilotBackend(
            backend,
            pilot_factory=pilot_factory,
        )

    return BrowserService(
        data_root=config.data_root,
        owner_scope=owner_scope,
        default_backend=config.default_backend,
        profile_schema_version=config.profile_schema_version,
        backend_factories={
            Backend.CHROMIUM: legacy_factory(Backend.CHROMIUM),
            Backend.FIREFOX: legacy_factory(Backend.FIREFOX),
        },
        session_lock=ProcessSessionLock(
            lock_path=config.data_root / "runtime" / "session.lock",
            owner_scope=owner_scope,
        ),
        artifact_retention_seconds=config.artifact_retention_seconds,
        artifact_quota_bytes=config.artifact_quota_bytes,
        trace_retention_seconds=config.trace_retention_seconds,
        trace_quota_bytes=config.trace_quota_bytes,
        max_artifact_chunk_bytes=config.max_artifact_chunk_bytes,
        developer_mode_available=developer_mode_available,
    )


def build_legacy_compact_runtime(
    *,
    config: RuntimeConfig,
    owner_scope: str,
    pilot_factory: Callable[..., object] | None = None,
    developer_mode_available: bool = False,
    shared_view_enabled: bool = False,
    shared_view_port: int = 8765,
) -> CompactRuntime:
    """Attach compact MCP and owner-local control to one browser authority."""

    service = build_legacy_browser_service(
        config=config,
        owner_scope=owner_scope,
        pilot_factory=pilot_factory,
        developer_mode_available=developer_mode_available,
    )
    mcp_router = CompactV1Router(service)
    host_router = HostControlRouter(service)
    host_server = UnixHostControlServer(
        path=config.data_root / "runtime" / "control.sock",
        router=host_router,
    )
    shared_view_server = (
        SharedViewServer(provider=service, port=shared_view_port)
        if shared_view_enabled
        else None
    )
    return CompactRuntime(
        service=service,
        mcp_router=mcp_router,
        host_router=host_router,
        host_server=host_server,
        shared_view_server=shared_view_server,
    )


__all__ = [
    "CompactRuntime",
    "build_legacy_browser_service",
    "build_legacy_compact_runtime",
]
