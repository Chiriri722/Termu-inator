"""Dependency-free wire contracts for the Termu-inator v1 runtime."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import Enum
import math
import re
from typing import Any, Mapping


class WireEnum(str, Enum):
    """String enum whose value is used directly on the wire."""

    def __str__(self) -> str:
        return self.value


class Backend(WireEnum):
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    FAKE = "fake"


class RiskClass(WireEnum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    DEVELOPER = "Developer"


class CapabilityStatus(WireEnum):
    SUPPORTED = "supported"
    EMULATED = "emulated"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    BROKEN = "broken"


class SessionState(WireEnum):
    STARTING = "starting"
    ACTIVE = "active"
    USER_TAKEOVER_REQUIRED = "user_takeover_required"
    USER_TAKEOVER_ACTIVE = "user_takeover_active"
    STOPPING = "stopping"
    STOPPED = "stopped"
    CRASHED = "crashed"


class PermissionPolicy(WireEnum):
    ASK = "ask"
    BLOCK = "block"
    SESSION_ALLOW = "session_allow"
    ALWAYS_ALLOW = "always_allow"


class ActionKind(WireEnum):
    CLICK = "click"
    TYPE = "type"
    KEY = "key"
    SCROLL = "scroll"
    SELECT = "select"
    CHECK = "check"
    HOVER = "hover"
    DRAG = "drag"


class ActionStatus(WireEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ChallengeKind(WireEnum):
    PERMISSION = "permission"
    CONFIRMATION = "confirmation"
    USER_TAKEOVER = "user_takeover"


class ChallengeState(WireEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class ErrorCode(WireEnum):
    INVALID_REQUEST = "invalid_request"
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_BUSY = "session_busy"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    PERMISSION_REQUIRED = "permission_required"
    PERMISSION_DENIED = "permission_denied"
    CONFIRMATION_REQUIRED = "confirmation_required"
    SESSION_PAUSED = "session_paused"
    OWNERSHIP_DENIED = "ownership_denied"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    OUTCOME_UNKNOWN = "outcome_unknown"
    STALE_OBSERVATION = "stale_observation"
    TARGET_NOT_FOUND = "target_not_found"
    TIMEOUT = "timeout"
    ACTION_FAILED = "action_failed"
    BACKEND_CRASHED = "backend_crashed"
    ARTIFACT_NOT_FOUND = "artifact_not_found"
    INTERNAL_ERROR = "internal_error"


ERROR_RETRYABLE: Mapping[ErrorCode, bool] = {
    ErrorCode.INVALID_REQUEST: False,
    ErrorCode.SESSION_NOT_FOUND: False,
    ErrorCode.SESSION_BUSY: True,
    ErrorCode.UNSUPPORTED_CAPABILITY: False,
    ErrorCode.PERMISSION_REQUIRED: False,
    ErrorCode.PERMISSION_DENIED: False,
    ErrorCode.CONFIRMATION_REQUIRED: False,
    ErrorCode.SESSION_PAUSED: False,
    ErrorCode.OWNERSHIP_DENIED: False,
    ErrorCode.IDEMPOTENCY_CONFLICT: False,
    ErrorCode.OUTCOME_UNKNOWN: False,
    ErrorCode.STALE_OBSERVATION: True,
    ErrorCode.TARGET_NOT_FOUND: True,
    ErrorCode.TIMEOUT: True,
    ErrorCode.ACTION_FAILED: False,
    ErrorCode.BACKEND_CRASHED: True,
    ErrorCode.ARTIFACT_NOT_FOUND: False,
    ErrorCode.INTERNAL_ERROR: False,
}


class RevisionDecision(WireEnum):
    VALID = "valid"
    REVALIDATE = "revalidate"
    STALE = "stale"


_EPOCH_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{7,127}$")
_REF_PATTERN = re.compile(r"^ref_[A-Za-z0-9_-]{16,}$")
_CAPABILITY_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_ARTIFACT_URI_PATTERN = re.compile(r"^artifact://sha256/[0-9a-f]{64}$")
_HTTP_URL_PATTERN = re.compile(r"^https?://[^\s]+$")
_VERIFICATION_KINDS = frozenset(
    {
        "target_dispatch",
        "url_change",
        "input_value",
        "checked_state",
        "selected_value",
        "scroll_position",
        "visibility",
        "dialog",
        "download",
        "dom_fingerprint",
    }
)


def _parse_wire_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO 8601 date-time") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed


@dataclass(frozen=True)
class PageRevision:
    document_epoch: str
    mutation_counter: int

    def __post_init__(self) -> None:
        if not _EPOCH_PATTERN.fullmatch(self.document_epoch):
            raise ValueError("document_epoch must be a 1-64 character opaque token")
        if self.mutation_counter < 0:
            raise ValueError("mutation_counter must be non-negative")

    def __str__(self) -> str:
        return f"{self.document_epoch}:{self.mutation_counter}"

    @classmethod
    def parse(cls, value: str) -> "PageRevision":
        try:
            epoch, counter = value.rsplit(":", 1)
            return cls(epoch, int(counter))
        except (TypeError, ValueError) as exc:
            raise ValueError("page revision must be '<document_epoch>:<counter>'") from exc


def classify_revision(
    expected: PageRevision,
    current: PageRevision,
    risk: RiskClass,
    *,
    fingerprint_matches: bool,
) -> RevisionDecision:
    """Apply the fail-closed ref/revision reuse contract."""

    if expected == current:
        return RevisionDecision.VALID
    if expected.document_epoch != current.document_epoch:
        return RevisionDecision.STALE
    if risk in (RiskClass.R0, RiskClass.R1) and fingerprint_matches:
        return RevisionDecision.REVALIDATE
    return RevisionDecision.STALE


DEFAULT_ACTION_RISK: Mapping[ActionKind, RiskClass] = {
    ActionKind.CLICK: RiskClass.R2,
    ActionKind.TYPE: RiskClass.R2,
    ActionKind.KEY: RiskClass.R1,
    ActionKind.SCROLL: RiskClass.R1,
    ActionKind.SELECT: RiskClass.R2,
    ActionKind.CHECK: RiskClass.R2,
    ActionKind.HOVER: RiskClass.R1,
    ActionKind.DRAG: RiskClass.R2,
}

TARGET_ACTIONS = {
    ActionKind.CLICK,
    ActionKind.TYPE,
    ActionKind.SELECT,
    ActionKind.CHECK,
    ActionKind.HOVER,
    ActionKind.DRAG,
}


@dataclass(frozen=True)
class Bounds:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.width, self.height)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in values
        ):
            raise ValueError("bounds must contain finite numbers")
        if self.width < 0 or self.height < 0:
            raise ValueError("bounds width and height must be non-negative")


@dataclass(frozen=True)
class Viewport:
    width: int
    height: int
    device_scale_factor: float = 1.0


@dataclass(frozen=True)
class InteractiveElement:
    ref: str
    role: str
    accessible_name: str = ""
    text: str = ""
    tag: str = ""
    type: str = ""
    bounds: Bounds | None = None
    visible: bool = True
    enabled: bool = True
    editable: bool = False
    checked: bool | None = None
    frame_path: tuple[str, ...] = ()
    shadow_path: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _REF_PATTERN.fullmatch(self.ref):
            raise ValueError("interactive element ref must be opaque")
        for name, value, maximum, allow_empty in (
            ("role", self.role, 128, False),
            ("accessible_name", self.accessible_name, 4_096, True),
            ("text", self.text, 16_384, True),
            ("tag", self.tag, 128, True),
            ("type", self.type, 128, True),
        ):
            if not isinstance(value, str) or len(value) > maximum or (
                not allow_empty and not value
            ):
                raise ValueError(f"interactive element {name} is invalid")
        if self.bounds is not None and not isinstance(self.bounds, Bounds):
            raise ValueError("interactive element bounds must be Bounds or None")
        if any(
            not isinstance(value, bool)
            for value in (self.visible, self.enabled, self.editable)
        ):
            raise ValueError("interactive element state flags must be booleans")
        if self.checked is not None and not isinstance(self.checked, bool):
            raise ValueError("interactive element checked must be boolean or None")
        for name, path in (
            ("frame_path", self.frame_path),
            ("shadow_path", self.shadow_path),
        ):
            if len(path) > 32 or any(
                not isinstance(item, str) or not 1 <= len(item) <= 256
                for item in path
            ):
                raise ValueError(f"interactive element {name} is invalid")


@dataclass(frozen=True)
class CapabilityLimit:
    name: str
    value: str | int | float | bool

    def __post_init__(self) -> None:
        if not _CAPABILITY_ID_PATTERN.fullmatch(self.name):
            raise ValueError("capability limit name must be a stable lowercase identifier")
        if not isinstance(self.value, (str, int, float, bool)):
            raise ValueError("capability limit value must be a JSON scalar")
        if isinstance(self.value, str) and len(self.value) > 256:
            raise ValueError("capability limit string value exceeds 256 characters")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("capability limit numeric value must be finite")


@dataclass(frozen=True)
class CapabilityRecord:
    capability_id: str
    status: CapabilityStatus
    last_probed_at: str
    reason_code: str | None = None
    limits: tuple[CapabilityLimit, ...] = ()
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _CAPABILITY_ID_PATTERN.fullmatch(self.capability_id):
            raise ValueError("capability_id must use the fixed lowercase vocabulary")
        _parse_wire_datetime(self.last_probed_at, "last_probed_at")
        if self.reason_code is not None and not _CAPABILITY_ID_PATTERN.fullmatch(
            self.reason_code
        ):
            raise ValueError("reason_code must be a stable lowercase identifier")


@dataclass(frozen=True)
class CapabilitySet:
    backend: Backend
    revision: str
    browser_version: str
    transport_version: str
    capabilities: tuple[CapabilityRecord, ...]

    def __post_init__(self) -> None:
        if not self.revision or not self.browser_version or not self.transport_version:
            raise ValueError("capability versions and revision must not be empty")
        identifiers = [item.capability_id for item in self.capabilities]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("capability identifiers must be unique")


@dataclass(frozen=True)
class SessionStatus:
    session_id: str
    state: SessionState
    backend: Backend
    running: bool
    active_page_id: str | None
    active_tab_id: str | None
    page_revision: PageRevision | None
    url: str
    title: str
    ready_state: str
    freshness_ms: int
    capabilities: CapabilitySet


@dataclass(frozen=True)
class SessionStartResult:
    session_id: str
    capabilities: CapabilitySet
    status: SessionStatus


@dataclass(frozen=True)
class SessionStopResult:
    session_id: str
    state: SessionState
    stopped_at: str


@dataclass(frozen=True)
class Dialog:
    dialog_id: str
    kind: str
    message: str
    open: bool

    def __post_init__(self) -> None:
        if not _ID_PATTERN.fullmatch(self.dialog_id):
            raise ValueError("dialog_id must be an opaque wire identifier")
        if self.kind not in {"alert", "confirm", "prompt", "beforeunload"}:
            raise ValueError("dialog kind is invalid")
        if not isinstance(self.message, str) or len(self.message) > 4_096:
            raise ValueError("dialog message exceeds 4096 characters")
        if not isinstance(self.open, bool):
            raise ValueError("dialog open must be a boolean")


@dataclass(frozen=True)
class Challenge:
    challenge_id: str
    kind: ChallengeKind
    state: ChallengeState
    preview: str
    expires_at: str | None

    def __post_init__(self) -> None:
        if not _ID_PATTERN.fullmatch(self.challenge_id):
            raise ValueError("challenge_id must be an opaque wire identifier")
        if not isinstance(self.kind, ChallengeKind):
            raise ValueError("challenge kind is invalid")
        if not isinstance(self.state, ChallengeState):
            raise ValueError("challenge state is invalid")
        if not isinstance(self.preview, str) or len(self.preview) > 4096:
            raise ValueError("challenge preview must not exceed 4096 characters")
        if self.expires_at is not None:
            _parse_wire_datetime(self.expires_at, "expires_at")


@dataclass(frozen=True)
class Download:
    download_id: str
    state: str
    filename: str
    mime_type: str | None
    size_bytes: int | None
    artifact_uri: str | None
    reason_code: str | None

    def __post_init__(self) -> None:
        if not _ID_PATTERN.fullmatch(self.download_id):
            raise ValueError("download_id must be an opaque wire identifier")
        if self.state not in {
            "started",
            "in_progress",
            "completed",
            "failed",
            "cancelled",
        }:
            raise ValueError("download state is invalid")
        if not isinstance(self.filename, str) or len(self.filename) > 255:
            raise ValueError("download filename must not exceed 255 characters")
        if self.mime_type is not None and (
            not isinstance(self.mime_type, str) or len(self.mime_type) > 255
        ):
            raise ValueError("download mime_type must not exceed 255 characters")
        if self.size_bytes is not None and (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or not 0 <= self.size_bytes <= 1_099_511_627_776
        ):
            raise ValueError("download size_bytes is out of bounds")
        if self.artifact_uri is not None and not _ARTIFACT_URI_PATTERN.fullmatch(
            self.artifact_uri
        ):
            raise ValueError("download artifact_uri is invalid")
        if self.reason_code is not None and not _CAPABILITY_ID_PATTERN.fullmatch(
            self.reason_code
        ):
            raise ValueError("download reason_code is invalid")


@dataclass(frozen=True)
class DownloadsResult:
    operation: str
    downloads: tuple[Download, ...]

    def __post_init__(self) -> None:
        if self.operation not in {"list", "wait"}:
            raise ValueError("download operation is invalid")
        if len(self.downloads) > 256 or any(
            not isinstance(item, Download) for item in self.downloads
        ):
            raise ValueError("downloads are invalid or unbounded")
        identifiers = tuple(item.download_id for item in self.downloads)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("download identifiers must be unique")
        if self.operation == "wait" and len(self.downloads) != 1:
            raise ValueError("download wait must return exactly one download")


@dataclass(frozen=True)
class ConsoleEntry:
    level: str
    message: str
    timestamp: str

    def __post_init__(self) -> None:
        if self.level not in {"debug", "info", "warning", "error"}:
            raise ValueError("console level is invalid")
        if not isinstance(self.message, str) or len(self.message) > 4_096:
            raise ValueError("console message exceeds 4096 characters")
        _parse_wire_datetime(self.timestamp, "timestamp")


@dataclass(frozen=True)
class NetworkEntry:
    request_id: str
    method: str
    url: str
    status: int | None
    resource_type: str
    started_at: str
    duration_ms: float | None

    def __post_init__(self) -> None:
        if not _ID_PATTERN.fullmatch(self.request_id):
            raise ValueError("request_id must be an opaque wire identifier")
        if not isinstance(self.method, str) or not 1 <= len(self.method) <= 16:
            raise ValueError("network method must contain 1 to 16 characters")
        if not isinstance(self.url, str) or len(self.url) > 8_192:
            raise ValueError("network URL exceeds 8192 characters")
        if self.status is not None and (
            isinstance(self.status, bool)
            or not isinstance(self.status, int)
            or not 100 <= self.status <= 599
        ):
            raise ValueError("network status is invalid")
        if not isinstance(self.resource_type, str) or len(self.resource_type) > 64:
            raise ValueError("network resource_type exceeds 64 characters")
        _parse_wire_datetime(self.started_at, "started_at")
        if self.duration_ms is not None and (
            isinstance(self.duration_ms, bool)
            or not isinstance(self.duration_ms, (int, float))
            or not math.isfinite(self.duration_ms)
            or self.duration_ms < 0
        ):
            raise ValueError("network duration_ms is invalid")


@dataclass(frozen=True)
class DomEntry:
    ref: str
    tag: str
    role: str
    name: str
    text: str
    bounds: Bounds | None

    def __post_init__(self) -> None:
        if not _REF_PATTERN.fullmatch(self.ref):
            raise ValueError("DOM ref must be an opaque observation ref")
        for field_name, maximum in (
            ("tag", 64),
            ("role", 128),
            ("name", 2_048),
            ("text", 4_096),
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or len(value) > maximum:
                raise ValueError(f"DOM {field_name} exceeds {maximum} characters")
        if self.bounds is not None and not isinstance(self.bounds, Bounds):
            raise ValueError("DOM bounds must be Bounds or None")


@dataclass(frozen=True)
class StyleEntry:
    name: str
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not 1 <= len(self.name) <= 128:
            raise ValueError("style name must contain 1 to 128 characters")
        if not isinstance(self.value, str) or len(self.value) > 2_048:
            raise ValueError("style value exceeds 2048 characters")


@dataclass(frozen=True)
class PerformanceEntry:
    name: str
    value: float
    unit: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not 1 <= len(self.name) <= 128:
            raise ValueError("performance name must contain 1 to 128 characters")
        if (
            isinstance(self.value, bool)
            or not isinstance(self.value, (int, float))
            or not math.isfinite(self.value)
        ):
            raise ValueError("performance value must be finite")
        if self.unit not in {"ms", "bytes", "count", "ratio"}:
            raise ValueError("performance unit is invalid")


DevtoolsEntry = (
    ConsoleEntry
    | NetworkEntry
    | DomEntry
    | StyleEntry
    | PerformanceEntry
)


@dataclass(frozen=True)
class DevtoolsResult:
    query: str
    entries: tuple[DevtoolsEntry, ...]
    truncated: bool

    def __post_init__(self) -> None:
        expected = {
            "console": (ConsoleEntry, 1_000),
            "network": (NetworkEntry, 1_000),
            "dom": (DomEntry, 2_048),
            "style": (StyleEntry, 256),
            "performance": (PerformanceEntry, 256),
        }.get(self.query)
        if expected is None:
            raise ValueError("Developer query is invalid")
        entry_type, maximum = expected
        if len(self.entries) > maximum or any(
            not isinstance(item, entry_type) for item in self.entries
        ):
            raise ValueError("Developer entries do not match the query")
        if not isinstance(self.truncated, bool):
            raise ValueError("Developer truncated flag must be a boolean")


@dataclass(frozen=True)
class Observation:
    session_id: str
    page_id: str
    tab_id: str
    sequence: int
    page_revision: PageRevision
    url: str
    origin: str
    title: str
    ready_state: str
    viewport: Viewport
    timestamp: str
    capability_revision: str
    text: str = ""
    text_truncated: bool = False
    accessibility: tuple[Mapping[str, Any], ...] = ()
    interactive_elements: tuple[InteractiveElement, ...] = ()
    dialogs: tuple[Dialog, ...] = ()
    challenges: tuple[Challenge, ...] = ()
    downloads_delta: tuple[Mapping[str, Any], ...] = ()
    screenshot_artifact_uri: str | None = None

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("observation sequence must be non-negative")
        if not self.capability_revision:
            raise ValueError("capability_revision must not be empty")
        if len(self.dialogs) > 64 or any(
            not isinstance(item, Dialog) for item in self.dialogs
        ):
            raise ValueError("observation dialogs are invalid or unbounded")
        if len(self.challenges) > 64 or any(
            not isinstance(item, Challenge) for item in self.challenges
        ):
            raise ValueError("observation challenges are invalid or unbounded")
        _parse_wire_datetime(self.timestamp, "timestamp")


@dataclass(frozen=True)
class WaitUrlCondition:
    kind: str
    url: str

    def __post_init__(self) -> None:
        if self.kind != "url":
            raise ValueError("URL wait kind must be url")
        if (
            not isinstance(self.url, str)
            or len(self.url) > 8_192
            or not _HTTP_URL_PATTERN.fullmatch(self.url)
        ):
            raise ValueError("wait URL must be a bounded HTTP(S) URL")


@dataclass(frozen=True)
class WaitTextCondition:
    kind: str
    text: str
    present: bool = True

    def __post_init__(self) -> None:
        if self.kind != "text":
            raise ValueError("text wait kind must be text")
        if not isinstance(self.text, str) or not 1 <= len(self.text) <= 4_096:
            raise ValueError("wait text must contain 1 to 4096 characters")
        if not isinstance(self.present, bool):
            raise ValueError("wait text present must be a boolean")


@dataclass(frozen=True)
class WaitRefStateCondition:
    kind: str
    target_ref: str
    state: str

    def __post_init__(self) -> None:
        if self.kind != "ref_state":
            raise ValueError("ref-state wait kind must be ref_state")
        if not _REF_PATTERN.fullmatch(self.target_ref):
            raise ValueError("wait target_ref must be an opaque observation ref")
        if self.state not in {"visible", "hidden", "enabled", "disabled"}:
            raise ValueError("wait ref state is invalid")


@dataclass(frozen=True)
class WaitNavigationCondition:
    kind: str
    from_revision: PageRevision

    def __post_init__(self) -> None:
        if self.kind != "navigation":
            raise ValueError("navigation wait kind must be navigation")
        if not isinstance(self.from_revision, PageRevision):
            raise ValueError("navigation wait requires a PageRevision")


@dataclass(frozen=True)
class WaitDownloadCondition:
    kind: str
    download_id: str

    def __post_init__(self) -> None:
        if self.kind != "download":
            raise ValueError("download wait kind must be download")
        if not _ID_PATTERN.fullmatch(self.download_id):
            raise ValueError("wait download_id must be an opaque wire identifier")


WaitCondition = (
    WaitUrlCondition
    | WaitTextCondition
    | WaitRefStateCondition
    | WaitNavigationCondition
    | WaitDownloadCondition
)


@dataclass(frozen=True)
class WaitResult:
    condition_kind: str
    satisfied: bool
    elapsed_ms: int
    observation: Observation | None
    download: Download | None

    def __post_init__(self) -> None:
        if self.condition_kind not in {
            "url",
            "text",
            "ref_state",
            "navigation",
            "download",
        }:
            raise ValueError("wait result condition_kind is invalid")
        if not isinstance(self.satisfied, bool):
            raise ValueError("wait result satisfied must be a boolean")
        if (
            isinstance(self.elapsed_ms, bool)
            or not isinstance(self.elapsed_ms, int)
            or not 0 <= self.elapsed_ms <= 120_000
        ):
            raise ValueError("wait result elapsed_ms is out of bounds")
        if self.observation is not None and not isinstance(
            self.observation,
            Observation,
        ):
            raise ValueError("wait result observation must be Observation or None")
        if self.download is not None and not isinstance(self.download, Download):
            raise ValueError("wait result download must be Download or None")
        if self.condition_kind != "download" and self.download is not None:
            raise ValueError("only a download wait may return a download")


@dataclass(frozen=True)
class Tab:
    tab_id: str
    page_id: str
    url: str
    title: str
    active: bool
    page_revision: PageRevision

    def __post_init__(self) -> None:
        for name in ("tab_id", "page_id"):
            if not _ID_PATTERN.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be an opaque wire identifier")
        if not isinstance(self.url, str) or len(self.url) > 8_192:
            raise ValueError("tab URL exceeds 8192 characters")
        if not isinstance(self.title, str) or len(self.title) > 2_048:
            raise ValueError("tab title exceeds 2048 characters")
        if not isinstance(self.active, bool):
            raise ValueError("tab active must be a boolean")
        if not isinstance(self.page_revision, PageRevision):
            raise ValueError("tab page_revision must be a PageRevision")


@dataclass(frozen=True)
class TabsResult:
    operation: str
    tabs: tuple[Tab, ...]
    active_tab_id: str | None
    observation: Observation | None

    def __post_init__(self) -> None:
        if self.operation not in {"list", "open", "switch", "close"}:
            raise ValueError("tab operation is invalid")
        if len(self.tabs) > 64 or any(
            not isinstance(item, Tab) for item in self.tabs
        ):
            raise ValueError("tabs are invalid or unbounded")
        tab_ids = tuple(item.tab_id for item in self.tabs)
        if len(tab_ids) != len(set(tab_ids)):
            raise ValueError("tab identifiers must be unique")
        active_tabs = tuple(item for item in self.tabs if item.active)
        if self.active_tab_id is None:
            if active_tabs:
                raise ValueError("tabs cannot be active without active_tab_id")
        elif (
            not _ID_PATTERN.fullmatch(self.active_tab_id)
            or len(active_tabs) != 1
            or active_tabs[0].tab_id != self.active_tab_id
        ):
            raise ValueError("active_tab_id must identify exactly one active tab")
        if self.observation is not None:
            if not isinstance(self.observation, Observation):
                raise ValueError("tab observation must be Observation or None")
            if self.active_tab_id is None:
                raise ValueError("tab observation requires an active tab")
            active = active_tabs[0]
            if (
                self.observation.tab_id != active.tab_id
                or self.observation.page_id != active.page_id
                or self.observation.page_revision != active.page_revision
            ):
                raise ValueError("tab observation must match the active tab identity")


@dataclass(frozen=True)
class ActionRequest:
    action_id: str
    idempotency_key: str
    session_id: str
    tab_id: str
    page_id: str
    expected_page_revision: PageRevision
    kind: ActionKind
    target_ref: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    timeout_ms: int = 30_000
    confirmation_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "action_id",
            "idempotency_key",
            "session_id",
            "tab_id",
            "page_id",
        ):
            if not _ID_PATTERN.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be an opaque wire identifier")
        if self.confirmation_id is not None and not _ID_PATTERN.fullmatch(
            self.confirmation_id
        ):
            raise ValueError("confirmation_id must be an opaque wire identifier")
        if self.kind in TARGET_ACTIONS and not self.target_ref:
            raise ValueError(f"target_ref is required for {self.kind.value}")
        if self.target_ref is not None and not _REF_PATTERN.fullmatch(self.target_ref):
            raise ValueError("target_ref must be an opaque observation ref")
        if not 1 <= self.timeout_ms <= 120_000:
            raise ValueError("timeout_ms must be between 1 and 120000")
        self._validate_parameters()

    def _validate_parameters(self) -> None:
        allowed: Mapping[ActionKind, set[str]] = {
            ActionKind.CLICK: {"button", "click_count"},
            ActionKind.TYPE: {"text", "clear"},
            ActionKind.KEY: {"key", "modifiers"},
            ActionKind.SCROLL: {"delta_x", "delta_y"},
            ActionKind.SELECT: {"value"},
            ActionKind.CHECK: {"checked"},
            ActionKind.HOVER: set(),
            ActionKind.DRAG: {"destination_ref"},
        }
        required: Mapping[ActionKind, set[str]] = {
            ActionKind.TYPE: {"text"},
            ActionKind.KEY: {"key"},
            ActionKind.SELECT: {"value"},
            ActionKind.CHECK: {"checked"},
            ActionKind.DRAG: {"destination_ref"},
        }
        keys = set(self.parameters)
        unknown = keys - allowed[self.kind]
        missing = required.get(self.kind, set()) - keys
        if unknown:
            raise ValueError(
                f"unsupported {self.kind.value} parameters: {', '.join(sorted(unknown))}"
            )
        if missing:
            raise ValueError(
                f"missing {self.kind.value} parameters: {', '.join(sorted(missing))}"
            )
        if self.kind is ActionKind.SCROLL:
            if not keys or not any(self.parameters.get(key, 0) for key in keys):
                raise ValueError("scroll requires a non-zero delta_x or delta_y")
        if self.kind is ActionKind.DRAG:
            destination = self.parameters["destination_ref"]
            if not isinstance(destination, str) or not _REF_PATTERN.fullmatch(destination):
                raise ValueError("drag destination_ref must be an opaque observation ref")

        if self.kind is ActionKind.CLICK:
            button = self.parameters.get("button", "left")
            click_count = self.parameters.get("click_count", 1)
            if not isinstance(button, str) or button not in {"left", "middle", "right"}:
                raise ValueError("click button must be left, middle, or right")
            if isinstance(click_count, bool) or not isinstance(click_count, int) or not 1 <= click_count <= 2:
                raise ValueError("click click_count must be 1 or 2")
        elif self.kind is ActionKind.TYPE:
            text = self.parameters["text"]
            clear = self.parameters.get("clear", False)
            if not isinstance(text, str) or len(text) > 100_000:
                raise ValueError("type text must be a string of at most 100000 characters")
            if not isinstance(clear, bool):
                raise ValueError("type clear must be boolean")
        elif self.kind is ActionKind.KEY:
            key = self.parameters["key"]
            modifiers = self.parameters.get("modifiers", ())
            if not isinstance(key, str) or not 1 <= len(key) <= 64:
                raise ValueError("key must be a non-empty string of at most 64 characters")
            if not isinstance(modifiers, (list, tuple)) or len(modifiers) > 4:
                raise ValueError("key modifiers must be an array of at most four values")
            if len(modifiers) != len(set(modifiers)) or any(
                modifier not in {"Alt", "Control", "Meta", "Shift"}
                for modifier in modifiers
            ):
                raise ValueError("key modifier is unsupported or duplicated")
        elif self.kind is ActionKind.SCROLL:
            for name in keys:
                value = self.parameters[name]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("scroll delta must be numeric")
                if not math.isfinite(value) or not -1_000_000 <= value <= 1_000_000:
                    raise ValueError("scroll delta must be finite and within bounds")
        elif self.kind is ActionKind.SELECT:
            value = self.parameters["value"]
            if not isinstance(value, str) or len(value) > 10_000:
                raise ValueError("select value must be a string of at most 10000 characters")
        elif self.kind is ActionKind.CHECK:
            if not isinstance(self.parameters["checked"], bool):
                raise ValueError("check checked must be boolean")

    @property
    def risk(self) -> RiskClass:
        """Return the server-owned minimum risk for this action kind.

        A later policy engine may raise this minimum after inspecting the
        target and effect, but caller input can never select a risk class.
        """

        return DEFAULT_ACTION_RISK[self.kind]


@dataclass(frozen=True)
class Verification:
    verification_id: str
    action_id: str
    kind: str
    target_ref: str | None
    passed: bool
    causal: bool
    expected_summary: str
    actual_summary: str
    observed_revision: PageRevision
    observed_at: str

    def __post_init__(self) -> None:
        for name in ("verification_id", "action_id"):
            if not _ID_PATTERN.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be an opaque wire identifier")
        if self.kind not in _VERIFICATION_KINDS:
            raise ValueError("verification kind is not in the closed vocabulary")
        if self.target_ref is not None and not _REF_PATTERN.fullmatch(self.target_ref):
            raise ValueError("verification target_ref must be an opaque observation ref")
        if len(self.expected_summary) > 2048 or len(self.actual_summary) > 2048:
            raise ValueError("verification summaries must not exceed 2048 characters")
        _parse_wire_datetime(self.observed_at, "observed_at")


@dataclass(frozen=True)
class ActionResult:
    status: ActionStatus
    before_revision: PageRevision
    after_revision: PageRevision
    executed_method: str
    verification: tuple[Verification, ...]
    changed_url: str | None = None
    changed_elements: tuple[str, ...] = ()
    download: Mapping[str, Any] | None = None
    artifact_uri: str | None = None
    diagnostics_id: str | None = None
    revalidated: bool = False

    def __post_init__(self) -> None:
        if not 1 <= len(self.verification) <= 32:
            raise ValueError("action result requires between 1 and 32 verification items")
        if self.status is ActionStatus.SUCCEEDED and not any(
            item.passed and item.causal for item in self.verification
        ):
            raise ValueError("succeeded action requires passed causal verification")
        if not 1 <= len(self.executed_method) <= 128:
            raise ValueError("executed_method must contain 1 to 128 characters")
        if self.changed_url is not None and len(self.changed_url) > 8192:
            raise ValueError("changed_url exceeds 8192 characters")
        if len(self.changed_elements) > 256 or any(
            not _REF_PATTERN.fullmatch(item) for item in self.changed_elements
        ):
            raise ValueError("changed_elements must contain at most 256 opaque refs")
        if self.artifact_uri is not None and not _ARTIFACT_URI_PATTERN.fullmatch(
            self.artifact_uri
        ):
            raise ValueError("artifact_uri must be a content-addressed artifact URI")
        if self.diagnostics_id is not None and not _ID_PATTERN.fullmatch(
            self.diagnostics_id
        ):
            raise ValueError("diagnostics_id must be an opaque wire identifier")


@dataclass(frozen=True)
class Artifact:
    uri: str
    sha256: str
    size_bytes: int
    mime_type: str
    created_at: str
    expires_at: str

    def __post_init__(self) -> None:
        if not self.uri.startswith("artifact://sha256/"):
            raise ValueError("artifact URI must use artifact://sha256/")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("artifact sha256 must contain 64 lowercase hex characters")
        if self.uri.removeprefix("artifact://sha256/") != self.sha256:
            raise ValueError("artifact URI digest must match sha256")
        if self.size_bytes < 0:
            raise ValueError("artifact size must be non-negative")
        if not self.mime_type:
            raise ValueError("artifact mime_type must not be empty")
        created = _parse_wire_datetime(self.created_at, "created_at")
        expires = _parse_wire_datetime(self.expires_at, "expires_at")
        if expires <= created:
            raise ValueError("artifact expires_at must be after created_at")


@dataclass(frozen=True)
class ArtifactChunk:
    uri: str
    offset: int
    next_offset: int
    eof: bool
    data_base64: str

    def __post_init__(self) -> None:
        if not _ARTIFACT_URI_PATTERN.fullmatch(self.uri):
            raise ValueError("artifact chunk URI must be content-addressed")
        if (
            isinstance(self.offset, bool)
            or not isinstance(self.offset, int)
            or self.offset < 0
            or isinstance(self.next_offset, bool)
            or not isinstance(self.next_offset, int)
            or self.next_offset < self.offset
        ):
            raise ValueError("artifact chunk offsets must be monotonic integers")
        if not isinstance(self.eof, bool):
            raise ValueError("artifact chunk eof must be a boolean")
        try:
            decoded = base64.b64decode(self.data_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("artifact chunk data must be valid base64") from exc
        if len(decoded) > 512 * 1024:
            raise ValueError("artifact chunk exceeds 512 KiB")
        if self.next_offset != self.offset + len(decoded):
            raise ValueError("artifact chunk next_offset must match decoded length")


@dataclass(frozen=True)
class TraceRecord:
    trace_id: str
    step_id: str
    action_kind: str
    risk: RiskClass
    page_revision: PageRevision
    permission: str
    verification_passed: bool
    started_at: str
    duration_ms: int
    diagnostics_id: str | None = None

    def __post_init__(self) -> None:
        if not _ID_PATTERN.fullmatch(self.trace_id):
            raise ValueError("trace_id must be an opaque wire identifier")
        if not _ID_PATTERN.fullmatch(self.step_id):
            raise ValueError("step_id must be an opaque wire identifier")
        if not 1 <= len(self.action_kind) <= 64:
            raise ValueError("action_kind must contain 1 to 64 characters")
        if not isinstance(self.risk, RiskClass):
            raise ValueError("risk must be a RiskClass")
        if not isinstance(self.page_revision, PageRevision):
            raise ValueError("page_revision must be a PageRevision")
        if not 1 <= len(self.permission) <= 64:
            raise ValueError("permission must contain 1 to 64 characters")
        if not isinstance(self.verification_passed, bool):
            raise ValueError("verification_passed must be a boolean")
        _parse_wire_datetime(self.started_at, "started_at")
        if (
            isinstance(self.duration_ms, bool)
            or not isinstance(self.duration_ms, int)
            or not 0 <= self.duration_ms <= 120_000
        ):
            raise ValueError("duration_ms must be between 0 and 120000")
        if self.diagnostics_id is not None and not _ID_PATTERN.fullmatch(
            self.diagnostics_id
        ):
            raise ValueError("diagnostics_id must be an opaque wire identifier")


@dataclass(frozen=True)
class TraceRecordsResult:
    operation: str
    traces: tuple[TraceRecord, ...]
    truncated: bool

    def __post_init__(self) -> None:
        if self.operation not in {"list", "get"}:
            raise ValueError("trace records operation must be list or get")
        if len(self.traces) > 1_000 or any(
            not isinstance(item, TraceRecord) for item in self.traces
        ):
            raise ValueError("trace records are invalid or unbounded")
        if not isinstance(self.truncated, bool):
            raise ValueError("trace records truncated must be a boolean")
        if self.operation == "get" and (
            len(self.traces) != 1 or self.truncated
        ):
            raise ValueError("trace get requires exactly one untruncated record")


@dataclass(frozen=True)
class TraceExportResult:
    operation: str
    artifact: Artifact

    def __post_init__(self) -> None:
        if self.operation != "export":
            raise ValueError("trace export operation must be export")
        if not isinstance(self.artifact, Artifact):
            raise ValueError("trace export artifact must be an Artifact")


TraceResult = TraceRecordsResult | TraceExportResult


@dataclass(frozen=True)
class PermissionDecision:
    project_id: str
    origin: str
    policy: PermissionPolicy
    created_at: str
    persistent: bool
    session_id: str | None = None
    expires_at: str | None = None

    def __post_init__(self) -> None:
        if not self.project_id or not self.origin:
            raise ValueError("permission project_id and origin must not be empty")
        created = _parse_wire_datetime(self.created_at, "created_at")
        if self.policy is PermissionPolicy.ASK:
            raise ValueError("ask is derived state, not a permission decision")
        if self.policy is PermissionPolicy.SESSION_ALLOW:
            if not self.session_id:
                raise ValueError("session_allow requires session_id")
            if self.persistent:
                raise ValueError("session_allow is memory-only")
            if self.expires_at is not None:
                raise ValueError("session_allow expires with its session")
        else:
            if not self.persistent:
                raise ValueError("block and always_allow are persistent decisions")
            if self.session_id is not None:
                raise ValueError("persistent decisions cannot bind session_id")
        if self.expires_at is not None:
            expires = _parse_wire_datetime(self.expires_at, "expires_at")
            if expires <= created:
                raise ValueError("permission expires_at must be after created_at")


@dataclass(frozen=True)
class PermissionsResult:
    operation: str
    decisions: tuple[PermissionDecision, ...]
    challenge: Challenge | None

    def __post_init__(self) -> None:
        if self.operation not in {"list", "status"}:
            raise ValueError("permission operation must be list or status")
        if len(self.decisions) > 1024 or any(
            not isinstance(item, PermissionDecision) for item in self.decisions
        ):
            raise ValueError("permission decisions are invalid or unbounded")
        if self.challenge is not None and not isinstance(self.challenge, Challenge):
            raise ValueError("permission challenge must be Challenge or None")
        if self.operation == "list" and self.challenge is not None:
            raise ValueError("permission list cannot include a challenge")
        if self.operation == "status" and (
            self.decisions or self.challenge is None
        ):
            raise ValueError(
                "permission status requires one challenge and no decisions"
            )


@dataclass(frozen=True)
class ErrorEnvelope:
    code: ErrorCode
    message: str
    retryable: bool
    details: Mapping[str, Any] = field(default_factory=dict)
    diagnostics_id: str | None = None

    def __post_init__(self) -> None:
        if not self.message:
            raise ValueError("error message must not be empty")
        if self.retryable is not ERROR_RETRYABLE[self.code]:
            raise ValueError("retryable must be derived from the error code")


def to_wire(value: Any) -> Any:
    """Convert contract values to dependency-free JSON-compatible values."""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, PageRevision):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {item.name: to_wire(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): to_wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_wire(item) for item in value]
    return value
