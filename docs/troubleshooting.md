# Operations and Troubleshooting

This guide covers the staged compact alpha and the preserved legacy `tbp`
environment. Keep those two surfaces distinct while diagnosing a failure.
Commands below preserve the previous environment or data by moving it to an
explicit backup path; they do not recursively delete a home or workspace tree.

## First Evidence to Collect

Record the exact command, exit code, stdout, stderr, Android and Termux version,
browser backend, Python path, and active virtual environment. For browser smoke,
also record final URL, title, body marker, valid non-empty PNG metadata, backend
identity, and clean stop. `No daemon running` after the final stop is the
expected clean state, not an installation failure.

For compact MCP, confirm the executable and versions from the MCP venv:

```bash
~/.venvs/termuinator-mcp-v1/bin/tbp-mcp-v1 --help
~/.venvs/termuinator-mcp-v1/bin/python -c \
  'import cryptography, mcp, websockets; print(cryptography.__version__, mcp.__version__, websockets.__version__)'
```

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
must go to stderr or be removed. Test a local idle start before involving SSH:

```bash
timeout 3 ~/.venvs/termuinator-mcp-v1/bin/tbp-mcp-v1 \
  --tool-profile observer \
  >~/.cache/termuinator/mcp-v1.stdout \
  2>~/.cache/termuinator/mcp-v1.stderr
test "$?" -eq 124
test ! -s ~/.cache/termuinator/mcp-v1.stdout
test ! -s ~/.cache/termuinator/mcp-v1.stderr
```

Then repeat through `ssh -T` from the host. Any remote shell startup text on
stdout is a failed integration gate even if the local test is clean.

## Browser or Daemon Does Not Start

Inspect `~/.tbp/daemon.log`, then use the normal lifecycle commands first:

```bash
~/.venvs/termuinator/bin/tbp status --json
~/.venvs/termuinator/bin/tbp stop --json
```

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

The native Firefox bridge accepts only an exact randomized console sentinel.
A JavaScript timeout invalidates the cached console/focus state, and compact
DOM observation retries that typed failure once with a fresh synchronization.
If the second attempt fails, the public response remains a generic,
retryable `backend_crashed`; clipboard contents and the raw inherited
exception are intentionally excluded.

Preserve the final URL/title, a screenshot artifact and its hash, the compact
error code/details, and the relevant timestamped daemon log lines. Do not use
clipboard contents as diagnostic evidence. One successful navigation is not a
substitute for a successful `browser_observe` result.

## Firefox Is Much Slower Than Chromium

The S22U baseline measured multi-second Firefox status/text calls while
Chromium met the warm budgets. This is a known backend-performance gate, not an
MCP import error. Use Chromium as the current default, keep Firefox explicit,
and rerun `scripts/benchmark_device.py` after any adapter optimization. Do not
weaken budgets or report parity from a single successful page load.

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

The installer deliberately refuses an existing venv. For an update, create
new sibling environments, validate them, and switch the host command only
after both backend smokes and MCP discovery pass. Example names are explicit so
the known-good environments remain recoverable:

```bash
export TERMUINATOR_CLI_VENV="$HOME/.venvs/termuinator-next"
export TERMUINATOR_MCP_VENV="$HOME/.venvs/termuinator-mcp-v1-next"
bash setup.sh
```

Do not reuse those names if either path already exists. Record the source
commit and dependency versions alongside the validation evidence.

## Rollback

Stop the new daemon/server, restore the previous Hermes/Codex command path, and
start a fresh host session. Because the old venv was preserved, rollback does
not require package mutation. Do not point two live MCP processes at the same
project profile.

## Uninstall

First stop all Termu-inator processes and disconnect the MCP host. A recoverable
uninstall moves each explicitly checked venv instead of deleting it:

```bash
test -d "$HOME/.venvs/termuinator"
mv "$HOME/.venvs/termuinator" "$HOME/.venvs/termuinator.retired"
test -d "$HOME/.venvs/termuinator-mcp-v1"
mv "$HOME/.venvs/termuinator-mcp-v1" "$HOME/.venvs/termuinator-mcp-v1.retired"
```

Choose unused destination names. Browser packages installed through `pkg` may
be shared with other workflows and are not removed automatically.

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

## Still Unsupported in the Real Legacy Adapters

The typed fake backend proves the tabs/dialog/download contracts, but current
Firefox/Chromium legacy adapters do not expose authoritative popup/tab events,
dialog events, or completed project-scoped download bytes. Those operations
must return `unsupported_capability`; a device-local `~/.tbp/downloads` listing
or a network URL is not equivalent evidence.
