# Progress: Termu-inator Modernization

## 2026-08-15

### Phase 1 — Fork Baseline & Discovery

- Created `findings.md` and `progress.md`, which were required by `task_plan.md` but absent.
- Read the planning-with-files operating rules and began repository discovery from the existing plan.
- Checked the Codex memory registry; no prior Termu-inator implementation history was available.
- Read all 886 lines of `task_plan.md` and extracted the product, architecture, security, testing, performance, and seven-phase exit gates.
- Updated `task_plan.md` to mark the three planning artifacts complete, advance the Phase 1 next step, and record the missing-companion-file error and resolution.
- Checked Git status: `main` tracks `origin/main`; current visible changes are limited to the planning artifacts touched in this task.
- Attempted architecture discovery through the code graph; recorded that a repository-specific index must first be created.
- Created a fast repository graph index (988 nodes, 4,550 edges) and captured the initial architecture, entry-point, hotspot, language, and file-tree baseline.
- Queried CLI and MCP function surfaces through the graph. The first broad query was too verbose and was logged; subsequent inventory work will use aggregate graph queries and a deterministic AST script.
- Inspected graph schema for function/decorator metadata. A complex aggregate query failed in the graph parser and was logged; the inventory implementation will avoid depending on that query syntax.
- Located the 627-line inline CLI parser and the centralized daemon `_dispatch` method through graph search, establishing the AST patterns the inventory script must recognize.
- Counted 148 current `browser_*` MCP functions and inspected daemon registry dispatch/serialization behavior through focused graph queries.
- Located the literal `_HANDLERS` registry and confirmed that MCP wrappers are thin transport adapters, finalizing the static inventory extraction strategy.
- Reviewed packaging and dependency metadata; recorded the current Python 3.10 floor, legacy project identity/claims, entry points, and absence of development tooling dependencies.
- Verified the public fork relationship, exact upstream baseline SHA/ancestry, clean object database, absence of tags/releases, preserved MIT license, and missing clone-visible fork notice.
- Marked only the factually complete fork-repository checkboxes; baseline tag and attribution checks remain pending.
- Refreshed the Phase 1 gate before implementation and confirmed the existing `tests/` files expose no graph-indexed `test_*` functions.
- Inspected the existing live-browser smoke style and MCP decorator form; selected dependency-free `unittest` plus static AST parsing for the inventory feature.
- Added `tests/test_inventory_current_surface.py` first (TDD RED), defining static CLI/MCP/daemon extraction, cross-surface mismatch reporting, and migration-bucket classification behavior before production implementation.
- Ran the RED test: it failed at import because `scripts.inventory_current_surface` does not yet exist (exit 1), confirming the feature is absent. Also recorded that the default interpreter is Python 3.9.
- Added an intentionally minimal `scripts/inventory_current_surface.py` import skeleton so the next RED run can fail on behavior assertions rather than module loading.
- Re-ran the inventory tests: both now fail on the intended behavior assertions (empty extraction and legacy-only classification), establishing a valid RED state.
- Added clone-visible fork attribution and baseline evidence via `README.md`, `NOTICE.md`, and `docs/upstream-baseline.md`; `git diff --check`, baseline ancestry, and unchanged LICENSE checks passed.
- Completed a read-only build/test audit across Python 3.11/3.12/3.14 and an offline wheel install. Recorded verified successes separately from missing-dependency failures and device-only unverified checks.
- The first large inventory implementation patch failed before editing due to a JavaScript escape error; the failure was logged and the minimal skeleton remains intact.
- A corrected replacement patch was also rejected because `apply_patch` does not allow Delete+Add for the same path in one operation; no file content changed, and the replacement is being split safely.
- Replaced the inventory skeleton with a static AST implementation covering nested CLI commands/aliases, decorated MCP tools and forwarded actions, daemon handler registry, cross-surface mismatches, deterministic JSON/Markdown output, and fail-safe migration classifications.
- Ran `PYTHONDONTWRITEBYTECODE=1 python3.11 -m unittest tests.test_inventory_current_surface -v`: 2 tests passed, completing the first RED-to-GREEN cycle.
- Ran the inventory on the real checkout: 163 CLI entries, 148 MCP tools, 140 daemon handlers, zero MCP/daemon mapping gaps, and every item assigned to a migration bucket.
- Verified the Markdown CLI output path by generating `/tmp/termu-inator-current-surface.md` successfully; no repository artifact was created by that check.
- Marked the Phase 1 inventory and initial classification tasks complete and advanced the next step to baseline tagging/capability/install evidence.
- Ran `git diff --check` successfully; noted that the current tracked diff stat covers README/task-plan edits only and does not yet represent untracked deliverables.
- Reviewed `docs/upstream-baseline.md`; its SHA, dates, fork relationship, no-tag caveat, reproduction commands, version inconsistencies, and attribution links match the audit evidence.
- The first tag-list command failed because zsh interpreted an unquoted format expression; the error was recorded and no refs changed.
- Re-ran the tag query successfully (empty) and verified the full baseline commit timestamp and subject before any local tag operation.
- Created the local annotated fork-owned tag `upstream-baseline/2026-03-08` at the pinned baseline commit; it has not been pushed to any remote and awaits pointer verification.
- Verified the tag object type is `tag` and its peeled target is the exact baseline SHA. A combined documentation/status patch was rejected on context mismatch and is being reapplied in smaller pieces.
- Updated the baseline document with the verified fork-owned local tag and marked the Phase 1 remote/commit/tag task complete; no remote tag was pushed.
- Ran the new inventory tests on Python 3.14: 2 passed. The parallel Python 3.12 invocation failed before testing because `python3.12` is not on PATH; this environment issue was logged for explicit-path retry.
- Re-ran the inventory tests with the explicit uv-managed Python 3.12.13 interpreter: 2 passed, resolving the PATH-only failure.
- Reviewed the first 300 lines of `docs/environment-baseline.md`; its evidence levels, host identity, interpreter paths, syntax/shell/CLI checks, offline wheel install, failed MCP/test collection checks, and packaging defects match the audit evidence.
- Finished reviewing `docs/environment-baseline.md`, including all explicit device/performance unknowns and ordered next steps, and marked the Phase 1 defect/document-discrepancy recording task complete.
- Reviewed the README fork notice, final license links, and `NOTICE.md`; provenance and attribution are coherent, while inherited anti-bot claims remain deliberately identified as baseline text pending Phase 2 wording changes.
- Located the backend startup methods and all eleven tab/window/viewport daemon handlers through the code graph as inputs to the capability matrix audit.
- Inspected `tab_new` and `tab_close`: confirmed Firefox-only `_xdt` execution and Chromium silent-success/no-op behavior, recorded as a capability defect.
- Inspected `viewport_set` and `window_list`: recorded their X11/xdotool and private-session dependencies for the capability matrix.
- Capability 감사 결과 통합 패치가 heading context 불일치로 편집 전 거부되었으며, 작은 패치로 재적용한다.
- Completed the independent graph+AST surface/capability audit. Corrected the CLI interpretation to 138 executable leaves plus 25 group nodes and recorded Firefox/Chromium silent-success, broken, partial, and unsupported behaviors for the matrix.
- Added second-cycle RED assertions for parser/group/leaf counts, group-alias leaf spelling expansion, MCP variant-sensitive classification, dynamic CLI/MCP/daemon names, duplicate daemon actions, and nested parser construction. Production code has not yet been changed for these review findings.
- Ran the second RED cycle on Python 3.11: 9 tests ran, 8 failed for the intended missing behaviors and the original classification unit test remained green. No unexpected import or syntax errors occurred.
- Implemented the review fixes and ran the second GREEN cycle on Python 3.11: all 9 tests passed. Parser/group/leaf semantics, alias propagation, variant-sensitive classification, and strict unresolved/duplicate guards are now covered.
- Re-ran the strict inventory on the real checkout successfully and recorded the corrected 163 parser / 25 group / 138 leaf / 175 spelling totals plus updated migration-bucket counts.
- Re-ran all 9 inventory tests on Python 3.12.13 and 3.14: both matrices passed, matching Python 3.11.
- Rechecked repository scope: all visible changes are expected Phase 1 planning, attribution, baseline-documentation, inventory, and test artifacts; inherited runtime modules remain untouched.
- Performed in-memory syntax compilation of the new script and test on Python 3.11 and 3.14: both interpreters reported `syntax-ok 2`.
- Reviewed the complete 255-line Firefox/Chromium capability matrix and its evidence boundaries; the independent audit validated all 65 local source links.
- Marked the Phase 1 capability-matrix task complete and advanced `Next Step` to the three remaining real-Termux installation, smoke, and performance gates.
- Re-ran all nine inventory tests on Python 3.11.15, 3.12.13, and 3.14.6; all 27 interpreter/test combinations passed.
- Generated the strict real-checkout JSON twice and confirmed byte identity with SHA-256 `9941885a109d73db0cef6af4294519877941c4b74d64883381a3bb56b0662ebe`; Markdown output generation also passed.
- Parsed the new script and test with Python 3.10 grammar mode successfully; actual Python 3.10 runtime execution remains unavailable and is not claimed.
- Reconciled the plan's global compatibility/delivery checklist with the completed attribution artifacts and marked only the MIT/original-author/fork-change preservation criterion complete.
- Re-ran tracked and per-file untracked whitespace checks with no diagnostics, confirmed no bytecode artifacts, and reviewed the complete tracked diff and plan checkbox state.
- Re-indexed the code graph (1,016 nodes / 4,612 edges). The graph intentionally excludes `scripts/`, so focused local source inspection was used only for the new inventory script after graph-backed test discovery.
- Added three final-review regression tests before implementation: a Core-named MCP wrapper forwarding Developer `eval`, dynamic CLI `required`, and dynamic CLI `aliases`.
- Ran the third RED cycle on Python 3.11: 12 tests ran, exactly the three new tests failed, and the previous nine remained green.
- Implemented fail-safe MCP name/action combination and literal CLI keyword validation; all 12 tests passed on Python 3.11.
- Re-ran all 12 tests on Python 3.12.13 and 3.14.6, regenerated deterministic JSON/Markdown, and rechecked Python 3.10 grammar. All checks passed; the real inventory JSON hash and audited counts remained unchanged.
- Added a two-case `**kwargs` parser regression test, observed both intended RED failures, then rejected keyword unpacking for static parser extraction and confirmed the targeted GREEN result.
- Re-ran broad `unittest discover`: all 13 inventory tests passed while the five inherited CDP modules retained their known `websockets` import errors (18 total, exit 1). Updated `docs/environment-baseline.md` to record the mixed automated/manual test state accurately.
- Completed the final Python 3.11/3.12.13/3.14.6 matrix with 13/13 passing on each interpreter, plus Python 3.10 grammar parsing, deterministic JSON/Markdown generation, and unchanged audited counts/checksum.
- Received final independent inventory approval: no blocker or style issue remains after the MCP/action, literal keyword, and `**kwargs` fail-closed fixes.
- Completed a final independent documentation/scope review: 87/87 local links and 77/77 line anchors passed, all whitespace checks passed, and Phase 1 correctly retains exactly three device-only unchecked gates.

### Verification

- `task_plan.md`: present, 886 lines.
- `findings.md`: created.
- `progress.md`: created.
