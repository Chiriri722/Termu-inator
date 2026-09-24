# Termu-inator Installation on Termux

This is the authoritative installation contract for the current v0.x
`termux-browser-pilot` distribution and its `tbp` / `tbp-mcp` commands.

The primary S22U environment has passed browser and MCP smoke tests, but the
isolated Secure Folder **clean-install gate is still pending**. Do not interpret
an upgrade of an existing environment as clean-install evidence.

## Choose the entrypoint and release identity explicitly

| Command | Current purpose |
|---|---|
| `tbp` | Legacy CLI/daemon, separate from the compact service |
| `tbp-mcp` | Legacy compatibility MCP; existing registrations stay unchanged |
| `tbp-mcp-v1` | Compact alpha MCP: interactive 14 tools, observer 12 tools |
| `tbp-control` | Owner-local approval, origin permission, and takeover control |

The distribution version is still `0.1.0a1`. A commit label such as `v.0.2.20`
does not change that version or the wheel filename. Identify a candidate by
its full commit/tree, wheel SHA-256, and verified installed source binding,
not by `tbp --version` or a filename alone.

The current compact alpha still lacks pre-follow redirect and DNS/peer
enforcement. Evaluation stays limited to controlled synthetic fixtures; a
successful install or device gate is not approval for general untrusted-web
use. See the [implemented boundaries and release targets](security-model.md).
Hermes registration and production cutover require separate owner approval.

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
- Both `tbp-mcp` and `tbp-mcp-v1` entrypoints exist; compact `--help` succeeds

These are installation checks, not proof of an MCP handshake or browser task.
For candidate acceptance, use the newly sealed
[release-candidate device gate](#release-candidate-device-gate), which checks
real protocol initialization, inventories, browser work, and cleanup in isolation.
An idle process stopped by `timeout` with code 124 only shows that its deadline
expired; it does not prove readiness. Do not start a second server against an
existing data root or overwrite previous stdio evidence to obtain that result.

## Hermes Configuration

Use the MCP venv entrypoint, never the CLI venv or system Python:

```yaml
mcp_servers:
  termuinator:
    command: /data/data/com.termux/files/home/.venvs/termuinator-mcp-v1/bin/tbp-mcp
    connect_timeout: 30.0
    enabled: true
```

Start a new Hermes session after an approved command change. The current legacy
MCP server exposes 148 tools. Compact acceptance does not automatically replace
that registration or authorize a default switch.

### Compact v1 alpha opt-in

The installer also creates the guarded compact entrypoint in the same MCP venv:

```text
/data/data/com.termux/files/home/.venvs/termuinator-mcp-v1/bin/tbp-mcp-v1
```

Use that command only when testing the compact alpha contract. The legacy
`tbp-mcp` path remains the device compatibility default until device acceptance
and a separately approved switch. Compact v1 exposes exactly 14 tools and does not
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
Process evidence is scoped to **all visible, same-UID processes**, not the entire
Android device. It no longer filters by browser names or reads command lines.
Private snapshots retain parent PIDs and start ticks, so PID reuse is not
mistaken for the original process. `device.process_census`
reports visibility separately; missing procfs is `UNAVAILABLE`, incomplete
entries are `UNKNOWN`, and an unverified survivor count is `null`, never zero.
Either condition closes the benchmark gate. Failed MCP initialization still
collects independent cleanup evidence when it can do so safely.

At initialization and before/after each MCP tool call, the verifier records
ancestry rooted in its trusted MCP child. `processes-observed.json` retains those
numeric identities privately, including when a call fails or is cancelled.
An observed descendant that remains after reparenting is a confirmed survivor;
a reused PID with different start ticks does not inherit ownership. New
processes without observed ancestry stay unattributed/`UNKNOWN`, not an asserted
candidate leak. Incomplete live observations cannot be retried into PASS.
This is sampled evidence, not OS containment or proof of invisible descendants.
The census never sends termination signals. In the local hardening, each MCP
profile keeps its first observed root generation; repeated sampling cannot
adopt a reused PID. Only a newly verified profile launch can bind a new root.

After each backend, including a successful one, `post_stop` records a separate
cleanup result. The same MCP generation and its current-UID, mode-0600 control
socket remain live, while browser descendants and leases must be released.
Unverified cleanup skips the next backend and observer restart without erasing
the browser result. After the interactive MCP exits, process and file cleanup
are checked again with no live-root exception before starting the observer.
The Korean note shows browser and transition results separately. These are
local regression guarantees, not a new S22U acceptance result.

The local Stage 2 gate also checks form values after type/check/select, requires
owner-local approval for the synthetic submit, and verifies one effect after
replaying the same confirmed request. Existing loopback fixtures exercise old
page revisions, retired refs, fresh-ref recovery, disabled/hidden targets, and
wait success/timeout. Each refusal must have the expected machine error code
and no observed effect; an RPC success alone cannot pass. These additions still
require a new sealed device candidate, not a rerun of an old output identity.

The same gate uses synthetic login/OTP pages to check both takeover states.
It requires blocked reads/captures, redacted status, and owner-local resume
that rotates page identity before a fresh observation. Page instructions must
not change site policy, tool inventory, or Developer Mode. The first response
that detects takeover is withheld too; for actions, a pause can follow a
completed durable effect, so retain the original idempotency key. Local tests
of this gate do not replace the pending two-backend S22U run.

Socket metadata or display-lease lookup failure also stays `null` in cleanup,
not successful absence. Display leases must be in a real owner-private directory.
The verifier does not query `/proc/net/unix` or claim host-wide socket cleanup.
It writes `final-verify-summary.ko.txt` alongside the canonical JSON/checksum:
a mode-0600 Korean completion note containing only fixed public statuses and
allowlisted failure labels. Failed backends include `failure_context` in the
manifest: the verifier stage and, when available, the MCP tool, action kind,
error code, and bounded backend diagnostic labels. Missing labels remain
unknown; no exception message, page content, path, or session ID is published.
These labels identify the failed check, not proof of a browser process crash.
If both a check and session stop fail, `failure_context` and `additional_failure`
preserve both contexts with the same public-label restrictions. Cancellation takes
precedence and aborts the remaining backend/restart work; it is not converted to
a retryable check error.
Profile failures also carry these labels. Neither failure suppresses the
independent final cleanup readback, and neither authorizes a rerun.
This note is derived from the manifest, not a separate approval or evidence source.
Closing Git/environment and PNG checks run independently, including after a
recorded failure or cancellation. PNGs must still match the captured artifact.
Canonical and benchmark share the same bounded PNG validator. A failed private
diagnostic write is recorded without discarding the public failure report when
the other output files can still be written.

`final-verify-files.json` binds the manifest, checksum, and Korean note to their
written bytes, SHA-256, current-owner identity, and 0600 mode. Its private reader
rejects FIFOs, symlinks, unsafe parents, and files replaced during the read.
Return this file with the three files it covers. It does not hash itself or
publish private diagnostic contents.

Publication verification is separate from the preserved run result: a run
manifest may say PASS while its return-file check fails. In that case the
command still exits 1 with stdout FAIL and `benchmark_allowed: false`; do not
edit the original manifest. The benchmark rejects a declared return-file
manifest that is missing, failed, or no longer matches the returned files.
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

The current local hardening changes also preserve ownership after an incomplete
shutdown: compact sessions stay `stopping`, page content stays hidden, and a new
session cannot start until owned cleanup succeeds. CLI `stop` cannot auto-start
a replacement daemon. Legacy socket/pidfile evidence and unresolved process
handles must not be erased to force a PASS. Daemon cleanup only removes its
recorded file identities after owned cleanup succeeds; the socket server itself
may already have closed its path, so absence alone is not termination proof.
Failed or cancelled startup also retains any unresolved pilot/backend and its
lease. New starts remain blocked, and the local view does not report idle while
that cleanup is pending. MCP transport shutdown cleans active and partially
started sessions through the same stop path. Firefox owns a BiDi client before
connecting and closes its callback listener as well as stopping its server loop.
These changes still need a newly sealed wheel/device run; direct child waits do not prove that every
browser descendant or host-wide socket has disappeared.

## Re-running the Device Benchmark

Only after the release-candidate device manifest permits it, use the repository
harness with the exact wheel, checksum-valid manifest, environment, and network
evidence:

```bash
umask 077
RC_VENV="$HOME/.venvs/termuinator-mcp-COMMIT12"
RC_WHEEL="$HOME/.cache/termuinator/wheels/COMMIT12/termux_browser_pilot-0.1.0a1-py3-none-any.whl"
RC_MANIFEST="$HOME/.cache/tfv/COMMIT12/final-verify-manifest.json"
"$RC_VENV/bin/python" scripts/benchmark_device.py \
  --tbp "$RC_VENV/bin/tbp" \
  --wheel "$RC_WHEEL" \
  --canonical-manifest "$RC_MANIFEST" \
  --isolated-runtime "$HOME/.cache/tfb/COMMIT12" \
  --tailscale-termux-state "Excluding mode; Termux OFF" \
  --network-kind "current Tailscale path"
```

The benchmark revalidates the adjacent manifest checksum, clean Git commit,
wheel and installed source digests, package versions, and Termux-native
cryptography before creating its output directory. It repeats the same
authority check after measurement. In the current hardened harness, a closing
failure preserves the measurements and a quality-FAIL report; it never approves
the changed environment. If the current environment differs from the canonical
manifest, preserve both environments and run a new canonical gate under a
newly sealed output identity; do not reuse or overwrite the old output.

Raw process diagnostics and the sanitized summary are written separately below
`~/.cache/tfb/COMMIT12/h/benchmark/`, with directory mode 0700 and file mode 0600.
Only the sanitized summary is suitable for repository documentation.

When using an isolated HOME, put `--output` inside that **child HOME**, not
inside the operator's original HOME. The harness rejects an outside path
before creating output or starting a daemon. Do not widen the runtime's
allowed directory to make an old handoff work. See the
[benchmark quality handoff](benchmark-quality-handoff.md) for the corrected layout.

The recommended `--isolated-runtime` option derives these paths automatically.
It launches one child without changing the operator's HOME and refuses an
existing runtime identity. Do not add `--output`, `--socket`, or `--pidfile` to
that invocation. The child also rejects pre-existing `.tbp` state before sending
any stop command. A fresh benchmark must not stop or reuse a production daemon.

The version 2 summary includes `quality.status` and fixed boolean checks.
Exit 0 requires `quality.status: PASS`: every requested sample must succeed,
screenshots must pass private PNG validation, all operation medians must meet
the existing budgets, and the final daemon socket and pidfile must be absent.
The local hardening also requires an authenticated daemon identity at each
start and PASS for the separate `process_cleanup` evidence. Socket peer PID/UID,
the private pidfile, and process generation bind shutdown to the recorded
daemon on the same connection. Missing startup census prevents launch; observed
survivors or incomplete evidence block subsequent launches. Measured-command
latency excludes before/finally ancestry inspection. This is sampled visible
same-UID evidence, not host-wide containment or global socket cleanup.
The closing environment, clean checkout, and independent PNG readback must also
pass. Each PNG is compared with its recorded hash, size, dimensions, and mode.
`baseline-files.json` similarly verifies the public summary and Korean note;
raw diagnostics remain private. Exit 0 also requires this publication check.
Exit 1 means quality or publication failed; a publication failure does not
overwrite the already recorded quality result. Exit 2 rejects invalid authority
or output preflight. A failure in one post-run check does not skip the remaining
independent checks. Public reports expose fixed statuses/counts; raw errors stay
private. Canonical PASS alone does not imply benchmark quality PASS.

## Existing Environments

If either target venv already exists, the installer stops before package
changes. Continue using the verified environment or create an explicitly named
new venv; do not delete the old environment until the new one passes imports,
stdio, both browser smokes, and Hermes discovery.

For recoverable update, rollback, uninstall, project-data reset, DNS/ABI
diagnosis, and stdio troubleshooting, follow the
[operations and troubleshooting guide](troubleshooting.md).
