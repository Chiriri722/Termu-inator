# Findings: Termu-inator Modernization

## Baseline Discovery

- `task_plan.md` exists and contains 886 lines of product scope, architecture, contracts, phased delivery gates, and safety rules.
- The plan names `findings.md` and `progress.md` as required persistent working-memory files, but neither file existed at the start of implementation.
- No Termu-inator-specific prior-work entry was found in the local Codex memory registry; the repository and `task_plan.md` are therefore the authoritative baseline.

## Open Questions

- Does the checkout already match the pinned upstream baseline commit?
- Which portions of the proposed architecture are already implemented?
- What build, lint, test, and device-validation commands are currently available?
- Are there pre-existing user changes that must be preserved?

## Plan Review — Product and Architecture

- The intended product is an AI-first browser runtime for interactive/login-heavy web tasks, not a general crawler or Android native-app automation tool.
- The central invariant is an `observe -> act(ref + expected revision) -> verify` loop with stale-reference rejection before any action.
- The proposed core is a backend-neutral orchestrator with Firefox native and Chromium CDP adapters, a compact MCP surface capped at 16 tools, artifact-backed screenshots/downloads, and a compatibility adapter for existing `tbp` users.
- Safety is part of the API contract: origin permission decisions, R0-R4 risk classes, one-time confirmation tokens for consequential actions, redacted traces, default-disabled raw CDP, and untrusted page content.
- The MVP exit criteria cover functionality, safety, deterministic local fixture reliability, performance, compatibility, documentation, and license/fork attribution—not just implementation completeness.
- Phase 1 requires a reproducible upstream baseline, generated current-surface inventory, capability matrix, installation/smoke evidence, performance measurements, and documented discrepancies before architectural replacement work begins.

## Plan Review — Delivery Gates

- Delivery is intentionally sequenced across seven phases: baseline discovery, contract freeze, typed-core migration, observe-act-verify, permissions/artifacts/shared view, productized MCP/CLI Developer Mode, and device hardening/alpha release.
- Each phase has an explicit exit gate. The current phase may not be marked complete until upstream behavior, installation, current tool/handler inventory, and backend capability differences are reproducibly documented.
- Release gating relies on deterministic local fixtures and security/contract tests; external anti-bot, OAuth, and public dynamic-page checks are explicitly non-gating.
- The performance targets include warm status at 300 ms or less, text-only observation at 2 seconds or less, verified ref action at 5 seconds or less, and a crash-free 100-action soak. Unrealistic device results must be documented rather than silently relaxing budgets.
- The unresolved design questions concern stable-ref lifetime, page revision inputs, artifact transport compatibility, shared-view transport, profile/session scope, uploads, raw eval, backend defaults, legacy lifetime, confirmation UI, and preservation of stealth features.

## Discovery Tooling

- Codebase graph search, snippet, trace, query, architecture, and indexing tools are available, but no project-listing operation is exposed in this session. The repository-derived project name must therefore be probed directly and indexed if absent.
- The direct architecture probe confirmed that no Termu-inator-specific graph is indexed. Existing graph projects cover the workspace root and unrelated repositories only.

## Checkout State

- The repository is on `main` and tracks `origin/main`.
- At the first Git status check during this run, the visible changes were the task-owned `task_plan.md` update plus newly created `findings.md` and `progress.md`.
- Live GitHub metadata confirms `Chiriri722/Termu-inator` is a public fork of `salviz/termux-browser-pilot`; local `origin` and `upstream` point to those repositories respectively.
- Local HEAD is `09b636a97a35042acb0de7f41858d965bc59963f`. The planned baseline `b95eccd3d1abc188c3aa488a23c519ebacc99fcf` is present, is an ancestor of HEAD, and currently matches live `upstream/main`; the only committed delta is the 886-line `task_plan.md`.
- Neither upstream nor the fork has Git tags or a GitHub release. The README's `v0.17.1` string is therefore not backed by an upstream tag/release, and baseline pinning remains partial until a fork-owned baseline tag/document is added.
- `git fsck --full --no-dangling` was clean, and README/LICENSE/pyproject/MCP/setup files are byte-identical to the pinned baseline.

## Attribution and Baseline Documentation

- `LICENSE` preserves the upstream MIT text and the `Termux Browser Pilot Contributors` copyright line.
- Clone-visible fork provenance is missing: README has no parent URL or fork notice, and there is no `NOTICE`, `AUTHORS`, or `docs` directory.
- Baseline metadata is internally inconsistent by inheritance: README says `v0.17.1`, `pyproject.toml` says `0.1.0a1`, no tag/release exists, and package/homepage/MCP names still describe upstream.
- The local `upstream` remote has a push URL identical to its fetch URL. A fail-closed push URL should be considered after documenting the local-only configuration change.
- Clone-visible provenance is now implemented in the README, `NOTICE.md`, and `docs/upstream-baseline.md`; the upstream LICENSE remains byte-identical.
- The baseline document distinguishes the upstream commit date (2026-03-08) from the verification date (2026-08-15) and reserves the fork-owned tag form `upstream-baseline/2026-03-08` without inventing an upstream semantic version.
- A correctly quoted local tag query confirms there are currently no tags. The pinned commit's author and committer timestamp is `2026-03-08T18:41:37+01:00`, supporting the date-based fork-owned tag name.
- The annotated local tag `upstream-baseline/2026-03-08` now peels exactly to `b95eccd3d1abc188c3aa488a23c519ebacc99fcf`; it remains intentionally unpushed.
- README and NOTICE links are internally consistent and keep the exact upstream SHA and copyright visible. README still contains inherited Cloudflare/stealth claims immediately after the new baseline note; the note scopes them as preserved upstream text, while Phase 2 must replace them with explicit non-guarantee product language.

## Current Architecture Snapshot

- A repository-specific fast graph index now contains 988 nodes and 4,550 edges across 26 Python files, two Bash files, and one TOML file.
- There are three executable entry points: `cli.py`, `src/daemon.py`, and `src/mcp_server.py`.
- The current code is a flat `src` package rather than the proposed `src/termuinator` service architecture. The graph exposes 440 functions, 202 methods, and only five browser-oriented test files.
- Structural hotspots confirm the refactor risk described in the plan: MCP helpers `_send` and `_result` each have fan-in 148, `Pilot.evaluate` fan-in 97, CLI transport/output helpers fan-in around 70, and cookie logic is tightly coupled across CLI, pilot, and CDP modules.
- The graph found a single hard-coded CDP discovery route (`http://127.0.0.1:9222/json/version`) and no existing contract-oriented package boundaries.
- Backend startup is centralized in `BrowserPilot.start`, with Chromium-specific `_start_chromium`, `_launch_chromium`, lock cleanup, and CDP wait methods. Backend behavior is not expressed as a formal capability object.
- Eleven tab/window/viewport handlers exist as top-level daemon functions. Their backend branching and unsupported behavior require direct snippet review before being represented in the capability matrix.

## Backend Capability Defects — Tabs

- `_handle_tab_new` and `_handle_tab_close` execute their actual tab keystrokes only when the session has the Firefox-private `_xdt` attribute.
- On Chromium, `tab_new` without a URL returns the current URL/title as a successful result without opening a tab. With a URL it navigates the existing tab. `tab_close` similarly returns the current state without closing anything.
- These are silent capability failures, not structured unsupported errors. The v1 capability contract must fail explicitly until Chromium receives real CDP target handling.

## Backend Capability Defects — Window and Viewport

- `viewport_set` is not a backend-neutral browser operation: it resolves an X11 window, invokes the external `xdotool windowsize` process, reads `session._display`, and only then evaluates the resulting inner viewport.
- `window_list` also delegates to X11-specific window discovery and compares against daemon `_main_wid`; backend support depends on helper behavior and private session attributes rather than an explicit contract.
- These functions can validate dimensions, but they cannot advertise cross-backend support safely until the helper/session requirements are probed and represented as capabilities.

## Backend Capability Matrix — Static Audit

- Current architecture has no capability negotiation, structured `unsupported_capability` error, stable element refs, page revision, permission/confirmation engine, artifact transport, or trace layer.
- Firefox exposes only 16 translated CDP methods; other raw CDP commands raise `NotImplementedError`. Its accessibility tree is a limited DOM heuristic, cookies omit HttpOnly and other-origin data, and event callbacks do not receive true CDP network events.
- Firefox full-page screenshot ignores the requested clip and captures a normal browser window. Firefox PDF returns empty base64 as success, producing a zero-byte file.
- Chromium lacks functional tab shortcut handling, OS window/viewport/mouse/swipe/session-save paths, and the Firefox coordinate fallback for cross-origin iframe clicks because those handlers use Firefox-private X11 members.
- Chromium launch does not connect downloads to the directory queried by `browser_downloads`; both backends return only filename/size/mtime, not completion, MIME, hash, or remotely retrievable bytes.
- MCP `browser_restart` does not preserve a Chromium backend and restarts into default Firefox. MCP auto-start also selects default Firefox rather than negotiating the requested backend.
- UA, geolocation, headers, throttling, response mocking, network/console capture, and related features are largely page JavaScript shims rather than complete browser/network capabilities.
- All 148 MCP tools are exposed without site permissions, consequential-action confirmation, Developer Mode separation, or trace redaction. This validates the plan's tool-surface and policy-boundary priorities.
- These conclusions are source-audit evidence only; every backend capability remains subject to controlled local-fixture and real-Termux validation.

## Packaging Baseline

- `pyproject.toml` still publishes `termux-browser-pilot` version `0.1.0a1`, describes Firefox as passing Cloudflare, links to the upstream repository, and exposes only `tbp` / `tbp-mcp` entry points.
- Supported Python is currently `>=3.10`. The modernization must not accidentally adopt Python 3.12-only syntax before the compatibility decision is explicitly changed in Phase 3.
- Runtime requirements are minimal: base `requirements.txt` contains only `websockets>=12.0`; MCP is an optional `mcp[cli]>=1.0` extra. There is no declared test, lint, typing, or development dependency set.

## Test Baseline — Initial Evidence

- Graph search found no `test_*` function definitions in the five files under `tests/`, indicating they are likely device/browser smoke scripts rather than a conventional unit-test suite. Test runner semantics must be inspected before adding the inventory test.
- `tests/test_basic.py` is a standalone async CDP smoke script with inline assertions and requires a live browser at port 9222; it is not discoverable as a unit test and writes `test_screenshot.png` into the repository root.
- The repository has no offline test harness, so the inventory feature should introduce standard-library `unittest` coverage and avoid adding a network dependency merely to validate static AST parsing.
- MCP tools use the stable syntactic form `@mcp.tool()` followed by thin async functions, allowing exact static extraction without importing the optional MCP package.
- The workstation's default `python3` is CPython 3.9 even though the package declares `>=3.10`; a passing local run alone cannot prove the advertised runtime floor until a 3.10+ interpreter is also exercised.
- Supported interpreters are available separately: all 26 Python files compile on Python 3.11.15, 3.12.13, and 3.14.6; `cli.py --version` succeeds on all three.
- The new inventory unit tests pass on Python 3.11 and 3.14. The bare `python3.12` command is not on this shell's PATH, so the earlier Python 3.12 audit needs its explicit interpreter path before the new tests can be repeated there.
- Using the explicit uv-managed Python 3.12.13 path, the new inventory unit tests also pass (2/2). The feature is now exercised on Python 3.11, 3.12, and 3.14; the declared minimum Python 3.10 remains unavailable and unverified.
- `python3.11 -m unittest discover -s tests -v` currently produces five import errors in a clean base environment because every legacy test imports the optional Chromium/websockets stack; four of the five scripts also execute `asyncio.run(main())` during import.
- The README's claimed five-site Firefox result is not reproducible from checked-in tests: current scripts use Chromium CDP, omit two claimed sites, and depend on external pages.

## Build and Install Baseline

- `bash -n setup.sh start_browser.sh` passes.
- An offline Python 3.11 wheel build, temporary-environment install, and `pip check` pass; the built wheel is `termux_browser_pilot-0.1.0a1-py3-none-any.whl` (145,269 bytes in the audit run).
- The base wheel installs a `tbp-mcp` entry point while `mcp` remains optional, so invoking `tbp-mcp` after a default install fails with `ModuleNotFoundError: mcp`.
- `src/cdp.py` imports `websockets.asyncio.client`, but metadata permits `websockets>=12.0`; that import path is not available in the declared minimum and requires either a dependency floor increase or a compatibility import.
- README's short manual installation path installs system/browser packages and websockets but does not install this project, so it cannot create the documented `tbp` command. `setup.sh` does install the package, but currently suppresses failure of its optional websockets install.
- No CI workflow, dev/test dependency group, test configuration, Python-version file, tox matrix, or lockfile exists.
- The current host is Darwin arm64 without Termux packages, Xvfb/openbox/xdotool/xclip, Firefox/Chromium, or a CDP listener at port 9222. Clean-Termux install, browser smoke, screenshots, device reliability, and performance remain explicitly unverified.
- `docs/environment-baseline.md` now records the exact interpreter paths, offline build procedure, artifact checksum, successful and failed commands, packaging defects, and evidence-level definitions so host checks cannot be mistaken for on-device validation.
- The environment baseline explicitly orders the remaining work: dependency/MCP packaging contracts, version alignment, offline tests/fixtures, manual-test segregation, clean Termux reproduction, per-backend fixtures, device performance, then non-gating public-site observations.
- The working tree currently contains only expected modernization artifacts and edits: README/task plan plus new notice, docs, findings/progress, inventory script, and its unit test. No inherited runtime module has been modified yet.

## Current Surface — Initial Evidence

- `cli.py` alone defines 76 functions, with dozens of daemon-backed `cmd_*_d` wrappers. This already indicates a much larger command surface than the proposed compact v1 API.
- `src/mcp_server.py` exposes a broad one-function-per-tool design. Sample tools include upload, user-agent mutation, viewport mutation, response waiting, window control, OTP entry, and multiple overlapping wait operations.
- Graph output confirms the plan's consolidation targets are grounded in current code rather than hypothetical future work; however, exact counts and classifications still need a deterministic AST inventory rather than a verbose connected-node dump.
- The graph schema records decorators directly on function nodes and includes 153 decoration edges, so decorator-based MCP discovery can be cross-checked without importing the runtime or requiring the `mcp` dependency.
- `cli.main` spans lines 430-1056 (627 lines) and constructs the entire nested argparse surface inline. It defaults `--browser auto` to Firefox and still names the program `tbp`.
- The CLI directly exposes capabilities the target plan places behind Developer/legacy boundaries, including raw eval, upload, geolocation and user-agent overrides, cookie/storage mutation, clipboard access, CSS/header injection, response capture/mocking, throttling, raw set-content, and profile/auth state mutation.
- Daemon dispatch is centralized in `Daemon._dispatch` (`src/daemon.py:198-225`); exact handler enumeration should follow this method rather than guessing from all `_handle_*` names.
- Graph enumeration found exactly 148 `browser_*` functions in `src/mcp_server.py`, versus the planned v1 hard cap of 16 tools (more than nine times the target surface).
- `Daemon._dispatch` resolves actions through a module-level `_HANDLERS` registry and serializes execution with `_cmd_lock`. Unknown actions fail closed with an available-action hint, but all handler exceptions are reduced to `str(e)` without a structured error taxonomy.
- The existing single-command lock is a useful compatibility primitive for the planned single-session MVP; it should be preserved behind the future service layer rather than reimplemented independently.
- The daemon registry is a single literal dictionary spanning `src/daemon.py:5124-5265`, making it safe to enumerate statically with `ast` without importing browser/device dependencies.
- MCP wrappers are thin async functions that generally forward one daemon action through `_send` and normalize it through `_result`; this supports a future compatibility adapter that delegates to one service path rather than duplicating behavior.

## Generated Surface Inventory

- The static AST inventory reports 163 CLI parser entries, 148 decorated MCP tools, and 140 daemon handlers. Independent AST review splits the CLI entries into 25 group containers and 138 executable leaf paths, with 77 top-level parsers and 24 aliases; the script summary must expose these separately to avoid calling containers executable commands.
- MCP/daemon forwarding is internally complete at the literal-action level: there are no MCP actions without handlers, no handlers without MCP exposure, and no MCP tools lacking a statically identifiable `_send` action.
- Migration buckets cover every extracted item. Executable CLI leaf counts are `44 core / 41 developer / 53 legacy / 0 remove`; MCP counts are `53 / 45 / 50 / 0`; daemon action counts are `53 / 36 / 51 / 0` respectively.
- The zero `remove` count means no extracted command currently matches the explicitly removed raw-coordinate-click contract; product claims and stealth implementation still require separate non-surface review.
- Markdown output generation completed successfully without importing runtime modules. Full inventory can be regenerated with `python scripts/inventory_current_surface.py --format markdown`.
- `git diff --check` currently passes for tracked edits. The ordinary diff stat omits new untracked deliverables, so final scope review must use `git status` plus explicit untracked-file inspection rather than relying on diff stat alone.
- The inventory implementation and unit test compile cleanly under Python 3.11 and 3.14 without producing bytecode artifacts.
- CLI reaches 129 of 140 daemon actions. The 11 MCP-only actions are `detect_challenge`, `elements`, `focus`, `mouse_locate`, `mouse_move`, `swipe`, `tab_to`, `type_otp`, `window_close`, `window_list`, and `window_switch`.
- The reviewed inventory now fails closed on dynamic/nested CLI parser construction, dynamic MCP actions, dynamic/unpacked daemon action keys, and duplicate daemon keys instead of silently producing incomplete zero-gap results.
- MCP migration buckets now use the public tool variant name rather than only the multiplexed daemon action, so storage/cookie mutations remain Developer candidates even when they share `storage` or `cookies` handlers.
- CLI output now separates all parser nodes, required command groups, executable leaves, and alias-expanded spellings; classification counts are based on executable leaves.
- The corrected real-checkout totals are 163 parser nodes, 25 required groups, 138 executable leaves, 175 alias-expanded executable spellings, 77 top-level parser choices, and 52 directly executable top-level commands.
- The second-cycle nine-test inventory suite passed on Python 3.11, 3.12.13, and 3.14 after the initial review fixes.

## Backend Capability Matrix Deliverable

- `docs/backend-capabilities.md` records a five-state Firefox/Chromium matrix (`verified`, `partial`, `broken`, `unsupported`, `unverified`) and explicitly keeps static source evidence separate from future Termux device evidence.
- The matrix covers navigation, tabs, screenshots/PDF, cookies/storage, accessibility, downloads, windows/viewport, native input, sessions, restart behavior, network/console shims, and cross-origin iframe fallback. Its 65 local source links were validated against existing files and line bounds.
- It prioritizes silent-success defects, missing capability negotiation, permission/confirmation boundaries, artifact retrieval, structured errors, traces, stable references, and revision preconditions, then provides an on-device checklist for both backends.
- This completes the Phase 1 matrix draft only. Clean Termux installation, `example.com` smoke, and latency/startup/RSS/screenshot-size measurements remain unverified on this non-Termux host.

## Final Inventory Reproducibility Check

- The final thirteen-test inventory suite passes unchanged on Python 3.11.15, 3.12.13, and 3.14.6.
- Two independent JSON generations are byte-identical (`cmp` exit 0) with SHA-256 `9941885a109d73db0cef6af4294519877941c4b74d64883381a3bb56b0662ebe`; Markdown generation also succeeds.
- Python 3.10 grammar parsing succeeds for both the inventory implementation and its tests. A real Python 3.10 runtime remains unavailable, so this is syntax compatibility evidence rather than runtime evidence.
- The final JSON summary preserves the audited totals and reports no MCP tools without literal actions, no MCP actions without daemon handlers, and no daemon actions absent from MCP exposure.
- The preserved upstream `LICENSE`, durable `NOTICE.md`, README fork notice, and exact baseline/change record in `docs/upstream-baseline.md` satisfy the plan's current attribution-preservation criterion; future rewrites must keep those notices intact.
- Final scope inspection shows only the expected Phase 1 artifacts: two tracked edits (`README.md`, `task_plan.md`) and the new notice, three baseline/capability documents, two working-memory files, one inventory script, and one focused unit-test module. No inherited browser/daemon runtime module was edited.

## Inventory Final-Review Findings

- A public MCP tool name could previously hide a more restricted forwarded action: a synthetic `browser_goto` wrapper forwarding `eval` was classified `core`. Classification must combine the tool variant and every forwarded action, never allowing an internal Developer/legacy/remove action to be promoted into Core.
- Dynamic CLI `required` and `aliases` keyword values were previously treated as false/empty rather than unresolved. This could turn a required group into a leaf or silently remove executable alias spellings, so both keywords must accept only statically verifiable literal values.
- A third TDD RED cycle added one test for the MCP/action mismatch and two tests for dynamic CLI keyword values. All three fail for the intended missing behaviors while the prior nine tests remain green.
- The third GREEN implementation combines each MCP wrapper name with every forwarded action using default-exposure restrictiveness (`core < legacy < developer < remove`) and rejects non-literal CLI `required`/`aliases` values.
- The first three final-review regressions brought the suite to 12 tests; all passed on all three supported interpreters before the keyword-unpacking case was added.
- CLI parser keyword unpacking (`**kwargs`) is now also rejected before extraction because it could conceal both `aliases` and `required`; the two-case regression test raises the final isolated suite to 13 tests.
- Current broad discovery runs 18 tests: all 13 dependency-free inventory tests pass, while the five inherited live-CDP modules still fail import without `websockets`. The environment document now describes this mixed suite rather than treating every checked-in test as manual-only.
- Final matrix verification passes all 13 tests on Python 3.11.15, 3.12.13, and 3.14.6 (39 interpreter/test combinations); Python 3.10 grammar parsing passes, the real totals remain unchanged, and repeated JSON retains SHA-256 `9941885a109d73db0cef6af4294519877941c4b74d64883381a3bb56b0662ebe`.
- Independent final inventory review found no remaining blocker or non-blocking style issue.
- Final documentation review found all 87 local Markdown links resolvable and all 77 source-line anchors/ranges in bounds. Exactly three Phase 1 gates remain open, matching the real-device evidence gap.
