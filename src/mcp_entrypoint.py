"""Guarded console entry point for the optional MCP server dependency."""

from __future__ import annotations

import sys
from collections.abc import Callable


def _load_server() -> Callable[[], object]:
    try:
        from .mcp_server import main as server_main
    except ModuleNotFoundError as exc:
        if exc.name in {"mcp", "anyio"} or (
            exc.name and exc.name.startswith("mcp.")
        ):
            print(
                "tbp-mcp requires the MCP dependency set. Install "
                "'termux-browser-pilot[mcp]==0.1.0a1' or run ./setup.sh "
                "inside Termux.",
                file=sys.stderr,
            )
            raise SystemExit(2) from None
        raise
    return server_main


def _load_v1_server() -> Callable[[], object]:
    try:
        from .mcp_v1_server import main as server_main
    except ModuleNotFoundError as exc:
        if exc.name in {"mcp", "anyio"} or (
            exc.name and exc.name.startswith("mcp.")
        ):
            print(
                "tbp-mcp-v1 requires the MCP dependency set. Install "
                "'termux-browser-pilot[mcp]==0.1.0a1' or run ./setup.sh "
                "inside Termux.",
                file=sys.stderr,
            )
            raise SystemExit(2) from None
        raise
    return server_main


def main() -> object:
    """Run the MCP server or fail with an actionable dependency message."""

    return _load_server()()


def main_v1() -> object:
    """Run compact MCP v1 or fail with an actionable dependency message."""

    return _load_v1_server()()


if __name__ == "__main__":
    main()
