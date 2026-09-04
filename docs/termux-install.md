# Termu-inator Installation on Termux

This is the authoritative installation contract for the current v0.x
`termux-browser-pilot` distribution and its `tbp` / `tbp-mcp` commands.

The primary S22U environment has passed browser and MCP smoke tests, but the
isolated Secure Folder **clean-install gate is still pending**. Do not interpret
an upgrade of an existing environment as clean-install evidence.

## Safety and Network Preconditions

1. Use a current supported Termux build and do not install this project into
   Termux's system Python with pip.
2. Back up or preserve existing `~/.venvs/termuinator` and
   `~/.venvs/termuinator-mcp-v1` environments. The installer refuses to
   overwrite either path.
3. On the verified S22U Tailscale configuration, Android split tunneling is in
   Excluding mode with the Termux toggle **OFF**. Turning that toggle on caused
   system-wide hostname resolution failures inside Termux even though direct IP
   HTTPS continued to work.
4. `crawl4ai` is neither required nor used as an installation-success signal.

## Automated Installation

Run from a trusted checkout or an unpacked, checksum-verified source archive:

```bash
cd Termu-inator
bash setup.sh
```

The installer visibly installs both browser backends and their native Termux
dependencies, including `python-cryptography`. It then creates:

- CLI environment: `~/.venvs/termuinator`
- MCP environment: `~/.venvs/termuinator-mcp-v1`

The CLI environment is a normal venv. The MCP environment is created with
`python -m venv --system-site-packages` so it can import Termux's Android-native
cryptography build. The installer passes `--only-binary=cryptography` to pip;
if the native package is missing or unusable, installation fails instead of
building a non-Termux wheel or source distribution.

The current Termux constraint set is:

```text
mcp==1.29.0
websockets==17.0.1
```

MCP's CLI extra is intentionally not installed.

## Verification

The installer runs these checks before reporting success:

- CLI and MCP `pip check`
- `tbp --version`
- `cryptography` resolves below the Termux `$PREFIX`
- MCP version is 1.29.0
- FastMCP and websockets import successfully
- `tbp-mcp` entrypoint exists in the MCP environment

Verify the stdio server without sending protocol data:

```bash
timeout 3 ~/.venvs/termuinator-mcp-v1/bin/tbp-mcp \
  >~/.cache/termuinator/mcp-stdio.stdout \
  2>~/.cache/termuinator/mcp-stdio.stderr
test "$?" -eq 124
test ! -s ~/.cache/termuinator/mcp-stdio.stdout
test ! -s ~/.cache/termuinator/mcp-stdio.stderr
```

Exit code 124 means the server remained available until `timeout` stopped it.
Both output files must be empty.

## Hermes Configuration

Use the MCP venv entrypoint, never the CLI venv or system Python:

```yaml
mcp_servers:
  termuinator:
    command: /data/data/com.termux/files/home/.venvs/termuinator-mcp-v1/bin/tbp-mcp
    connect_timeout: 30.0
    enabled: true
```

Start a new Hermes session after changing the command. The current legacy MCP
server exposes 148 tools; the modernization gate will replace that default with
the compact 14-tool server.

### Compact v1 alpha opt-in

The installer also creates the guarded compact entrypoint in the same MCP venv:

```text
/data/data/com.termux/files/home/.venvs/termuinator-mcp-v1/bin/tbp-mcp-v1
```

Use that command only when testing the compact alpha contract. The legacy
`tbp-mcp` path remains the device compatibility default until the Firefox and
Chromium adapter gates pass. Compact v1 exposes exactly 14 tools and does not
expose raw eval, cookie/header mutation, response bodies, or raw CDP.

Use `--tool-profile observer` to hide `browser_act` and `browser_tabs` at the
server boundary, or `--tool-profile interactive` for the complete compact
surface. Ready-to-merge Hermes and Codex examples plus Tailscale SSH and
artifact recovery instructions are in [the integration guide](integrations.md).

Developer queries have two independent local gates. Start the compact process
with `--developer-mode` to make the bounded read-only feature available, then
grant only the currently observed origin from another local Termux shell:

```bash
~/.venvs/termuinator-mcp-v1/bin/tbp-control developer-mode \
  SESSION_ID https://example.com enable
```

Revoke it with the same command ending in `disable`. Availability alone does
not grant an origin, an ordinary navigation permission does not grant Developer
access, and neither setting enables response bodies, credentials, raw eval, or
raw CDP. Developer Mode remains OFF when `--developer-mode` is absent.

### Read-only shared view

The compact server can explicitly start the static dashboard on Android
loopback. It remains OFF unless requested:

```bash
~/.venvs/termuinator-mcp-v1/bin/tbp-mcp-v1 --shared-view
```

The default address is `http://127.0.0.1:8765/`. The process reports the exact
URL on stderr so MCP stdout remains protocol-only. Use another unprivileged
port when necessary:

```bash
~/.venvs/termuinator-mcp-v1/bin/tbp-mcp-v1 \
  --shared-view --shared-view-port 9123
```

The dashboard is GET/HEAD-only. It shows the last cached screenshot, redacted
URL/title/tab state, value-free pending permission and confirmation summaries,
and up to 20 recent secret-free trace records. It has no approve, deny,
takeover, resume, policy, or browser-action route, and all page content is
suppressed while confidential takeover is required or active.

The current alpha intentionally rejects direct Tailnet/wildcard binding. From a
Mac already connected to the same tailnet, forward the Android loopback port
through the Termux SSH server (commonly port 8022), substituting the real
Termux user and Tailscale address:

```bash
ssh -N -L 8765:127.0.0.1:8765 -p 8022 TERMUX_USER@TAILSCALE_ADDRESS
```

Then open `http://127.0.0.1:8765/` on the Mac. This SSH forwarding pattern does
not turn the dashboard into an approval surface. Direct Tailnet HTTP binding
and bearer authentication are deferred and are not implemented in this alpha.

`--developer-mode` and `--shared-view` are independent and may be combined;
neither one grants the other's authority.

## Browser Smoke

Test each backend independently and stop it before switching:

```bash
~/.venvs/termuinator/bin/tbp start --browser firefox --json
~/.venvs/termuinator/bin/tbp goto https://example.com --json
~/.venvs/termuinator/bin/tbp text --json
~/.venvs/termuinator/bin/tbp screenshot ~/.cache/termuinator/firefox-smoke.png --json
~/.venvs/termuinator/bin/tbp stop --json

~/.venvs/termuinator/bin/tbp start --browser chromium --json
~/.venvs/termuinator/bin/tbp goto https://example.com --json
~/.venvs/termuinator/bin/tbp text --json
~/.venvs/termuinator/bin/tbp screenshot ~/.cache/termuinator/chromium-smoke.png --json
~/.venvs/termuinator/bin/tbp stop --json
```

For each backend, record the backend identity, final URL, title, body evidence,
valid non-empty PNG metadata, and clean stop. A screenshot file alone does not
prove navigation succeeded.

The compact v1 adapter allocates an owned free X display and a loopback
ephemeral Chromium CDP port. The preserved v0.x CLI commands above retain their
historic `:99` and `9222` defaults. If a compact Chromium start fails, follow
the private bounded-diagnostic procedure in the
[operations and troubleshooting guide](troubleshooting.md); do not clear X11
locks or kill unrelated browser/window-manager processes.

## Release-candidate Device Gate

For a new commit, install its wheel into a new commit-suffixed MCP venv. Keep
the prior venv and Hermes entry unchanged until the new one passes. Use that
venv's pip to install the wheel, and do not move or delete the wheel afterward:
the final verifier compares the preserved bytes and SHA-256 with pip's installed
`direct_url.json` record. It also binds every tracked `cli.py` / `src/**/*.py`
byte, the README payload, LICENSE/NOTICE, exact package metadata and entrypoints,
and every wheel `RECORD` hash and size to the clean checkout. Editable installs
and installers that omit the archive hash do not qualify as release-candidate
evidence.

Create the side-by-side environment explicitly with system site packages so
Termux's native cryptography remains authoritative. The checkout constraint
file pins the compact MCP dependencies:

```bash
PROJECT_ROOT=/ABSOLUTE/PATH/TO/Termu-inator
COMMIT12=REPLACE_WITH_COMMIT12
RC_VENV="$HOME/.venvs/termuinator-mcp-$COMMIT12"
WHEEL=/ABSOLUTE/PATH/TO/termux_browser_pilot-0.1.0a1-py3-none-any.whl

test ! -e "$RC_VENV"
python -m venv --system-site-packages "$RC_VENV"
"$RC_VENV/bin/python" -m pip install \
  --constraint "$PROJECT_ROOT/requirements-termux.txt" \
  --only-binary=cryptography \
  "${WHEEL}[mcp]"
"$RC_VENV/bin/python" -m pip --disable-pip-version-check check
```

Do not use `uv pip` for this release-candidate install: the verifier requires
pip's archive hash in `direct_url.json`. Do not change the existing Hermes MCP
entry until the side-by-side candidate passes.

Run the canonical verifier from a clean checkout at the exact expected commit.
Replace every uppercase placeholder; the output parent may exist, but the
commit-specific output directory must not. Use the short output parent below:
the compact runtime limits its owner-private Unix socket path to 100 bytes, and
the verifier rejects a path that cannot fit before starting MCP or a browser.

```bash
mkdir -p ~/.cache/tfv

~/.venvs/termuinator-mcp-COMMIT12/bin/python scripts/final_verify.py \
  --project-root /ABSOLUTE/PATH/TO/Termu-inator \
  --mcp-command ~/.venvs/termuinator-mcp-COMMIT12/bin/tbp-mcp-v1 \
  --control-command ~/.venvs/termuinator-mcp-COMMIT12/bin/tbp-control \
  --wheel ~/.cache/termuinator/wheels/termux_browser_pilot-0.1.0a1-py3-none-any.whl \
  --expected-commit FULL_40_HEX_COMMIT \
  --expected-wheel-sha256 FULL_64_HEX_WHEEL_SHA256 \
  --output ~/.cache/tfv/COMMIT12
```

The script always tests both Chromium and Firefox; there is no single-backend
pass option. It uses only the bundled `127.0.0.1` fixture, grants that ephemeral
origin through the owner-local control socket, requires default accessibility,
text, ready state, a usable interactive ref, a valid PNG read to EOF, matching
URI/metadata/local hashes, 0700/0600 storage modes, clean session/process/socket
cleanup, and an observer restart on the same isolated data root. Raw stderr,
process, and error diagnostics stay in the private output directory.
The child MCP processes also receive an isolated mode 0700 `HOME`, so inherited
`~/.tbp` profiles, downloads, and daemon state cannot affect or be changed by
the gate.

On success the command exits 0 and prints `status: PASS` with
`benchmark_allowed: true`. From the report directory, verify the manifest hash:

```bash
cd ~/.cache/tfv/COMMIT12
sha256sum -c final-verify-manifest.sha256
```

Any exit code 1, FAIL/SKIPPED backend, nonzero stderr, stale process/socket, or
`benchmark_allowed: false` keeps the benchmark and RC approval closed. Do not
fix such a result by weakening bounds, changing Tailscale/DNS, or removing
packages; preserve the report and diagnose the recorded stage first.

## Re-running the Device Benchmark

Only after the release-candidate device manifest permits it, use the repository
harness with the exact wheel, checksum-valid manifest, environment, and network
evidence:

```bash
RC_VENV="$HOME/.venvs/termuinator-mcp-COMMIT12"
RC_WHEEL="$HOME/.cache/termuinator/wheels/COMMIT12/termux_browser_pilot-0.1.0a1-py3-none-any.whl"
RC_MANIFEST="$HOME/.cache/tfv/COMMIT12/final-verify-manifest.json"
"$RC_VENV/bin/python" scripts/benchmark_device.py \
  --tbp "$RC_VENV/bin/tbp" \
  --wheel "$RC_WHEEL" \
  --canonical-manifest "$RC_MANIFEST" \
  --output "$HOME/.cache/termuinator/benchmark/COMMIT12" \
  --tailscale-termux-state "Excluding mode; Termux OFF" \
  --network-kind "current Tailscale path"
```

The benchmark revalidates the adjacent manifest checksum, clean Git commit,
wheel and installed source digests, package versions, and Termux-native
cryptography before creating its output directory. It repeats the same
authority check after measurement and writes reports only when the closing
identity is unchanged. If the current environment differs from the canonical
manifest, preserve both environments and run a new canonical gate under a
newly sealed output identity; do not reuse or overwrite the old output.

Raw process diagnostics and the sanitized summary are written separately below
`~/.cache/termuinator/benchmark/`, with directory mode 0700 and file mode 0600.
Only the sanitized summary is suitable for repository documentation.

## Existing Environments

If either target venv already exists, the installer stops before package
changes. Continue using the verified environment or create an explicitly named
new venv; do not delete the old environment until the new one passes imports,
stdio, both browser smokes, and Hermes discovery.

For recoverable update, rollback, uninstall, project-data reset, DNS/ABI
diagnosis, and stdio troubleshooting, follow the
[operations and troubleshooting guide](troubleshooting.md).
