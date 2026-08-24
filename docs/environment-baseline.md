# Environment and package baseline

This document records the host, package, and test baseline observed on
2026-08-15. It is evidence for Phase 1 discovery, not proof that the project
works on Termux or Android.

Run the commands in this document from the repository root unless a command
changes directories explicitly.

## Interpret the results by evidence level

- **Verified** means the command ran on the audit host and its result is
  recorded below.
- **Failed** means the command ran but did not meet its expected outcome. A
  failed host check is not automatically a browser product failure.
- **Unverified** means the required Termux, Android, browser, or device
  environment was unavailable. Do not convert these items into pass or fail
  results without running them on the required target.

External websites can change independently of this repository. Results from
Cloudflare, fingerprinting, OAuth, or other public sites are non-gating smoke
evidence only. Release gates should use deterministic local fixtures, contract
tests, and controlled on-device checks.

## Baseline identity

| Property | Observed value |
| --- | --- |
| Date | 2026-08-15 |
| Repository | `Chiriri722/Termu-inator` |
| Branch | `main` |
| Commit | `09b636a97a35042acb0de7f41858d965bc59963f` |
| Upstream | `https://github.com/salviz/termux-browser-pilot.git` |
| Host | `Darwin 25.6.0 arm64` |
| Target declared by the project | Termux on Android, `aarch64` |

The audit used temporary directories under `/private/tmp` for wheel builds and
virtual environments. It set `PYTHONDONTWRITEBYTECODE=1` for import and test
checks, so the checks did not add Python cache files to the repository.

## Verified host checks

### The host has supported Python versions, but the default is unsupported

Run:

```bash
uname -srm
python3 --version
command -v python3
UV_CACHE_DIR=/private/tmp/termu-inator-uv-cache uv python list --only-installed
```

Observed:

```text
Darwin 25.6.0 arm64
Python 3.9.6
/usr/bin/python3

cpython-3.14.6  /opt/homebrew/bin/python3.14
cpython-3.12.13  /Users/chiriri722/.local/share/uv/python/cpython-3.12-macos-aarch64-none/bin/python3.12
cpython-3.11.15  /Users/chiriri722/.local/bin/python3.11
cpython-3.9.6   /usr/bin/python3
```

The package declares `requires-python = ">=3.10"` in
[`pyproject.toml`](../pyproject.toml#L11). The default `python3` on this host
does not satisfy that declaration, but Python 3.11, 3.12, and 3.14 are
available. Commands below use explicit interpreter paths to avoid testing the
wrong Python.

Python 3.10, the declared minimum, was not installed and remains unverified.

### All Python files parse on the installed supported interpreters

Run:

```bash
for python_path in \
  /Users/chiriri722/.local/bin/python3.11 \
  /Users/chiriri722/.local/share/uv/python/cpython-3.12-macos-aarch64-none/bin/python3.12 \
  /opt/homebrew/bin/python3; do
  "$python_path" -c 'import pathlib; paths=sorted(pathlib.Path(".").rglob("*.py")); [compile(path.read_text(encoding="utf-8"), str(path), "exec") for path in paths]; print(f"syntax-ok: {len(paths)} files")'
done
```

Observed:

```text
syntax-ok: 26 files
syntax-ok: 26 files
syntax-ok: 26 files
```

This check validates parsing only. It does not execute browser behavior or
prove runtime compatibility with every supported dependency version.

### Both shell scripts pass Bash syntax validation

Run:

```bash
bash -n setup.sh start_browser.sh
```

Observed: exit status `0`, with no output.

This result does not validate Termux package names or run either installer.

### CLI metadata loads without browser dependencies

Run:

```bash
for python_path in \
  /Users/chiriri722/.local/bin/python3.11 \
  /Users/chiriri722/.local/share/uv/python/cpython-3.12-macos-aarch64-none/bin/python3.12 \
  /opt/homebrew/bin/python3; do
  PYTHONDONTWRITEBYTECODE=1 "$python_path" cli.py --version
done

PYTHONDONTWRITEBYTECODE=1 \
  /Users/chiriri722/.local/bin/python3.11 cli.py --help
```

Observed:

```text
tbp 0.1.0a1
tbp 0.1.0a1
tbp 0.1.0a1
```

`--help` also exited with status `0` and listed the current CLI surface. These
commands parse arguments and package imports; they do not start the daemon or a
browser.

### The base package imports without Chromium or MCP extras

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 \
  /Users/chiriri722/.local/bin/python3.11 \
  -c 'import src; print(src.__version__, src.CDPSession, src.Pilot.__name__)'
```

Observed:

```text
0.1.0a1 None Pilot
```

The base import works because [`src/__init__.py`](../src/__init__.py#L13)
catches the missing Chromium import. `CDPSession` becoming `None` is expected
without the `chromium` extra, but it means Chromium tests cannot run in the
base environment.

## Verified package build and installation

The following sequence builds from the committed tree, disables package index
access, installs the wheel without optional dependencies, and exercises both
console entry points:

```bash
audit_tmp="$(mktemp -d /private/tmp/termu-inator-build.XXXXXX)"
mkdir "$audit_tmp/src" "$audit_tmp/wheels"
git archive HEAD | tar -x -C "$audit_tmp/src"

PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
  /Users/chiriri722/.local/bin/python3.11 -m pip wheel \
  --no-deps \
  --no-build-isolation \
  --wheel-dir "$audit_tmp/wheels" \
  "$audit_tmp/src"

wheel_path="$(find "$audit_tmp/wheels" -type f -name '*.whl' -print -quit)"
/Users/chiriri722/.local/bin/python3.11 -m venv "$audit_tmp/venv"

PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
  "$audit_tmp/venv/bin/pip" install --no-deps "$wheel_path"

PYTHONDONTWRITEBYTECODE=1 "$audit_tmp/venv/bin/tbp" --version
"$audit_tmp/venv/bin/pip" check
PYTHONDONTWRITEBYTECODE=1 "$audit_tmp/venv/bin/tbp-mcp"
```

Observed successful outcomes:

- The wheel build completed without network access.
- The artifact was
  `termux_browser_pilot-0.1.0a1-py3-none-any.whl`.
- The observed artifact size was 145,269 bytes.
- The observed SHA-256 was
  `1a5eae6cdb823d88e28f7a4e206cbc9c8ac8209de4f164539b8a02cdd63a7e2e`.
  This is an audit observation, not a published release checksum.
- Installing the base wheel succeeded.
- `tbp --version` printed `tbp 0.1.0a1`.
- `pip check` printed `No broken requirements found.`

The final `tbp-mcp` command failed as documented in the next section.

## Failed checks

### The base installation exposes a nonfunctional `tbp-mcp` command

The base wheel installs the `tbp-mcp` entry point declared in
[`pyproject.toml`](../pyproject.toml#L32), but `mcp[cli]` is an optional
dependency. Running the command after the successful base installation exited
with status `1`:

```text
ModuleNotFoundError: No module named 'mcp'
```

`pip check` still passes because optional dependencies are not missing package
requirements. This makes the base package metadata internally valid while the
installed MCP entry point and the checked-in [`.mcp.json`](../.mcp.json) are not
usable without an additional install step.

The README mentions `pip install termux-browser-pilot[mcp]`, but the default
installer does not install that extra.

### The inherited browser tests do not collect in the base environment

Run on supported Python 3.11 without optional dependencies:

```bash
PYTHONDONTWRITEBYTECODE=1 \
  /Users/chiriri722/.local/bin/python3.11 \
  -m unittest discover -s tests -v
```

Observed after adding the Phase 1 static inventory suite: exit status `1`;
13 inventory tests passed and five inherited modules produced import errors:

```text
ModuleNotFoundError: No module named 'websockets'
Ran 18 tests in 0.011s
FAILED (errors=5)
```

This result shows that the base environment cannot collect the five inherited
browser files. It does not show that browser behavior itself failed. The new
[`tests/test_inventory_current_surface.py`](../tests/test_inventory_current_surface.py)
suite is dependency-free and passes independently on Python 3.11.15, 3.12.13,
and 3.14.6:

```bash
PYTHONDONTWRITEBYTECODE=1 \
  /Users/chiriri722/.local/bin/python3.11 \
  -m unittest tests.test_inventory_current_surface -v
```

Installing `websockets` alone would not make these tests device-independent.
When explicitly executed, all five files import `CDPSession` and connect to
`http://127.0.0.1:9222/json/version`. Their current boundaries are:

- All five defer project/CDP imports until `main()` and use an exact
  `if __name__ == "__main__"` guard, so unit-test discovery does not connect to
  a browser, navigate, write screenshots, or require optional `websockets`.
- An AST contract test preserves that import-time boundary.
- [`tests/test_basic.py`](../tests/test_basic.py#L21) contains the strongest
  substantive assertions; the four fingerprint/public-site diagnostics remain
  observational manual scripts.
- The scripts require an already-running Chromium CDP endpoint.
- Four scripts navigate to public websites or collect browser fingerprinting
  diagnostics.
- The repository still has no pytest/tox configuration or GitHub Actions
  workflow. It now has deterministic local HTTP fixtures, but real-browser
  fixture execution remains a device gate.

The current `tests/` directory remains mixed, but broad `unittest discover` is
now an inert and reliable local gate: the five manual modules import without
collecting tests or performing I/O. Moving them to an explicit manual/on-device
directory remains a naming cleanup, not a safety prerequisite.

## Dependency and packaging defects

### Raise or adapt the `websockets` lower bound

[`pyproject.toml`](../pyproject.toml#L27) and
[`requirements.txt`](../requirements.txt#L1) allow `websockets==12.x`, while
[`src/cdp.py`](../src/cdp.py#L10) imports:

```python
from websockets.asyncio.client import connect as ws_connect
```

The official [websockets 12.0 client API](https://websockets.readthedocs.io/en/12.0/reference/asyncio/client.html)
documents `websockets.client.connect`. The import path used by this project is
documented by the [websockets 13.0 asyncio client API](https://websockets.readthedocs.io/en/13.0/reference/asyncio/client.html).
A resolver is currently allowed to install 12.x and produce an import failure.

Fix this by either:

- requiring a tested version that provides `websockets.asyncio`, or
- using a compatibility import and testing the exact declared lower bound.

### Choose one installation contract for MCP

The project should make one of these contracts explicit:

- install the MCP dependency whenever `tbp-mcp` and `.mcp.json` are installed,
  or
- keep MCP optional and avoid presenting its command/configuration as usable
  after the default install.

Add packaging tests for both the base installation and each supported extra.

### Synchronize the release version

Three version statements conflict:

- [`README.md`](../README.md#L1): `v0.17.1`
- [`pyproject.toml`](../pyproject.toml#L7) and
  [`src/__init__.py`](../src/__init__.py#L2): `0.1.0a1`
- [`README.md`](../README.md#L826): a fix described as available in `v0.17.2+`

Use one authoritative version source and derive package and CLI versions from
it. Historical compatibility notes should identify the upstream version or
commit they describe.

### Complete the manual installation path

The README's manual installation commands install Termux packages and
`websockets`, but do not install this Python project. That sequence does not
create the `tbp` command. Add an explicit package install step and state which
extras it includes.

[`setup.sh`](../setup.sh#L33) also suppresses failure while installing
`websockets`. If Chromium support is selected, a failed Python dependency
install should be reported as an unavailable capability rather than a complete
Chromium installation.

### Add a reproducible quality environment

The audited tree has no:

- `.python-version`;
- dependency lock or constraints file;
- `requirements-dev.txt` or equivalent development extra;
- `pytest.ini`, `tox.ini`, or equivalent test configuration; or
- `.github/workflows` CI configuration.

At minimum, test the declared Python floor and the latest supported Python,
build the wheel, install base and optional extras, run `pip check`, and exercise
each installed console entry point.

## Termux, device, browser, and performance checks remain unverified

The audit host did not contain `pkg`, Xvfb, xdotool, xclip, openbox, Firefox,
Chromium, or chromium-browser. Nothing was listening on
`127.0.0.1:9222`. The following probe confirmed that limitation:

```bash
uname -srm
for binary in pkg Xvfb xdotool xclip openbox firefox chromium chromium-browser; do
  if command -v "$binary" >/dev/null 2>&1; then
    echo "$binary: $(command -v "$binary")"
  else
    echo "$binary: MISSING"
  fi
done
curl --fail --silent --show-error --max-time 1 \
  http://127.0.0.1:9222/json/version
```

Observed: every listed target binary was missing, and curl exited with status
`7` because port 9222 was closed.

These items remain explicitly unverified:

- clean installation in a fresh Termux environment;
- the declared Python 3.10 minimum;
- Termux repository and package availability;
- Firefox startup and native xdotool/clipboard control;
- Chromium startup and CDP connectivity;
- Xvfb and openbox focus routing;
- example.com navigation, text extraction, interaction, and screenshot smoke;
- WebGL, accessibility, cookie, download, proxy, and session behavior;
- Cloudflare, bot-detection, and OAuth public-site observations;
- Android sleep/wake and background process reclamation;
- low-memory and browser-crash recovery;
- daemon warm-command latency and browser startup latency;
- RSS, screenshot size, sustained action, and idle/resume measurements.

Do not mark the Phase 1 installation or browser smoke gates complete from the
host-only checks in this document.

## Run the next verification steps in this order

1. Correct the `websockets` lower bound or compatibility import, then install
   and import the exact minimum version in CI.
2. Decide whether MCP is part of the default product install. Verify `tbp` and
   `tbp-mcp` in separate base and extra installation tests.
3. Synchronize README, package, and CLI versions.
4. Add device-free unit tests, package smoke tests, and deterministic local HTTP
   browser fixtures. Run them on Python 3.10 and the latest supported Python.
5. Keep the public-site and fingerprint scripts behind their tested `__main__`
   and lazy-import boundaries; optionally move them to an explicitly named
   manual/on-device area and add stronger machine-checkable assertions.
6. Reproduce `setup.sh` in a clean Termux environment and record the Android,
   Termux, Python, browser, and system-package versions.
7. Run separate Firefox and Chromium capability matrices against local fixtures
   before running example.com or other public-site smoke checks.
8. Measure startup, warm-command latency, RSS, screenshot size, soak behavior,
   and idle/resume behavior on the target device.
9. Record public-site results with date, browser version, network conditions,
   and final URL, but keep them outside the release gate.
