"""Typed browser backend boundary owned by the service layer."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Protocol, runtime_checkable

from ..contracts import (
    ActionKind,
    Backend,
    Bounds,
    CapabilitySet,
    ConsoleEntry,
    DomEntry,
    InteractiveElement,
    NetworkEntry,
    PerformanceEntry,
    StyleEntry,
    Viewport,
)


@dataclass(frozen=True)
class BackendArtifactPayload:
    """Raw backend bytes awaiting service-owned artifact publication."""

    data: bytes
    mime_type: str

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("backend artifact data must be non-empty bytes")
        if self.mime_type == "image/png":
            if not self.data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("PNG screenshot payload has an invalid signature")
        elif self.mime_type == "image/webp":
            if not (
                len(self.data) >= 12
                and self.data.startswith(b"RIFF")
                and self.data[8:12] == b"WEBP"
            ):
                raise ValueError("WebP screenshot payload has an invalid signature")
        else:
            raise ValueError("backend screenshot MIME type must be PNG or WebP")


@dataclass(frozen=True)
class BackendStatus:
    """A backend-maintained control-plane snapshot.

    Reading this object must not invoke page JavaScript or perform transport
    I/O. Backends refresh it after lifecycle, navigation, and action events.
    """

    backend: Backend
    running: bool
    url: str
    title: str
    ready_state: str
    updated_at_monotonic: float


@dataclass(frozen=True)
class BackendDialogSnapshot:
    """Private dialog handle and bounded browser-modal state."""

    backend_dialog_id: str
    kind: str
    message: str
    open: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.backend_dialog_id, str)
            or not 1 <= len(self.backend_dialog_id) <= 256
            or any(ord(character) < 32 for character in self.backend_dialog_id)
        ):
            raise ValueError("backend_dialog_id must be a bounded opaque handle")
        if self.kind not in {"alert", "confirm", "prompt", "beforeunload"}:
            raise ValueError("backend dialog kind is invalid")
        if not isinstance(self.message, str) or len(self.message) > 4_096:
            raise ValueError("backend dialog message exceeds 4096 characters")
        if not isinstance(self.open, bool):
            raise ValueError("backend dialog open must be a boolean")


@dataclass(frozen=True)
class BackendPageSnapshot:
    """Backend-owned page data before the service assigns public identity."""

    url: str
    title: str
    ready_state: str
    viewport: Viewport | None
    text: str = ""
    text_truncated: bool = False
    accessibility: tuple[Mapping[str, Any], ...] = ()
    interactive_elements: tuple["RawInteractiveElement", ...] = ()
    dialogs: tuple[BackendDialogSnapshot, ...] = ()
    screenshot: BackendArtifactPayload | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.url, str) or len(self.url) > 8_192:
            raise ValueError("backend snapshot URL exceeds 8192 characters")
        if not isinstance(self.title, str) or len(self.title) > 4_096:
            raise ValueError("backend snapshot title exceeds 4096 characters")
        if not isinstance(self.ready_state, str) or not self.ready_state:
            raise ValueError("backend snapshot ready_state must not be empty")
        if self.viewport is not None and not isinstance(self.viewport, Viewport):
            raise ValueError("backend snapshot viewport must be a Viewport or None")
        if not isinstance(self.text, str) or len(self.text) > 100_000:
            raise ValueError("backend snapshot text exceeds 100000 characters")
        if not isinstance(self.text_truncated, bool):
            raise ValueError("backend snapshot text_truncated must be a boolean")
        if len(self.accessibility) > 10_000 or any(
            not isinstance(item, Mapping) for item in self.accessibility
        ):
            raise ValueError("backend accessibility summary is invalid or unbounded")
        if len(self.interactive_elements) > 10_000 or any(
            not isinstance(item, RawInteractiveElement)
            for item in self.interactive_elements
        ):
            raise ValueError("backend interactive elements are invalid or unbounded")
        if len(self.dialogs) > 64 or any(
            not isinstance(item, BackendDialogSnapshot) for item in self.dialogs
        ):
            raise ValueError("backend dialogs are invalid or unbounded")
        if self.screenshot is not None and not isinstance(
            self.screenshot,
            BackendArtifactPayload,
        ):
            raise ValueError("backend screenshot must be a raw artifact payload or None")


@dataclass(frozen=True)
class BackendTabSnapshot:
    """Private tab handle and bounded metadata returned by one backend."""

    backend_tab_id: str
    url: str
    title: str
    active: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.backend_tab_id, str)
            or not 1 <= len(self.backend_tab_id) <= 256
            or any(ord(character) < 32 for character in self.backend_tab_id)
        ):
            raise ValueError("backend_tab_id must be a bounded opaque handle")
        if not isinstance(self.url, str) or len(self.url) > 8_192:
            raise ValueError("backend tab URL exceeds 8192 characters")
        if not isinstance(self.title, str) or len(self.title) > 2_048:
            raise ValueError("backend tab title exceeds 2048 characters")
        if not isinstance(self.active, bool):
            raise ValueError("backend tab active must be a boolean")


@dataclass(frozen=True)
class BackendTabsResult:
    """Typed private tab inventory plus an optional fresh active snapshot."""

    tabs: tuple[BackendTabSnapshot, ...]
    active_backend_tab_id: str | None
    active_snapshot: BackendPageSnapshot | None

    def __post_init__(self) -> None:
        if not self.tabs or len(self.tabs) > 64 or any(
            not isinstance(item, BackendTabSnapshot) for item in self.tabs
        ):
            raise ValueError("backend tabs must contain 1 to 64 typed entries")
        identifiers = tuple(item.backend_tab_id for item in self.tabs)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("backend tab handles must be unique")
        active = tuple(item for item in self.tabs if item.active)
        if (
            not isinstance(self.active_backend_tab_id, str)
            or len(active) != 1
            or active[0].backend_tab_id != self.active_backend_tab_id
        ):
            raise ValueError("backend result must identify exactly one active tab")
        if self.active_snapshot is not None and not isinstance(
            self.active_snapshot,
            BackendPageSnapshot,
        ):
            raise ValueError("active_snapshot must be BackendPageSnapshot or None")


@dataclass(frozen=True)
class BackendDownloadSnapshot:
    """Private download identity and optional completed payload bytes."""

    backend_download_id: str
    state: str
    filename: str
    mime_type: str | None = None
    size_bytes: int | None = None
    data: bytes | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.backend_download_id, str)
            or not 1 <= len(self.backend_download_id) <= 256
            or any(ord(character) < 32 for character in self.backend_download_id)
        ):
            raise ValueError("backend_download_id must be a bounded opaque handle")
        if self.state not in {
            "started",
            "in_progress",
            "completed",
            "failed",
            "cancelled",
        }:
            raise ValueError("backend download state is invalid")
        if (
            not isinstance(self.filename, str)
            or not 1 <= len(self.filename) <= 255
            or self.filename in {".", ".."}
            or any(character in self.filename for character in ("/", "\\", "\x00"))
        ):
            raise ValueError("backend download filename must be a safe basename")
        if self.mime_type is not None and (
            not isinstance(self.mime_type, str)
            or not 1 <= len(self.mime_type) <= 255
            or any(ord(character) < 32 for character in self.mime_type)
        ):
            raise ValueError("backend download MIME type is invalid")
        if self.size_bytes is not None and (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or not 0 <= self.size_bytes <= 1_099_511_627_776
        ):
            raise ValueError("backend download size is out of bounds")
        if self.reason_code is not None and (
            not isinstance(self.reason_code, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.reason_code) is None
        ):
            raise ValueError("backend download reason code is invalid")
        if self.state == "completed":
            if not isinstance(self.data, bytes) or not self.data:
                raise ValueError("completed backend download requires non-empty bytes")
            if self.size_bytes is not None and self.size_bytes != len(self.data):
                raise ValueError("completed backend download size does not match bytes")
        elif self.data is not None:
            raise ValueError("only a completed backend download may contain bytes")


@dataclass(frozen=True)
class BackendDownloadsResult:
    """Bounded typed private download inventory."""

    downloads: tuple[BackendDownloadSnapshot, ...]

    def __post_init__(self) -> None:
        if len(self.downloads) > 256 or any(
            not isinstance(item, BackendDownloadSnapshot) for item in self.downloads
        ):
            raise ValueError("backend downloads are invalid or unbounded")
        identifiers = tuple(item.backend_download_id for item in self.downloads)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("backend download handles must be unique")


@dataclass(frozen=True)
class BackendConsoleEntry:
    level: str
    message: str
    timestamp: str

    def __post_init__(self) -> None:
        ConsoleEntry(
            level=self.level,
            message=self.message,
            timestamp=self.timestamp,
        )


@dataclass(frozen=True)
class BackendNetworkEntry:
    backend_request_id: str
    method: str
    url: str
    status: int | None
    resource_type: str
    started_at: str
    duration_ms: float | None

    def __post_init__(self) -> None:
        _validate_private_handle(self.backend_request_id, "backend_request_id")
        NetworkEntry(
            request_id="request_abcdefgh",
            method=self.method,
            url=self.url,
            status=self.status,
            resource_type=self.resource_type,
            started_at=self.started_at,
            duration_ms=self.duration_ms,
        )


@dataclass(frozen=True)
class BackendDomEntry:
    backend_node_id: str
    tag: str
    role: str
    name: str
    text: str
    bounds: Bounds | None

    def __post_init__(self) -> None:
        _validate_private_handle(self.backend_node_id, "backend_node_id")
        DomEntry(
            ref="ref_abcdefghijklmnop",
            tag=self.tag,
            role=self.role,
            name=self.name,
            text=self.text,
            bounds=self.bounds,
        )


@dataclass(frozen=True)
class BackendStyleEntry:
    name: str
    value: str

    def __post_init__(self) -> None:
        StyleEntry(name=self.name, value=self.value)


@dataclass(frozen=True)
class BackendPerformanceEntry:
    name: str
    value: float
    unit: str

    def __post_init__(self) -> None:
        PerformanceEntry(name=self.name, value=self.value, unit=self.unit)


BackendDevtoolsEntry = (
    BackendConsoleEntry
    | BackendNetworkEntry
    | BackendDomEntry
    | BackendStyleEntry
    | BackendPerformanceEntry
)


@dataclass(frozen=True)
class BackendDevtoolsResult:
    query: str
    entries: tuple[BackendDevtoolsEntry, ...]
    truncated: bool

    def __post_init__(self) -> None:
        expected = {
            "console": (BackendConsoleEntry, 1_000),
            "network": (BackendNetworkEntry, 1_000),
            "dom": (BackendDomEntry, 2_048),
            "style": (BackendStyleEntry, 256),
            "performance": (BackendPerformanceEntry, 256),
        }.get(self.query)
        if expected is None:
            raise ValueError("backend Developer query is invalid")
        entry_type, maximum = expected
        if len(self.entries) > maximum or any(
            not isinstance(item, entry_type) for item in self.entries
        ):
            raise ValueError("backend Developer entries do not match the query")
        if not isinstance(self.truncated, bool):
            raise ValueError("backend Developer truncated flag must be boolean")


@dataclass(frozen=True)
class BackendDevtoolsQuery:
    query: str
    parameters: Mapping[str, Any]
    backend_node_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.parameters, Mapping) or any(
            not isinstance(key, str) for key in self.parameters
        ):
            raise ValueError("backend Developer parameters must be an object")
        values = dict(self.parameters)
        if self.query == "console":
            valid = set(values) <= {"level", "limit"} and self.backend_node_id is None
            if "level" in values and values["level"] not in {
                "debug",
                "info",
                "warning",
                "error",
            }:
                valid = False
            if "limit" in values and not _bounded_integer(values["limit"], 1, 1_000):
                valid = False
        elif self.query == "network":
            valid = set(values) <= {"url_filter", "limit"} and self.backend_node_id is None
            if "url_filter" in values and (
                not isinstance(values["url_filter"], str)
                or len(values["url_filter"]) > 2_048
            ):
                valid = False
            if "limit" in values and not _bounded_integer(values["limit"], 1, 1_000):
                valid = False
        elif self.query == "dom":
            valid = set(values) <= {"max_depth"}
            if "max_depth" in values and not _bounded_integer(values["max_depth"], 0, 32):
                valid = False
        elif self.query == "style":
            properties = values.get("properties", ())
            valid = (
                set(values) <= {"properties"}
                and self.backend_node_id is not None
                and isinstance(properties, (list, tuple))
                and len(properties) <= 128
                and all(
                    isinstance(item, str) and 1 <= len(item) <= 128
                    for item in properties
                )
                and len(properties) == len(set(properties))
            )
        elif self.query == "performance":
            valid = (
                set(values) == {"scope"}
                and values.get("scope") in {"navigation", "resources", "summary"}
                and self.backend_node_id is None
            )
        else:
            valid = False
        if self.backend_node_id is not None:
            try:
                _validate_private_handle(self.backend_node_id, "backend_node_id")
            except ValueError:
                valid = False
        if not valid:
            raise ValueError("backend Developer query arguments are invalid")


@dataclass(frozen=True)
class RawInteractiveElement:
    """Backend handle and normalized semantics before public ref issuance."""

    backend_node_id: str
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
        if (
            not isinstance(self.backend_node_id, str)
            or not 1 <= len(self.backend_node_id) <= 256
            or any(ord(character) < 32 for character in self.backend_node_id)
        ):
            raise ValueError("backend_node_id must be a bounded opaque handle")
        InteractiveElement(
            ref="ref_" + "a" * 16,
            role=self.role,
            accessible_name=self.accessible_name,
            text=self.text,
            tag=self.tag,
            type=self.type,
            bounds=self.bounds,
            visible=self.visible,
            enabled=self.enabled,
            editable=self.editable,
            checked=self.checked,
            frame_path=self.frame_path,
            shadow_path=self.shadow_path,
        )

    def semantic_fingerprint(self) -> str:
        payload = json.dumps(
            {
                "role": self.role,
                "accessible_name": self.accessible_name,
                "tag": self.tag,
                "type": self.type,
                "frame_path": self.frame_path,
                "shadow_path": self.shadow_path,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_public(self, ref: str) -> InteractiveElement:
        return InteractiveElement(
            ref=ref,
            role=self.role,
            accessible_name=self.accessible_name,
            text=self.text,
            tag=self.tag,
            type=self.type,
            bounds=self.bounds,
            visible=self.visible,
            enabled=self.enabled,
            editable=self.editable,
            checked=self.checked,
            frame_path=self.frame_path,
            shadow_path=self.shadow_path,
        )


@dataclass(frozen=True)
class BackendAction:
    """Resolved private-handle action sent to one backend."""

    kind: ActionKind
    backend_node_id: str | None
    destination_backend_node_id: str | None
    parameters: Mapping[str, Any]
    timeout_ms: int

    def __post_init__(self) -> None:
        target_kinds = {
            ActionKind.CLICK,
            ActionKind.TYPE,
            ActionKind.SELECT,
            ActionKind.CHECK,
            ActionKind.HOVER,
            ActionKind.DRAG,
        }
        if self.kind in target_kinds and not self.backend_node_id:
            raise ValueError("target action requires a private backend node handle")
        if self.kind is ActionKind.DRAG and not self.destination_backend_node_id:
            raise ValueError("drag requires a private destination node handle")
        if self.kind is not ActionKind.DRAG and self.destination_backend_node_id is not None:
            raise ValueError("only drag accepts a destination node handle")
        for handle in (self.backend_node_id, self.destination_backend_node_id):
            if handle is not None and not 1 <= len(handle) <= 256:
                raise ValueError("backend node handle exceeds 256 characters")
        if not 1 <= self.timeout_ms <= 120_000:
            raise ValueError("backend action timeout is out of bounds")


@dataclass(frozen=True)
class BackendActionEvidence:
    """Closed raw before/after evidence; it does not declare public success."""

    target_event_dispatched: bool = False
    before_url: str | None = None
    after_url: str | None = None
    before_value: str | None = None
    after_value: str | None = None
    before_checked: bool | None = None
    after_checked: bool | None = None
    before_selected: str | None = None
    after_selected: str | None = None
    before_scroll: tuple[float, float] | None = None
    after_scroll: tuple[float, float] | None = None
    before_visible: bool | None = None
    after_visible: bool | None = None
    before_hovered: bool | None = None
    after_hovered: bool | None = None
    dialog_opened: bool = False
    download: Mapping[str, Any] | None = None
    source_moved: bool = False
    target_changed: bool = False
    dom_changed: bool = False

    def __post_init__(self) -> None:
        for value in (
            self.target_event_dispatched,
            self.dialog_opened,
            self.source_moved,
            self.target_changed,
            self.dom_changed,
        ):
            if not isinstance(value, bool):
                raise ValueError("backend evidence flags must be booleans")
        for value in (
            self.before_url,
            self.after_url,
            self.before_value,
            self.after_value,
            self.before_selected,
            self.after_selected,
        ):
            if value is not None and (not isinstance(value, str) or len(value) > 100_000):
                raise ValueError("backend string evidence is invalid or unbounded")
        for value in (
            self.before_checked,
            self.after_checked,
            self.before_visible,
            self.after_visible,
            self.before_hovered,
            self.after_hovered,
        ):
            if value is not None and not isinstance(value, bool):
                raise ValueError("backend state evidence must be boolean or None")
        for value in (self.before_scroll, self.after_scroll):
            if value is not None and (
                len(value) != 2
                or any(
                    isinstance(item, bool) or not isinstance(item, (int, float))
                    for item in value
                )
            ):
                raise ValueError("backend scroll evidence must be an x/y pair")
        if self.download is not None and not isinstance(self.download, Mapping):
            raise ValueError("backend download evidence must be a mapping or None")


@dataclass(frozen=True)
class BackendActionOutcome:
    """Backend dispatch output awaiting service-owned verification."""

    executed_method: str
    snapshot: BackendPageSnapshot
    evidence: BackendActionEvidence
    document_changed: bool = False
    diagnostics_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.executed_method, str) or not 1 <= len(self.executed_method) <= 128:
            raise ValueError("executed_method must contain 1 to 128 characters")
        if not isinstance(self.snapshot, BackendPageSnapshot):
            raise ValueError("backend outcome requires a page snapshot")
        if not isinstance(self.evidence, BackendActionEvidence):
            raise ValueError("backend outcome requires typed evidence")
        if not isinstance(self.document_changed, bool):
            raise ValueError("document_changed must be a boolean")
        if self.document_changed and self.evidence.dom_changed:
            raise ValueError("document and DOM change flags are mutually exclusive")


@runtime_checkable
class BrowserBackend(Protocol):
    """Backend operations available to the browser orchestrator."""

    backend: Backend

    async def start(
        self, profile_dir: Path, viewport: Viewport | None
    ) -> CapabilitySet:
        """Start the requested backend without automatic fallback."""

    async def stop(self) -> None:
        """Stop the browser and release backend resources."""

    def cached_status(self) -> BackendStatus:
        """Return the latest in-memory control-plane status."""

    async def navigate(
        self, operation: str, url: str | None, timeout_ms: int
    ) -> BackendPageSnapshot:
        """Navigate and return backend-owned page data."""

    async def observe(
        self,
        *,
        include_screenshot: bool,
        include_accessibility: bool,
        text_limit: int,
    ) -> BackendPageSnapshot:
        """Read backend-owned page data for service normalization."""

    async def act(self, action: BackendAction) -> BackendActionOutcome:
        """Dispatch one resolved private-handle action and return raw evidence."""

    async def wait(
        self, condition: Mapping[str, Any], timeout_ms: int
    ) -> Mapping[str, Any]:
        """Wait for a structured condition."""

    async def tabs(
        self,
        operation: str,
        *,
        backend_tab_id: str | None = None,
        url: str | None = None,
    ) -> BackendTabsResult:
        """Perform a typed operation using only private backend handles."""

    async def screenshot(
        self, mode: str, backend_node_id: str | None = None
    ) -> BackendArtifactPayload:
        """Capture raw bytes, optionally for a resolved private node handle."""

    async def downloads(
        self, operation: str, backend_download_id: str | None = None
    ) -> BackendDownloadsResult:
        """List or wait for downloads."""

    async def devtools(
        self, query: BackendDevtoolsQuery
    ) -> BackendDevtoolsResult:
        """Run an approved Developer-mode query."""


def _validate_private_handle(value: object, name: str) -> None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 256
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"{name} must be a bounded opaque handle")


def _bounded_integer(value: object, minimum: int, maximum: int) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int)
        and minimum <= value <= maximum
    )
