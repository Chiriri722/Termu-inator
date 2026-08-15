#!/usr/bin/env python3
"""Build a static inventory of the legacy CLI, MCP, and daemon surfaces.

Project modules are parsed rather than imported so this command works without
Termux, a running browser, or the optional MCP dependency.
"""

from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from itertools import product
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Union


MIGRATION_BUCKETS = ("core", "developer", "legacy", "remove")

_CLASSIFICATION_RESTRICTIVENESS = {
    "core": 0,
    "legacy": 1,
    "developer": 2,
    "remove": 3,
}

_CORE_NAMES = {
    "a11y",
    "annotate",
    "back",
    "block",
    "blocklist",
    "bounding_box",
    "check",
    "click",
    "dblclick",
    "detect_challenge",
    "dialog_clear",
    "dialog_dismiss",
    "dialog_handle",
    "dialog_logs",
    "downloads",
    "drag",
    "element_state",
    "elements",
    "find",
    "focus",
    "forward",
    "goto",
    "hover",
    "input_value",
    "links",
    "press",
    "reload",
    "screenshot",
    "screenshot_annotate",
    "screenshot_element",
    "scroll",
    "scroll_to",
    "select",
    "shutdown",
    "start",
    "status",
    "stop",
    "swipe",
    "tab_close",
    "tab_goto",
    "tab_new",
    "tab_next",
    "tab_prev",
    "tab_to",
    "text",
    "title",
    "type",
    "type_otp",
    "unblock",
    "url",
    "wait",
    "wait_for",
    "waitact",
    "waitfor",
    "window_close",
    "window_list",
    "window_switch",
}

_DEVELOPER_PREFIXES = (
    "attr_",
    "console_",
    "cookie_set",
    "cookies_",
    "css_",
    "eval",
    "geo_",
    "headers_",
    "iframe_eval",
    "mock_",
    "network_",
    "perf",
    "responses_",
    "set_content",
    "storage_",
    "throttle_",
    "useragent_",
)

_REMOVE_NAMES = {
    "coordinate_click",
    "raw_coordinate_click",
    "unverified_coordinate_click",
}


def _canonical_name(name: str) -> str:
    normalized = name.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized.startswith("browser_"):
        normalized = normalized[len("browser_") :]
    return normalized


def classify_surface(name: str) -> str:
    """Return the planned migration bucket for a current surface name.

    Unknown features remain legacy until reviewed, which avoids accidentally
    promoting a powerful command into the default toolset.
    """

    canonical = _canonical_name(name)
    if canonical in _REMOVE_NAMES:
        return "remove"
    if canonical.startswith(_DEVELOPER_PREFIXES):
        return "developer"
    if canonical in _CORE_NAMES:
        return "core"
    return "legacy"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _assignment_target(statement: ast.AST) -> Optional[str]:
    if isinstance(statement, ast.Assign):
        targets: Iterable[ast.expr] = statement.targets
    elif isinstance(statement, ast.AnnAssign):
        targets = (statement.target,)
    else:
        return None
    for target in targets:
        if isinstance(target, ast.Name):
            return target.id
    return None


def _statement_call(statement: ast.AST) -> Optional[ast.Call]:
    if not isinstance(statement, (ast.Assign, ast.AnnAssign, ast.Expr)):
        return None
    value = statement.value
    return value if isinstance(value, ast.Call) else None


def _constant_string(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _string_sequence(node: ast.AST) -> Optional[list[str]]:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    values = []
    for item in node.elts:
        value = _constant_string(item)
        if value is None:
            return None
        values.append(value)
    return values


def _classify_mcp_tool(name: str, actions: Sequence[str]) -> str:
    """Classify a wrapper without hiding a more restricted forwarded action.

    The ordering describes default-exposure restrictiveness, not implementation
    quality: Core is the only default bucket, legacy remains non-default,
    Developer requires an explicit mode, and remove must not be exposed.
    """

    buckets = [classify_surface(name)]
    buckets.extend(classify_surface(action) for action in actions)
    if not actions:
        buckets.append("legacy")
    return max(
        buckets, key=lambda bucket: _CLASSIFICATION_RESTRICTIVENESS[bucket]
    )


def _extract_cli_commands(path: Path) -> list[dict[str, Any]]:
    tree = _parse(path)
    main = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "main"
        ),
        None,
    )
    if main is None:
        raise ValueError(f"CLI main() not found in {path}")

    group_paths: dict[str, tuple[str, ...]] = {}
    required_groups: set[tuple[str, ...]] = set()
    parser_paths: dict[str, tuple[str, ...]] = {}
    commands: list[dict[str, Any]] = []
    processed_calls: set[int] = set()

    for statement in main.body:
        call = _statement_call(statement)
        if call is None or not isinstance(call.func, ast.Attribute):
            continue
        owner = call.func.value
        if not isinstance(owner, ast.Name):
            continue
        target = _assignment_target(statement)

        if call.func.attr in {"add_parser", "add_subparsers"} and any(
            keyword.arg is None for keyword in call.keywords
        ):
            raise ValueError(
                f"dynamic CLI keyword arguments at "
                f"{path}:{getattr(call, 'lineno', '?')}"
            )

        if call.func.attr == "add_subparsers":
            processed_calls.add(id(call))
            if target is not None:
                parent_path = parser_paths.get(owner.id, ())
                group_paths[target] = parent_path
                required = False
                for keyword in call.keywords:
                    if keyword.arg != "required":
                        continue
                    if not (
                        isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, bool)
                    ):
                        raise ValueError(
                            f"dynamic CLI required at "
                            f"{path}:{getattr(call, 'lineno', '?')}"
                        )
                    required = keyword.value.value
                if required and parent_path:
                    required_groups.add(parent_path)
            continue
        if call.func.attr != "add_parser" or owner.id not in group_paths:
            continue
        processed_calls.add(id(call))
        if not call.args:
            raise ValueError(f"dynamic CLI command without a name in {path}")

        command = _constant_string(call.args[0])
        if command is None:
            raise ValueError(
                f"dynamic CLI command at {path}:{getattr(call, 'lineno', '?')}"
            )
        path_parts = (*group_paths[owner.id], command)
        aliases = []
        for keyword in call.keywords:
            if keyword.arg == "aliases":
                literal_aliases = _string_sequence(keyword.value)
                if literal_aliases is None:
                    raise ValueError(
                        f"dynamic CLI aliases at "
                        f"{path}:{getattr(call, 'lineno', '?')}"
                    )
                aliases = literal_aliases
                break
        commands.append(
            {
                "path": " ".join(path_parts),
                "name": command,
                "aliases": sorted(aliases),
                "line": getattr(statement, "lineno", None),
                "classification": classify_surface("_".join(path_parts)),
                "_parts": path_parts,
            }
        )
        if target is not None:
            parser_paths[target] = path_parts

    parser_calls = [
        node
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"add_parser", "add_subparsers"}
    ]
    unresolved = [call for call in parser_calls if id(call) not in processed_calls]
    if unresolved:
        first = unresolved[0]
        raise ValueError(
            f"nested CLI parser construction at "
            f"{path}:{getattr(first, 'lineno', '?')}"
        )

    aliases_by_path = {
        item["_parts"]: item["aliases"]
        for item in commands
    }
    for item in commands:
        parts = item.pop("_parts")
        item["kind"] = "group" if parts in required_groups else "leaf"
        spelling_parts = []
        for index, part in enumerate(parts):
            prefix = parts[: index + 1]
            spelling_parts.append([part, *aliases_by_path.get(prefix, [])])
        item["spellings"] = sorted(
            " ".join(choice) for choice in product(*spelling_parts)
        )

    return sorted(commands, key=lambda item: (item["path"], item["line"] or 0))


def _is_mcp_tool(decorator: ast.expr) -> bool:
    if not isinstance(decorator, ast.Call):
        return False
    called = decorator.func
    if not isinstance(called, ast.Attribute) or called.attr != "tool":
        return False
    return isinstance(called.value, ast.Name) and called.value.id == "mcp"


def _sent_actions(function: ast.AST) -> list[str]:
    actions = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "_send":
            continue
        action = _constant_string(node.args[0])
        if action is None:
            raise ValueError(
                f"dynamic MCP action at line {getattr(node, 'lineno', '?')}"
            )
        actions.add(action)
    return sorted(actions)


def _extract_mcp_tools(path: Path) -> list[dict[str, Any]]:
    tools = []
    for node in _parse(path).body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(_is_mcp_tool(item) for item in node.decorator_list):
            continue
        actions = _sent_actions(node)
        tools.append(
            {
                "name": node.name,
                "actions": actions,
                "line": node.lineno,
                "classification": _classify_mcp_tool(node.name, actions),
            }
        )
    return sorted(tools, key=lambda item: item["name"])


def _handler_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return "<dynamic>"


def _extract_daemon_handlers(path: Path) -> list[dict[str, Any]]:
    registry = None
    for statement in _parse(path).body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        if _assignment_target(statement) != "_HANDLERS":
            continue
        if isinstance(statement.value, ast.Dict):
            registry = statement.value
            break
    if registry is None:
        raise ValueError(f"literal _HANDLERS registry not found in {path}")

    handlers = []
    seen_actions = set()
    for key, value in zip(registry.keys, registry.values):
        if key is None:
            raise ValueError(f"dynamic daemon action unpacking in {path}")
        action = _constant_string(key)
        if action is None:
            raise ValueError(
                f"dynamic daemon action at {path}:{getattr(key, 'lineno', '?')}"
            )
        if action in seen_actions:
            raise ValueError(f"duplicate daemon action {action!r} in {path}")
        seen_actions.add(action)
        handlers.append(
            {
                "action": action,
                "handler": _handler_name(value),
                "line": getattr(key, "lineno", None),
                "classification": classify_surface(action),
            }
        )
    return sorted(handlers, key=lambda item: item["action"])


def _bucket_counts(items: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(item["classification"] for item in items)
    return {bucket: counts.get(bucket, 0) for bucket in MIGRATION_BUCKETS}


def build_inventory(root: Union[str, Path]) -> dict[str, Any]:
    """Return a deterministic inventory for the repository rooted at root."""

    repository = Path(root).resolve()
    source_paths = {
        "cli": repository / "cli.py",
        "mcp": repository / "src" / "mcp_server.py",
        "daemon": repository / "src" / "daemon.py",
    }
    missing = [str(path) for path in source_paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "inventory source file(s) missing: " + ", ".join(missing)
        )

    cli_parser_nodes = _extract_cli_commands(source_paths["cli"])
    cli_commands = [
        item for item in cli_parser_nodes if item["kind"] == "leaf"
    ]
    cli_groups = [
        item for item in cli_parser_nodes if item["kind"] == "group"
    ]
    mcp_tools = _extract_mcp_tools(source_paths["mcp"])
    daemon_handlers = _extract_daemon_handlers(source_paths["daemon"])
    mcp_actions = {
        action for tool in mcp_tools for action in tool["actions"]
    }
    daemon_actions = {item["action"] for item in daemon_handlers}

    summary = {
        "cli_commands": len(cli_commands),
        "cli_parser_nodes": len(cli_parser_nodes),
        "cli_group_commands": len(cli_groups),
        "cli_leaf_commands": len(cli_commands),
        "cli_aliases": sum(len(item["aliases"]) for item in cli_parser_nodes),
        "cli_executable_spellings": sum(
            len(item["spellings"]) for item in cli_commands
        ),
        "top_level_cli_commands": sum(
            " " not in item["path"] for item in cli_commands
        ),
        "top_level_cli_parser_nodes": sum(
            " " not in item["path"] for item in cli_parser_nodes
        ),
        "mcp_tools": len(mcp_tools),
        "daemon_handlers": len(daemon_handlers),
        "unmapped_mcp_actions": sorted(mcp_actions - daemon_actions),
        "unexposed_daemon_actions": sorted(daemon_actions - mcp_actions),
        "mcp_tools_without_static_actions": sorted(
            item["name"] for item in mcp_tools if not item["actions"]
        ),
        "classification_counts": {
            "cli": _bucket_counts(cli_commands),
            "mcp": _bucket_counts(mcp_tools),
            "daemon": _bucket_counts(daemon_handlers),
        },
    }
    return {
        "schema_version": 1,
        "sources": {
            name: str(path.relative_to(repository))
            for name, path in source_paths.items()
        },
        "summary": summary,
        "cli_parser_nodes": cli_parser_nodes,
        "cli_groups": cli_groups,
        "cli_commands": cli_commands,
        "mcp_tools": mcp_tools,
        "daemon_handlers": daemon_handlers,
    }


def _render_markdown(inventory: dict[str, Any]) -> str:
    summary = inventory["summary"]
    lines = [
        "# Current Browser Surface Inventory",
        "",
        "Generated statically; project modules were not imported.",
        "",
        "## Summary",
        "",
        f"- CLI parser nodes: {summary['cli_parser_nodes']}",
        f"- CLI command groups: {summary['cli_group_commands']}",
        f"- Executable CLI leaf commands: {summary['cli_leaf_commands']}",
        f"- Executable CLI spellings with aliases: "
        f"{summary['cli_executable_spellings']}",
        f"- Top-level CLI parser nodes: "
        f"{summary['top_level_cli_parser_nodes']}",
        f"- CLI aliases: {summary['cli_aliases']}",
        f"- MCP tools: {summary['mcp_tools']}",
        f"- Daemon handlers: {summary['daemon_handlers']}",
        f"- MCP actions without daemon handlers: "
        f"{summary['unmapped_mcp_actions'] or 'none'}",
        f"- Daemon actions without MCP tools: "
        f"{summary['unexposed_daemon_actions'] or 'none'}",
        "",
    ]
    for heading, key, name_key in (
        ("CLI Commands", "cli_commands", "path"),
        ("CLI Command Groups", "cli_groups", "path"),
        ("MCP Tools", "mcp_tools", "name"),
        ("Daemon Handlers", "daemon_handlers", "action"),
    ):
        lines.extend(
            (f"## {heading}", "", "| Name | Classification |", "|---|---|")
        )
        for item in inventory[key]:
            lines.append(f"| {item[name_key]} | {item['classification']} |")
        lines.append("")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--format", choices=("json", "markdown"), default="json"
    )
    parser.add_argument("--output", type=Path, help="Write output to a file")
    args = parser.parse_args(argv)

    inventory = build_inventory(args.root)
    if args.format == "json":
        rendered = json.dumps(inventory, indent=2, sort_keys=True) + "\n"
    else:
        rendered = _render_markdown(inventory) + "\n"

    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
