"""Strict JSON Schema sources for the compact Termu-inator v1 contract."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .contracts import ERROR_RETRYABLE, ActionKind, ErrorCode


SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
CONTRACT_ID = (
    "https://github.com/Chiriri722/Termu-inator/schemas/v1/contracts.schema.json"
)
MANIFEST_ID = (
    "https://github.com/Chiriri722/Termu-inator/schemas/v1/tool-manifest.json"
)
MANIFEST_SCHEMA_ID = (
    "https://github.com/Chiriri722/Termu-inator/schemas/v1/"
    "tool-manifest.schema.json"
)

PUBLIC_TOOL_NAMES = (
    "browser_session_start",
    "browser_session_status",
    "browser_session_stop",
    "browser_navigate",
    "browser_observe",
    "browser_act",
    "browser_wait",
    "browser_tabs",
    "browser_screenshot",
    "browser_downloads",
    "browser_artifact_read",
    "browser_permissions",
    "browser_devtools",
    "browser_trace",
)


def _object(
    properties: Mapping[str, Any], required: tuple[str, ...] = ()
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "object",
        "properties": dict(properties),
        "additionalProperties": False,
    }
    if required:
        result["required"] = list(required)
    return result


def _union(*branches: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "oneOf": list(branches)}


def _string_enum(*values: str, default: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "string", "enum": list(values)}
    if default is not None:
        result["default"] = default
    return result


def _bounded_string(max_length: int, *, min_length: int = 0) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "string", "maxLength": max_length}
    if min_length:
        result["minLength"] = min_length
    return result


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"oneOf": [schema, {"type": "null"}]}


def _local_ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/$defs/{name}"}


def _external_ref(name: str) -> dict[str, str]:
    return {"$ref": f"contracts.schema.json#/$defs/{name}"}


ID_SCHEMA = {
    "type": "string",
    "pattern": "^[A-Za-z][A-Za-z0-9_-]{7,127}$",
    "maxLength": 128,
}
REF_SCHEMA = {
    "type": "string",
    "pattern": "^ref_[A-Za-z0-9_-]{16,}$",
    "maxLength": 160,
}
ARTIFACT_URI_SCHEMA = {
    "type": "string",
    "pattern": "^artifact://sha256/[0-9a-f]{64}$",
}
HTTP_URL_SCHEMA = {
    "type": "string",
    "format": "uri",
    "pattern": "^https?://[^\\s]+$",
    "maxLength": 8192,
}
ORIGIN_SCHEMA = {
    "type": "string",
    "pattern": "^https?://[^/\\s]+$",
    "maxLength": 2048,
}
DATE_TIME_SCHEMA = {"type": "string", "format": "date-time"}
PAGE_REVISION_SCHEMA = {
    "type": "string",
    "pattern": "^[A-Za-z0-9_-]{1,64}:[0-9]+$",
}


def _error_variant(code: ErrorCode, retryable: bool) -> dict[str, Any]:
    detail_value = _nullable(_bounded_string(512))
    return _object(
        {
            "code": _string_enum(code.value),
            "message": _bounded_string(500, min_length=1),
            "retryable": {"type": "boolean", "const": retryable},
            "details": _object(
                {
                    "backend": detail_value,
                    "session_id": detail_value,
                    "capability": detail_value,
                    "challenge_id": detail_value,
                    "owner_scope": detail_value,
                    "expected_revision": detail_value,
                    "actual_revision": detail_value,
                    "reason_code": detail_value,
                }
            ),
            "diagnostics_id": _nullable(ID_SCHEMA),
        },
        ("code", "message", "retryable", "details", "diagnostics_id"),
    )


ERROR_ENVELOPE_SCHEMA = _union(
    *[
        _error_variant(code, ERROR_RETRYABLE[code])
        for code in ErrorCode
    ]
)

CAPABILITY_LIMIT_SCHEMA = _object(
    {
        "name": {
            "type": "string",
            "pattern": "^[a-z][a-z0-9_.-]{0,63}$",
        },
        "value": {
            "oneOf": [
                {"type": "string", "maxLength": 256},
                {"type": "number"},
                {"type": "boolean"},
            ]
        },
    },
    ("name", "value"),
)

CAPABILITY_RECORD_SCHEMA = _object(
    {
        "capability_id": {
            "type": "string",
            "pattern": "^[a-z][a-z0-9_.-]{0,63}$",
        },
        "status": _string_enum(
            "supported", "emulated", "partial", "unsupported", "broken"
        ),
        "reason_code": _nullable(
            {
                "type": "string",
                "pattern": "^[a-z][a-z0-9_.-]{0,63}$",
            }
        ),
        "limits": {
            "type": "array",
            "items": _local_ref("CapabilityLimit"),
            "maxItems": 32,
        },
        "dependencies": {
            "type": "array",
            "items": _bounded_string(128, min_length=1),
            "maxItems": 32,
            "uniqueItems": True,
        },
        "last_probed_at": DATE_TIME_SCHEMA,
    },
    (
        "capability_id",
        "status",
        "reason_code",
        "limits",
        "dependencies",
        "last_probed_at",
    ),
)

CAPABILITY_SET_SCHEMA = _object(
    {
        "backend": _string_enum("chromium", "firefox"),
        "revision": _bounded_string(128, min_length=1),
        "browser_version": _bounded_string(128, min_length=1),
        "transport_version": _bounded_string(128, min_length=1),
        "capabilities": {
            "type": "array",
            "items": _local_ref("CapabilityRecord"),
            "maxItems": 128,
        },
    },
    (
        "backend",
        "revision",
        "browser_version",
        "transport_version",
        "capabilities",
    ),
)

BOUNDS_SCHEMA = _object(
    {
        "x": {"type": "number"},
        "y": {"type": "number"},
        "width": {"type": "number", "minimum": 0},
        "height": {"type": "number", "minimum": 0},
    },
    ("x", "y", "width", "height"),
)

VIEWPORT_SCHEMA = _object(
    {
        "width": {"type": "integer", "minimum": 1, "maximum": 16384},
        "height": {"type": "integer", "minimum": 1, "maximum": 16384},
        "device_scale_factor": {
            "type": "number",
            "exclusiveMinimum": 0,
            "maximum": 8,
        },
    },
    ("width", "height", "device_scale_factor"),
)

ACCESSIBILITY_NODE_SCHEMA = _object(
    {
        "ref": _nullable(REF_SCHEMA),
        "role": _bounded_string(128),
        "name": _bounded_string(2048),
        "text": _bounded_string(4096),
        "depth": {"type": "integer", "minimum": 0, "maximum": 128},
    },
    ("ref", "role", "name", "text", "depth"),
)

INTERACTIVE_ELEMENT_SCHEMA = _object(
    {
        "ref": REF_SCHEMA,
        "role": _bounded_string(128),
        "accessible_name": _bounded_string(2048),
        "text": _bounded_string(4096),
        "tag": _bounded_string(64),
        "type": _bounded_string(64),
        "bounds": _nullable(_local_ref("Bounds")),
        "visible": {"type": "boolean"},
        "enabled": {"type": "boolean"},
        "editable": {"type": "boolean"},
        "checked": _nullable({"type": "boolean"}),
        "frame_path": {
            "type": "array",
            "items": ID_SCHEMA,
            "maxItems": 16,
        },
        "shadow_path": {
            "type": "array",
            "items": ID_SCHEMA,
            "maxItems": 32,
        },
    },
    (
        "ref",
        "role",
        "accessible_name",
        "text",
        "tag",
        "type",
        "bounds",
        "visible",
        "enabled",
        "editable",
        "checked",
        "frame_path",
        "shadow_path",
    ),
)

DIALOG_SCHEMA = _object(
    {
        "dialog_id": ID_SCHEMA,
        "kind": _string_enum("alert", "confirm", "prompt", "beforeunload"),
        "message": _bounded_string(4096),
        "open": {"type": "boolean"},
    },
    ("dialog_id", "kind", "message", "open"),
)

CHALLENGE_SCHEMA = _object(
    {
        "challenge_id": ID_SCHEMA,
        "kind": _string_enum("permission", "confirmation", "user_takeover"),
        "state": _string_enum(
            "pending", "approved", "denied", "expired", "consumed"
        ),
        "preview": _bounded_string(4096),
        "expires_at": _nullable(DATE_TIME_SCHEMA),
    },
    ("challenge_id", "kind", "state", "preview", "expires_at"),
)

DOWNLOAD_SCHEMA = _object(
    {
        "download_id": ID_SCHEMA,
        "state": _string_enum(
            "started", "in_progress", "completed", "failed", "cancelled"
        ),
        "filename": _bounded_string(255),
        "mime_type": _nullable(_bounded_string(255)),
        "size_bytes": _nullable(
            {"type": "integer", "minimum": 0, "maximum": 1099511627776}
        ),
        "artifact_uri": _nullable(ARTIFACT_URI_SCHEMA),
        "reason_code": _nullable(
            {
                "type": "string",
                "pattern": "^[a-z][a-z0-9_.-]{0,63}$",
            }
        ),
    },
    (
        "download_id",
        "state",
        "filename",
        "mime_type",
        "size_bytes",
        "artifact_uri",
        "reason_code",
    ),
)

OBSERVATION_SCHEMA = _object(
    {
        "session_id": ID_SCHEMA,
        "page_id": ID_SCHEMA,
        "tab_id": ID_SCHEMA,
        "sequence": {"type": "integer", "minimum": 0},
        "page_revision": PAGE_REVISION_SCHEMA,
        "url": _bounded_string(8192),
        "origin": _nullable(ORIGIN_SCHEMA),
        "title": _bounded_string(2048),
        "ready_state": _string_enum("loading", "interactive", "complete", "unknown"),
        "viewport": _local_ref("Viewport"),
        "timestamp": DATE_TIME_SCHEMA,
        "capability_revision": _bounded_string(128, min_length=1),
        "text": _bounded_string(100000),
        "text_truncated": {"type": "boolean"},
        "accessibility": {
            "type": "array",
            "items": _local_ref("AccessibilityNode"),
            "maxItems": 4096,
        },
        "interactive_elements": {
            "type": "array",
            "items": _local_ref("InteractiveElement"),
            "maxItems": 4096,
        },
        "dialogs": {
            "type": "array",
            "items": _local_ref("Dialog"),
            "maxItems": 16,
        },
        "challenges": {
            "type": "array",
            "items": _local_ref("Challenge"),
            "maxItems": 16,
        },
        "downloads_delta": {
            "type": "array",
            "items": _local_ref("Download"),
            "maxItems": 64,
        },
        "screenshot_artifact_uri": _nullable(ARTIFACT_URI_SCHEMA),
    },
    (
        "session_id",
        "page_id",
        "tab_id",
        "sequence",
        "page_revision",
        "url",
        "origin",
        "title",
        "ready_state",
        "viewport",
        "timestamp",
        "capability_revision",
        "text",
        "text_truncated",
        "accessibility",
        "interactive_elements",
        "dialogs",
        "challenges",
        "downloads_delta",
        "screenshot_artifact_uri",
    ),
)


def _action_common(kind: ActionKind, parameters: dict[str, Any]) -> dict[str, Any]:
    target_required = kind in {
        ActionKind.CLICK,
        ActionKind.TYPE,
        ActionKind.SELECT,
        ActionKind.CHECK,
        ActionKind.HOVER,
        ActionKind.DRAG,
    }
    properties: dict[str, Any] = {
        "action_id": ID_SCHEMA,
        "idempotency_key": ID_SCHEMA,
        "session_id": ID_SCHEMA,
        "tab_id": ID_SCHEMA,
        "page_id": ID_SCHEMA,
        "expected_page_revision": PAGE_REVISION_SCHEMA,
        "kind": _string_enum(kind.value),
        "target_ref": REF_SCHEMA if target_required else _nullable(REF_SCHEMA),
        "parameters": parameters,
        "timeout_ms": {
            "type": "integer",
            "minimum": 1,
            "maximum": 120000,
            "default": 30000,
        },
        "confirmation_id": _nullable(ID_SCHEMA),
    }
    required = (
        "action_id",
        "idempotency_key",
        "session_id",
        "tab_id",
        "page_id",
        "expected_page_revision",
        "kind",
        "target_ref",
        "parameters",
        "timeout_ms",
        "confirmation_id",
    )
    return _object(properties, required)


SCROLL_PARAMETERS = _object(
    {
        "delta_x": {"type": "number", "minimum": -1000000, "maximum": 1000000},
        "delta_y": {"type": "number", "minimum": -1000000, "maximum": 1000000},
    }
)
SCROLL_PARAMETERS["anyOf"] = [
    {"required": ["delta_x"]},
    {"required": ["delta_y"]},
]

ACTION_REQUEST_SCHEMA = _union(
    _action_common(
        ActionKind.CLICK,
        _object(
            {
                "button": _string_enum("left", "middle", "right", default="left"),
                "click_count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2,
                    "default": 1,
                },
            }
        ),
    ),
    _action_common(
        ActionKind.TYPE,
        _object(
            {
                "text": _bounded_string(100000),
                "clear": {"type": "boolean", "default": False},
            },
            ("text",),
        ),
    ),
    _action_common(
        ActionKind.KEY,
        _object(
            {
                "key": _bounded_string(64, min_length=1),
                "modifiers": {
                    "type": "array",
                    "items": _string_enum("Alt", "Control", "Meta", "Shift"),
                    "maxItems": 4,
                    "uniqueItems": True,
                },
            },
            ("key",),
        ),
    ),
    _action_common(ActionKind.SCROLL, SCROLL_PARAMETERS),
    _action_common(
        ActionKind.SELECT,
        _object({"value": _bounded_string(10000)}, ("value",)),
    ),
    _action_common(
        ActionKind.CHECK,
        _object({"checked": {"type": "boolean"}}, ("checked",)),
    ),
    _action_common(ActionKind.HOVER, _object({})),
    _action_common(
        ActionKind.DRAG,
        _object({"destination_ref": REF_SCHEMA}, ("destination_ref",)),
    ),
)

VERIFICATION_SCHEMA = _object(
    {
        "verification_id": ID_SCHEMA,
        "action_id": ID_SCHEMA,
        "kind": _string_enum(
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
        ),
        "target_ref": _nullable(REF_SCHEMA),
        "passed": {"type": "boolean"},
        "causal": {"type": "boolean"},
        "expected_summary": _bounded_string(2048),
        "actual_summary": _bounded_string(2048),
        "observed_revision": PAGE_REVISION_SCHEMA,
        "observed_at": DATE_TIME_SCHEMA,
    },
    (
        "verification_id",
        "action_id",
        "kind",
        "target_ref",
        "passed",
        "causal",
        "expected_summary",
        "actual_summary",
        "observed_revision",
        "observed_at",
    ),
)

ACTION_RESULT_SCHEMA = _object(
    {
        "status": _string_enum("succeeded", "failed"),
        "before_revision": PAGE_REVISION_SCHEMA,
        "after_revision": PAGE_REVISION_SCHEMA,
        "executed_method": _bounded_string(128, min_length=1),
        "verification": {
            "type": "array",
            "items": _local_ref("Verification"),
            "minItems": 1,
            "maxItems": 32,
        },
        "changed_url": _nullable(_bounded_string(8192)),
        "changed_elements": {
            "type": "array",
            "items": REF_SCHEMA,
            "maxItems": 256,
        },
        "download": _nullable(_local_ref("Download")),
        "artifact_uri": _nullable(ARTIFACT_URI_SCHEMA),
        "diagnostics_id": _nullable(ID_SCHEMA),
        "revalidated": {"type": "boolean"},
    },
    (
        "status",
        "before_revision",
        "after_revision",
        "executed_method",
        "verification",
        "changed_url",
        "changed_elements",
        "download",
        "artifact_uri",
        "diagnostics_id",
        "revalidated",
    ),
)

ARTIFACT_SCHEMA = _object(
    {
        "uri": ARTIFACT_URI_SCHEMA,
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "size_bytes": {
            "type": "integer",
            "minimum": 0,
            "maximum": 1099511627776,
        },
        "mime_type": _bounded_string(255, min_length=1),
        "created_at": DATE_TIME_SCHEMA,
        "expires_at": DATE_TIME_SCHEMA,
    },
    ("uri", "sha256", "size_bytes", "mime_type", "created_at", "expires_at"),
)

SESSION_PERMISSION_SCHEMA = _object(
    {
        "project_id": _bounded_string(4096, min_length=1),
        "origin": ORIGIN_SCHEMA,
        "policy": _string_enum("session_allow"),
        "created_at": DATE_TIME_SCHEMA,
        "persistent": {"type": "boolean", "const": False},
        "session_id": ID_SCHEMA,
        "expires_at": {"type": "null"},
    },
    (
        "project_id",
        "origin",
        "policy",
        "created_at",
        "persistent",
        "session_id",
        "expires_at",
    ),
)

PERSISTENT_PERMISSION_SCHEMA = _object(
    {
        "project_id": _bounded_string(4096, min_length=1),
        "origin": ORIGIN_SCHEMA,
        "policy": _string_enum("block", "always_allow"),
        "created_at": DATE_TIME_SCHEMA,
        "persistent": {"type": "boolean", "const": True},
        "session_id": {"type": "null"},
        "expires_at": _nullable(DATE_TIME_SCHEMA),
    },
    (
        "project_id",
        "origin",
        "policy",
        "created_at",
        "persistent",
        "session_id",
        "expires_at",
    ),
)

PERMISSION_DECISION_SCHEMA = _union(
    SESSION_PERMISSION_SCHEMA, PERSISTENT_PERMISSION_SCHEMA
)

SESSION_STATUS_SCHEMA = _object(
    {
        "session_id": ID_SCHEMA,
        "state": _string_enum(
            "starting",
            "active",
            "user_takeover_required",
            "user_takeover_active",
            "stopping",
            "stopped",
            "crashed",
        ),
        "backend": _string_enum("chromium", "firefox"),
        "running": {"type": "boolean"},
        "active_page_id": _nullable(ID_SCHEMA),
        "active_tab_id": _nullable(ID_SCHEMA),
        "page_revision": _nullable(PAGE_REVISION_SCHEMA),
        "url": _bounded_string(8192),
        "title": _bounded_string(2048),
        "ready_state": _string_enum("loading", "interactive", "complete", "unknown", "closed"),
        "freshness_ms": {"type": "integer", "minimum": 0, "maximum": 86400000},
        "capabilities": _local_ref("CapabilitySet"),
    },
    (
        "session_id",
        "state",
        "backend",
        "running",
        "active_page_id",
        "active_tab_id",
        "page_revision",
        "url",
        "title",
        "ready_state",
        "freshness_ms",
        "capabilities",
    ),
)

SESSION_START_RESULT_SCHEMA = _object(
    {
        "session_id": ID_SCHEMA,
        "capabilities": _local_ref("CapabilitySet"),
        "status": _local_ref("SessionStatus"),
    },
    ("session_id", "capabilities", "status"),
)

SESSION_STOP_RESULT_SCHEMA = _object(
    {
        "session_id": ID_SCHEMA,
        "state": _string_enum("stopped", "crashed"),
        "stopped_at": DATE_TIME_SCHEMA,
    },
    ("session_id", "state", "stopped_at"),
)

WAIT_CONDITION_SCHEMA = _union(
    _object(
        {"kind": _string_enum("url"), "url": HTTP_URL_SCHEMA},
        ("kind", "url"),
    ),
    _object(
        {
            "kind": _string_enum("text"),
            "text": _bounded_string(4096, min_length=1),
            "present": {"type": "boolean", "default": True},
        },
        ("kind", "text"),
    ),
    _object(
        {
            "kind": _string_enum("ref_state"),
            "target_ref": REF_SCHEMA,
            "state": _string_enum("visible", "hidden", "enabled", "disabled"),
        },
        ("kind", "target_ref", "state"),
    ),
    _object(
        {
            "kind": _string_enum("navigation"),
            "from_revision": PAGE_REVISION_SCHEMA,
        },
        ("kind", "from_revision"),
    ),
    _object(
        {
            "kind": _string_enum("download"),
            "download_id": ID_SCHEMA,
        },
        ("kind", "download_id"),
    ),
)

WAIT_RESULT_SCHEMA = _object(
    {
        "condition_kind": _string_enum(
            "url", "text", "ref_state", "navigation", "download"
        ),
        "satisfied": {"type": "boolean"},
        "elapsed_ms": {"type": "integer", "minimum": 0, "maximum": 120000},
        "observation": _nullable(_local_ref("Observation")),
        "download": _nullable(_local_ref("Download")),
    },
    ("condition_kind", "satisfied", "elapsed_ms", "observation", "download"),
)

TAB_SCHEMA = _object(
    {
        "tab_id": ID_SCHEMA,
        "page_id": ID_SCHEMA,
        "url": _bounded_string(8192),
        "title": _bounded_string(2048),
        "active": {"type": "boolean"},
        "page_revision": PAGE_REVISION_SCHEMA,
    },
    ("tab_id", "page_id", "url", "title", "active", "page_revision"),
)

TABS_RESULT_SCHEMA = _object(
    {
        "operation": _string_enum("list", "open", "switch", "close"),
        "tabs": {"type": "array", "items": _local_ref("Tab"), "maxItems": 64},
        "active_tab_id": _nullable(ID_SCHEMA),
        "observation": _nullable(_local_ref("Observation")),
    },
    ("operation", "tabs", "active_tab_id", "observation"),
)

DOWNLOADS_RESULT_SCHEMA = _object(
    {
        "operation": _string_enum("list", "wait"),
        "downloads": {
            "type": "array",
            "items": _local_ref("Download"),
            "maxItems": 256,
        },
    },
    ("operation", "downloads"),
)

ARTIFACT_CHUNK_SCHEMA = _object(
    {
        "uri": ARTIFACT_URI_SCHEMA,
        "offset": {"type": "integer", "minimum": 0},
        "next_offset": {"type": "integer", "minimum": 0},
        "eof": {"type": "boolean"},
        "data_base64": {
            "type": "string",
            "contentEncoding": "base64",
            "maxLength": 699052,
        },
    },
    ("uri", "offset", "next_offset", "eof", "data_base64"),
)

PERMISSIONS_RESULT_SCHEMA = _object(
    {
        "operation": _string_enum("list", "status"),
        "decisions": {
            "type": "array",
            "items": _local_ref("PermissionDecision"),
            "maxItems": 1024,
        },
        "challenge": _nullable(_local_ref("Challenge")),
    },
    ("operation", "decisions", "challenge"),
)

CONSOLE_ENTRY_SCHEMA = _object(
    {
        "level": _string_enum("debug", "info", "warning", "error"),
        "message": _bounded_string(4096),
        "timestamp": DATE_TIME_SCHEMA,
    },
    ("level", "message", "timestamp"),
)

NETWORK_ENTRY_SCHEMA = _object(
    {
        "request_id": ID_SCHEMA,
        "method": _bounded_string(16, min_length=1),
        "url": _bounded_string(8192),
        "status": _nullable({"type": "integer", "minimum": 100, "maximum": 599}),
        "resource_type": _bounded_string(64),
        "started_at": DATE_TIME_SCHEMA,
        "duration_ms": _nullable({"type": "number", "minimum": 0}),
    },
    (
        "request_id",
        "method",
        "url",
        "status",
        "resource_type",
        "started_at",
        "duration_ms",
    ),
)

DOM_ENTRY_SCHEMA = _object(
    {
        "ref": REF_SCHEMA,
        "tag": _bounded_string(64),
        "role": _bounded_string(128),
        "name": _bounded_string(2048),
        "text": _bounded_string(4096),
        "bounds": _nullable(_local_ref("Bounds")),
    },
    ("ref", "tag", "role", "name", "text", "bounds"),
)

STYLE_ENTRY_SCHEMA = _object(
    {
        "name": _bounded_string(128, min_length=1),
        "value": _bounded_string(2048),
    },
    ("name", "value"),
)

PERFORMANCE_ENTRY_SCHEMA = _object(
    {
        "name": _bounded_string(128, min_length=1),
        "value": {"type": "number"},
        "unit": _string_enum("ms", "bytes", "count", "ratio"),
    },
    ("name", "value", "unit"),
)

DEVTOOLS_RESULT_SCHEMA = _union(
    _object(
        {
            "query": _string_enum("console"),
            "entries": {
                "type": "array",
                "items": _local_ref("ConsoleEntry"),
                "maxItems": 1000,
            },
            "truncated": {"type": "boolean"},
        },
        ("query", "entries", "truncated"),
    ),
    _object(
        {
            "query": _string_enum("network"),
            "entries": {
                "type": "array",
                "items": _local_ref("NetworkEntry"),
                "maxItems": 1000,
            },
            "truncated": {"type": "boolean"},
        },
        ("query", "entries", "truncated"),
    ),
    _object(
        {
            "query": _string_enum("dom"),
            "entries": {
                "type": "array",
                "items": _local_ref("DomEntry"),
                "maxItems": 2048,
            },
            "truncated": {"type": "boolean"},
        },
        ("query", "entries", "truncated"),
    ),
    _object(
        {
            "query": _string_enum("style"),
            "entries": {
                "type": "array",
                "items": _local_ref("StyleEntry"),
                "maxItems": 256,
            },
            "truncated": {"type": "boolean"},
        },
        ("query", "entries", "truncated"),
    ),
    _object(
        {
            "query": _string_enum("performance"),
            "entries": {
                "type": "array",
                "items": _local_ref("PerformanceEntry"),
                "maxItems": 256,
            },
            "truncated": {"type": "boolean"},
        },
        ("query", "entries", "truncated"),
    ),
)

TRACE_RECORD_SCHEMA = _object(
    {
        "trace_id": ID_SCHEMA,
        "step_id": ID_SCHEMA,
        "action_kind": _bounded_string(64, min_length=1),
        "risk": _string_enum("R0", "R1", "R2", "R3", "R4", "Developer"),
        "page_revision": PAGE_REVISION_SCHEMA,
        "permission": _bounded_string(64, min_length=1),
        "verification_passed": {"type": "boolean"},
        "started_at": DATE_TIME_SCHEMA,
        "duration_ms": {"type": "integer", "minimum": 0, "maximum": 120000},
        "diagnostics_id": _nullable(ID_SCHEMA),
    },
    (
        "trace_id",
        "step_id",
        "action_kind",
        "risk",
        "page_revision",
        "permission",
        "verification_passed",
        "started_at",
        "duration_ms",
        "diagnostics_id",
    ),
)

TRACE_RESULT_SCHEMA = _union(
    _object(
        {
            "operation": _string_enum("list", "get"),
            "traces": {
                "type": "array",
                "items": _local_ref("TraceRecord"),
                "maxItems": 1000,
            },
            "truncated": {"type": "boolean"},
        },
        ("operation", "traces", "truncated"),
    ),
    _object(
        {
            "operation": _string_enum("export"),
            "artifact": _local_ref("Artifact"),
        },
        ("operation", "artifact"),
    ),
)

CONTRACT_SCHEMA: dict[str, Any] = {
    "$schema": SCHEMA_DIALECT,
    "$id": CONTRACT_ID,
    "title": "Termu-inator v1 contracts",
    "$defs": {
        "PageRevision": PAGE_REVISION_SCHEMA,
        "ErrorEnvelope": ERROR_ENVELOPE_SCHEMA,
        "CapabilityLimit": CAPABILITY_LIMIT_SCHEMA,
        "CapabilityRecord": CAPABILITY_RECORD_SCHEMA,
        "CapabilitySet": CAPABILITY_SET_SCHEMA,
        "Bounds": BOUNDS_SCHEMA,
        "Viewport": VIEWPORT_SCHEMA,
        "AccessibilityNode": ACCESSIBILITY_NODE_SCHEMA,
        "InteractiveElement": INTERACTIVE_ELEMENT_SCHEMA,
        "Dialog": DIALOG_SCHEMA,
        "Challenge": CHALLENGE_SCHEMA,
        "Download": DOWNLOAD_SCHEMA,
        "Observation": OBSERVATION_SCHEMA,
        "ActionRequest": ACTION_REQUEST_SCHEMA,
        "Verification": VERIFICATION_SCHEMA,
        "ActionResult": ACTION_RESULT_SCHEMA,
        "Artifact": ARTIFACT_SCHEMA,
        "PermissionDecision": PERMISSION_DECISION_SCHEMA,
        "SessionStatus": SESSION_STATUS_SCHEMA,
        "SessionStartResult": SESSION_START_RESULT_SCHEMA,
        "SessionStopResult": SESSION_STOP_RESULT_SCHEMA,
        "WaitCondition": WAIT_CONDITION_SCHEMA,
        "WaitResult": WAIT_RESULT_SCHEMA,
        "Tab": TAB_SCHEMA,
        "TabsResult": TABS_RESULT_SCHEMA,
        "DownloadsResult": DOWNLOADS_RESULT_SCHEMA,
        "ArtifactChunk": ARTIFACT_CHUNK_SCHEMA,
        "PermissionsResult": PERMISSIONS_RESULT_SCHEMA,
        "ConsoleEntry": CONSOLE_ENTRY_SCHEMA,
        "NetworkEntry": NETWORK_ENTRY_SCHEMA,
        "DomEntry": DOM_ENTRY_SCHEMA,
        "StyleEntry": STYLE_ENTRY_SCHEMA,
        "PerformanceEntry": PERFORMANCE_ENTRY_SCHEMA,
        "DevtoolsResult": DEVTOOLS_RESULT_SCHEMA,
        "TraceRecord": TRACE_RECORD_SCHEMA,
        "TraceResult": TRACE_RESULT_SCHEMA,
    },
}


def _tool(
    name: str,
    purpose: str,
    risk_policy: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    *,
    developer: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "purpose": purpose,
        "risk_policy": risk_policy,
        "developer_mode_required": developer,
        "input_schema": input_schema,
        "output_schema": output_schema,
    }


SESSION_ID_PROPERTY = {"session_id": ID_SCHEMA}
PAGE_PRECONDITIONS = {
    **SESSION_ID_PROPERTY,
    "tab_id": ID_SCHEMA,
    "page_id": ID_SCHEMA,
    "expected_page_revision": PAGE_REVISION_SCHEMA,
}
PAGE_REQUIRED = (
    "session_id",
    "tab_id",
    "page_id",
    "expected_page_revision",
)


def _devtools_branch(query: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return _object(
        {
            **PAGE_PRECONDITIONS,
            "query": _string_enum(query),
            "parameters": parameters,
        },
        PAGE_REQUIRED + ("query", "parameters"),
    )


DEVTOOLS_INPUT_SCHEMA = _union(
    _devtools_branch(
        "console",
        _object(
            {
                "level": _string_enum("debug", "info", "warning", "error"),
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            }
        ),
    ),
    _devtools_branch(
        "network",
        _object(
            {
                "url_filter": _bounded_string(2048),
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            }
        ),
    ),
    _devtools_branch(
        "dom",
        _object(
            {
                "target_ref": _nullable(REF_SCHEMA),
                "max_depth": {"type": "integer", "minimum": 0, "maximum": 32},
            }
        ),
    ),
    _devtools_branch(
        "style",
        _object(
            {
                "target_ref": REF_SCHEMA,
                "properties": {
                    "type": "array",
                    "items": _bounded_string(128, min_length=1),
                    "maxItems": 128,
                    "uniqueItems": True,
                },
            },
            ("target_ref",),
        ),
    ),
    _devtools_branch(
        "performance",
        _object(
            {
                "scope": _string_enum("navigation", "resources", "summary")
            },
            ("scope",),
        ),
    ),
)


TOOL_MANIFEST: dict[str, Any] = {
    "$schema": MANIFEST_SCHEMA_ID,
    "$id": MANIFEST_ID,
    "manifest_version": "1.0",
    "contract_version": "1.0",
    "backend_protocol_version": "1.0",
    "mcp_protocol_version": "2025-11-25",
    "default_tool_count": len(PUBLIC_TOOL_NAMES),
    "max_tool_count": 16,
    "tools": [
        _tool(
            "browser_session_start",
            "Start the single active browser session for a host-bound project.",
            "R1",
            _object(
                {
                    "project_id": _bounded_string(4096, min_length=1),
                    "backend": _string_enum("chromium", "firefox", default="chromium"),
                    "viewport": _external_ref("Viewport"),
                },
                ("project_id",),
            ),
            _external_ref("SessionStartResult"),
        ),
        _tool(
            "browser_session_status",
            "Read cached control-plane session and backend state.",
            "R0",
            _object(SESSION_ID_PROPERTY, ("session_id",)),
            _external_ref("SessionStatus"),
        ),
        _tool(
            "browser_session_stop",
            "Gracefully stop the active session.",
            "R1",
            _object(SESSION_ID_PROPERTY, ("session_id",)),
            _external_ref("SessionStopResult"),
        ),
        _tool(
            "browser_navigate",
            "Navigate an observed page while enforcing origin policy before dispatch.",
            "server_derived",
            _union(
                _object(
                    {
                        **PAGE_PRECONDITIONS,
                        "operation": _string_enum("goto"),
                        "url": HTTP_URL_SCHEMA,
                        "timeout_ms": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 120000,
                            "default": 30000,
                        },
                    },
                    PAGE_REQUIRED + ("operation", "url"),
                ),
                _object(
                    {
                        **PAGE_PRECONDITIONS,
                        "operation": _string_enum("back", "forward", "reload"),
                        "timeout_ms": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 120000,
                            "default": 30000,
                        },
                    },
                    PAGE_REQUIRED + ("operation",),
                ),
            ),
            _external_ref("Observation"),
        ),
        _tool(
            "browser_observe",
            "Return bounded text, accessibility state, refs, and optional screenshot.",
            "R0",
            _object(
                {
                    **PAGE_PRECONDITIONS,
                    "include_screenshot": {"type": "boolean", "default": False},
                    "include_accessibility": {"type": "boolean", "default": True},
                    "text_limit": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100000,
                        "default": 100000,
                    },
                },
                PAGE_REQUIRED,
            ),
            _external_ref("Observation"),
        ),
        _tool(
            "browser_act",
            "Execute one typed ref-based action and derive causal verification.",
            "server_derived",
            _external_ref("ActionRequest"),
            _external_ref("ActionResult"),
        ),
        _tool(
            "browser_wait",
            "Wait for one closed page, ref, navigation, or download condition.",
            "R0",
            _object(
                {
                    **PAGE_PRECONDITIONS,
                    "condition": _external_ref("WaitCondition"),
                    "timeout_ms": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 120000,
                        "default": 30000,
                    },
                },
                PAGE_REQUIRED + ("condition",),
            ),
            _external_ref("WaitResult"),
        ),
        _tool(
            "browser_tabs",
            "List, open, switch, or close tabs without silent backend fallback.",
            "server_derived",
            _union(
                _object(
                    {**SESSION_ID_PROPERTY, "operation": _string_enum("list")},
                    ("session_id", "operation"),
                ),
                _object(
                    {
                        **SESSION_ID_PROPERTY,
                        "operation": _string_enum("open"),
                        "url": HTTP_URL_SCHEMA,
                    },
                    ("session_id", "operation", "url"),
                ),
                _object(
                    {
                        **SESSION_ID_PROPERTY,
                        "operation": _string_enum("switch", "close"),
                        "tab_id": ID_SCHEMA,
                    },
                    ("session_id", "operation", "tab_id"),
                ),
            ),
            _external_ref("TabsResult"),
        ),
        _tool(
            "browser_screenshot",
            "Capture an observed viewport, full page, or element as an artifact.",
            "R0",
            _union(
                _object(
                    {
                        **PAGE_PRECONDITIONS,
                        "mode": _string_enum("viewport", "full", default="viewport"),
                    },
                    PAGE_REQUIRED,
                ),
                _object(
                    {
                        **PAGE_PRECONDITIONS,
                        "mode": _string_enum("element"),
                        "target_ref": REF_SCHEMA,
                    },
                    PAGE_REQUIRED + ("mode", "target_ref"),
                ),
            ),
            _external_ref("Artifact"),
        ),
        _tool(
            "browser_downloads",
            "List downloads or wait for one known download identifier.",
            "server_derived",
            _union(
                _object(
                    {**SESSION_ID_PROPERTY, "operation": _string_enum("list")},
                    ("session_id", "operation"),
                ),
                _object(
                    {
                        **SESSION_ID_PROPERTY,
                        "operation": _string_enum("wait"),
                        "download_id": ID_SCHEMA,
                    },
                    ("session_id", "operation", "download_id"),
                ),
            ),
            _external_ref("DownloadsResult"),
        ),
        _tool(
            "browser_artifact_read",
            "Read one project-authorized bounded base64 artifact chunk.",
            "R2",
            _object(
                {
                    **SESSION_ID_PROPERTY,
                    "uri": ARTIFACT_URI_SCHEMA,
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 524288,
                        "default": 524288,
                    },
                },
                ("session_id", "uri"),
            ),
            _external_ref("ArtifactChunk"),
        ),
        _tool(
            "browser_permissions",
            "List origin decisions or inspect one server-owned pending challenge.",
            "R0",
            _union(
                _object(
                    {**SESSION_ID_PROPERTY, "operation": _string_enum("list")},
                    ("session_id", "operation"),
                ),
                _object(
                    {
                        **SESSION_ID_PROPERTY,
                        "operation": _string_enum("status"),
                        "challenge_id": ID_SCHEMA,
                    },
                    ("session_id", "operation", "challenge_id"),
                ),
            ),
            _external_ref("PermissionsResult"),
        ),
        _tool(
            "browser_devtools",
            "Run one approved bounded read-only browser-internals query.",
            "developer",
            DEVTOOLS_INPUT_SCHEMA,
            _external_ref("DevtoolsResult"),
            developer=True,
        ),
        _tool(
            "browser_trace",
            "List, inspect, or export bounded redacted action traces.",
            "R0",
            _union(
                _object(
                    {**SESSION_ID_PROPERTY, "operation": _string_enum("list")},
                    ("session_id", "operation"),
                ),
                _object(
                    {
                        **SESSION_ID_PROPERTY,
                        "operation": _string_enum("get", "export"),
                        "trace_id": ID_SCHEMA,
                    },
                    ("session_id", "operation", "trace_id"),
                ),
            ),
            _external_ref("TraceResult"),
        ),
    ],
}


MANIFEST_SCHEMA: dict[str, Any] = {
    "$schema": SCHEMA_DIALECT,
    "$id": MANIFEST_SCHEMA_ID,
    "title": "Termu-inator internal tool manifest",
    **_object(
        {
            "$schema": {"type": "string", "const": MANIFEST_SCHEMA_ID},
            "$id": {"type": "string", "const": MANIFEST_ID},
            "manifest_version": {"type": "string", "const": "1.0"},
            "contract_version": {"type": "string", "const": "1.0"},
            "backend_protocol_version": {"type": "string", "const": "1.0"},
            "mcp_protocol_version": {"type": "string", "const": "2025-11-25"},
            "default_tool_count": {"type": "integer", "const": 14},
            "max_tool_count": {"type": "integer", "const": 16},
            "tools": {
                "type": "array",
                "minItems": 14,
                "maxItems": 16,
                "items": _object(
                    {
                        "name": {
                            "type": "string",
                            "pattern": "^[A-Za-z0-9_.-]{1,128}$",
                        },
                        "purpose": _bounded_string(512, min_length=1),
                        "risk_policy": _string_enum(
                            "R0", "R1", "R2", "R3", "R4", "server_derived", "developer"
                        ),
                        "developer_mode_required": {"type": "boolean"},
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "object"},
                    },
                    (
                        "name",
                        "purpose",
                        "risk_policy",
                        "developer_mode_required",
                        "input_schema",
                        "output_schema",
                    ),
                ),
            },
        },
        (
            "$schema",
            "$id",
            "manifest_version",
            "contract_version",
            "backend_protocol_version",
            "mcp_protocol_version",
            "default_tool_count",
            "max_tool_count",
            "tools",
        ),
    ),
}


READ_ONLY_TOOLS = {
    "browser_session_status",
    "browser_observe",
    "browser_wait",
    "browser_screenshot",
    "browser_downloads",
    "browser_artifact_read",
    "browser_permissions",
    "browser_devtools",
    "browser_trace",
}
IDEMPOTENT_TOOLS = READ_ONLY_TOOLS | {"browser_session_stop", "browser_act"}
OPEN_WORLD_TOOLS = {
    "browser_navigate",
    "browser_act",
    "browser_tabs",
    "browser_downloads",
    "browser_devtools",
}


def _inline_contract_refs(value: Any, stack: tuple[str, ...] = ()) -> Any:
    if isinstance(value, list):
        return [_inline_contract_refs(item, stack) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)
    ref = value.get("$ref")
    if isinstance(ref, str) and (
        ref.startswith("contracts.schema.json#/$defs/")
        or ref.startswith("#/$defs/")
    ):
        name = ref.rsplit("/", 1)[-1]
        if name in stack:
            raise ValueError(f"recursive contract ref is not supported: {name}")
        try:
            definition = CONTRACT_SCHEMA["$defs"][name]
        except KeyError as exc:
            raise ValueError(f"unknown contract ref: {name}") from exc
        return _inline_contract_refs(definition, stack + (name,))
    return {
        key: _inline_contract_refs(item, stack)
        for key, item in value.items()
    }


def build_contract_schema() -> dict[str, Any]:
    return deepcopy(CONTRACT_SCHEMA)


def build_manifest_schema() -> dict[str, Any]:
    return deepcopy(MANIFEST_SCHEMA)


def build_tool_manifest() -> dict[str, Any]:
    return deepcopy(TOOL_MANIFEST)


def build_mcp_tools() -> list[dict[str, Any]]:
    """Generate pinned MCP 2025-11-25 Tool records from the internal source."""

    result = []
    for tool in TOOL_MANIFEST["tools"]:
        name = tool["name"]
        result.append(
            {
                "name": name,
                "description": tool["purpose"],
                "inputSchema": _inline_contract_refs(tool["input_schema"]),
                "outputSchema": _inline_contract_refs(tool["output_schema"]),
                "annotations": {
                    "readOnlyHint": name in READ_ONLY_TOOLS,
                    "destructiveHint": name == "browser_act",
                    "idempotentHint": name in IDEMPOTENT_TOOLS,
                    "openWorldHint": name in OPEN_WORLD_TOOLS,
                },
            }
        )
    return result
