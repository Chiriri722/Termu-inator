"""Dependency-free routing core for the compact MCP v1 surface."""

from __future__ import annotations

import math
from typing import Any, Mapping

from .contracts import (
    ActionKind,
    ActionRequest,
    ErrorCode,
    PageRevision,
    Viewport,
    WaitCondition,
    WaitDownloadCondition,
    WaitNavigationCondition,
    WaitRefStateCondition,
    WaitTextCondition,
    WaitUrlCondition,
    to_wire,
)
from .errors import TermuinatorError
from .schema import PUBLIC_TOOL_NAMES, build_mcp_tools


_IMPLEMENTED_TOOLS = frozenset(
    {
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
    }
)


def compact_tool_definitions() -> list[dict[str, Any]]:
    """Return the reviewed self-contained MCP Tool projection."""

    return build_mcp_tools()


class CompactV1Router:
    """Decode validated wire arguments and call one typed browser service."""

    def __init__(self, service: object) -> None:
        self._service = service

    async def dispatch(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        if tool_name not in PUBLIC_TOOL_NAMES:
            raise TermuinatorError(
                ErrorCode.INVALID_REQUEST,
                "Unknown compact browser tool",
                details={"capability": self._bounded_capability(tool_name)},
            )
        if tool_name not in _IMPLEMENTED_TOOLS:
            raise TermuinatorError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                "The compact browser capability is not implemented yet",
                details={"capability": tool_name},
            )
        if not isinstance(arguments, Mapping) or any(
            not isinstance(key, str) for key in arguments
        ):
            raise self._invalid(tool_name)
        values = dict(arguments)

        try:
            result = await self._dispatch_implemented(tool_name, values)
        except TermuinatorError:
            raise
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise self._invalid(tool_name) from exc
        except Exception as exc:
            raise TermuinatorError(
                ErrorCode.INTERNAL_ERROR,
                "Compact browser tool execution failed internally",
                details={"capability": tool_name},
            ) from exc

        payload = to_wire(result)
        if not isinstance(payload, dict):
            raise TermuinatorError(
                ErrorCode.INTERNAL_ERROR,
                "Compact browser tool returned a non-object result",
                details={"capability": tool_name},
            )
        return payload

    async def _dispatch_implemented(
        self,
        tool_name: str,
        values: dict[str, Any],
    ) -> object:
        if tool_name == "browser_session_start":
            return await self._service.session_start(
                project_id=self._string(values, "project_id"),
                backend=self._optional_string(values, "backend"),
                viewport=self._viewport(values.get("viewport")),
            )
        if tool_name == "browser_session_status":
            return await self._service.session_status(
                self._string(values, "session_id")
            )
        if tool_name == "browser_session_stop":
            return await self._service.session_stop(
                self._string(values, "session_id")
            )
        if tool_name == "browser_navigate":
            operation = self._string(values, "operation")
            required = {
                "session_id",
                "tab_id",
                "page_id",
                "expected_page_revision",
                "operation",
            }
            if operation == "goto":
                self._require_fields(
                    values,
                    required=required | {"url"},
                    optional={"timeout_ms"},
                )
                url = WaitUrlCondition(
                    kind="url",
                    url=self._string(values, "url"),
                ).url
            elif operation in {"back", "forward", "reload"}:
                self._require_fields(
                    values,
                    required=required,
                    optional={"timeout_ms"},
                )
                url = None
            else:
                raise ValueError("navigation operation is invalid")
            return await self._service.navigate(
                session_id=self._string(values, "session_id"),
                tab_id=self._string(values, "tab_id"),
                page_id=self._string(values, "page_id"),
                expected_revision=self._revision(values),
                operation=operation,
                url=url,
                timeout_ms=self._integer(
                    values,
                    "timeout_ms",
                    default=30_000,
                    minimum=1,
                    maximum=120_000,
                ),
            )
        if tool_name == "browser_observe":
            return await self._service.observe(
                session_id=self._string(values, "session_id"),
                tab_id=self._string(values, "tab_id"),
                page_id=self._string(values, "page_id"),
                expected_revision=self._revision(values),
                include_screenshot=self._boolean(
                    values,
                    "include_screenshot",
                    default=False,
                ),
                include_accessibility=self._boolean(
                    values,
                    "include_accessibility",
                    default=True,
                ),
                text_limit=self._integer(
                    values,
                    "text_limit",
                    default=100_000,
                    minimum=0,
                    maximum=100_000,
                ),
            )
        if tool_name == "browser_act":
            return await self._service.act(self._action_request(values))
        if tool_name == "browser_wait":
            self._require_fields(
                values,
                required={
                    "session_id",
                    "tab_id",
                    "page_id",
                    "expected_page_revision",
                    "condition",
                },
                optional={"timeout_ms"},
            )
            return await self._service.wait(
                session_id=self._string(values, "session_id"),
                tab_id=self._string(values, "tab_id"),
                page_id=self._string(values, "page_id"),
                expected_revision=self._revision(values),
                condition=self._wait_condition(values.get("condition")),
                timeout_ms=self._integer(
                    values,
                    "timeout_ms",
                    default=30_000,
                    minimum=1,
                    maximum=120_000,
                ),
            )
        if tool_name == "browser_tabs":
            operation = self._string(values, "operation")
            if operation == "list":
                self._require_exact_fields(
                    values,
                    {"session_id", "operation"},
                )
                tab_id = None
                url = None
            elif operation == "open":
                self._require_exact_fields(
                    values,
                    {"session_id", "operation", "url"},
                )
                tab_id = None
                url = self._string(values, "url")
            elif operation in {"switch", "close"}:
                self._require_exact_fields(
                    values,
                    {"session_id", "operation", "tab_id"},
                )
                tab_id = self._string(values, "tab_id")
                url = None
            else:
                raise ValueError("tab operation is invalid")
            return await self._service.tabs(
                session_id=self._string(values, "session_id"),
                operation=operation,
                tab_id=tab_id,
                url=url,
            )
        if tool_name == "browser_screenshot":
            return await self._service.screenshot(
                session_id=self._string(values, "session_id"),
                tab_id=self._string(values, "tab_id"),
                page_id=self._string(values, "page_id"),
                expected_revision=self._revision(values),
                mode=self._string(values, "mode", default="viewport"),
                target_ref=self._optional_string(values, "target_ref"),
            )
        if tool_name == "browser_downloads":
            operation = self._string(values, "operation")
            if operation == "list":
                self._require_exact_fields(
                    values,
                    {"session_id", "operation"},
                )
                download_id = None
            elif operation == "wait":
                self._require_exact_fields(
                    values,
                    {"session_id", "operation", "download_id"},
                )
                download_id = self._string(values, "download_id")
            else:
                raise ValueError("download operation is invalid")
            return await self._service.downloads(
                session_id=self._string(values, "session_id"),
                operation=operation,
                download_id=download_id,
            )
        if tool_name == "browser_artifact_read":
            return await self._service.artifact_read(
                session_id=self._string(values, "session_id"),
                uri=self._string(values, "uri"),
                offset=self._integer(
                    values,
                    "offset",
                    default=0,
                    minimum=0,
                ),
                limit=self._integer(
                    values,
                    "limit",
                    default=512 * 1024,
                    minimum=1,
                    maximum=512 * 1024,
                ),
            )
        if tool_name == "browser_permissions":
            operation = self._string(values, "operation")
            if operation not in {"list", "status"}:
                raise ValueError("permission operation is invalid")
            return await self._service.permissions(
                session_id=self._string(values, "session_id"),
                operation=operation,
                challenge_id=self._optional_string(values, "challenge_id"),
            )
        if tool_name == "browser_devtools":
            self._require_exact_fields(
                values,
                {
                    "session_id",
                    "tab_id",
                    "page_id",
                    "expected_page_revision",
                    "query",
                    "parameters",
                },
            )
            query = self._string(values, "query")
            parameters = self._devtools_parameters(
                query,
                values.get("parameters"),
            )
            return await self._service.devtools(
                session_id=self._string(values, "session_id"),
                tab_id=self._string(values, "tab_id"),
                page_id=self._string(values, "page_id"),
                expected_revision=self._revision(values),
                query=query,
                parameters=parameters,
            )
        if tool_name == "browser_trace":
            operation = self._string(values, "operation")
            if operation == "list":
                self._require_exact_fields(
                    values,
                    {"session_id", "operation"},
                )
                trace_id = None
            elif operation in {"get", "export"}:
                self._require_exact_fields(
                    values,
                    {"session_id", "operation", "trace_id"},
                )
                trace_id = self._string(values, "trace_id")
            else:
                raise ValueError("trace operation is invalid")
            return await self._service.trace(
                session_id=self._string(values, "session_id"),
                operation=operation,
                trace_id=trace_id,
            )
        raise AssertionError("implemented tool dispatch is incomplete")

    @staticmethod
    def error_payload(error: TermuinatorError) -> dict[str, Any]:
        if not isinstance(error, TermuinatorError):
            raise TypeError("error_payload requires TermuinatorError")
        payload = to_wire(error.to_envelope())
        if not isinstance(payload, dict):
            raise AssertionError("error envelope must serialize to an object")
        return payload

    @staticmethod
    def _invalid(tool_name: str) -> TermuinatorError:
        return TermuinatorError(
            ErrorCode.INVALID_REQUEST,
            "Compact browser tool arguments are invalid",
            details={"capability": tool_name},
        )

    @staticmethod
    def _bounded_capability(value: object) -> str:
        if isinstance(value, str) and 1 <= len(value) <= 64:
            return value
        return "unknown"

    @staticmethod
    def _string(
        values: Mapping[str, Any],
        name: str,
        *,
        default: str | None = None,
    ) -> str:
        value = values.get(name, default)
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string")
        return value

    @staticmethod
    def _optional_string(values: Mapping[str, Any], name: str) -> str | None:
        value = values.get(name)
        if value is not None and not isinstance(value, str):
            raise TypeError(f"{name} must be a string or null")
        return value

    @staticmethod
    def _require_exact_fields(
        values: Mapping[str, Any],
        expected: set[str],
    ) -> None:
        if set(values) != expected:
            raise ValueError("tool arguments do not match the frozen field set")

    @staticmethod
    def _require_fields(
        values: Mapping[str, Any],
        *,
        required: set[str],
        optional: set[str] | None = None,
    ) -> None:
        allowed = required | (optional or set())
        keys = set(values)
        if not required.issubset(keys) or not keys.issubset(allowed):
            raise ValueError("tool arguments do not match the frozen field set")

    @staticmethod
    def _boolean(
        values: Mapping[str, Any],
        name: str,
        *,
        default: bool,
    ) -> bool:
        value = values.get(name, default)
        if not isinstance(value, bool):
            raise TypeError(f"{name} must be a boolean")
        return value

    @staticmethod
    def _integer(
        values: Mapping[str, Any],
        name: str,
        *,
        default: int,
        minimum: int,
        maximum: int | None = None,
    ) -> int:
        value = values.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
        if value < minimum or (maximum is not None and value > maximum):
            raise ValueError(f"{name} is out of bounds")
        return value

    @classmethod
    def _revision(cls, values: Mapping[str, Any]) -> PageRevision:
        return PageRevision.parse(cls._string(values, "expected_page_revision"))

    @classmethod
    def _viewport(cls, value: object) -> Viewport | None:
        if value is None:
            return None
        if not isinstance(value, Mapping) or set(value) != {
            "width",
            "height",
            "device_scale_factor",
        }:
            raise TypeError("viewport must contain the exact frozen fields")
        width = cls._integer(value, "width", default=0, minimum=1, maximum=16_384)
        height = cls._integer(
            value,
            "height",
            default=0,
            minimum=1,
            maximum=16_384,
        )
        scale = value["device_scale_factor"]
        if (
            isinstance(scale, bool)
            or not isinstance(scale, (int, float))
            or not math.isfinite(scale)
            or not 0 < scale <= 8
        ):
            raise ValueError("device_scale_factor is out of bounds")
        return Viewport(width=width, height=height, device_scale_factor=float(scale))

    @classmethod
    def _wait_condition(cls, value: object) -> WaitCondition:
        if not isinstance(value, Mapping) or any(
            not isinstance(key, str) for key in value
        ):
            raise TypeError("condition must be an object")
        kind = cls._string(value, "kind")
        if kind == "url":
            cls._require_exact_fields(value, {"kind", "url"})
            return WaitUrlCondition(
                kind=kind,
                url=cls._string(value, "url"),
            )
        if kind == "text":
            cls._require_fields(
                value,
                required={"kind", "text"},
                optional={"present"},
            )
            return WaitTextCondition(
                kind=kind,
                text=cls._string(value, "text"),
                present=cls._boolean(value, "present", default=True),
            )
        if kind == "ref_state":
            cls._require_exact_fields(
                value,
                {"kind", "target_ref", "state"},
            )
            return WaitRefStateCondition(
                kind=kind,
                target_ref=cls._string(value, "target_ref"),
                state=cls._string(value, "state"),
            )
        if kind == "navigation":
            cls._require_exact_fields(value, {"kind", "from_revision"})
            return WaitNavigationCondition(
                kind=kind,
                from_revision=PageRevision.parse(
                    cls._string(value, "from_revision")
                ),
            )
        if kind == "download":
            cls._require_exact_fields(value, {"kind", "download_id"})
            return WaitDownloadCondition(
                kind=kind,
                download_id=cls._string(value, "download_id"),
            )
        raise ValueError("wait condition kind is invalid")

    @classmethod
    def _devtools_parameters(
        cls,
        query: str,
        value: object,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping) or any(
            not isinstance(key, str) for key in value
        ):
            raise TypeError("Developer parameters must be an object")
        parameters = dict(value)
        if query == "console":
            if not set(parameters) <= {"level", "limit"}:
                raise ValueError("console parameters are invalid")
            if "level" in parameters and parameters["level"] not in {
                "debug",
                "info",
                "warning",
                "error",
            }:
                raise ValueError("console level is invalid")
            if "limit" in parameters:
                cls._integer(
                    parameters,
                    "limit",
                    default=0,
                    minimum=1,
                    maximum=1_000,
                )
        elif query == "network":
            if not set(parameters) <= {"url_filter", "limit"}:
                raise ValueError("network parameters are invalid")
            if "url_filter" in parameters:
                url_filter = cls._string(parameters, "url_filter")
                if len(url_filter) > 2_048:
                    raise ValueError("network URL filter is too long")
            if "limit" in parameters:
                cls._integer(
                    parameters,
                    "limit",
                    default=0,
                    minimum=1,
                    maximum=1_000,
                )
        elif query == "dom":
            if not set(parameters) <= {"target_ref", "max_depth"}:
                raise ValueError("DOM parameters are invalid")
            if "target_ref" in parameters:
                cls._optional_string(parameters, "target_ref")
            if "max_depth" in parameters:
                cls._integer(
                    parameters,
                    "max_depth",
                    default=0,
                    minimum=0,
                    maximum=32,
                )
        elif query == "style":
            if not {"target_ref"}.issubset(parameters) or not set(
                parameters
            ) <= {"target_ref", "properties"}:
                raise ValueError("style parameters are invalid")
            cls._string(parameters, "target_ref")
            if "properties" in parameters:
                properties = parameters["properties"]
                if (
                    not isinstance(properties, list)
                    or len(properties) > 128
                    or not all(
                        isinstance(item, str) and 1 <= len(item) <= 128
                        for item in properties
                    )
                    or len(properties) != len(set(properties))
                ):
                    raise ValueError("style properties are invalid")
        elif query == "performance":
            if set(parameters) != {"scope"} or parameters.get("scope") not in {
                "navigation",
                "resources",
                "summary",
            }:
                raise ValueError("performance parameters are invalid")
        else:
            raise ValueError("Developer query is invalid")
        return parameters

    @classmethod
    def _action_request(cls, values: Mapping[str, Any]) -> ActionRequest:
        parameters = values.get("parameters")
        if not isinstance(parameters, Mapping) or any(
            not isinstance(key, str) for key in parameters
        ):
            raise TypeError("parameters must be an object")
        try:
            kind = ActionKind(cls._string(values, "kind"))
        except ValueError as exc:
            raise ValueError("action kind is invalid") from exc
        return ActionRequest(
            action_id=cls._string(values, "action_id"),
            idempotency_key=cls._string(values, "idempotency_key"),
            session_id=cls._string(values, "session_id"),
            tab_id=cls._string(values, "tab_id"),
            page_id=cls._string(values, "page_id"),
            expected_page_revision=cls._revision(values),
            kind=kind,
            target_ref=cls._optional_string(values, "target_ref"),
            parameters=dict(parameters),
            timeout_ms=cls._integer(
                values,
                "timeout_ms",
                default=30_000,
                minimum=1,
                maximum=120_000,
            ),
            confirmation_id=cls._optional_string(values, "confirmation_id"),
        )


__all__ = ["CompactV1Router", "compact_tool_definitions"]
