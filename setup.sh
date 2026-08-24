#!/usr/bin/env bash
# Termu-inator fail-closed installer for Termux.
set -euo pipefail

die() {
    echo "ERROR: $*" >&2
    exit 1
}

command -v pkg >/dev/null 2>&1 || die "This installer must run inside Termux (missing pkg)."
: "${PREFIX:?Termux PREFIX is not set}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_ROOT="${TERMUINATOR_VENV_ROOT:-$HOME/.venvs}"
CLI_VENV="${TERMUINATOR_CLI_VENV:-$VENV_ROOT/termuinator}"
MCP_VENV="${TERMUINATOR_MCP_VENV:-$VENV_ROOT/termuinator-mcp-v1}"

refuse_existing() {
    if [[ -e "$1" ]]; then
        die "Refusing to overwrite existing virtual environment: $1"
    fi
}

refuse_existing "$CLI_VENV"
refuse_existing "$MCP_VENV"

echo "=== Termu-inator Installer ==="
echo "[1/5] Installing Termux repositories and native packages..."
pkg install -y x11-repo tur-repo
pkg install -y \
    ca-certificates chromium firefox file imagemagick openbox python \
    python-cryptography xclip xdotool xorg-server-xvfb

echo "[2/5] Verifying Termux native cryptography..."
python - "$PREFIX" <<'PY'
from pathlib import Path
import sys

import cryptography

prefix = Path(sys.argv[1]).resolve()
module_path = Path(cryptography.__file__).resolve()
try:
    module_path.relative_to(prefix)
except ValueError:
    raise SystemExit(
        f"cryptography must come from the Termux prefix {prefix}; got {module_path}"
    )
print(f"native cryptography {cryptography.__version__}: {module_path}")
PY

echo "[3/5] Creating isolated CLI environment..."
mkdir -p "$VENV_ROOT"
python -m venv "$CLI_VENV"
"$CLI_VENV/bin/python" -m pip install --upgrade pip
"$CLI_VENV/bin/python" -m pip install "$SCRIPT_DIR"

echo "[4/5] Creating MCP environment with Termux system packages..."
python -m venv --system-site-packages "$MCP_VENV"
"$MCP_VENV/bin/python" -m pip install --upgrade pip
"$MCP_VENV/bin/python" -m pip install \
    --only-binary=cryptography \
    --constraint "$SCRIPT_DIR/requirements-termux.txt" \
    "$SCRIPT_DIR[mcp]"

echo "[5/5] Verifying both environments..."
"$CLI_VENV/bin/python" -m pip check
"$MCP_VENV/bin/python" -m pip check
"$CLI_VENV/bin/tbp" --version
"$MCP_VENV/bin/python" - "$PREFIX" <<'PY'
from importlib import metadata
from pathlib import Path
import sys

import cryptography
import websockets
from mcp.server.fastmcp import FastMCP

prefix = Path(sys.argv[1]).resolve()
crypto_path = Path(cryptography.__file__).resolve()
try:
    crypto_path.relative_to(prefix)
except ValueError:
    raise SystemExit(f"MCP venv did not reuse Termux cryptography: {crypto_path}")
mcp_version = metadata.version("mcp")
print(f"mcp={mcp_version}")
print(f"websockets={websockets.__version__}")
print(f"cryptography={cryptography.__version__}")
print(f"FastMCP={FastMCP.__name__}")
PY

[[ -x "$MCP_VENV/bin/tbp-mcp" ]] || die "tbp-mcp entrypoint was not installed."
[[ -x "$MCP_VENV/bin/tbp-mcp-v1" ]] || die "tbp-mcp-v1 entrypoint was not installed."
"$MCP_VENV/bin/tbp-mcp-v1" --help >/dev/null

echo
echo "=== Installation complete ==="
echo "CLI: $CLI_VENV/bin/tbp"
echo "MCP legacy: $MCP_VENV/bin/tbp-mcp"
echo "MCP compact: $MCP_VENV/bin/tbp-mcp-v1"
echo "Hermes compact command: $MCP_VENV/bin/tbp-mcp-v1 --tool-profile observer"
