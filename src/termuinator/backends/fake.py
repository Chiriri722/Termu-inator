"""Deterministic in-memory backend for service and policy tests."""

from __future__ import annotations

from dataclasses import replace
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..contracts import (
    Backend,
    CapabilityRecord,
    CapabilitySet,
    CapabilityStatus,
    ErrorCode,
    Viewport,
)
from ..errors import TermuinatorError
from .base import (
    BackendAction,
    BackendActionOutcome,
    BackendArtifactPayload,
    BackendDevtoolsQuery,
    BackendDevtoolsResult,
    BackendDownloadSnapshot,
    BackendDownloadsResult,
    BackendPageSnapshot,
    BackendStatus,
    BackendTabSnapshot,
    BackendTabsResult,
)


class FakeBackend:
    """Small fake that makes lifecycle and fallback behavior observable."""

    def __init__(
        self,
        backend: Backend,
        *,
        start_error: Exception | None = None,
        snapshot: BackendPageSnapshot | None = None,
        action_outcome: BackendActionOutcome | None = None,
        action_error: Exception | None = None,
        tabs_supported: bool = False,
        navigation_results: Mapping[
            tuple[str, str | None], BackendPageSnapshot
        ] | None = None,
        download_sequences: Mapping[
            str, tuple[BackendDownloadSnapshot, ...]
        ] | None = None,
        devtools_results: Mapping[str, BackendDevtoolsResult] | None = None,
    ) -> None:
        if action_outcome is not None and action_error is not None:
            raise ValueError("fake action_outcome and action_error are mutually exclusive")
        if not isinstance(tabs_supported, bool):
            raise ValueError("tabs_supported must be a boolean")
        self.backend = backend
        self.start_error = start_error
        self.calls: list[str] = []
        self.action_calls: list[BackendAction] = []
        self.screenshot_calls: list[tuple[str, str | None]] = []
        self.tab_calls: list[tuple[str, str | None, str | None]] = []
        self.navigation_calls: list[tuple[str, str | None, int]] = []
        self.download_calls: list[tuple[str, str | None]] = []
        self.devtools_calls: list[BackendDevtoolsQuery] = []
        self.profile_dir: Path = Path(".")
        self.viewport: Viewport | None = None
        self._action_outcome = action_outcome
        self._action_error = action_error
        self._tabs_supported = tabs_supported
        self._navigation_results = dict(navigation_results or {})
        for key, configured_snapshot in self._navigation_results.items():
            if (
                not isinstance(key, tuple)
                or len(key) != 2
                or key[0] not in {"goto", "back", "forward", "reload"}
                or (key[1] is not None and not isinstance(key[1], str))
                or not isinstance(configured_snapshot, BackendPageSnapshot)
            ):
                raise ValueError("navigation_results contains an invalid entry")
        self._download_sequences = dict(download_sequences or {})
        self._download_indices: dict[str, int] = {}
        for identifier, sequence in self._download_sequences.items():
            if (
                not isinstance(identifier, str)
                or not isinstance(sequence, tuple)
                or not sequence
                or any(
                    not isinstance(item, BackendDownloadSnapshot)
                    or item.backend_download_id != identifier
                    for item in sequence
                )
            ):
                raise ValueError("download_sequences contains an invalid entry")
            self._download_indices[identifier] = 0
        self._devtools_results = dict(devtools_results or {})
        for query, result in self._devtools_results.items():
            if (
                query not in {"console", "network", "dom", "style", "performance"}
                or not isinstance(result, BackendDevtoolsResult)
                or result.query != query
            ):
                raise ValueError("devtools_results contains an invalid entry")
        self._snapshot = snapshot or BackendPageSnapshot(
            url="about:blank",
            title="",
            ready_state="complete",
            viewport=None,
        )
        self._tab_serial = 1
        self._active_backend_tab_id = "backend-tab-1"
        self._tab_snapshots = {
            self._active_backend_tab_id: self._snapshot,
        }
        self._status = BackendStatus(
            backend=backend,
            running=False,
            url="",
            title="",
            ready_state="closed",
            updated_at_monotonic=time.monotonic(),
        )

    async def start(
        self, profile_dir: Path, viewport: Viewport | None
    ) -> CapabilitySet:
        self.calls.append("start")
        if self.start_error is not None:
            raise self.start_error
        self.profile_dir = profile_dir
        self.viewport = viewport
        if self._snapshot.viewport is None and viewport is not None:
            self._snapshot = replace(self._snapshot, viewport=viewport)
            self._tab_snapshots[self._active_backend_tab_id] = self._snapshot
        self._status = BackendStatus(
            backend=self.backend,
            running=True,
            url=self._snapshot.url,
            title=self._snapshot.title,
            ready_state=self._snapshot.ready_state,
            updated_at_monotonic=time.monotonic(),
        )
        probed_at = datetime.now(timezone.utc).isoformat()
        return CapabilitySet(
            backend=self.backend,
            revision="fake-v1",
            browser_version="fake-1",
            transport_version="fake-1",
            capabilities=tuple(
                CapabilityRecord(
                    capability_id=capability_id,
                    status=self._capability_status(capability_id),
                    reason_code=self._capability_reason(capability_id),
                    last_probed_at=probed_at,
                )
                for capability_id in (
                    "navigate",
                    "observe",
                    "act",
                    "screenshot",
                    "cached_status",
                    "tabs",
                    "downloads",
                    "devtools",
                )
            ),
        )

    def _capability_status(self, capability_id: str) -> CapabilityStatus:
        if capability_id in {"observe", "cached_status"}:
            return CapabilityStatus.SUPPORTED
        if capability_id == "navigate" and self._navigation_results:
            return CapabilityStatus.SUPPORTED
        if capability_id == "screenshot" and self._snapshot.screenshot is not None:
            return CapabilityStatus.SUPPORTED
        if capability_id == "act" and (
            self._action_outcome is not None or self._action_error is not None
        ):
            return CapabilityStatus.SUPPORTED
        if capability_id == "tabs" and self._tabs_supported:
            return CapabilityStatus.SUPPORTED
        if capability_id == "downloads" and self._download_sequences:
            return CapabilityStatus.SUPPORTED
        if capability_id == "devtools" and self._devtools_results:
            return CapabilityStatus.SUPPORTED
        return CapabilityStatus.UNSUPPORTED

    def _capability_reason(self, capability_id: str) -> str | None:
        if self._capability_status(capability_id) is CapabilityStatus.SUPPORTED:
            return None
        return {
            "navigate": "fake_navigation_not_configured",
            "act": "fake_action_not_configured",
            "screenshot": "fake_screenshot_not_configured",
            "tabs": "fake_tabs_not_configured",
            "downloads": "fake_downloads_not_configured",
            "devtools": "fake_devtools_not_configured",
        }.get(capability_id)

    async def stop(self) -> None:
        self.calls.append("stop")
        self._status = BackendStatus(
            backend=self.backend,
            running=False,
            url=self._status.url,
            title=self._status.title,
            ready_state="closed",
            updated_at_monotonic=time.monotonic(),
        )

    def cached_status(self) -> BackendStatus:
        return self._status

    async def navigate(
        self, operation: str, url: str | None, timeout_ms: int
    ) -> BackendPageSnapshot:
        if (
            operation not in {"goto", "back", "forward", "reload"}
            or isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or not 1 <= timeout_ms <= 120_000
        ):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Fake navigation arguments are invalid",
            )
        self.navigation_calls.append((operation, url, timeout_ms))
        snapshot = self._navigation_results.get((operation, url))
        if snapshot is None:
            raise TermuinatorError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                "Fake navigation result is not configured",
                details={"capability": "navigate", "operation": operation},
            )
        self._snapshot = snapshot
        if self._tabs_supported:
            self._tab_snapshots[self._active_backend_tab_id] = snapshot
        self._refresh_status()
        return snapshot

    async def observe(
        self,
        *,
        include_screenshot: bool,
        include_accessibility: bool,
        text_limit: int,
    ) -> BackendPageSnapshot:
        self.calls.append("observe")
        if include_screenshot and self._snapshot.screenshot is None:
            raise TermuinatorError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                "Fake screenshot payload is not configured",
            )
        if not 0 <= text_limit <= 100_000:
            raise ValueError("text_limit must be between 0 and 100000")
        return replace(
            self._snapshot,
            text=self._snapshot.text[:text_limit],
            text_truncated=len(self._snapshot.text) > text_limit,
            accessibility=(
                self._snapshot.accessibility if include_accessibility else ()
            ),
            screenshot=(self._snapshot.screenshot if include_screenshot else None),
        )

    async def act(self, action: BackendAction) -> BackendActionOutcome:
        self.action_calls.append(action)
        if self._action_error is not None:
            raise self._action_error
        if self._action_outcome is None:
            raise TermuinatorError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                "Fake action outcome is not configured",
            )
        return self._action_outcome

    async def wait(
        self, condition: Mapping[str, Any], timeout_ms: int
    ) -> Mapping[str, Any]:
        raise NotImplementedError("fake waits are introduced with the observe engine")

    def inject_popup(self, snapshot: BackendPageSnapshot) -> str:
        """Inject one browser-originated popup for deterministic lifecycle tests."""

        if not self._tabs_supported:
            raise ValueError("popup injection requires tabs_supported")
        if not isinstance(snapshot, BackendPageSnapshot):
            raise TypeError("popup snapshot must be BackendPageSnapshot")
        self._tab_serial += 1
        backend_tab_id = f"backend-popup-{self._tab_serial}"
        self._tab_snapshots[backend_tab_id] = snapshot
        self._active_backend_tab_id = backend_tab_id
        self._snapshot = snapshot
        self._refresh_status()
        return backend_tab_id

    async def tabs(
        self,
        operation: str,
        *,
        backend_tab_id: str | None = None,
        url: str | None = None,
    ) -> BackendTabsResult:
        if not self._tabs_supported:
            raise TermuinatorError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                "Fake tab lifecycle is not configured",
                details={"capability": "tabs"},
            )
        self.tab_calls.append((operation, backend_tab_id, url))
        if operation == "list":
            if backend_tab_id is not None or url is not None:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Tab list does not accept a target or URL",
                )
            active_snapshot = None
        elif operation == "open":
            if backend_tab_id is not None or not isinstance(url, str):
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Tab open requires only a URL",
                )
            self._tab_serial += 1
            self._active_backend_tab_id = f"backend-tab-{self._tab_serial}"
            self._snapshot = BackendPageSnapshot(
                url=url,
                title="",
                ready_state="complete",
                viewport=self.viewport,
            )
            self._tab_snapshots[self._active_backend_tab_id] = self._snapshot
            active_snapshot = self._snapshot
            self._refresh_status()
        elif operation == "switch":
            if url is not None or backend_tab_id not in self._tab_snapshots:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Tab switch target does not exist",
                )
            assert backend_tab_id is not None
            self._active_backend_tab_id = backend_tab_id
            self._snapshot = self._tab_snapshots[backend_tab_id]
            active_snapshot = self._snapshot
            self._refresh_status()
        elif operation == "close":
            if url is not None or backend_tab_id not in self._tab_snapshots:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Tab close target does not exist",
                )
            if len(self._tab_snapshots) == 1:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "The final controlled tab cannot be closed",
                )
            assert backend_tab_id is not None
            was_active = backend_tab_id == self._active_backend_tab_id
            del self._tab_snapshots[backend_tab_id]
            if was_active:
                self._active_backend_tab_id = next(iter(self._tab_snapshots))
            self._snapshot = self._tab_snapshots[self._active_backend_tab_id]
            active_snapshot = self._snapshot
            self._refresh_status()
        else:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Tab operation is invalid",
            )
        return BackendTabsResult(
            tabs=tuple(
                BackendTabSnapshot(
                    backend_tab_id=identifier,
                    url=snapshot.url,
                    title=snapshot.title,
                    active=identifier == self._active_backend_tab_id,
                )
                for identifier, snapshot in self._tab_snapshots.items()
            ),
            active_backend_tab_id=self._active_backend_tab_id,
            active_snapshot=active_snapshot,
        )

    def _refresh_status(self) -> None:
        self._status = BackendStatus(
            backend=self.backend,
            running=True,
            url=self._snapshot.url,
            title=self._snapshot.title,
            ready_state=self._snapshot.ready_state,
            updated_at_monotonic=time.monotonic(),
        )

    async def screenshot(
        self, mode: str, backend_node_id: str | None = None
    ) -> BackendArtifactPayload:
        self.screenshot_calls.append((mode, backend_node_id))
        if self._snapshot.screenshot is None:
            raise TermuinatorError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                "Fake screenshot payload is not configured",
            )
        return self._snapshot.screenshot

    async def downloads(
        self, operation: str, backend_download_id: str | None = None
    ) -> BackendDownloadsResult:
        if not self._download_sequences:
            raise TermuinatorError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                "Fake download lifecycle is not configured",
                details={"capability": "downloads"},
            )
        if operation == "list":
            if backend_download_id is not None:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Download list does not accept a target",
                )
            self.download_calls.append((operation, None))
            snapshots = tuple(
                sequence[self._download_indices[identifier]]
                for identifier, sequence in self._download_sequences.items()
            )
        elif operation == "wait":
            if backend_download_id not in self._download_sequences:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Download wait target does not exist",
                )
            assert backend_download_id is not None
            self.download_calls.append((operation, backend_download_id))
            sequence = self._download_sequences[backend_download_id]
            current = self._download_indices[backend_download_id]
            current = min(current + 1, len(sequence) - 1)
            self._download_indices[backend_download_id] = current
            snapshots = (sequence[current],)
        else:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Download operation is invalid",
            )
        return BackendDownloadsResult(downloads=snapshots)

    async def devtools(
        self, query: BackendDevtoolsQuery
    ) -> BackendDevtoolsResult:
        if not isinstance(query, BackendDevtoolsQuery):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Fake Developer query must be typed",
            )
        result = self._devtools_results.get(query.query)
        if result is None:
            raise TermuinatorError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                "Fake Developer query is not configured",
                details={"capability": "devtools", "query": query.query},
            )
        self.devtools_calls.append(query)
        return result
