# Hermes and Codex Integration

These examples expose the compact v1 stdio server without enabling raw eval,
cookies, response bodies, headers, upload, or raw CDP. They contain placeholders
only; never commit a device address, username, private key, token, or password.

## Choose a tool profile

`tbp-mcp-v1` enforces one of two closed profiles at both discovery and call
time:

- `--tool-profile observer` hides `browser_act` and `browser_tabs`. It still
  includes session lifecycle and permission-gated navigation so a fresh stdio
  process can open and inspect a page. Those operational tools are not claimed
  to be side-effect-free.
- `--tool-profile interactive` exposes the frozen 14-tool compact surface.
  Site permission, action-risk classification, confirmation, idempotency, and
  takeover checks still apply.

The host examples repeat the same allowlist as defense in depth. A host filter
cannot widen the server profile. Developer Mode is separate: add
`--developer-mode` only for a deliberate test session, then grant the exact
observed origin locally with `tbp-control developer-mode ... enable`.

## Android and Tailscale prerequisite

On the S22U configuration that produced the
[initial device baseline](device-baseline-s22u-2026-08-16.md) and the
[v0.2.17 compact benchmark](device-benchmark-s22u-v0217-2026-08-31.md), Tailscale used
split-tunneling in **Excluding** mode. In that app list, keep **Termux: OFF**.
Turning Termux ON in the exclusion list broke Android/Termux DNS while direct IP
connectivity remained available. This wording refers to the app toggle inside
the Excluding list, not to turning Tailscale off.

Before starting an agent session, verify both name resolution and the exact MCP
environment:

```bash
curl -4 -I --max-time 15 https://example.com
~/.venvs/termuinator-mcp-v1/bin/python -c \
  'import socket; print(socket.getaddrinfo("example.com", 443))'
~/.venvs/termuinator-mcp-v1/bin/tbp-mcp-v1 --help
```

## Hermes on the Termux device

Hermes reads `mcp_servers` from `~/.hermes/config.yaml`. Start with
[`examples/hermes/observer.yaml`](../examples/hermes/observer.yaml). Move to
[`interactive.yaml`](../examples/hermes/interactive.yaml) only when page
actions are required. Merge the selected `mcp_servers.termuinator` block into
the existing file; do not replace unrelated user configuration.

Both examples disable parallel calls because Termu-inator v0.1 owns one active
session. After editing, use Hermes' `/reload-mcp` command or start a fresh
session, then confirm that the observer profile does not discover
`browser_act` or `browser_tabs`.

## Codex on macOS over Tailscale SSH

Codex supports local-command stdio MCP servers through a
`[mcp_servers.<name>]` table. Copy either
[`examples/codex/observer.toml`](../examples/codex/observer.toml) or
[`interactive.toml`](../examples/codex/interactive.toml) into a trusted
project `.codex/config.toml` or merge it into `~/.codex/config.toml`.

Replace only `TERMUX_USER@TAILSCALE_ADDRESS`. Keep the executable path absolute.
The examples use SSH port 8022, no pseudo-terminal, batch authentication, and
strict known-host verification. Establish and verify a key plus the device host
key before Codex starts the server:

```bash
ssh -T -p 8022 TERMUX_USER@TAILSCALE_ADDRESS \
  /data/data/com.termux/files/home/.venvs/termuinator-mcp-v1/bin/tbp-mcp-v1 \
  --help
```

`--help` must exit without a traceback. For the real stdio launch, do not add a
remote shell banner or any wrapper output to stdout. Use `codex mcp list` or
`/mcp` to verify the connected server and visible profile.

The configuration fields and approval modes follow the current
[official OpenAI Codex MCP documentation](https://developers.openai.com/codex/mcp/).
The Hermes `args` and `tools.include` fields follow the
[NousResearch Hermes MCP guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/mcp.md).

## Shared view over an SSH local forward

If the compact server was explicitly started with `--shared-view`, forward its
literal-loopback listener instead of binding it directly to the Tailnet:

```bash
ssh -N -L 8765:127.0.0.1:8765 -p 8022 \
  TERMUX_USER@TAILSCALE_ADDRESS
```

Open `http://127.0.0.1:8765/` on the Mac. The view is read-only and suppresses
page content during confidential takeover.

## Recover a screenshot or download artifact

Do not copy Android-private paths with `scp`. Use the artifact URI returned by
the compact contract, for example `artifact://sha256/<digest>`, and repeatedly
call `browser_artifact_read` with the same `session_id` and URI:

1. Start at `offset: 0` and request at most 524288 bytes.
2. Require the response `offset` to equal the requested offset.
3. Decode `data_base64`, append those bytes locally, and continue from
   `next_offset`.
4. Stop only when `eof` is true.
5. Compute local `sha256` and require it to equal both the artifact metadata
   hash and the digest embedded in the URI before opening the file.

Never accept a filesystem path from a model or page as an artifact identifier.
Keep the reconstructed file outside the repository unless it is a deliberately
reviewed fixture.

## Smoke evidence

For each backend, capture the first and final `browser_session_status`, the
normalized URL/title/body/ready state from `browser_observe`, at least one
fixture interactive ref, the active capability record, and bounded role/name
accessibility records. Keep `include_accessibility: true`; a text-only
observation is diagnostic evidence and does not pass the default observer gate.

Run the deterministic loopback fixture before any public URL. Recover a
non-empty PNG through `browser_artifact_read`, require EOF and matching URI,
metadata, and reconstructed-byte SHA-256 values, and verify the device artifact
is owner-only before `browser_session_stop`. A successful import, screenshot
path, or `example.com` result by itself is not a browser round-trip pass.

Stop the first compact stdio process and start the second profile on the same
isolated data root to verify that no stale `control.sock` blocks reconnection.
The canonical automation for this gate is
[`scripts/final_verify.py`](../scripts/final_verify.py). Run it with the Python,
`tbp-mcp-v1`, and `tbp-control` entrypoints from one commit-suffixed MCP venv,
the full expected commit, and the preserved wheel path and SHA-256 used by pip.
It refuses editable installs, dirty or mismatched checkouts, a non-Termux
cryptography origin, partial backend selection, and an existing output
directory. Before startup it also requires exact checkout/wheel/installed
Python source bytes, release metadata, entrypoints, licenses, and wheel RECORD
integrity. Use the short `~/.cache/tfv/COMMIT12` output path from the Termux
guide so the private Unix control socket remains within its portable limit. It
then runs Chromium and Firefox against `/forms` on the bundled
loopback fixture, reads the screenshot artifact to EOF, compares MCP, URI,
durable-file, and reconstructed hashes, checks modes 0700/0600, stops each
session, and restarts the observer profile on the same data root.

Exit code 0 plus manifest `status: PASS` and `benchmark_allowed: true` is the
only result that opens the compact benchmark gate. A FAIL manifest remains
useful diagnostic evidence but must not be renamed or summarized as a partial
pass. Verify `final-verify-manifest.sha256` from inside its output directory.
The benchmark harness independently rechecks that checksum and the current
commit, wheel, installed source, Python/Android identity, and recorded package
versions before creating a new non-reusable output identity, then repeats that
check before publishing its reports. A native Termux package update after
canonical PASS therefore requires a newly sealed canonical run rather than a
delayed benchmark against the old manifest.
Keep public-site navigation and DNS results as non-gating smoke evidence.
