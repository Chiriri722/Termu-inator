"""Offline contract tests for the current-surface inventory."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.inventory_current_surface import build_inventory, classify_surface


class InventoryCurrentSurfaceTests(unittest.TestCase):
    def test_build_inventory_extracts_static_surfaces_and_cross_checks_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / "cli.py").write_text(
                '''
def main():
    parser = object()
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("goto", aliases=["go"])
    p = sub.add_parser("tab")
    tab_sub = p.add_subparsers(dest="tab_action", required=True)
    tab_sub.add_parser("new")
''',
                encoding="utf-8",
            )
            (root / "src" / "mcp_server.py").write_text(
                '''
@mcp.tool()
async def browser_goto(url: str):
    return await _send("goto", {"url": url})

@mcp.tool()
async def browser_orphan():
    return await _send("missing")

async def browser_helper():
    return await _send("helper")
''',
                encoding="utf-8",
            )
            (root / "src" / "daemon.py").write_text(
                '''
async def _handle_goto(self, params):
    return params

async def _handle_status(self, params):
    return params

_HANDLERS = {
    "goto": _handle_goto,
    "status": _handle_status,
}
''',
                encoding="utf-8",
            )

            inventory = build_inventory(root)

        parser_nodes = {
            item["path"]: item for item in inventory.get("cli_parser_nodes", [])
        }
        commands = {item["path"]: item for item in inventory["cli_commands"]}
        self.assertEqual(set(parser_nodes), {"goto", "tab", "tab new"})
        self.assertEqual(set(commands), {"goto", "tab new"})
        self.assertEqual(commands["goto"]["aliases"], ["go"])
        self.assertEqual(parser_nodes["tab"].get("kind"), "group")
        self.assertEqual(commands["tab new"].get("kind"), "leaf")
        self.assertEqual(
            [item["name"] for item in inventory["mcp_tools"]],
            ["browser_goto", "browser_orphan"],
        )
        self.assertEqual(
            [item["action"] for item in inventory["daemon_handlers"]],
            ["goto", "status"],
        )
        self.assertEqual(inventory["summary"]["cli_commands"], 2)
        self.assertEqual(inventory["summary"].get("cli_parser_nodes"), 3)
        self.assertEqual(inventory["summary"].get("cli_group_commands"), 1)
        self.assertEqual(inventory["summary"].get("cli_leaf_commands"), 2)
        self.assertEqual(inventory["summary"]["mcp_tools"], 2)
        self.assertEqual(inventory["summary"]["daemon_handlers"], 2)
        self.assertEqual(inventory["summary"]["unmapped_mcp_actions"], ["missing"])
        self.assertEqual(inventory["summary"]["unexposed_daemon_actions"], ["status"])

    def test_classify_surface_uses_fail_safe_migration_buckets(self) -> None:
        self.assertEqual(classify_surface("goto"), "core")
        self.assertEqual(classify_surface("console_logs"), "developer")
        self.assertEqual(classify_surface("profile_save"), "legacy")
        self.assertEqual(classify_surface("raw_coordinate_click"), "remove")
        self.assertEqual(classify_surface("future_unknown_action"), "legacy")

    def test_mcp_variant_name_preserves_sensitive_mutation_classification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / "cli.py").write_text("def main():\n    pass\n", encoding="utf-8")
            (root / "src" / "mcp_server.py").write_text(
                '''
@mcp.tool()
async def browser_storage_set(key: str, value: str):
    return await _send("storage", {"action": "set", "key": key, "value": value})

@mcp.tool()
async def browser_cookies_clear():
    return await _send("cookies", {"clear": True})
''',
                encoding="utf-8",
            )
            (root / "src" / "daemon.py").write_text(
                '_HANDLERS = {"storage": handle_storage, "cookies": handle_cookies}\n',
                encoding="utf-8",
            )

            inventory = build_inventory(root)

        classifications = {
            item["name"]: item["classification"] for item in inventory["mcp_tools"]
        }
        self.assertEqual(classifications["browser_storage_set"], "developer")
        self.assertEqual(classifications["browser_cookies_clear"], "developer")

    def test_mcp_classification_cannot_hide_more_restricted_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._write_minimal_repository(Path(temp_dir))
            (root / "src" / "mcp_server.py").write_text(
                '''
@mcp.tool()
async def browser_goto(script: str):
    return await _send("eval", {"script": script})
''',
                encoding="utf-8",
            )
            (root / "src" / "daemon.py").write_text(
                '_HANDLERS = {"eval": handle_eval}\n', encoding="utf-8"
            )

            inventory = build_inventory(root)

        self.assertEqual(
            inventory["mcp_tools"][0]["classification"], "developer"
        )

    def test_group_aliases_expand_executable_leaf_spellings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._write_minimal_repository(Path(temp_dir))
            (root / "cli.py").write_text(
                '''
def main():
    parser = object()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("network", aliases=["net"])
    network_sub = p.add_subparsers(dest="network_action", required=True)
    network_sub.add_parser("start")
    network_sub.add_parser("logs")
''',
                encoding="utf-8",
            )

            inventory = build_inventory(root)

        parser_nodes = {
            item["path"]: item for item in inventory["cli_parser_nodes"]
        }
        commands = {item["path"]: item for item in inventory["cli_commands"]}
        self.assertEqual(parser_nodes["network"].get("kind"), "group")
        self.assertEqual(
            commands["network start"].get("spellings"),
            ["net start", "network start"],
        )
        self.assertEqual(inventory["summary"].get("cli_executable_spellings"), 4)

    def test_dynamic_cli_command_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._write_minimal_repository(Path(temp_dir))
            (root / "cli.py").write_text(
                '''
COMMAND = "goto"
def main():
    parser = object()
    sub = parser.add_subparsers(dest="command")
    sub.add_parser(COMMAND)
''',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "dynamic CLI command"):
                build_inventory(root)

    def test_dynamic_cli_required_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._write_minimal_repository(Path(temp_dir))
            (root / "cli.py").write_text(
                '''
REQUIRED = True
def main():
    parser = object()
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("tab")
    tab_sub = p.add_subparsers(dest="tab_action", required=REQUIRED)
    tab_sub.add_parser("new")
''',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "dynamic CLI required"):
                build_inventory(root)

    def test_dynamic_cli_aliases_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._write_minimal_repository(Path(temp_dir))
            (root / "cli.py").write_text(
                '''
ALIASES = ["go"]
def main():
    parser = object()
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("goto", aliases=ALIASES)
''',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "dynamic CLI aliases"):
                build_inventory(root)

    def test_dynamic_cli_keyword_unpacking_fails_closed(self) -> None:
        sources = {
            "parser aliases": '''
def main():
    parser = object()
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("goto", **{"aliases": ["go"]})
''',
            "subparser required": '''
def main():
    parser = object()
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("tab")
    tab_sub = p.add_subparsers(**{"required": True})
    tab_sub.add_parser("new")
''',
        }
        for label, source in sources.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                root = self._write_minimal_repository(Path(temp_dir))
                (root / "cli.py").write_text(source, encoding="utf-8")

                with self.assertRaisesRegex(
                    ValueError, "dynamic CLI keyword arguments"
                ):
                    build_inventory(root)

    def test_dynamic_mcp_action_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._write_minimal_repository(Path(temp_dir))
            (root / "src" / "mcp_server.py").write_text(
                '''
ACTION = "goto"
@mcp.tool()
async def browser_goto():
    return await _send(ACTION)
''',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "dynamic MCP action"):
                build_inventory(root)

    def test_dynamic_daemon_action_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._write_minimal_repository(Path(temp_dir))
            (root / "src" / "daemon.py").write_text(
                'ACTION = "goto"\n_HANDLERS = {ACTION: handle_goto}\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "dynamic daemon action"):
                build_inventory(root)

    def test_duplicate_daemon_action_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._write_minimal_repository(Path(temp_dir))
            (root / "src" / "daemon.py").write_text(
                '_HANDLERS = {"goto": first, "goto": second}\n', encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "duplicate daemon action"):
                build_inventory(root)

    def test_nested_cli_parser_construction_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._write_minimal_repository(Path(temp_dir))
            (root / "cli.py").write_text(
                '''
def main():
    parser = object()
    sub = parser.add_subparsers(dest="command", required=True)
    if enabled:
        sub.add_parser("goto")
''',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "nested CLI parser"):
                build_inventory(root)

    @staticmethod
    def _write_minimal_repository(root: Path) -> Path:
        (root / "src").mkdir()
        (root / "cli.py").write_text("def main():\n    pass\n", encoding="utf-8")
        (root / "src" / "mcp_server.py").write_text(
            '@mcp.tool()\nasync def browser_goto():\n    return await _send("goto")\n',
            encoding="utf-8",
        )
        (root / "src" / "daemon.py").write_text(
            '_HANDLERS = {"goto": handle_goto}\n', encoding="utf-8"
        )
        return root


if __name__ == "__main__":
    unittest.main()
