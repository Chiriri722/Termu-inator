# Operations and Troubleshooting

This guide covers the staged compact alpha and the preserved legacy `tbp`
environment. Keep those two surfaces distinct while diagnosing a failure.
Maintenance requires owner approval and exact resource ownership. Preserve the
previous environment and evidence; never use a process-name kill or recursively
delete a home/workspace tree to recover a candidate.

## First Evidence to Collect

Keep the exact command, exit code, stdout, stderr, Android and Termux version,
browser backend, Python path, and active virtual environment locally in private
0700 directories/0600 files. Share sanitized codes, counts, hashes, and approved
fixture evidence, not raw browser/stdio logs or credentials. For browser smoke,
also record final URL, title, body marker, valid non-empty PNG metadata, backend
identity, and clean stop. `No daemon running` after the final stop is the
expected clean state, not an installation failure.

For compact MCP, confirm the executable and versions from the MCP venv:

```bash
~/.venvs/termuinator-mcp-v1/bin/tbp-mcp-v1 --help
~/.venvs/termuinator-mcp-v1/bin/python -c \
  'from importlib import metadata; import cryptography, mcp, websockets; print(cryptography.__version__, metadata.version("mcp"), websockets.__version__)'
```

These version values are diagnostic information, not wheel/source provenance
or proof of the native Termux cryptography path. The canonical verifier checks
those separately. Do not repair a failed sealed run in place or reuse its output.

## DNS Fails While Direct IP HTTPS Works

Typical evidence is `Could not resolve host` from curl and
`socket.gaierror` from Python while `https://1.1.1.1/cdn-cgi/trace` succeeds.
On the verified S22U, the cause was Tailscale Android split tunneling in
Excluding mode with the Termux app selected. Keep **Termux: OFF** in that
Excluding list. This means Termux is not excluded from Tailscale; it does not
mean turning Tailscale off.

After changing only that Android app-list toggle, recheck both resolver paths:

```bash
curl -4 -I --max-time 15 https://example.com
python -c 'import socket; print(socket.getaddrinfo("example.com", 443, type=socket.SOCK_STREAM))'
```

Do not reinstall Python packages or force a resolver address until these two
checks distinguish Android routing from a package problem. Removing `crawl4ai`
was not the cause of the successful network recovery.

## Android Cryptography ABI Import Failure

The MCP venv must reuse Termux's native `python-cryptography`; do not let pip
compile or install a generic Android-incompatible cryptography wheel. The
supported layout is a `--system-site-packages` MCP venv plus the pinned MCP
constraints from `requirements-termux.txt`.

```bash
pkg install python-cryptography
~/.venvs/termuinator-mcp-v1/bin/python -c \
  'import cryptography; print(cryptography.__version__, cryptography.__file__)'
```

The printed module path must be below the Termux `$PREFIX`. If it is not, stop;
create a new venv instead of mutating the known-good one in place.

## Compact MCP Starts but the Host Finds the Wrong Tools

Run the packaged compact command, not the 148-tool legacy command:

```bash
~/.venvs/termuinator-mcp-v1/bin/tbp-mcp-v1 --tool-profile observer
```

Observer intentionally hides `browser_act` and `browser_tabs`; interactive
exposes the frozen 14-tool set. A call hidden by the selected profile returns
`unsupported_capability`. It is not silently forwarded to the legacy server.
After changing Hermes configuration, run `reload-mcp` or start a new Hermes
session.

## MCP Stdio Is Contaminated or Times Out

MCP stdout is protocol-only. Shell banners, debug prints, and wrapper messages
must not appear there. Start with the completed sealed run's sanitized protocol
and stderr counts; a nonzero count is not permission to publish its private log.
The [candidate gate](termux-install.md#release-candidate-device-gate) performs
real initialization and discovery in an isolated runtime. A three-second idle
timeout alone does not establish readiness. Do not overwrite a previous capture
or start another server on a live data root while diagnosing it.

An SSH transport check is a separate approved check, not an automatic retry.
It must use its own private output and isolated candidate. Any shell startup
text on MCP stdout is a failed integration gate, even when local stdio is clean.

## Browser or Daemon Does Not Start

First identify the interface and exact runtime. `~/.tbp/daemon.log` belongs to
the legacy daemon, not necessarily the compact session under investigation.
Legacy commands can auto-start a daemon; do not use them as a read-only probe
for a compact failure. Any stop must target the verified candidate through its
own host/session or authenticated lifecycle command, not another existing daemon.

Do not blindly remove PID, socket, or profile-lock files. A path may have been
replaced or may still belong to a live process. Capture the log and process
state, verify ownership/liveness, and use a clean new profile or reboot before
manual recovery. Compact service errors such as `backend_crashed`,
`outcome_unknown`, `session_busy`, or `unsupported_capability` are deliberate
fail-closed results; preserve their diagnostic identifier.

The compact adapter does not reuse the legacy fixed runtime resources. It
claims the first free X display in `:99` through `:199` with an owner-private
lease and chooses a loopback ephemeral CDP port for every Chromium launch
attempt. The v0.x `tbp` surface deliberately retains its public `:99` and
`9222` defaults for compatibility. Neither path is allowed to kill an
unrelated Xvfb/openbox process or remove an X11 lock/socket blindly.

When compact Chromium fails before CDP is ready, the public result remains the
bounded `backend_crashed` error. The last three failed-attempt stderr tails are
stored locally in `chromium-startup.log` below Python's temporary directory in
the `termuinator-runtime` subdirectory. Find the exact root without guessing:

```bash
~/.venvs/termuinator-mcp-v1/bin/python -c \
  'import tempfile; print(tempfile.gettempdir() + "/termuinator-runtime")'
```

The runtime directory is mode 0700 and the diagnostic file is mode 0600. A
multi-process failure followed by a successful fallback can still leave an
earlier failed-attempt record. Inspect it only on the device; Chromium stderr
can contain local paths or other private context, so do not paste or transfer
the whole file without redaction.

## Firefox Loads the Page but Observation Fails

An established Firefox BiDi connection supplies JavaScript observation without
the global clipboard. Its failure does not silently fall back to the console.
The compatibility console path applies only when startup did not establish
BiDi and uses an exact randomized sentinel. Compact DOM collection has a
bounded retry for its typed JavaScript timeout; it is not permission to replay
an uncertain state-changing action.

Preserve the final URL/title, a screenshot artifact and its hash, the compact
error code/allowlisted stage, and timestamp. Keep raw diagnostic logs private
and never use clipboard contents as evidence. `backend_crashed` alone does not
prove an OS process crash. Successful navigation does not prove observation.

## Firefox Is Much Slower Than Chromium

The original S22U baseline had multi-second Firefox status/text calls; the
[later compact measurements](device-benchmark-s22u-v0217-2026-08-31.md) cleared
those warm budgets. Do not treat that old baseline as a current regression or
silently change the chosen backend. Compare only checksum-bound evidence with
its recorded environment. A new benchmark requires a new sealed identity and
the immediately preceding canonical PASS, not an ad hoc rerun of an old report.

## Shared View Cannot Be Reached from the Mac

The alpha viewer binds literal loopback only. Start it explicitly and use an
SSH local forward; do not change it to a wildcard or Tailnet listener:

```bash
~/.venvs/termuinator-mcp-v1/bin/tbp-mcp-v1 --shared-view
ssh -N -L 8765:127.0.0.1:8765 -p 8022 TERMUX_USER@TAILSCALE_ADDRESS
```

The viewer is read-only and deliberately suppresses page data during
confidential takeover. It cannot approve, resume, or execute actions.

## Update without overwriting

The installer deliberately refuses an existing venv. It also runs `pkg install`
and pip upgrades, so it is not a read-only diagnostic or a sealed-candidate
update procedure. Only use the following example when native package changes
are separately approved; the known-good environments remain recoverable:

```bash
export TERMUINATOR_CLI_VENV="$HOME/.venvs/termuinator-next"
export TERMUINATOR_MCP_VENV="$HOME/.venvs/termuinator-mcp-v1-next"
bash setup.sh
```

Do not reuse those names if either path already exists. Record the source
commit and dependency versions alongside the validation evidence.

For the S22U candidate workflow, instead use the checksum-bound wheel and new
commit-suffixed venv/runtime paths from the sealed instruction. Keep the old
venv, registration, profile, and reports unchanged. Do not change native
packages after canonical and then run benchmark under the same authority.

Before any separately approved host switch, preserve the exact old command,
arguments/tool profile, runtime config location, and data-root identity in a
private backup. Confirm the candidate's new canonical/quality/action evidence
and remaining acceptance limits. Never start two servers on the same profile
or use a successful smoke as permission to activate the compact alpha.

## Rollback

Stop only the identified new daemon/server, confirm its owned cleanup, restore
the previously recorded Hermes/Codex command and arguments, and start a fresh
host session. If ownership or cleanup is uncertain, stop and report it; do not
unlink a lock/socket to force a restart. A preserved venv restores code, not
browser data that was mutated or migrated. Candidate validation must therefore
use isolated data roots, and any later data migration needs its own backup and
rollback approval. Do not change packages or erase candidate evidence to roll back.

## Uninstall

Disconnect only the selected registration and stop its verified owned processes.
For each venv explicitly selected for removal, verify the exact source is an
owned real directory and its backup destination is unused, including no dangling
symlink. Move that directory to the checked backup path rather than deleting it;
if any check fails, leave it untouched. Preserve other venvs and reports.
Browser packages installed through `pkg` may be shared and are not removed
automatically. No uninstall command is part of canonical or benchmark validation.

## Project data reset

Compact profiles and service state default to
`${XDG_DATA_HOME:-$HOME/.local/share}/termuinator`. Legacy `tbp` data under
`~/.tbp` is separate. The current alpha has no one-command project reset, so a
reset remains an owner-local maintenance operation.

Stop the compact server, identify the exact project digest from its owner scope
and project ID, verify that the resolved path is one child below the data root,
then move only that project directory to a uniquely named backup. Do not use a
glob or a broad recursive delete. If the owner scope, project ID, or path is
uncertain, keep the data and request a diagnostic review instead.

Moving a browser project directory does not erase sibling service-owned policy,
journal, trace, or artifact state. Do not claim a complete privacy reset or move
the whole state tree; such a reset needs a separately scoped owner-approved plan.

## Still Unsupported in the Real Legacy Adapters

The typed fake backend proves the tabs/dialog/download contracts, but current
Firefox/Chromium legacy adapters do not expose authoritative popup/tab events,
dialog events, or completed project-scoped download bytes. Those operations
must return `unsupported_capability`; a device-local `~/.tbp/downloads` listing
or a network URL is not equivalent evidence.
