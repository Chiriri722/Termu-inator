"""Regression tests for the portable and Termux installation contracts."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PackagingMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    def test_runtime_dependency_matches_supported_websockets_api(self) -> None:
        self.assertRegex(
            self.pyproject,
            r'(?m)^dependencies\s*=\s*\[\s*"websockets>=13,<18"\s*\]$',
        )
        self.assertNotIn('websockets>=12.0', self.pyproject)

    def test_mcp_extra_is_exact_and_does_not_install_cli_extra(self) -> None:
        self.assertRegex(
            self.pyproject,
            r'(?m)^mcp\s*=\s*\[\s*"mcp==1\.29\.0"\s*\]$',
        )
        self.assertNotIn("mcp[cli]", self.pyproject)

    def test_project_metadata_does_not_claim_antibot_success(self) -> None:
        project_block = self.pyproject.split("[project.optional-dependencies]", 1)[0]
        self.assertNotRegex(project_block.lower(), r"passes? cloudflare|bypass")
        self.assertNotIn('"cloudflare"', project_block.lower())
        self.assertIn("Chiriri722/Termu-inator", self.pyproject)

    def test_mcp_entrypoint_uses_dependency_guard(self) -> None:
        self.assertIn('tbp-mcp = "src.mcp_entrypoint:main"', self.pyproject)
        self.assertIn(
            'tbp-mcp-v1 = "src.mcp_entrypoint:main_v1"',
            self.pyproject,
        )


class TermuxRequirementsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.requirements = (ROOT / "requirements-termux.txt").read_text(
            encoding="utf-8"
        )

    def test_device_versions_are_reproducible(self) -> None:
        active = {
            line.strip()
            for line in self.requirements.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertEqual(active, {"mcp==1.29.0", "websockets==17.0.1"})

    def test_cryptography_is_never_requested_from_pip(self) -> None:
        self.assertNotRegex(self.requirements.lower(), r"^\s*cryptography\b")


class InstallerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.installer = (ROOT / "setup.sh").read_text(encoding="utf-8")

    def test_installer_is_fail_closed(self) -> None:
        self.assertIn("set -euo pipefail", self.installer)
        self.assertNotIn("--break-system-packages", self.installer)
        self.assertNotIn("|| true", self.installer)
        self.assertNotRegex(self.installer, r"pip install[^\n]*2>/dev/null")

    def test_installer_creates_separate_cli_and_mcp_venvs(self) -> None:
        self.assertIn('CLI_VENV="${TERMUINATOR_CLI_VENV:-$VENV_ROOT/termuinator}"', self.installer)
        self.assertIn(
            'MCP_VENV="${TERMUINATOR_MCP_VENV:-$VENV_ROOT/termuinator-mcp-v1}"',
            self.installer,
        )
        self.assertIn("python -m venv", self.installer)
        self.assertIn("--system-site-packages", self.installer)

    def test_installer_requires_termux_native_cryptography(self) -> None:
        self.assertIn("python-cryptography", self.installer)
        self.assertIn("cryptography", self.installer)
        self.assertIn("$PREFIX", self.installer)
        self.assertIn("--only-binary=cryptography", self.installer)
        self.assertIn('metadata.version("mcp")', self.installer)

    def test_installer_does_not_overwrite_existing_venvs(self) -> None:
        self.assertIn("Refusing to overwrite existing virtual environment", self.installer)

    def test_installer_verifies_both_mcp_entrypoints(self) -> None:
        self.assertIn('[[ -x "$MCP_VENV/bin/tbp-mcp" ]]', self.installer)
        self.assertIn('[[ -x "$MCP_VENV/bin/tbp-mcp-v1" ]]', self.installer)
        self.assertIn('MCP compact: $MCP_VENV/bin/tbp-mcp-v1', self.installer)


class InstallationDocumentationTests(unittest.TestCase):
    def test_termux_guide_matches_the_installer_contract(self) -> None:
        guide = (ROOT / "docs" / "termux-install.md").read_text(encoding="utf-8")
        for expected in (
            "python-cryptography",
            "~/.venvs/termuinator",
            "~/.venvs/termuinator-mcp-v1",
            "--system-site-packages",
            "mcp==1.29.0",
            "Termux toggle **OFF**",
        ):
            self.assertIn(expected, guide)
        self.assertIn("clean-install gate is still pending", guide)

    def test_readme_routes_installation_to_the_termux_guide(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        quick_start = readme.split("## Quick Start", 1)[1].split("\n## ", 1)[0]
        self.assertIn("docs/termux-install.md", quick_start)
        self.assertIn("bash setup.sh", quick_start)
        self.assertNotIn("pip install websockets", quick_start)

    def test_final_gate_uses_a_portable_termux_output_path(self) -> None:
        guide = (ROOT / "docs" / "termux-install.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("--output ~/.cache/tfv/COMMIT12", guide)
        self.assertIn("cd ~/.cache/tfv/COMMIT12", guide)
        self.assertNotIn(
            "--output ~/.cache/termuinator/final-verify/COMMIT12",
            guide,
        )
        device_socket = Path(
            "/data/data/com.termux/files/home/.cache/tfv/COMMIT12/"
            "d/termuinator/runtime/control.sock"
        )
        self.assertLessEqual(len(os.fsencode(device_socket)), 100)

    def test_benchmark_uses_the_verified_commit_suffixed_venv(self) -> None:
        guide = (ROOT / "docs" / "termux-install.md").read_text(
            encoding="utf-8"
        )
        benchmark = guide.split("## Re-running the Device Benchmark", 1)[1]
        self.assertIn(
            'RC_VENV="$HOME/.venvs/termuinator-mcp-COMMIT12"',
            benchmark,
        )
        self.assertIn(
            '"$RC_VENV/bin/python" scripts/benchmark_device.py',
            benchmark,
        )
        self.assertIn('--tbp "$RC_VENV/bin/tbp"', benchmark)
        self.assertNotIn("~/.venvs/termuinator-mcp-v1/bin/python", benchmark)

    def test_lifecycle_and_troubleshooting_guide_is_explicit_and_safe(self) -> None:
        guide = (ROOT / "docs" / "troubleshooting.md").read_text(
            encoding="utf-8"
        )
        for expected in (
            "Termux: OFF",
            "Could not resolve host",
            "python-cryptography",
            "tbp-mcp-v1 --tool-profile observer",
            "Update without overwriting",
            "Rollback",
            "Uninstall",
            "Project data reset",
            "No daemon running",
            "unsupported_capability",
        ):
            self.assertIn(expected, guide)
        self.assertNotIn("rm -rf $HOME", guide)
        self.assertNotIn("rm -rf ~", guide)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        install = (ROOT / "docs" / "termux-install.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("docs/troubleshooting.md", readme)
        self.assertIn("troubleshooting.md", install)
        self.assertNotIn("pkill -f", readme)

    def test_design_docs_distinguish_normative_targets_from_current_alpha(self) -> None:
        architecture = (ROOT / "docs" / "architecture.md").read_text(
            encoding="utf-8"
        )
        security = (ROOT / "docs" / "security-model.md").read_text(
            encoding="utf-8"
        )
        migration = (ROOT / "docs" / "migration-from-tbp.md").read_text(
            encoding="utf-8"
        )
        capabilities = (ROOT / "docs" / "backend-capabilities.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("Normative target", architecture)
        self.assertIn("Current alpha gaps", architecture)
        self.assertIn("Normative target", security)
        self.assertIn("does not yet intercept redirects", security)
        self.assertIn("Current alpha checkout", migration)
        self.assertIn("`tbp-mcp-v1`", migration)
        self.assertIn("Compact v1 delta", capabilities)


class ManualBrowserScriptBoundaryTests(unittest.TestCase):
    SCRIPTS = (
        "test_basic.py",
        "test_native_fp.py",
        "test_nowsecure.py",
        "test_sannysoft.py",
        "test_webgl.py",
    )

    def test_live_cdp_scripts_are_inert_during_unittest_discovery(self) -> None:
        for name in self.SCRIPTS:
            with self.subTest(script=name):
                tree = ast.parse(
                    (ROOT / "tests" / name).read_text(encoding="utf-8"),
                    filename=name,
                )
                eager_project_imports = [
                    node
                    for node in tree.body
                    if isinstance(node, ast.ImportFrom)
                    and node.module is not None
                    and (node.module == "src" or node.module.startswith("src."))
                ]
                eager_runs = [
                    node
                    for node in tree.body
                    if isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and isinstance(node.value.func.value, ast.Name)
                    and node.value.func.value.id == "asyncio"
                    and node.value.func.attr == "run"
                ]
                main_guards = [
                    node
                    for node in tree.body
                    if isinstance(node, ast.If)
                    and isinstance(node.test, ast.Compare)
                    and isinstance(node.test.left, ast.Name)
                    and node.test.left.id == "__name__"
                    and any(
                        isinstance(comparator, ast.Constant)
                        and comparator.value == "__main__"
                        for comparator in node.test.comparators
                    )
                ]
                self.assertEqual(eager_project_imports, [])
                self.assertEqual(eager_runs, [])
                self.assertEqual(len(main_guards), 1)


class McpEntrypointTests(unittest.TestCase):
    def test_mcp_server_rebuilds_settings_before_fastmcp_init(self) -> None:
        source = (ROOT / "src" / "mcp_server.py").read_text(encoding="utf-8")
        rebuild = source.index("Settings.model_rebuild()")
        construction = source.index("mcp = FastMCP(")
        self.assertLess(rebuild, construction)
        self.assertNotIn("passes Cloudflare", source)

    def test_missing_mcp_extra_has_actionable_error_without_traceback(self) -> None:
        code = """
import builtins
real_import = builtins.__import__
def blocked(name, *args, **kwargs):
    if name == 'mcp' or name.startswith('mcp.'):
        error = ModuleNotFoundError("No module named 'mcp'")
        error.name = 'mcp'
        raise error
    return real_import(name, *args, **kwargs)
builtins.__import__ = blocked
from src.mcp_entrypoint import main
main()
"""
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertIn("termux-browser-pilot[mcp]", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_compact_entrypoint_has_the_same_optional_dependency_guard(self) -> None:
        code = """
import builtins
real_import = builtins.__import__
def blocked(name, *args, **kwargs):
    if name == 'mcp' or name.startswith('mcp.'):
        error = ModuleNotFoundError("No module named 'mcp'")
        error.name = 'mcp'
        raise error
    return real_import(name, *args, **kwargs)
builtins.__import__ = blocked
from src.mcp_entrypoint import main_v1
main_v1()
"""
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertIn("termux-browser-pilot[mcp]", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
