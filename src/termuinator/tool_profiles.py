"""Closed server-side profiles over the frozen compact MCP surface."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from .schema import PUBLIC_TOOL_NAMES


_OBSERVER_BLOCKED = frozenset({"browser_act", "browser_tabs"})
_OBSERVER_TOOLS = tuple(
    name for name in PUBLIC_TOOL_NAMES if name not in _OBSERVER_BLOCKED
)

TOOL_PROFILES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "observer": _OBSERVER_TOOLS,
        "interactive": PUBLIC_TOOL_NAMES,
    }
)


def resolve_tool_profile(name: str) -> tuple[str, ...]:
    if not isinstance(name, str) or name not in TOOL_PROFILES:
        raise ValueError("unknown compact tool profile")
    return TOOL_PROFILES[name]


__all__ = ["TOOL_PROFILES", "resolve_tool_profile"]
