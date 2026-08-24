"""Hermes/Codex example configurations remain aligned with tool profiles."""

from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib
import unittest

from src.termuinator.tool_profiles import resolve_tool_profile


ROOT = Path(__file__).resolve().parents[1]


def _yaml_inline_list(text: str, key: str) -> tuple[str, ...]:
    match = re.search(rf"^\s*{re.escape(key)}:\s*(\[.*\])\s*$", text, re.MULTILINE)
    if match is None:
        raise AssertionError(f"missing inline YAML list: {key}")
    value = json.loads(match.group(1))
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AssertionError(f"invalid inline YAML list: {key}")
    return tuple(value)


class IntegrationExampleTests(unittest.TestCase):
    def test_hermes_observer_and_interactive_profiles_are_defense_in_depth(self) -> None:
        for profile in ("observer", "interactive"):
            with self.subTest(profile=profile):
                path = ROOT / "examples" / "hermes" / f"{profile}.yaml"
                text = path.read_text(encoding="utf-8")
                self.assertIn(
                    'command: "/data/data/com.termux/files/home/.venvs/'
                    'termuinator-mcp-v1/bin/tbp-mcp-v1"',
                    text,
                )
                self.assertEqual(
                    _yaml_inline_list(text, "args"),
                    ("--tool-profile", profile),
                )
                self.assertEqual(
                    _yaml_inline_list(text, "include"),
                    resolve_tool_profile(profile),
                )
                self.assertIn("supports_parallel_tool_calls: false", text)
                self.assertIn("resources: false", text)
                self.assertIn("prompts: false", text)
                self.assertNotRegex(text, r"(?i)(token|password|secret):\s*\S+")

    def test_codex_ssh_profiles_use_official_stdio_config_fields(self) -> None:
        for profile in ("observer", "interactive"):
            with self.subTest(profile=profile):
                path = ROOT / "examples" / "codex" / f"{profile}.toml"
                parsed = tomllib.loads(path.read_text(encoding="utf-8"))
                server = parsed["mcp_servers"]["termuinator"]
                self.assertEqual(server["command"], "ssh")
                self.assertIn("-T", server["args"])
                self.assertIn("8022", server["args"])
                self.assertIn("TERMUX_USER@TAILSCALE_ADDRESS", server["args"])
                self.assertTrue(
                    any(
                        item.endswith("/tbp-mcp-v1")
                        for item in server["args"]
                        if isinstance(item, str)
                    )
                )
                self.assertEqual(
                    tuple(server["enabled_tools"]),
                    resolve_tool_profile(profile),
                )
                self.assertEqual(server["default_tools_approval_mode"], "writes")
                self.assertTrue(server["required"])
                self.assertNotIn("--developer-mode", server["args"])

    def test_integration_guide_documents_artifact_recovery_and_network_gate(self) -> None:
        text = (ROOT / "docs" / "integrations.md").read_text(encoding="utf-8")
        for required in (
            "browser_artifact_read",
            "artifact://sha256/",
            "base64",
            "sha256",
            "Termux: OFF",
            "--tool-profile observer",
            "--tool-profile interactive",
            "https://developers.openai.com/codex/mcp/",
            "https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/mcp.md",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
