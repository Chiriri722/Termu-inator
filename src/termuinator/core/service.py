"""Typed, backend-neutral single-session browser service."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import time
from typing import Callable, Mapping

from ..backends.base import (
    BackendArtifactPayload,
    BackendConsoleEntry,
    BackendDevtoolsQuery,
    BackendDevtoolsResult,
    BackendDownloadSnapshot,
    BackendDownloadsResult,
    BackendDomEntry,
    BackendNetworkEntry,
    BackendPageSnapshot,
    BackendPerformanceEntry,
    BackendStyleEntry,
    BackendTabsResult,
    BrowserBackend,
)
from ..contracts import (
    ActionKind,
    ActionRequest,
    ActionResult,
    Artifact,
    ArtifactChunk,
    Backend,
    CapabilitySet,
    Challenge,
    ChallengeKind,
    ChallengeState,
    ConsoleEntry,
    DevtoolsResult,
    Download,
    DownloadsResult,
    DomEntry,
    ErrorCode,
    NetworkEntry,
    Observation,
    PageRevision,
    PermissionDecision,
    PermissionPolicy,
    PermissionsResult,
    PerformanceEntry,
    RiskClass,
    SessionStartResult,
    SessionState,
    SessionStatus,
    SessionStopResult,
    StyleEntry,
    Tab,
    TabsResult,
    TraceExportResult,
    TraceRecord,
    TraceRecordsResult,
    TraceResult,
    Viewport,
    WaitCondition,
    WaitDownloadCondition,
    WaitNavigationCondition,
    WaitResult,
    to_wire,
)
from ..errors import TermuinatorError
from ..shared_view import SharedViewArtifact, SharedViewState
from .action_policy import ActionRiskClassifier
from .actions import ActionExecutor
from .confirmations import ConfirmationEngine
from .durable_artifacts import DurableArtifactStore
from .durable_permissions import DurablePermissionEngine
from .durable_traces import DurableTraceRecorder
from .element_refs import ElementBinding
from .idempotency import DurableActionJournal, JournalState, canonical_action_digest
from .observation import ObservationEngine
from .permissions import PermissionEngine, canonical_origin
from .redaction import redact_sensitive_text, redact_url_metadata
from .sessions import SessionLock
from .waits import evaluate_wait, is_wait_condition


BackendFactory = Callable[[], BrowserBackend]
PermissionFactory = Callable[[str], PermissionEngine]
ConfirmationFactory = Callable[[str], ConfirmationEngine]


@dataclass
class _TabState:
    backend_tab_id: str | None
    observation: ObservationEngine
    url: str
    title: str


@dataclass
class _DownloadState:
    backend_download_id: str
    download_id: str
    latest: Download | None = None


@dataclass(frozen=True)
class DeveloperModeStatus:
    session_id: str
    origin: str
    enabled: bool


@dataclass
class _ActiveSession:
    session_id: str
    project_id: str
    project_digest: str
    backend: BrowserBackend
    capabilities: CapabilitySet
    state: SessionState
    observation: ObservationEngine
    tabs: dict[str, _TabState]
    downloads: dict[str, _DownloadState]
    pending_permissions: dict[str, Challenge]
    developer_origins: set[str]
    developer_request_ids: dict[str, str]
    default_viewport: Viewport | None
    artifacts: DurableArtifactStore
    traces: DurableTraceRecorder
    journal: DurableActionJournal
    permissions: PermissionEngine
    confirmations: ConfirmationEngine


class BrowserService:
    """Own session state and select exactly one requested browser backend."""

    def __init__(
        self,
        *,
        data_root: Path,
        owner_scope: str,
        default_backend: Backend,
        profile_schema_version: str,
        backend_factories: Mapping[Backend, BackendFactory],
        session_lock: SessionLock,
        permission_factory: PermissionFactory | None = None,
        confirmation_factory: ConfirmationFactory | None = None,
        action_executor: ActionExecutor | None = None,
        risk_classifier: ActionRiskClassifier | None = None,
        artifact_retention_seconds: int = 86_400,
        artifact_quota_bytes: int = 500 * 1024 * 1024,
        trace_retention_seconds: int = 7 * 86_400,
        trace_quota_bytes: int = 100 * 1024 * 1024,
        max_artifact_chunk_bytes: int = 512 * 1024,
        developer_mode_available: bool = False,
    ) -> None:
        if (
            not isinstance(owner_scope, str)
            or not owner_scope.strip()
            or owner_scope != owner_scope.strip()
            or "\x00" in owner_scope
            or len(owner_scope) > 4096
        ):
            raise ValueError("owner_scope must be a non-empty canonical identifier")
        if not re.fullmatch(r"v[1-9][0-9]{0,3}", profile_schema_version):
            raise ValueError("profile_schema_version must be a canonical vN identifier")
        if (
            isinstance(artifact_retention_seconds, bool)
            or not isinstance(artifact_retention_seconds, int)
            or not 1 <= artifact_retention_seconds <= 31 * 86_400
        ):
            raise ValueError("artifact_retention_seconds is out of bounds")
        if (
            isinstance(artifact_quota_bytes, bool)
            or not isinstance(artifact_quota_bytes, int)
            or artifact_quota_bytes < 1
        ):
            raise ValueError("artifact_quota_bytes must be positive")
        if (
            isinstance(trace_retention_seconds, bool)
            or not isinstance(trace_retention_seconds, int)
            or not 1 <= trace_retention_seconds <= 31 * 86_400
        ):
            raise ValueError("trace_retention_seconds is out of bounds")
        if (
            isinstance(trace_quota_bytes, bool)
            or not isinstance(trace_quota_bytes, int)
            or trace_quota_bytes < 1
        ):
            raise ValueError("trace_quota_bytes must be positive")
        if (
            isinstance(max_artifact_chunk_bytes, bool)
            or not isinstance(max_artifact_chunk_bytes, int)
            or not 1 <= max_artifact_chunk_bytes <= 512 * 1024
        ):
            raise ValueError(
                "max_artifact_chunk_bytes must be between 1 and 512 KiB"
            )
        if not isinstance(developer_mode_available, bool):
            raise ValueError("developer_mode_available must be a boolean")
        self._data_root = data_root
        self._owner_scope = owner_scope
        self._default_backend = self._parse_backend(default_backend)
        self._profile_schema_version = profile_schema_version
        self._backend_factories = dict(backend_factories)
        self._session_lock = session_lock
        self._permission_factory = permission_factory
        self._confirmation_factory = confirmation_factory or (
            lambda project_id: ConfirmationEngine(
                owner_scope=self._owner_scope,
                project_id=project_id,
            )
        )
        self._action_executor = action_executor or ActionExecutor()
        self._risk_classifier = risk_classifier or ActionRiskClassifier()
        self._artifact_retention_seconds = artifact_retention_seconds
        self._artifact_quota_bytes = artifact_quota_bytes
        self._trace_retention_seconds = trace_retention_seconds
        self._trace_quota_bytes = trace_quota_bytes
        self._max_artifact_chunk_bytes = max_artifact_chunk_bytes
        self._developer_mode_available = developer_mode_available
        self._active: _ActiveSession | None = None
        self._mutex = asyncio.Lock()

    async def session_start(
        self,
        *,
        project_id: str,
        backend: Backend | str | None = None,
        viewport: Viewport | None = None,
    ) -> SessionStartResult:
        project_digest = self._project_digest(project_id)
        selected = (
            self._default_backend if backend is None else self._parse_backend(backend)
        )

        async with self._mutex:
            if self._active is not None:
                raise TermuinatorError(
                    ErrorCode.SESSION_BUSY,
                    "A browser session is already active",
                    retryable=True,
                    details={"active_backend": self._active.capabilities.backend.value},
                )

            factory = self._backend_factories.get(selected)
            if factory is None:
                raise TermuinatorError(
                    ErrorCode.UNSUPPORTED_CAPABILITY,
                    f"Backend '{selected.value}' is not configured",
                    details={"backend": selected.value},
                )

            lease_acquired = False
            try:
                self._session_lock.acquire()
                lease_acquired = True
                profile_dir = self._prepare_profile(project_digest, selected)
                state_root = self._prepare_state_root()
                journal = DurableActionJournal(
                    root=state_root,
                    owner_scope=self._owner_scope,
                    project_id=project_id,
                )
                permissions = (
                    self._permission_factory(project_id)
                    if self._permission_factory is not None
                    else DurablePermissionEngine(
                        root=state_root,
                        owner_scope=self._owner_scope,
                        project_id=project_id,
                    )
                )
                confirmations = self._confirmation_factory(project_id)
                implementation = factory()
                if implementation.backend != selected:
                    raise TermuinatorError(
                        ErrorCode.INTERNAL_ERROR,
                        "Backend factory returned the wrong backend",
                        details={"backend": selected.value},
                    )

                try:
                    capabilities = await implementation.start(profile_dir, viewport)
                except TermuinatorError:
                    raise
                except Exception as exc:
                    raise TermuinatorError(
                        ErrorCode.BACKEND_CRASHED,
                        f"Backend '{selected.value}' failed to start",
                        retryable=True,
                        details={"backend": selected.value},
                    ) from exc

                if capabilities.backend != selected:
                    try:
                        await implementation.stop()
                    finally:
                        raise TermuinatorError(
                            ErrorCode.INTERNAL_ERROR,
                            "Backend capability identity mismatch",
                            details={"backend": selected.value},
                        )

                session_id = "session_" + secrets.token_urlsafe(24)
                observation = ObservationEngine(
                    session_id=session_id,
                    capability_revision=capabilities.revision,
                    default_viewport=viewport,
                )
                artifacts = DurableArtifactStore(
                    root=state_root,
                    owner_project_digest=project_digest,
                    authorize_session=lambda candidate, expected=session_id: (
                        isinstance(candidate, str)
                        and secrets.compare_digest(candidate, expected)
                    ),
                    retention_seconds=self._artifact_retention_seconds,
                    quota_bytes=self._artifact_quota_bytes,
                    max_chunk_bytes=self._max_artifact_chunk_bytes,
                )
                traces = DurableTraceRecorder(
                    root=state_root,
                    owner_project_digest=project_digest,
                    authorize_session=lambda candidate, expected=session_id: (
                        isinstance(candidate, str)
                        and secrets.compare_digest(candidate, expected)
                    ),
                    retention_seconds=self._trace_retention_seconds,
                    quota_bytes=self._trace_quota_bytes,
                )
                self._active = _ActiveSession(
                    session_id=session_id,
                    project_id=project_id,
                    project_digest=project_digest,
                    backend=implementation,
                    capabilities=capabilities,
                    state=SessionState.ACTIVE,
                    observation=observation,
                    tabs={
                        observation.tab_id: _TabState(
                            backend_tab_id=None,
                            observation=observation,
                            url=implementation.cached_status().url,
                            title=implementation.cached_status().title,
                        )
                    },
                    downloads={},
                    pending_permissions={},
                    developer_origins=set(),
                    developer_request_ids={},
                    default_viewport=viewport,
                    artifacts=artifacts,
                    traces=traces,
                    journal=journal,
                    permissions=permissions,
                    confirmations=confirmations,
                )
                status = self._status_result(self._active)
                return SessionStartResult(
                    session_id=session_id,
                    capabilities=capabilities,
                    status=status,
                )
            except Exception:
                if lease_acquired:
                    self._session_lock.release()
                raise

    async def session_status(self, session_id: str) -> SessionStatus:
        async with self._mutex:
            active = self._require_session(session_id)
            return self._status_result(active)

    async def shared_view_snapshot(self) -> SharedViewState:
        """Compose one bounded local dashboard snapshot without browser I/O."""

        generated_at = datetime.now(timezone.utc).isoformat()
        async with self._mutex:
            active = self._active
            if active is None:
                return SharedViewState(
                    generated_at=generated_at,
                    session_id=None,
                    state="idle",
                    backend=None,
                    running=False,
                    active_tab_id=None,
                    page_revision=None,
                    url="",
                    title="",
                    ready_state="idle",
                    freshness_ms=0,
                    screenshot_artifact_uri=None,
                    pending_permissions=(),
                    pending_confirmations=(),
                    recent_traces=(),
                    traces_truncated=False,
                    confidential=False,
                )

            status = self._status_result(active)
            confidential = active.state in {
                SessionState.USER_TAKEOVER_REQUIRED,
                SessionState.USER_TAKEOVER_ACTIVE,
            }
            if confidential:
                return SharedViewState(
                    generated_at=generated_at,
                    session_id=active.session_id,
                    state=active.state.value,
                    backend=status.backend,
                    running=status.running,
                    active_tab_id=None,
                    page_revision=None,
                    url="",
                    title="",
                    ready_state="takeover",
                    freshness_ms=status.freshness_ms,
                    screenshot_artifact_uri=None,
                    pending_permissions=(),
                    pending_confirmations=(),
                    recent_traces=(),
                    traces_truncated=False,
                    confidential=True,
                )

            last = active.observation.last_observation
            pending_confirmations = tuple(
                Challenge(
                    challenge_id=item.challenge_id,
                    kind=item.kind,
                    state=item.state,
                    preview=redact_sensitive_text(item.preview),
                    expires_at=item.expires_at,
                )
                for item in active.confirmations.list_pending(limit=16)
            )
            recent_traces, traces_truncated = active.traces.list_page(
                session_id=active.session_id,
                limit=20,
            )
            return SharedViewState(
                generated_at=generated_at,
                session_id=active.session_id,
                state=active.state.value,
                backend=status.backend,
                running=status.running,
                active_tab_id=status.active_tab_id,
                page_revision=status.page_revision,
                url=redact_url_metadata(status.url),
                title=redact_sensitive_text(status.title),
                ready_state=status.ready_state,
                freshness_ms=status.freshness_ms,
                screenshot_artifact_uri=(
                    last.screenshot_artifact_uri if last is not None else None
                ),
                pending_permissions=tuple(active.pending_permissions.values()),
                pending_confirmations=pending_confirmations,
                recent_traces=recent_traces,
                traces_truncated=traces_truncated,
                confidential=False,
            )

    async def shared_view_screenshot(self) -> SharedViewArtifact:
        """Read only the cached current screenshot through verified storage."""

        async with self._mutex:
            active = self._active
            if active is None:
                raise TermuinatorError(
                    ErrorCode.ARTIFACT_NOT_FOUND,
                    "No current shared-view screenshot is available",
                )
            if active.state in {
                SessionState.USER_TAKEOVER_REQUIRED,
                SessionState.USER_TAKEOVER_ACTIVE,
            }:
                raise TermuinatorError(
                    ErrorCode.SESSION_PAUSED,
                    "Shared-view page content is hidden during local takeover",
                )
            last = active.observation.last_observation
            uri = last.screenshot_artifact_uri if last is not None else None
            if uri is None:
                raise TermuinatorError(
                    ErrorCode.ARTIFACT_NOT_FOUND,
                    "No current shared-view screenshot is available",
                )

            chunks: list[bytes] = []
            offset = 0
            while True:
                chunk = active.artifacts.read(
                    session_id=active.session_id,
                    uri=uri,
                    offset=offset,
                    limit=self._max_artifact_chunk_bytes,
                )
                raw = base64.b64decode(chunk.data_base64, validate=True)
                chunks.append(raw)
                offset = chunk.next_offset
                if offset > 8 * 1024 * 1024:
                    raise TermuinatorError(
                        ErrorCode.ARTIFACT_NOT_FOUND,
                        "Current screenshot exceeds the shared-view limit",
                    )
                if chunk.eof:
                    break
            data = b"".join(chunks)
            if data.startswith(b"\x89PNG\r\n\x1a\n"):
                mime_type = "image/png"
            elif (
                len(data) >= 12
                and data.startswith(b"RIFF")
                and data[8:12] == b"WEBP"
            ):
                mime_type = "image/webp"
            else:
                raise TermuinatorError(
                    ErrorCode.ARTIFACT_NOT_FOUND,
                    "Current screenshot has an unsupported image format",
                )
            return SharedViewArtifact(data=data, mime_type=mime_type)

    async def navigate(
        self,
        *,
        session_id: str,
        tab_id: str,
        page_id: str,
        expected_revision: PageRevision,
        operation: str,
        url: str | None = None,
        timeout_ms: int = 30_000,
    ) -> Observation:
        """Navigate one active observed page through closed origin policy."""

        if operation == "goto":
            valid_operation = (
                isinstance(url, str)
                and len(url) <= 8_192
                and re.fullmatch(r"https?://[^\s]+", url) is not None
            )
        elif operation in {"back", "forward", "reload"}:
            valid_operation = url is None
        else:
            valid_operation = False
        if not valid_operation or (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or not 1 <= timeout_ms <= 120_000
        ):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Navigation operation arguments are invalid",
            )

        async with self._mutex:
            active = self._require_session(session_id)
            self._require_remote_active(active)
            active.observation.require_context(
                session_id=session_id,
                tab_id=tab_id,
                page_id=page_id,
                expected_revision=expected_revision,
            )
            if operation == "goto":
                assert url is not None
                self._require_origin_permission(
                    active,
                    url=url,
                    quarantine=False,
                )
            try:
                snapshot = await active.backend.navigate(
                    operation,
                    url,
                    timeout_ms,
                )
            except TermuinatorError:
                raise
            except TimeoutError as exc:
                raise TermuinatorError(
                    ErrorCode.TIMEOUT,
                    "Backend navigation timed out",
                    retryable=True,
                    details={"backend": active.capabilities.backend.value},
                ) from exc
            except Exception as exc:
                raise TermuinatorError(
                    ErrorCode.BACKEND_CRASHED,
                    "Backend navigation failed",
                    retryable=True,
                    details={"backend": active.capabilities.backend.value},
                ) from exc
            if not isinstance(snapshot, BackendPageSnapshot):
                raise TermuinatorError(
                    ErrorCode.BACKEND_CRASHED,
                    "Backend returned an invalid navigation snapshot",
                    retryable=True,
                    details={"backend": active.capabilities.backend.value},
                )

            observation = active.observation.capture(
                snapshot,
                document_changed=True,
            )
            state = active.tabs.get(observation.tab_id)
            if state is None:
                raise TermuinatorError(
                    ErrorCode.INTERNAL_ERROR,
                    "Active navigation tab identity is missing",
                )
            state.url = observation.url
            state.title = observation.title
            if observation.url.startswith(("http://", "https://")):
                self._require_origin_permission(
                    active,
                    url=observation.url,
                    quarantine=True,
                )
            self._apply_observation_handoff(active, observation)
            return observation

    async def observe(
        self,
        *,
        session_id: str,
        tab_id: str,
        page_id: str,
        expected_revision: PageRevision,
        include_screenshot: bool,
        include_accessibility: bool,
        text_limit: int,
    ) -> Observation:
        async with self._mutex:
            active = self._require_session(session_id)
            self._require_remote_active(active)
            active.observation.require_context(
                session_id=session_id,
                tab_id=tab_id,
                page_id=page_id,
                expected_revision=expected_revision,
            )
            try:
                snapshot = await active.backend.observe(
                    include_screenshot=include_screenshot,
                    include_accessibility=include_accessibility,
                    text_limit=text_limit,
                )
            except TermuinatorError:
                raise
            except Exception as exc:
                raise TermuinatorError(
                    ErrorCode.BACKEND_CRASHED,
                    "Backend observation failed",
                    retryable=True,
                    details={"backend": active.capabilities.backend.value},
                ) from exc
            screenshot_artifact_uri: str | None = None
            if snapshot.screenshot is not None:
                artifact = active.artifacts.put(
                    session_id=session_id,
                    data=snapshot.screenshot.data,
                    mime_type=snapshot.screenshot.mime_type,
                )
                screenshot_artifact_uri = artifact.uri
            elif include_screenshot:
                raise TermuinatorError(
                    ErrorCode.UNSUPPORTED_CAPABILITY,
                    "Backend did not return the requested screenshot payload",
                    details={"backend": active.capabilities.backend.value},
                )
            observation = active.observation.capture(
                snapshot,
                screenshot_artifact_uri=screenshot_artifact_uri,
            )
            self._apply_observation_handoff(active, observation)
            return observation

    async def wait(
        self,
        *,
        session_id: str,
        tab_id: str,
        page_id: str,
        expected_revision: PageRevision,
        condition: WaitCondition,
        timeout_ms: int = 30_000,
    ) -> WaitResult:
        """Poll fresh bounded observations for one closed condition."""

        if not is_wait_condition(condition):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "browser_wait requires a typed WaitCondition",
            )
        if (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or not 1 <= timeout_ms <= 120_000
        ):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "browser_wait timeout_ms must be between 1 and 120000",
            )
        if isinstance(condition, WaitNavigationCondition) and (
            condition.from_revision != expected_revision
        ):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Navigation wait revision must match the page precondition",
            )

        started = time.monotonic()
        last_observation: Observation | None = None
        last_download: Download | None = None
        while True:
            async with self._mutex:
                active = self._require_session(session_id)
                self._require_remote_active(active)
                active.observation.require_context(
                    session_id=session_id,
                    tab_id=tab_id,
                    page_id=page_id,
                    expected_revision=expected_revision,
                )
                current = active.observation.last_observation
                if current is None:
                    raise TermuinatorError(
                        ErrorCode.STALE_OBSERVATION,
                        "A wait requires a prior page observation",
                    )
                if isinstance(condition, WaitDownloadCondition):
                    target = active.downloads.get(condition.download_id)
                    if target is None:
                        raise TermuinatorError(
                            ErrorCode.INVALID_REQUEST,
                            "The requested public download does not exist",
                        )
                    last_download = target.latest
                    if (
                        last_download is not None
                        and last_download.state
                        in {"completed", "failed", "cancelled"}
                    ):
                        return WaitResult(
                            condition_kind=condition.kind,
                            satisfied=True,
                            elapsed_ms=self._wait_elapsed_ms(started),
                            observation=None,
                            download=last_download,
                        )
                    remaining_ms = timeout_ms - self._wait_elapsed_ms(started)
                    if remaining_ms <= 0:
                        return WaitResult(
                            condition_kind=condition.kind,
                            satisfied=False,
                            elapsed_ms=self._wait_elapsed_ms(started),
                            observation=None,
                            download=last_download,
                        )
                    try:
                        backend_result = await asyncio.wait_for(
                            self._backend_downloads(
                                active,
                                operation="wait",
                                backend_download_id=target.backend_download_id,
                            ),
                            timeout=remaining_ms / 1_000,
                        )
                    except asyncio.TimeoutError:
                        return WaitResult(
                            condition_kind=condition.kind,
                            satisfied=False,
                            elapsed_ms=self._wait_elapsed_ms(started),
                            observation=None,
                            download=last_download,
                        )
                    reconciled = self._reconcile_downloads(
                        active,
                        operation="wait",
                        result=backend_result,
                        expected_backend_download_id=target.backend_download_id,
                    )
                    last_download = reconciled.downloads[0]
                    elapsed_ms = self._wait_elapsed_ms(started)
                    if (
                        last_download.state
                        in {"completed", "failed", "cancelled"}
                        or elapsed_ms >= timeout_ms
                    ):
                        return WaitResult(
                            condition_kind=condition.kind,
                            satisfied=(
                                last_download.state
                                in {"completed", "failed", "cancelled"}
                            ),
                            elapsed_ms=elapsed_ms,
                            observation=None,
                            download=last_download,
                        )
                    continue
                if last_observation is None and evaluate_wait(condition, current):
                    return WaitResult(
                        condition_kind=condition.kind,
                        satisfied=True,
                        elapsed_ms=self._wait_elapsed_ms(started),
                        observation=current,
                        download=None,
                    )

                remaining_ms = timeout_ms - self._wait_elapsed_ms(started)
                if remaining_ms <= 0:
                    return WaitResult(
                        condition_kind=condition.kind,
                        satisfied=False,
                        elapsed_ms=self._wait_elapsed_ms(started),
                        observation=current,
                        download=None,
                    )
                try:
                    snapshot = await asyncio.wait_for(
                        active.backend.observe(
                            include_screenshot=False,
                            include_accessibility=False,
                            text_limit=(
                                100_000 if condition.kind == "text" else 0
                            ),
                        ),
                        timeout=remaining_ms / 1_000,
                    )
                except asyncio.TimeoutError:
                    return WaitResult(
                        condition_kind=condition.kind,
                        satisfied=False,
                        elapsed_ms=self._wait_elapsed_ms(started),
                        observation=current,
                        download=None,
                    )
                except TermuinatorError:
                    raise
                except Exception as exc:
                    raise TermuinatorError(
                        ErrorCode.BACKEND_CRASHED,
                        "Backend wait observation failed",
                        retryable=True,
                        details={"backend": active.capabilities.backend.value},
                    ) from exc

                document_changed = snapshot.url != current.url
                last_observation = active.observation.capture(
                    snapshot,
                    document_changed=document_changed,
                )
                satisfied = evaluate_wait(condition, last_observation)
                elapsed_ms = self._wait_elapsed_ms(started)
                handoff_required = self._apply_observation_handoff(
                    active,
                    last_observation,
                )
                if (
                    satisfied
                    or elapsed_ms >= timeout_ms
                    or document_changed
                    or handoff_required
                ):
                    return WaitResult(
                        condition_kind=condition.kind,
                        satisfied=satisfied,
                        elapsed_ms=elapsed_ms,
                        observation=last_observation,
                        download=None,
                    )

            remaining_ms = timeout_ms - self._wait_elapsed_ms(started)
            if remaining_ms <= 0:
                return WaitResult(
                    condition_kind=condition.kind,
                    satisfied=False,
                    elapsed_ms=self._wait_elapsed_ms(started),
                    observation=last_observation,
                    download=None,
                )
            await asyncio.sleep(min(0.1, remaining_ms / 1_000))

    async def tabs(
        self,
        *,
        session_id: str,
        operation: str,
        tab_id: str | None = None,
        url: str | None = None,
    ) -> TabsResult:
        """List or mutate tabs while keeping backend handles private."""

        self._validate_tab_request(
            operation=operation,
            tab_id=tab_id,
            url=url,
        )
        async with self._mutex:
            active = self._require_session(session_id)
            self._require_remote_active(active)
            target = active.tabs.get(tab_id) if tab_id is not None else None
            if tab_id is not None and target is None:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "The requested public tab does not exist",
                )
            if operation == "close" and len(active.tabs) == 1:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "The final controlled tab cannot be closed",
                )

            if operation != "list" and any(
                state.backend_tab_id is None for state in active.tabs.values()
            ):
                inventory = await self._backend_tabs(active, operation="list")
                self._reconcile_tabs(active, operation="list", result=inventory)
                target = active.tabs.get(tab_id) if tab_id is not None else None

            backend_tab_id = (
                target.backend_tab_id if target is not None else None
            )
            result = await self._backend_tabs(
                active,
                operation=operation,
                backend_tab_id=backend_tab_id,
                url=url,
            )
            return self._reconcile_tabs(
                active,
                operation=operation,
                result=result,
            )

    async def artifact_read(
        self,
        *,
        session_id: str,
        uri: str,
        offset: int,
        limit: int,
    ) -> ArtifactChunk:
        async with self._mutex:
            active = self._require_session(session_id)
            self._require_remote_active(active)
            return active.artifacts.read(
                session_id=session_id,
                uri=uri,
                offset=offset,
                limit=limit,
            )

    async def downloads(
        self,
        *,
        session_id: str,
        operation: str,
        download_id: str | None = None,
    ) -> DownloadsResult:
        """List or advance downloads without exposing backend handles or paths."""

        self._validate_download_request(
            operation=operation,
            download_id=download_id,
        )
        async with self._mutex:
            active = self._require_session(session_id)
            self._require_remote_active(active)
            target = (
                active.downloads.get(download_id)
                if download_id is not None
                else None
            )
            if operation == "wait" and target is None:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "The requested public download does not exist",
                )
            result = await self._backend_downloads(
                active,
                operation=operation,
                backend_download_id=(
                    target.backend_download_id if target is not None else None
                ),
            )
            return self._reconcile_downloads(
                active,
                operation=operation,
                result=result,
                expected_backend_download_id=(
                    target.backend_download_id if target is not None else None
                ),
            )

    async def screenshot(
        self,
        *,
        session_id: str,
        tab_id: str,
        page_id: str,
        expected_revision: PageRevision,
        mode: str,
        target_ref: str | None = None,
    ) -> Artifact:
        async with self._mutex:
            active = self._require_session(session_id)
            self._require_remote_active(active)
            if mode not in {"viewport", "full", "element"}:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Screenshot mode must be viewport, full, or element",
                )
            if mode == "element":
                if not isinstance(target_ref, str):
                    raise TermuinatorError(
                        ErrorCode.INVALID_REQUEST,
                        "Element screenshots require target_ref",
                    )
            elif target_ref is not None:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Only element screenshots accept target_ref",
                )

            active.observation.require_context(
                session_id=session_id,
                tab_id=tab_id,
                page_id=page_id,
                expected_revision=expected_revision,
            )
            backend_node_id: str | None = None
            if target_ref is not None:
                backend_node_id = active.observation.resolve_ref(
                    ref=target_ref,
                    expected_revision=expected_revision,
                    risk=RiskClass.R0,
                ).backend_node_id
            try:
                payload = await active.backend.screenshot(mode, backend_node_id)
            except TermuinatorError:
                raise
            except Exception as exc:
                raise TermuinatorError(
                    ErrorCode.BACKEND_CRASHED,
                    "Backend screenshot failed",
                    retryable=True,
                    details={"backend": active.capabilities.backend.value},
                ) from exc
            if not isinstance(payload, BackendArtifactPayload):
                raise TermuinatorError(
                    ErrorCode.BACKEND_CRASHED,
                    "Backend returned an invalid screenshot payload",
                    details={"backend": active.capabilities.backend.value},
                )
            return active.artifacts.put(
                session_id=session_id,
                data=payload.data,
                mime_type=payload.mime_type,
            )

    async def permissions(
        self,
        *,
        session_id: str,
        operation: str,
        challenge_id: str | None = None,
    ) -> PermissionsResult:
        async with self._mutex:
            active = self._require_session(session_id)
            self._require_remote_active(active)
            if not isinstance(operation, str):
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Trace operation must be a string",
                )
            if operation == "list":
                if challenge_id is not None:
                    raise TermuinatorError(
                        ErrorCode.INVALID_REQUEST,
                        "Permission list does not accept challenge_id",
                    )
                return PermissionsResult(
                    operation="list",
                    decisions=active.permissions.list(session_id),
                    challenge=None,
                )
            if operation == "status":
                if not isinstance(challenge_id, str):
                    raise TermuinatorError(
                        ErrorCode.INVALID_REQUEST,
                        "Permission status requires challenge_id",
                    )
                return PermissionsResult(
                    operation="status",
                    decisions=(),
                    challenge=active.confirmations.status(challenge_id),
                )
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Permission operation must be list or status",
            )

    async def devtools(
        self,
        *,
        session_id: str,
        tab_id: str,
        page_id: str,
        expected_revision: PageRevision,
        query: str,
        parameters: Mapping[str, object],
    ) -> DevtoolsResult:
        """Run one bounded read-only Developer query after local site approval."""

        async with self._mutex:
            active = self._require_session(session_id)
            self._require_remote_active(active)
            active.observation.require_context(
                session_id=session_id,
                tab_id=tab_id,
                page_id=page_id,
                expected_revision=expected_revision,
            )
            observation = active.observation.last_observation
            if observation is None:
                raise TermuinatorError(
                    ErrorCode.STALE_OBSERVATION,
                    "A Developer query requires a prior page observation",
                )
            if not self._developer_mode_available:
                raise TermuinatorError(
                    ErrorCode.UNSUPPORTED_CAPABILITY,
                    "Developer Mode is not available for this runtime",
                    details={"capability": "browser_devtools"},
                )
            if observation.origin not in active.developer_origins:
                raise TermuinatorError(
                    ErrorCode.PERMISSION_REQUIRED,
                    "Developer Mode requires a local grant for the current origin",
                    details={
                        "capability": "browser_devtools",
                        "origin": observation.origin,
                    },
                )
            backend_query = self._prepare_devtools_query(
                active,
                query=query,
                parameters=parameters,
                expected_revision=expected_revision,
            )
            try:
                result = await active.backend.devtools(backend_query)
            except TermuinatorError:
                raise
            except Exception as exc:
                raise TermuinatorError(
                    ErrorCode.BACKEND_CRASHED,
                    "Backend Developer query failed",
                    retryable=True,
                    details={"backend": active.capabilities.backend.value},
                ) from exc
            if not isinstance(result, BackendDevtoolsResult) or result.query != query:
                raise TermuinatorError(
                    ErrorCode.INTERNAL_ERROR,
                    "Backend returned an invalid Developer result",
                    details={"backend": active.capabilities.backend.value},
                )
            return self._normalize_devtools_result(active, result)

    async def trace(
        self,
        *,
        session_id: str,
        operation: str,
        trace_id: str | None = None,
    ) -> TraceResult:
        """Read or export secret-free traces for the active project session."""

        async with self._mutex:
            active = self._require_session(session_id)
            self._require_remote_active(active)
            if operation == "list":
                if trace_id is not None:
                    raise TermuinatorError(
                        ErrorCode.INVALID_REQUEST,
                        "Trace list does not accept trace_id",
                    )
                records, truncated = active.traces.list_page(
                    session_id=session_id,
                    limit=1_000,
                )
                return TraceRecordsResult(
                    operation="list",
                    traces=records,
                    truncated=truncated,
                )
            if operation in {"get", "export"}:
                if not isinstance(trace_id, str):
                    raise TermuinatorError(
                        ErrorCode.INVALID_REQUEST,
                        f"Trace {operation} requires trace_id",
                    )
                record = active.traces.get(
                    session_id=session_id,
                    trace_id=trace_id,
                )
                if operation == "get":
                    return TraceRecordsResult(
                        operation="get",
                        traces=(record,),
                        truncated=False,
                    )
                payload = json.dumps(
                    {
                        "format": "termuinator-trace-export-v1",
                        "trace": to_wire(record),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
                artifact = active.artifacts.put(
                    session_id=session_id,
                    data=payload,
                    mime_type="application/json",
                )
                return TraceExportResult(
                    operation="export",
                    artifact=artifact,
                )
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Trace operation must be list, get, or export",
            )

    async def local_takeover_start(self, session_id: str) -> SessionStatus:
        """Enter local user control without exposing a remote mutation surface."""

        async with self._mutex:
            active = self._require_session(session_id)
            if active.state is not SessionState.USER_TAKEOVER_REQUIRED:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Local takeover can start only when user takeover is required",
                    details={"state": active.state.value},
                )
            active.state = SessionState.USER_TAKEOVER_ACTIVE
            return self._status_result(active)

    async def local_permission_record(
        self,
        *,
        session_id: str,
        origin: str,
        policy: PermissionPolicy,
    ) -> PermissionDecision:
        """Record a host-authorized origin decision for the active session."""

        async with self._mutex:
            active = self._require_session(session_id)
            if not isinstance(policy, PermissionPolicy):
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Local permission policy is invalid",
                )
            bound_session = (
                active.session_id
                if policy is PermissionPolicy.SESSION_ALLOW
                else None
            )
            normalized = canonical_origin(origin)
            decision = active.permissions.record(
                origin=normalized,
                policy=policy,
                session_id=bound_session,
            )
            active.pending_permissions.pop(normalized, None)
            return decision

    async def local_developer_mode_set(
        self,
        *,
        session_id: str,
        origin: str,
        enabled: bool,
    ) -> DeveloperModeStatus:
        """Grant or revoke Developer reads for the currently observed origin."""

        async with self._mutex:
            active = self._require_session(session_id)
            self._require_remote_active(active)
            if not self._developer_mode_available:
                raise TermuinatorError(
                    ErrorCode.UNSUPPORTED_CAPABILITY,
                    "Developer Mode is not available for this runtime",
                    details={"capability": "browser_devtools"},
                )
            if not isinstance(enabled, bool):
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Developer Mode enabled must be a boolean",
                )
            try:
                normalized = canonical_origin(origin)
            except (TypeError, ValueError) as exc:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Developer Mode origin is invalid",
                ) from exc
            observation = active.observation.last_observation
            if observation is None or observation.origin != normalized:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Developer Mode can change only for the current observed origin",
                )
            if enabled:
                active.developer_origins.add(normalized)
            else:
                active.developer_origins.discard(normalized)
            return DeveloperModeStatus(
                session_id=active.session_id,
                origin=normalized,
                enabled=enabled,
            )

    async def local_confirmation_decide(
        self,
        *,
        session_id: str,
        operation: str,
        confirmation_id: str,
    ) -> Challenge:
        """Approve or deny one server-owned challenge from a local host."""

        async with self._mutex:
            active = self._require_session(session_id)
            if operation == "approve":
                return active.confirmations.approve(confirmation_id)
            if operation == "deny":
                return active.confirmations.deny(confirmation_id)
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Local confirmation operation must be approve or deny",
            )

    async def local_takeover_resume(self, session_id: str) -> Observation:
        """Refresh page identity after local control and resume remote automation."""

        async with self._mutex:
            active = self._require_session(session_id)
            if active.state is not SessionState.USER_TAKEOVER_ACTIVE:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Local takeover can resume only while local control is active",
                    details={"state": active.state.value},
                )
            try:
                snapshot = await active.backend.observe(
                    include_screenshot=False,
                    include_accessibility=False,
                    text_limit=0,
                )
            except TermuinatorError:
                raise
            except Exception as exc:
                raise TermuinatorError(
                    ErrorCode.BACKEND_CRASHED,
                    "Backend takeover resume observation failed",
                    retryable=True,
                    details={"backend": active.capabilities.backend.value},
                ) from exc

            observation = active.observation.capture(
                snapshot,
                document_changed=True,
                suppress_sensitive_handoff=True,
            )
            if any(dialog.open for dialog in observation.dialogs):
                raise TermuinatorError(
                    ErrorCode.SESSION_PAUSED,
                    "A browser dialog remains open under local user control",
                    details={"state": active.state.value},
                )
            active.state = SessionState.ACTIVE
            return observation

    async def act(self, request: ActionRequest) -> ActionResult:
        if not isinstance(request, ActionRequest):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "browser_act requires a typed ActionRequest",
            )
        async with self._mutex:
            active = self._require_session(request.session_id)
            self._require_remote_active(active)
            claim = active.journal.reserve(request)
            if claim.state is JournalState.TERMINAL:
                if claim.result is None:
                    raise TermuinatorError(
                        ErrorCode.INTERNAL_ERROR,
                        "Terminal action journal record has no result",
                    )
                return claim.result
            observation = active.observation.last_observation
            if observation is None:
                raise TermuinatorError(
                    ErrorCode.STALE_OBSERVATION,
                    "An action requires a prior page observation",
                )
            active.observation.require_context(
                session_id=request.session_id,
                tab_id=request.tab_id,
                page_id=request.page_id,
                expected_revision=request.expected_page_revision,
            )
            if observation.origin == "null" or not observation.url.startswith(
                ("http://", "https://")
            ):
                raise TermuinatorError(
                    ErrorCode.PERMISSION_REQUIRED,
                    "Actions require an allowed HTTP(S) origin",
                    details={"origin": None},
                )

            permission = active.permissions.evaluate(
                url=observation.url,
                session_id=active.session_id,
            )
            if permission is PermissionPolicy.BLOCK:
                raise TermuinatorError(
                    ErrorCode.PERMISSION_DENIED,
                    "The current origin is blocked",
                    details={"origin": observation.origin},
                )
            if permission is PermissionPolicy.ASK:
                challenge = self._pending_permission_challenge(
                    active,
                    observation.origin,
                )
                raise TermuinatorError(
                    ErrorCode.PERMISSION_REQUIRED,
                    "The current origin requires local permission",
                    details={
                        "origin": observation.origin,
                        "challenge": to_wire(challenge),
                    },
                )
            if permission not in {
                PermissionPolicy.SESSION_ALLOW,
                PermissionPolicy.ALWAYS_ALLOW,
            }:
                raise TermuinatorError(
                    ErrorCode.INTERNAL_ERROR,
                    "Permission engine returned an invalid action policy",
                )

            target, destination = self._resolve_action_bindings(active, request)
            assessment = self._risk_classifier.assess(
                request=request,
                target=target,
                destination=destination,
                origin=observation.origin,
            )
            if assessment.requires_takeover:
                active.state = SessionState.USER_TAKEOVER_REQUIRED
                raise TermuinatorError(
                    ErrorCode.SESSION_PAUSED,
                    "Confidential local user takeover is required",
                    details={
                        "reason_code": assessment.reason_code,
                        "preview": assessment.preview,
                        "risk": assessment.risk.value,
                    },
                )

            requires_confirmation = (
                assessment.requires_confirmation
                or claim.state is JournalState.WAITING_CONFIRMATION
            )
            if requires_confirmation:
                action_digest = canonical_action_digest(request)
                challenge = active.confirmations.prepare(
                    session_id=active.session_id,
                    origin=observation.origin,
                    page_revision=request.expected_page_revision,
                    action_digest=action_digest,
                    idempotency_key=request.idempotency_key,
                    preview=assessment.preview,
                )
                if claim.state is JournalState.RESERVED:
                    active.journal.mark_waiting_confirmation(request)
                if request.confirmation_id is None:
                    raise TermuinatorError(
                        ErrorCode.CONFIRMATION_REQUIRED,
                        "The consequential action requires local confirmation",
                        details={"challenge": to_wire(challenge)},
                    )
                active.confirmations.consume(
                    request.confirmation_id,
                    session_id=active.session_id,
                    origin=observation.origin,
                    page_revision=request.expected_page_revision,
                    action_digest=action_digest,
                    idempotency_key=request.idempotency_key,
                    preview=assessment.preview,
                )
            elif request.confirmation_id is not None:
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "This action does not accept a confirmation identifier",
                )

            trace_started_at = datetime.now(timezone.utc).isoformat()
            trace_started_monotonic = time.monotonic()
            active.journal.mark_dispatched(request)
            try:
                result = await self._action_executor.execute(
                    request=request,
                    backend=active.backend,
                    observation=active.observation,
                    target_binding=target,
                    destination_binding=destination,
                    effective_risk=assessment.risk,
                )
            except Exception as exc:
                raise TermuinatorError(
                    ErrorCode.OUTCOME_UNKNOWN,
                    "The dispatched action did not produce a durable terminal result",
                    details={"action_id": request.action_id},
                ) from exc
            after_observation = active.observation.last_observation
            if after_observation is not None:
                self._apply_observation_handoff(active, after_observation)
            trace = TraceRecord(
                trace_id="trace_" + secrets.token_urlsafe(24),
                step_id="step_" + secrets.token_urlsafe(24),
                action_kind=request.kind.value,
                risk=assessment.risk,
                page_revision=request.expected_page_revision,
                permission=permission.value,
                verification_passed=any(
                    item.passed and item.causal for item in result.verification
                ),
                started_at=trace_started_at,
                duration_ms=min(
                    120_000,
                    max(0, int((time.monotonic() - trace_started_monotonic) * 1000)),
                ),
                diagnostics_id=result.diagnostics_id,
            )
            try:
                active.traces.append(
                    session_id=active.session_id,
                    record=trace,
                )
            except Exception as exc:
                raise TermuinatorError(
                    ErrorCode.OUTCOME_UNKNOWN,
                    "The action completed but its audit trace was not durable",
                    details={"action_id": request.action_id},
                ) from exc
            try:
                active.journal.record_terminal(request, result)
            except Exception as exc:
                raise TermuinatorError(
                    ErrorCode.OUTCOME_UNKNOWN,
                    "The action completed but its terminal result was not durable",
                    details={"action_id": request.action_id},
                ) from exc
            return result

    async def session_stop(self, session_id: str) -> SessionStopResult:
        async with self._mutex:
            active = self._require_session(session_id)
            stop_error: Exception | None = None
            try:
                await active.backend.stop()
            except Exception as exc:
                stop_error = exc

            active.permissions.clear_session(active.session_id)

            self._active = None
            lease_error: Exception | None = None
            try:
                self._session_lock.release()
            except Exception as exc:
                lease_error = exc
            if stop_error is not None:
                raise TermuinatorError(
                    ErrorCode.BACKEND_CRASHED,
                    f"Backend '{active.capabilities.backend.value}' failed to stop cleanly",
                    retryable=True,
                    details={"backend": active.capabilities.backend.value},
                ) from stop_error
            if lease_error is not None:
                raise TermuinatorError(
                    ErrorCode.INTERNAL_ERROR,
                    "Browser session lease failed to release cleanly",
                ) from lease_error
            return SessionStopResult(
                session_id=active.session_id,
                state=SessionState.STOPPED,
                stopped_at=datetime.now(timezone.utc).isoformat(),
            )

    def _status_result(self, active: _ActiveSession) -> SessionStatus:
        cached = active.backend.cached_status()
        confidential_takeover = active.state in {
            SessionState.USER_TAKEOVER_REQUIRED,
            SessionState.USER_TAKEOVER_ACTIVE,
        }
        freshness_ms = min(
            86_400_000,
            max(0, int((time.monotonic() - cached.updated_at_monotonic) * 1000)),
        )
        return SessionStatus(
            session_id=active.session_id,
            state=active.state,
            backend=cached.backend,
            running=cached.running,
            active_page_id=active.observation.page_id,
            active_tab_id=active.observation.tab_id,
            page_revision=active.observation.revision,
            url="" if confidential_takeover else cached.url,
            title="" if confidential_takeover else cached.title,
            ready_state="takeover" if confidential_takeover else cached.ready_state,
            freshness_ms=freshness_ms,
            capabilities=active.capabilities,
        )

    async def _backend_tabs(
        self,
        active: _ActiveSession,
        *,
        operation: str,
        backend_tab_id: str | None = None,
        url: str | None = None,
    ) -> BackendTabsResult:
        try:
            result = await active.backend.tabs(
                operation,
                backend_tab_id=backend_tab_id,
                url=url,
            )
        except TermuinatorError:
            raise
        except Exception as exc:
            raise TermuinatorError(
                ErrorCode.BACKEND_CRASHED,
                "Backend tab operation failed",
                retryable=True,
                details={"backend": active.capabilities.backend.value},
            ) from exc
        if not isinstance(result, BackendTabsResult):
            raise TermuinatorError(
                ErrorCode.INTERNAL_ERROR,
                "Backend returned an untyped tab result",
                details={"backend": active.capabilities.backend.value},
            )
        return result

    def _reconcile_tabs(
        self,
        active: _ActiveSession,
        *,
        operation: str,
        result: BackendTabsResult,
    ) -> TabsResult:
        by_backend_id = {
            state.backend_tab_id: state
            for state in active.tabs.values()
            if state.backend_tab_id is not None
        }
        unbound = tuple(
            state
            for state in active.tabs.values()
            if state.backend_tab_id is None
        )
        if unbound:
            if len(unbound) != 1 or operation != "list":
                raise TermuinatorError(
                    ErrorCode.INTERNAL_ERROR,
                    "Public and backend tab identity could not be synchronized",
                )
            unbound[0].backend_tab_id = result.active_backend_tab_id
            by_backend_id[result.active_backend_tab_id] = unbound[0]

        reconciled: dict[str, _TabState] = {}
        active_state: _TabState | None = None
        for backend_tab in result.tabs:
            state = by_backend_id.get(backend_tab.backend_tab_id)
            if state is None:
                observation = ObservationEngine(
                    session_id=active.session_id,
                    capability_revision=active.capabilities.revision,
                    default_viewport=active.default_viewport,
                )
                state = _TabState(
                    backend_tab_id=backend_tab.backend_tab_id,
                    observation=observation,
                    url=backend_tab.url,
                    title=backend_tab.title,
                )
            else:
                state.url = backend_tab.url
                state.title = backend_tab.title
            reconciled[state.observation.tab_id] = state
            if backend_tab.active:
                active_state = state

        if active_state is None:
            raise TermuinatorError(
                ErrorCode.INTERNAL_ERROR,
                "Backend tab inventory has no active tab",
            )
        active.tabs = reconciled
        active.observation = active_state.observation

        observation: Observation | None = None
        if result.active_snapshot is not None:
            previous = active_state.observation.last_observation
            observation = active_state.observation.capture(
                result.active_snapshot,
                document_changed=(
                    previous is not None
                    and previous.url != result.active_snapshot.url
                ),
            )
            self._apply_observation_handoff(active, observation)
            active_state.url = observation.url
            active_state.title = observation.title

        return TabsResult(
            operation=operation,
            tabs=tuple(
                Tab(
                    tab_id=state.observation.tab_id,
                    page_id=state.observation.page_id,
                    url=state.url,
                    title=state.title,
                    active=state is active_state,
                    page_revision=state.observation.revision,
                )
                for state in active.tabs.values()
            ),
            active_tab_id=active_state.observation.tab_id,
            observation=observation,
        )

    async def _backend_downloads(
        self,
        active: _ActiveSession,
        *,
        operation: str,
        backend_download_id: str | None = None,
    ) -> BackendDownloadsResult:
        try:
            result = await active.backend.downloads(
                operation,
                backend_download_id=backend_download_id,
            )
        except TermuinatorError:
            raise
        except Exception as exc:
            raise TermuinatorError(
                ErrorCode.BACKEND_CRASHED,
                "Backend download operation failed",
                retryable=True,
                details={"backend": active.capabilities.backend.value},
            ) from exc
        if not isinstance(result, BackendDownloadsResult):
            raise TermuinatorError(
                ErrorCode.INTERNAL_ERROR,
                "Backend returned an untyped download result",
                details={"backend": active.capabilities.backend.value},
            )
        return result

    def _reconcile_downloads(
        self,
        active: _ActiveSession,
        *,
        operation: str,
        result: BackendDownloadsResult,
        expected_backend_download_id: str | None,
    ) -> DownloadsResult:
        if operation == "wait" and (
            len(result.downloads) != 1
            or result.downloads[0].backend_download_id
            != expected_backend_download_id
        ):
            raise TermuinatorError(
                ErrorCode.INTERNAL_ERROR,
                "Backend download wait returned the wrong private target",
                details={"backend": active.capabilities.backend.value},
            )

        by_backend_id = {
            state.backend_download_id: state
            for state in active.downloads.values()
        }
        public_downloads: list[Download] = []
        for snapshot in result.downloads:
            state = by_backend_id.get(snapshot.backend_download_id)
            if state is None:
                state = _DownloadState(
                    backend_download_id=snapshot.backend_download_id,
                    download_id="download_" + secrets.token_urlsafe(24),
                )
                active.downloads[state.download_id] = state
                by_backend_id[snapshot.backend_download_id] = state
            self._validate_download_transition(state.latest, snapshot)

            artifact_uri = (
                state.latest.artifact_uri if state.latest is not None else None
            )
            mime_type = snapshot.mime_type
            size_bytes = snapshot.size_bytes
            if snapshot.state == "completed":
                assert snapshot.data is not None
                if artifact_uri is None:
                    artifact = active.artifacts.put(
                        session_id=active.session_id,
                        data=snapshot.data,
                        mime_type=mime_type or "application/octet-stream",
                    )
                    artifact_uri = artifact.uri
                    mime_type = artifact.mime_type
                    size_bytes = artifact.size_bytes
                elif state.latest is not None:
                    mime_type = state.latest.mime_type
                    size_bytes = state.latest.size_bytes

            public = Download(
                download_id=state.download_id,
                state=snapshot.state,
                filename=snapshot.filename,
                mime_type=mime_type,
                size_bytes=size_bytes,
                artifact_uri=artifact_uri,
                reason_code=snapshot.reason_code,
            )
            state.latest = public
            public_downloads.append(public)
        return DownloadsResult(
            operation=operation,
            downloads=tuple(public_downloads),
        )

    @staticmethod
    def _prepare_devtools_query(
        active: _ActiveSession,
        *,
        query: str,
        parameters: Mapping[str, object],
        expected_revision: PageRevision,
    ) -> BackendDevtoolsQuery:
        if (
            not isinstance(query, str)
            or not isinstance(parameters, Mapping)
            or any(not isinstance(key, str) for key in parameters)
        ):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Developer query arguments are invalid",
            )
        values = dict(parameters)
        backend_node_id: str | None = None
        if query == "console":
            valid = set(values) <= {"level", "limit"}
            if "level" in values and values["level"] not in {
                "debug",
                "info",
                "warning",
                "error",
            }:
                valid = False
            if "limit" in values and not BrowserService._bounded_int_value(
                values["limit"], 1, 1_000
            ):
                valid = False
        elif query == "network":
            valid = set(values) <= {"url_filter", "limit"}
            if "url_filter" in values and (
                not isinstance(values["url_filter"], str)
                or len(values["url_filter"]) > 2_048
            ):
                valid = False
            if "limit" in values and not BrowserService._bounded_int_value(
                values["limit"], 1, 1_000
            ):
                valid = False
        elif query == "dom":
            valid = set(values) <= {"target_ref", "max_depth"}
            target_ref = values.pop("target_ref", None)
            if target_ref is not None:
                if not isinstance(target_ref, str):
                    valid = False
                else:
                    backend_node_id = active.observation.resolve_ref(
                        ref=target_ref,
                        expected_revision=expected_revision,
                        risk=RiskClass.DEVELOPER,
                    ).backend_node_id
            if "max_depth" in values and not BrowserService._bounded_int_value(
                values["max_depth"], 0, 32
            ):
                valid = False
        elif query == "style":
            valid = set(values) <= {"target_ref", "properties"}
            target_ref = values.pop("target_ref", None)
            properties = values.get("properties", ())
            if not isinstance(target_ref, str):
                valid = False
            else:
                backend_node_id = active.observation.resolve_ref(
                    ref=target_ref,
                    expected_revision=expected_revision,
                    risk=RiskClass.DEVELOPER,
                ).backend_node_id
            if (
                not isinstance(properties, (list, tuple))
                or len(properties) > 128
                or not all(
                    isinstance(item, str) and 1 <= len(item) <= 128
                    for item in properties
                )
                or len(properties) != len(set(properties))
            ):
                valid = False
        elif query == "performance":
            valid = (
                set(values) == {"scope"}
                and values.get("scope")
                in {"navigation", "resources", "summary"}
            )
        else:
            valid = False
        if not valid:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Developer query arguments are invalid",
                details={
                    "capability": "browser_devtools",
                    "query": query if isinstance(query, str) else "unknown",
                },
            )
        try:
            return BackendDevtoolsQuery(
                query=query,
                parameters=values,
                backend_node_id=backend_node_id,
            )
        except (TypeError, ValueError) as exc:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Developer query arguments are invalid",
                details={"capability": "browser_devtools", "query": query},
            ) from exc

    @staticmethod
    def _normalize_devtools_result(
        active: _ActiveSession,
        result: BackendDevtoolsResult,
    ) -> DevtoolsResult:
        entries: list[object] = []
        for item in result.entries:
            if isinstance(item, BackendConsoleEntry):
                entries.append(
                    ConsoleEntry(
                        level=item.level,
                        message=redact_sensitive_text(item.message),
                        timestamp=item.timestamp,
                    )
                )
            elif isinstance(item, BackendNetworkEntry):
                request_id = active.developer_request_ids.get(
                    item.backend_request_id
                )
                if request_id is None:
                    request_id = "request_" + secrets.token_urlsafe(24)
                    active.developer_request_ids[item.backend_request_id] = request_id
                entries.append(
                    NetworkEntry(
                        request_id=request_id,
                        method=item.method,
                        url=redact_url_metadata(item.url),
                        status=item.status,
                        resource_type=item.resource_type,
                        started_at=item.started_at,
                        duration_ms=item.duration_ms,
                    )
                )
            elif isinstance(item, BackendDomEntry):
                ref = active.observation.ref_for_backend_node(
                    item.backend_node_id
                )
                if ref is None:
                    raise TermuinatorError(
                        ErrorCode.INTERNAL_ERROR,
                        "Backend Developer DOM result was not previously observed",
                    )
                entries.append(
                    DomEntry(
                        ref=ref,
                        tag=item.tag,
                        role=item.role,
                        name=item.name,
                        text=item.text,
                        bounds=item.bounds,
                    )
                )
            elif isinstance(item, BackendStyleEntry):
                entries.append(StyleEntry(name=item.name, value=item.value))
            elif isinstance(item, BackendPerformanceEntry):
                entries.append(
                    PerformanceEntry(
                        name=item.name,
                        value=item.value,
                        unit=item.unit,
                    )
                )
            else:
                raise TermuinatorError(
                    ErrorCode.INTERNAL_ERROR,
                    "Backend Developer result contains an unknown entry",
                )
        return DevtoolsResult(
            query=result.query,
            entries=tuple(entries),
            truncated=result.truncated,
        )

    @staticmethod
    def _bounded_int_value(value: object, minimum: int, maximum: int) -> bool:
        return (
            not isinstance(value, bool)
            and isinstance(value, int)
            and minimum <= value <= maximum
        )

    def _require_origin_permission(
        self,
        active: _ActiveSession,
        *,
        url: str,
        quarantine: bool,
    ) -> None:
        policy = active.permissions.evaluate(
            url=url,
            session_id=active.session_id,
        )
        if policy in {
            PermissionPolicy.SESSION_ALLOW,
            PermissionPolicy.ALWAYS_ALLOW,
        }:
            return
        if quarantine:
            active.state = SessionState.USER_TAKEOVER_REQUIRED
        origin = canonical_origin(url)
        if policy is PermissionPolicy.BLOCK:
            raise TermuinatorError(
                ErrorCode.PERMISSION_DENIED,
                "Navigation origin is blocked",
                details={"origin": origin},
            )
        if policy is PermissionPolicy.ASK:
            challenge = self._pending_permission_challenge(active, origin)
            raise TermuinatorError(
                ErrorCode.PERMISSION_REQUIRED,
                "Navigation origin requires local permission",
                details={
                    "origin": origin,
                    "challenge": to_wire(challenge),
                },
            )
        raise TermuinatorError(
            ErrorCode.INTERNAL_ERROR,
            "Permission engine returned an invalid navigation policy",
        )

    @staticmethod
    def _pending_permission_challenge(
        active: _ActiveSession,
        origin: str,
    ) -> Challenge:
        existing = active.pending_permissions.get(origin)
        if existing is not None:
            return existing
        challenge = Challenge(
            challenge_id="permission_" + secrets.token_urlsafe(24),
            kind=ChallengeKind.PERMISSION,
            state=ChallengeState.PENDING,
            preview=f"Allow browser access to {origin}",
            expires_at=None,
        )
        active.pending_permissions[origin] = challenge
        return challenge

    @staticmethod
    def _apply_observation_handoff(
        active: _ActiveSession,
        observation: Observation,
    ) -> bool:
        handoff_required = bool(observation.challenges) or any(
            dialog.open for dialog in observation.dialogs
        )
        if handoff_required:
            active.state = SessionState.USER_TAKEOVER_REQUIRED
        return handoff_required

    @staticmethod
    def _validate_tab_request(
        *,
        operation: str,
        tab_id: str | None,
        url: str | None,
    ) -> None:
        if operation == "list":
            valid = tab_id is None and url is None
        elif operation == "open":
            valid = (
                tab_id is None
                and isinstance(url, str)
                and len(url) <= 8_192
                and re.fullmatch(r"https?://[^\s]+", url) is not None
            )
        elif operation in {"switch", "close"}:
            valid = (
                isinstance(tab_id, str)
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{7,127}", tab_id)
                is not None
                and url is None
            )
        else:
            valid = False
        if not valid:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Tab operation arguments are invalid",
            )

    @staticmethod
    def _validate_download_request(
        *,
        operation: str,
        download_id: str | None,
    ) -> None:
        if operation == "list":
            valid = download_id is None
        elif operation == "wait":
            valid = (
                isinstance(download_id, str)
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{7,127}", download_id)
                is not None
            )
        else:
            valid = False
        if not valid:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Download operation arguments are invalid",
            )

    @staticmethod
    def _validate_download_transition(
        previous: Download | None,
        current: BackendDownloadSnapshot,
    ) -> None:
        if previous is None:
            return
        allowed = {
            "started": {
                "started",
                "in_progress",
                "completed",
                "failed",
                "cancelled",
            },
            "in_progress": {
                "in_progress",
                "completed",
                "failed",
                "cancelled",
            },
            "completed": {"completed"},
            "failed": {"failed"},
            "cancelled": {"cancelled"},
        }
        if current.state not in allowed[previous.state]:
            raise TermuinatorError(
                ErrorCode.INTERNAL_ERROR,
                "Backend download lifecycle regressed",
            )
        if previous.state not in {"completed", "failed", "cancelled"}:
            return
        current_mime = current.mime_type
        current_size = current.size_bytes
        if current.state == "completed":
            assert current.data is not None
            current_mime = current_mime or "application/octet-stream"
            current_size = len(current.data)
        if (
            current.filename != previous.filename
            or current_mime != previous.mime_type
            or current_size != previous.size_bytes
            or current.reason_code != previous.reason_code
        ):
            raise TermuinatorError(
                ErrorCode.INTERNAL_ERROR,
                "Backend terminal download metadata changed",
            )
        if current.state == "completed":
            digest = hashlib.sha256(current.data).hexdigest()
            expected_uri = f"artifact://sha256/{digest}"
            if previous.artifact_uri != expected_uri:
                raise TermuinatorError(
                    ErrorCode.INTERNAL_ERROR,
                    "Backend terminal download bytes changed",
                )

    @staticmethod
    def _wait_elapsed_ms(started: float) -> int:
        return min(
            120_000,
            max(0, int((time.monotonic() - started) * 1_000)),
        )

    def _require_session(self, session_id: str) -> _ActiveSession:
        if self._active is None or self._active.session_id != session_id:
            raise TermuinatorError(
                ErrorCode.SESSION_NOT_FOUND,
                "Browser session was not found",
                details={"session_id": session_id},
            )
        return self._active

    @staticmethod
    def _require_remote_active(active: _ActiveSession) -> None:
        if active.state is not SessionState.ACTIVE:
            raise TermuinatorError(
                ErrorCode.SESSION_PAUSED,
                "The browser session requires local user takeover",
                details={"state": active.state.value},
            )

    @staticmethod
    def _resolve_action_bindings(
        active: _ActiveSession,
        request: ActionRequest,
    ) -> tuple[ElementBinding | None, ElementBinding | None]:
        target = (
            active.observation.resolve_ref(
                ref=request.target_ref,
                expected_revision=request.expected_page_revision,
                risk=request.risk,
            )
            if request.target_ref is not None
            else None
        )
        destination = (
            active.observation.resolve_ref(
                ref=request.parameters["destination_ref"],
                expected_revision=request.expected_page_revision,
                risk=request.risk,
            )
            if request.kind is ActionKind.DRAG
            else None
        )
        return target, destination

    @staticmethod
    def _parse_backend(backend: Backend | str) -> Backend:
        try:
            selected = Backend(backend)
        except (TypeError, ValueError) as exc:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Unknown browser backend",
                details={"backend": str(backend)},
            ) from exc
        if selected not in (Backend.CHROMIUM, Backend.FIREFOX):
            raise TermuinatorError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                f"Backend '{selected.value}' is not public",
                details={"backend": selected.value},
            )
        return selected

    def _project_digest(self, project_id: str) -> str:
        if (
            not isinstance(project_id, str)
            or not project_id.strip()
            or project_id != project_id.strip()
            or "\x00" in project_id
            or len(project_id) > 4096
        ):
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "project_id must be a non-empty canonical identifier",
            )
        digest = hashlib.sha256()
        digest.update(b"termuinator-owner-project-v1\x00")
        digest.update(self._owner_scope.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(project_id.encode("utf-8"))
        return digest.hexdigest()

    def _prepare_profile(self, project_digest: str, backend: Backend) -> Path:
        directories = (
            self._data_root,
            self._data_root / "projects",
            self._data_root / "projects" / project_digest,
            self._data_root / "projects" / project_digest / "profiles",
            self._data_root / "projects" / project_digest / "profiles" / backend.value,
            self._data_root
            / "projects"
            / project_digest
            / "profiles"
            / backend.value
            / self._profile_schema_version,
            self._data_root
            / "projects"
            / project_digest
            / "profiles"
            / backend.value
            / self._profile_schema_version
            / "profile",
        )
        for directory in directories:
            if directory.is_symlink():
                raise TermuinatorError(
                    ErrorCode.INVALID_REQUEST,
                    "Profile path contains a symbolic link",
                )
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory.chmod(0o700)

        profile_dir = directories[-1]
        projects_root = directories[1].resolve(strict=True)
        resolved_profile = profile_dir.resolve(strict=True)
        try:
            resolved_profile.relative_to(projects_root)
        except ValueError as exc:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Profile path escaped the project data root",
            ) from exc
        return profile_dir

    def _prepare_state_root(self) -> Path:
        state_root = self._data_root / "state"
        if state_root.is_symlink():
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Service state path cannot be a symbolic link",
            )
        state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        state_root.chmod(0o700)
        return state_root
