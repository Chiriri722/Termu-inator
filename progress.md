# Progress: Termu-inator Modernization

## 2026-08-24

### Shared View RED → GREEN Cycle 1

- Added RED coverage for a bounded value-only pending-confirmation list, cached/idle/confidential service snapshots, current screenshot retrieval, loopback-only binding, Host-header rejection, security headers, a two-second static dashboard, and the absence of HTTP mutation controls.
- The intentional Python 3.12.13 RED run executed 8 tests: 6 existing confirmation tests passed, while the new confirmation case failed on missing `list_pending()` and the shared-view module failed to import. Both expected gaps are recorded in `task_plan.md`.
- Added a newest-first, 64-entry-bounded `ConfirmationEngine.list_pending()` that refreshes expiry and returns public `Challenge` values only.
- Implemented `SharedViewState`, verified PNG/WebP `SharedViewArtifact`, and a dependency-free loopback HTTP server with GET/HEAD-only routing, strict Host validation, 16 KiB request-header bounds, no request bodies, no-store/CSP/anti-embed headers, external static assets, and no approval or control endpoints.
- Added local service projections for idle, active, and confidential takeover states. Active snapshots use only cached status, the last observation, bounded pending confirmations, and 20 recent durable traces; screenshot reads accept only the current observation's verified artifact and stop entirely during takeover.
- The targeted suite is GREEN at 14 tests on Python 3.12.13 with warnings promoted to errors. The first retries exposed and then removed a non-ASCII bytes-literal syntax error and a JavaScript Unicode-escape warning.
- Added the next RED layer for trusted runtime composition and startup lifecycle. The Python 3.12.13 runtime suite produced the expected two errors for the absent optional server field and builder flag; default-OFF behavior and explicit startup remain the implementation target.
- Integrated the viewer into `CompactRuntime` as an optional server over the exact same `BrowserService`. `tbp-mcp-v1 --shared-view [--shared-view-port PORT]` is the sole startup path, remains default OFF, binds literal `127.0.0.1`, reports its URL on stderr only, and closes before the owner-local control socket during stdio shutdown.
- Added stable, value-free pending permission challenges for `ASK` origins and clear them only after the local host records allow/block. This completes the dashboard's pending permission and confirmation summaries without adding an HTTP approval route.
- Added defense-in-depth redaction for shared-view URL credentials/query/fragment and credential-shaped page titles at both service composition and HTTP serialization boundaries.
- Shared-view confirmation/service/HTTP/runtime verification is GREEN at 20 tests on Python 3.12.13 with warnings as errors; the pinned Python 3.11.15 + MCP 1.29 stdio lifecycle suite is GREEN at 6 tests. Navigation/action/permission regressions are also GREEN at 17 tests.
- Minimized the HTTP prompt projection further: challenge IDs remain server-side and only kind/state/redacted preview/expiry are visible. The expanded shared-view/navigation/action/permission/runtime matrix is GREEN at 36 host tests plus 6 pinned-MCP tests.
- Updated `README.md`, `docs/termux-install.md`, `docs/architecture.md`, `docs/security-model.md`, and `task_plan.md` with the explicit startup flags, stderr-only URL, Mac-to-Termux SSH local forwarding, default-OFF/literal-loopback boundary, confidential suppression, and the fact that direct Tailnet HTTP binding remains unimplemented.

### DOM Replacement Fixture RED → GREEN Cycle 1

- Added RED coverage for a deterministic same-semantics node replacement route and for the registry invariant that a changed private node identity always receives a fresh public ref. The registry test was already GREEN; both fixture tests returned the expected 404 until the new route is added.
- Added `/stale-replacement` and its manifest entry. The page replaces the target node identity while preserving its button semantics and reports a deterministic generation counter; fixture and element-ref suites are GREEN at 9 tests on Python 3.12.13 with warnings as errors.

### Legacy Stable Observe/Act RED → GREEN Cycle 1

- Added RED adapter coverage for bounded DOM normalization with repeat-stable private handles, click/type dispatch through fresh handle coordinates, typed before/after evidence, and disconnected-handle rejection before input. The intentional run produced three failures at the existing empty-interactive and unsupported-action boundaries; seven inherited adapter tests remained GREEN.

### Phase 1 — Device Evidence Synchronization

- Confirmed the worktree is clean at `df0330207df94c5ac20d74c91c630826b5c065e6` and matches `origin/main`; upstream `main` remains at the pinned `b95eccd` baseline.
- Re-ran the 13 inventory tests successfully on Python 3.11.15, 3.12.13, and 3.14.7; the workstation default Python 3.9 run also passed but is not support-floor evidence.
- Verified the three S22U raw files against their device/Mac SHA-256 manifests.
- Inspected the raw report schema and recorded two failed `jq` assumptions before switching to the real `.backends[]` representation.
- Added `docs/device-baseline-s22u-2026-08-16.md` with sanitized smoke, performance, RSS, network-root-cause, evidence-level, and integrity information.
- Marked the Firefox/Chromium `example.com` smoke and performance baseline Phase 1 items complete. Clean isolated Termux installation remains open.
- Locked the approved implementation decisions in `task_plan.md`: split CLI/MCP venvs, Chromium default, project-scoped persistent profiles, single active session, static read-only shared view, Developer-only raw eval, compact-MVP upload exclusion, and v0.x public-name retention.

### Packaging RED → GREEN Cycle 1

- Added `tests/test_packaging_contract.py` before implementation. The intentional RED run produced nine assertion failures and one missing-file error, all mapped to existing packaging defects: dependency floors, unbounded MCP extra, anti-bot metadata, direct MCP entrypoint, unsafe installer behavior, absent venv split, absent native-cryptography guard, and absent Termux constraints.
- Updated metadata to use `websockets>=13,<18`, pin `mcp==1.29.0` without the CLI extra, remove the Cloudflare-success description, and point fork-owned URLs at `Chiriri722/Termu-inator` while preserving an explicit upstream URL.
- Added `requirements-termux.txt` with only the validated MCP and websockets pins; `cryptography` remains a Termux-native package and is intentionally absent.
- Added `src/mcp_entrypoint.py`, which turns a missing optional MCP dependency into a concise stderr message and exit code 2 instead of a traceback.
- Replaced the global pip installer with a fail-closed Termux installer that refuses existing target venvs, installs native dependencies visibly, creates separate CLI/MCP venvs, reuses and verifies Termux cryptography, constrains pip from building cryptography, runs `pip check`, and prints the exact Hermes command path.
- Added a second two-assertion RED cycle for the residual `cloudflare` keyword and the unproven `mcp.__version__` attribute, then removed the keyword and switched installer verification to `importlib.metadata.version("mcp")`.
- The first GREEN retry caught the `metadata` import in the wrong installer heredoc. Moved it into the MCP verification block and avoided escaped quotes inside an f-string expression.
- Packaging contract tests reached GREEN (11/11), shell syntax passed, and `git diff --check` passed. The host Python lacked the optional `build` module, so artifact validation is moving to a disposable venv rather than modifying the workstation interpreter.
- The first disposable-build command was rejected before execution because its cleanup trap contained recursive deletion. No files were created; the retry keeps the `mktemp` directory and reports its path instead.
- Built wheel and sdist successfully in `/tmp/termuinator-package.g6Khv1`; base install, `pip check`, `tbp --version`, and guarded `tbp-mcp` error all passed. MCP extra installed exact MCP 1.29.0 and websockets 17.0.1 and passed imports.
- Corrected the stdio probe design after its first `communicate()` call supplied EOF. With stdin kept open, `tbp-mcp` remained live for three seconds, but Pydantic Settings emitted a 431-byte incomplete-forward-reference warning to stderr.
- Confirmed under `PYTHONWARNINGS=error` that `Settings.model_rebuild()` before `FastMCP(...)` resolves the warning; added a third RED regression for initialization order and stale anti-bot instructions.
- The first isolated invocation of that regression used a slash in the unittest module name and failed in the loader before testing behavior; the retry uses dotted module notation.
- The corrected isolated RED failed on the intended missing `Settings.model_rebuild()` call. Added the rebuild before FastMCP construction and replaced MCP startup instructions with observe-first, verify-after-act, untrusted-page, capability-aware language.
- Packaging contract tests are GREEN at 12/12. With the source checkout on `PYTHONPATH`, MCP import passes under `PYTHONWARNINGS=error`, and stdio remains live for three seconds with zero stdout/stderr bytes.
- Disposable artifact evidence: wheel SHA-256 `d18f432a1c34d339ab2be91a6155cc4761e928af962f9c7dbaa5667d798c98eb`; sdist SHA-256 `3c465dd03af96c0ea2e7713894ba16bde494cdc7bd36cdac131c95cca0d2326c`. These are pre-final artifacts and remain under `/tmp/termuinator-package.g6Khv1`.

### Portable Device Benchmark RED → GREEN Cycle

- Added `tests/test_benchmark_device.py` first; the intended RED failed because `scripts.benchmark_device` did not exist.
- Added `scripts/benchmark_device.py` with parameterized project/tbp/output/socket/PID/URL/backends/sample counts, private raw diagnostics, a path/PID/process-argument-free sanitized summary, Termux `ps` fallback, strict daemon cleanup, and no device-specific absolute paths.
- The portable benchmark tests passed 3/3, and sanitizing the transferred S22U raw report reproduced every documented latency/RSS/screenshot aggregate while excluding device paths, PIDs, and process arguments.
- Added installation documentation assertions first. The intended RED found the absent authoritative guide and the README's broken manual-install path.
- Added `docs/termux-install.md` covering non-overwrite behavior, dual venvs, native cryptography, exact Termux pins, stdio verification, Hermes configuration, Tailscale state, both browser smokes, portable benchmark usage, and the still-open clean-install gate. Routed README Quick Start and MCP instructions to it.
- Located the Mac Tailscale app CLI and verified `galaxy-s22-ultra` is online (`100.75.81.89`, 106 ms direct ping). Read-only TCP probes found no SSH listener on ports 22 or 8022, so the Secure Folder gate cannot be driven from this checkout without a new device-side access action.

### Phase 2 — Contract RED → GREEN Cycle 1

- Added `tests/test_v1_contracts.py` first; the intended RED failed because the internal `src.termuinator` namespace did not exist.
- Added dependency-free contract enums/dataclasses, strict page revision parsing, fail-closed DOM revalidation rules, action target/timeout validation, stable error codes, capability/artifact/permission models, and JSON wire conversion under `src/termuinator/`.
- Added a generated contract schema and exact 14-tool manifest source with Chromium default, required project ID, 512 KiB artifact chunks, read-only permission inspection, Developer-only devtools, and no compact eval/upload tools.
- Checked in minified JSON snapshots for the common contracts and tool manifest. Tests compare parsed JSON structures rather than formatting, so schema changes require an explicit reviewed snapshot update.
- Added architecture, tool-contract, and security RFCs covering all six acceptance flows, session/profile/backend choices, ref/revision rules, verification, error taxonomy, permissions, 120-second one-shot confirmation, 512 KiB artifact reads, retention, read-only view, Developer/legacy isolation, and v0.x compatibility.
- Snapshot structures passed immediately; the RFC boundary test caught one capitalization-only phrase drift, which was normalized to the canonical `project-scoped persistent profiles` wording.
- Added a final Phase 2 RED for missing backend target rules and migration lifetime. Documented Chromium default/Firefox explicit selection, forbidden fallback, structured unsupported behavior, capability vocabulary, v0.1/v0.2 legacy availability, possible v0.3 legacy removal, and separate v1 naming migration.
- The first migration-doc GREEN retry found a line-wrap-only canonical phrase mismatch; normalized it without changing the migration policy.
- Moved build-generated `termux_browser_pilot.egg-info` out of the checkout into the preserved packaging temp directory; no build artifact remains in the repository status.
- Re-indexed the current worktree into the code graph (1,297 nodes / 5,431 edges) so subsequent refactor discovery includes the new contract package.
- Ran the package, benchmark, and v1 contract suites together on Python 3.11: all 29 tests passed.
- Loaded the bundled `agbrowse` Web AI operating guide, checked CLI/provider help, and verified the project-scoped ChatGPT browser state before mutation.
- Dry-ran the seven-file RFC/schema context package: 39,833-byte ZIP, about 19,082 estimated tokens, no exclusions or warnings, and no device evidence or secrets included.
- Sent an adversarial architecture/security review through durable session `01M0RAP74JAS45CND4TSGX55G4`. The initial selector-based model check was inconclusive, but a read-only accessibility snapshot subsequently verified the active `Pro` tier and `Pro 생각 중` state.

### Phase 2 — Contract RED → GREEN Cycle 2

- Added four security/shape regressions before implementation. The intended RED produced two failures and two missing-schema-key errors for caller risk downgrade, sessionless artifact reads, target-ref conditions, and multiplexed operation preconditions.
- Made `ActionRequest.risk` a server-owned action-kind minimum. Untrusted `risk_context` can no longer lower the result; the future policy engine may only raise it after target/effect inspection.
- Bound `browser_artifact_read` to an active `session_id` and documented project-ownership verification rather than treating an unguessable content hash as authority.
- Replaced permissive nullable multiplexed fields with operation-specific `oneOf` schemas for navigation, tabs, screenshots, permission challenge inspection, and trace retrieval/export. Added an `ActionRequest` conditional requiring a valid observed ref for every target action.
- Updated the tool/security RFCs and the stale shared-view plan checkbox to preserve the approved static read-only boundary.
- Regenerated both reviewed JSON snapshots mechanically. The v1 contract suite is GREEN at 16/16.
- Validated the common contract schema plus all 28 tool input/output schemas against Draft 2020-12 using the preserved disposable MCP venv (`jsonschema 4.26.0`): `schema-ok contracts=1 tools=14 io=28`.
- Re-ran the complete dependency-free inventory/packaging/benchmark/contract suite: 46/46 passed on Python 3.11.15, 3.12.13, and 3.14.
- The first durable watcher terminated on its per-poll deadline with an empty answer even though Pro was still reasoning. Reused the same persisted session with a longer direct poll; no prompt or attachment was resent.
- Recovered and triaged the complete Pro review. Contract freeze remains deliberately open while its independently reproducible blocker/high findings are converted into RED tests and corrected schemas/RFCs.

### Phase 2 — Contract RED → GREEN Cycle 3

- Added ten independent contract-freeze regressions for manifest versioning, strict tool outputs, self-contained MCP schemas, the exact action union, terminal action results, code-owned retryability, capability fidelity, artifact lifetime, permission-state validity, and observation revision/capability binding.
- The intended RED run produced six failures and four errors, confirming that the prior generic schemas and boolean capability flags did not yet satisfy the reviewed boundaries.
- Reworked the dependency-free contracts and schema generator around explicit capability records, opaque revision-bound observations, exact action branches, server-side confirmation identifiers, content-addressed artifacts, crash-safe error states, and strict per-tool outputs.
- Added a companion manifest schema and an actual MCP Tool projection with self-contained `inputSchema`/`outputSchema` documents pinned to protocol revision `2025-11-25`.
- Replaced stale snapshots with generated `contracts.schema.json`, `tool-manifest.schema.json`, and `tool-manifest.json`. Draft 2020-12 check-schema validation passed for all three contract surfaces, the manifest instance, and all 28 projected MCP input/output schemas.
- Aligned the dependency-free Python models with the frozen wire fields: typed capability limits, full causal verification records, `diagnostics_id`, code-owned retryability, opaque ID checks, and closed action-parameter validation.
- Added full page precondition coverage and observed the intended RED only on all eight `browser_act` branches. Added `tab_id` to the model and schema, regenerated snapshots, and restored GREEN.
- Added a backend/profile-schema isolation RED showing that Chromium and Firefox shared one profile path. The core now uses `<project-digest>/profiles/<backend>/v1/profile` while retaining 0700, symlink, and root-containment checks.
- Corrected actual MCP annotations after a RED proved `browser_act` contradicted its durable idempotency contract. Its `idempotentHint` is now true.
- Updated architecture, tool, security, backend capability, and task-plan prose for server-held approvals, MCP protocol-vs-tool errors, confidential takeover, owner scope, HTTP(S)/redirect/private-network policy, durable idempotency, capability fidelity, shared-view controls, and browser/profile trust boundaries.
- Validated representative `Observation`, `ActionRequest`, `ActionResult`, `Artifact`, and `PermissionDecision` `to_wire()` payloads—including date-time formats—against their checked-in Draft 2020-12 definitions.
- The focused contract/schema/core suite is GREEN at 46/46, and the full dependency-free Python 3.11 suite is GREEN at 74/74 before the final two regression additions. Cross-interpreter verification remains open before M1 can be frozen.

### Phase 3 — Typed Service RED → GREEN Cycle 1

- Added six lifecycle tests first. The intended RED failed at import because the backend/core packages did not exist.
- Added a structured `TermuinatorError`, full typed `BrowserBackend` protocol, deterministic lifecycle fake, and backend-neutral `BrowserService`.
- The service defaults to Chromium, never falls back after an explicit backend failure, allows one active session, serves status from the backend's in-memory cache, hashes project identifiers before filesystem use, creates 0700 profile directories, and rejects symlink/escape candidates.
- The focused core service suite is GREEN at 6/6. This is a local service/fake milestone, not evidence that real Firefox/Chromium adapters or compatibility smoke already pass.

### Phase 3 — Contracts, Configuration, and Lifecycle RED → GREEN Cycle 2

- Replaced private service result duplicates with the frozen public `SessionStartResult`, `SessionStatus`, and `SessionStopResult` models, then tightened their runtime validation and exact wire shape.
- Made transport-established owner scope a required service constructor input and domain-separated it with project ID before hashing. Profiles are now isolated by owner/project digest, backend, and profile-schema version.
- Added a dependency-free, frozen runtime config with safe defaults; bounded 0600 JSON loading; `O_NOFOLLOW`; a closed key set; absolute data-root validation; and strict backend, schema, quota, retention, and chunk-size bounds.
- Added `LegacyPilotBackend` as an explicit-backend lifecycle strangler. It injects the inherited `Pilot`, preserves start/stop and cached status, and returns structured `unsupported_capability` for every operation not yet migrated.
- Reproduced and fixed the duplicate Openbox launch in the inherited Xvfb lifecycle. Added start-time Chromium binary discovery for Termux package-name variants while ensuring an explicit binary never falls back silently.
- Added an O(1) daemon status cache updated by lifecycle/navigation handlers. The Firefox status handler no longer performs native page URL/title evaluations and exposes monotonic freshness instead.
- The combined configuration, adapter, lifecycle, daemon-cache, and service suites reached GREEN at 23/23 before the native text-path optimization cycle.

### Firefox Native Text Latency RED → GREEN Cycle

- Traced warm text observation through the Firefox DevTools-console bridge and found a fixed 500 ms sleep after `Ctrl+Return`, before checking an already available local callback result.
- Added a deterministic native-session test first. Its RED recorded `[0.1, 0.2, 0.5]`, proving the unconditional post-execute delay without launching Firefox or X11.
- Removed only the fixed post-execute sleep. The callback/clipboard is now polled immediately; the existing bounded 300 ms wait remains between unsuccessful poll attempts.
- The focused regression is GREEN at 1/1. This removes 500 ms from the source path under the tested condition but does not close the S22U `text <= 2s` performance gate until it is remeasured on device.

### Phase 3 — Trusted Composition and Core Storage Boundaries

- Added a RED composition test proving the validated runtime config was not wired into any service. Added `build_legacy_browser_service()` to bind trusted owner scope, configured default backend/profile schema, and explicit Firefox/Chromium lifecycle factories.
- Made `BrowserService` require `default_backend` and `profile_schema_version`; removed its duplicate schema constant and made an omitted session-start backend select the validated configured value. Composition plus existing service tests are GREEN at 10/10.
- Added schema-aligned `ArtifactChunk` and `TraceRecord` runtime models with monotonic offsets, validated bounded base64, exact typed trace fields, opaque IDs, causal revision type, aware timestamps, and duration bounds.
- Added explicit `ArtifactStore`, `TraceRecorder`, and `PermissionEngine` protocols with deterministic bounded in-memory implementations. Artifact reads require active-session authorization before lookup, chunk/offset bounds, expiry, and project quota; traces accept only the closed typed record; session permissions are canonical-origin scoped and cleared with the session.
- The storage-boundary RED initially stopped on the two schema-only missing runtime models. After the typed models and interfaces were implemented, all 3 focused tests passed. This completes the Phase 3 basic harness only; durable 0600 content-addressed files, persistent permissions, and durable trace retention remain Phase 5 work.

### Phase 3 — Raw Backend Snapshots and Process Lease

- Found that the initial backend protocol incorrectly required adapters to mint public `Observation` identity owned by the service. Added `BackendPageSnapshot` and changed navigate/observe return types so adapters provide only URL/title/ready-state/viewport/text/accessibility data.
- Migrated explicit legacy `goto` with millisecond-to-second timeout conversion and bounded text/accessibility observation. Navigation is now advertised as `partial` (`goto` only), observation as `partial` (no stable refs or screenshot artifacts), and all other unported operations remain structured `unsupported_capability` failures.
- Added a RED adapter test before the raw snapshot existed. After implementation, one prior lifecycle assertion correctly failed because it still expected navigation to be unsupported; it now checks the partial fidelity limits. The adapter suite is GREEN at 5/5.
- Added `ProcessSessionLock`, a private 0600, `O_NOFOLLOW`, non-blocking `flock` lease with owner-scope hashing. Kernel ownership makes crash recovery automatic and avoids trusting PID reuse or deleting another process's lock file.
- Made the lease a mandatory `BrowserService` dependency. It is acquired before profile/backend startup, held for the active session, released after stop, and released on every startup failure. The trusted composition root supplies the process lock under the configured data root.
- Process-lock, service, and runtime-composition suites are GREEN at 13/13. This closes the Phase 3 single-session manager/lock item; inherited `Pilot` still carries a redundant compatibility lock until transport migration removes the duplicate path.
- The complete dependency-free Python 3.11 regression set is GREEN at 102/102 after the contract models, raw snapshot protocol, process lease, and native latency changes. `git diff --check` also passes; live-CDP scripts remain a separate device/browser gate.

### Phase 4 Foundation — Observation Identity and Stable Refs

- Added finite/non-negative geometry and bounded public interactive-element validation. Introduced `RawInteractiveElement` so private backend node handles never appear in public `InteractiveElement` records.
- Added `ElementRefRegistry` with random opaque refs, stable reuse for unchanged semantics, invalidation when the same handle changes role/name/path semantics or disappears, document-epoch rotation, and low-risk fingerprint revalidation rules. Frame and shadow paths are preserved and fingerprint-bound.
- Added `ObservationEngine` to mint session-owned page/tab IDs, sequence numbers, document epochs, mutation counters, canonical origins, viewport fallback, timestamps, capability revision, and public refs around backend snapshots. Its focused ref/observation suites are GREEN at 5/5.
- Connected read-only `BrowserService.observe()` to the engine and fake backend. Session-start status now exposes the initial page context; stale tab/page/revision checks happen before backend I/O. The service suite is GREEN at 11/11 after updating one stale nullable-status assertion.
- Navigation remains deliberately unwired at the service boundary until an adapter can enforce origin policy before every redirect follow. The inherited direct adapter supports `goto` only as a partial compatibility capability and is not yet a safe compact-v1 navigation path.
- Added `BackendAction`, `BackendActionEvidence`, and `BackendActionOutcome` so adapters receive only resolved private node handles and return closed raw effects rather than public success claims.
- Added `ActionExecutor` with pre-dispatch session/tab/page/revision validation, private destination-ref resolution for drag, post-action observation capture, secret-value redaction, and service-owned causal verification. The focused executor suite is GREEN at 7/7: all eight closed action kinds, stale revision, current-revision stale ref, both drag handles, URL change, download, and non-causal dispatch failure are covered.
- Re-indexed the repository graph after the Phase 4 additions (1,896 nodes / 8,737 edges). No durable idempotency implementation exists yet, so public action transport wiring remains blocked on the journal and confirmation boundary.
- Added seven durability/security tests before implementation for semantic action digests, terminal replay after restart, private file modes and identifier hashing, digest conflict, interrupted-dispatch recovery, waiting-confirmation recovery, transition ordering, and symlink refusal. The intended RED is a missing `core.idempotency` module import.
- Implemented `DurableActionJournal` with semantic canonical action digests, hashed owner/project/key placement, 0700 directories, 0600 `O_NOFOLLOW` files, per-key non-blocking `flock`, bounded strict JSON, same-directory fsync plus atomic replace, closed terminal `ActionResult` decoding, and the four frozen states. After adversarial type-confusion and non-directory-path coverage, the focused suite is GREEN at 9/9.
- Added six confirmation tests before implementation for the exact public challenge shape, non-authoritative identifier, explicit local approval, one-shot consume, revision/payload binding invalidation, expiry, owner isolation, and denial. The intended RED stops at the missing runtime `Challenge` model.
- Added exact runtime `ChallengeKind`, `ChallengeState`, and `Challenge` contracts plus `ConfirmationEngine`. The engine holds a separate 256-bit nonce and HMAC approval proof server-side, canonicalizes origin, binds every required context field, expires at 120 seconds, and consumes approval once. The focused suite is GREEN at 6/6.
- Added six risk-policy tests before implementation for minimum-risk preservation, submit/delete and Enter R4 elevation, password/OTP confidential takeover, untrusted-semantics non-downgrade, destination-aware drag risk, and private-handle-free previews. The intended RED is a missing `core.action_policy` module.
- Implemented `ActionRiskClassifier` and closed `ActionRiskAssessment`. It preserves explicit per-kind floors, raises submit/delete/send/permission intent and Enter to R4, routes password/OTP/file entry to R3 confidential takeover, considers drag destinations, canonicalizes origin, and never includes backend handles or typed secrets in previews. The focused suite is GREEN at 6/6.
- Added four service-level action tests for default-deny permission, reserved continuation, terminal replay, R4 one-shot confirmation, confidential takeover, and post-dispatch unknown outcomes. After correcting the test import boundary, the intended RED reaches the missing configurable fake-action seam.
- Made fake action outcomes/errors injectable and corrected fake `act` capability fidelity. Added `BrowserService.act()` orchestration with default-deny origin policy, project-scoped durable journal, target/destination classification, one-shot confirmation, takeover pause, pre-resolved effective-risk dispatch, terminal replay, and `outcome_unknown` after any dispatched uncertainty. The service integration suite is GREEN at 4/4 and the combined core/action/policy/confirmation/idempotency/observation/runtime suite is GREEN at 49/49.
- Added a focused capability-fidelity regression and corrected fake `navigate` to explicit unsupported while observe/cached-status and configured act remain supported. The fake capability suite is GREEN at 2/2.
- Expanded confirmation binding coverage across revision, origin, action digest, and idempotency key; all invalidations expire the approval and the suite remains GREEN at 6/6.
- Added four durable-permission tests before implementation for restart persistence, session-only cleanup/non-persistence, cross-instance merge, 0700/0600 modes, identifier hashing, symlink refusal, and type-confused corruption. The intended RED is a missing `core.durable_permissions` module.
- Implemented `DurablePermissionEngine` and made it the safe default service store. Persistent `always_allow`/`block` decisions merge under a per-project `flock` and atomic 0600 JSON, while `session_allow` never reaches disk and is cleared on stop. The focused suite is GREEN at 4/4 and the service/storage/runtime regression is GREEN at 19/19.
- Ran full Python 3.11 discovery: 151 tests were collected, 146 passed, and only the five previously documented live-CDP modules failed import because optional `websockets` is absent from the base interpreter. No new modernization test failed.
- Ran the explicit dependency-free Python 3.11 authority suite excluding those five device scripts: 146/146 passed.
- Added four durable-artifact tests before implementation for restart-safe chunk reads, private modes, session/project isolation, expiry/LRU quota, tamper detection, and symlink refusal. The intended RED is a missing `core.durable_artifacts` module.
- Implemented `DurableArtifactStore` with owner/project-scoped namespaces, authorization-before-lookup, atomic private data/metadata publication, full SHA-256 verification before reads, bounded base64 chunks, retention cleanup, and LRU quota eviction. The focused suite is GREEN at 4/4.
- Added two service artifact tests before integration for observation-linked screenshot publication/chunk round-trip and explicit unsupported behavior when requested bytes are absent. The intended RED stops at the missing raw backend artifact payload contract.
- Replaced the backend-owned public artifact return with a validated raw `BackendArtifactPayload` boundary, added optional snapshot screenshots, and kept the legacy adapter explicitly unsupported until its real capture path is migrated.
- Connected `BrowserService.observe()` to the durable owner/project artifact store, injected the resulting content URI into the same observation sequence, added active-session chunk reads, and passed the three validated artifact limits through the production composition root. The focused service-artifact suite is GREEN at 2/2; `git diff --check` passes.
- Ran the screenshot/storage/service/fake/runtime/observation regression set: 22/22 passed. Marked the Phase 4 screenshot–observation linkage complete and advanced Phase 5 from pending to in-progress without closing its standalone metadata, MCP transport, SSH, download, or shared-view gates.
- Added the next standalone-screenshot tests before implementation: full PNG metadata, WebP element capture through a resolved private handle, exact mode/target union validation, and stale-context rejection before backend I/O. The intended RED has 3 errors at the absent `BrowserService.screenshot()` method while the two prior artifact tests remain GREEN.
- Added service-owned standalone screenshot publication. All modes enforce session/tab/page/revision preconditions; element refs resolve to private backend handles; backend failures are normalized; and the durable store returns complete SHA-256/size/MIME/lifetime metadata. The fake records only private capture inputs. The focused PNG/WebP service suite is GREEN at 5/5.
- Ran the expanded artifact/fake/service/runtime/observation/legacy-adapter regression set: 30/30 passed. Marked Phase 5 PNG/WebP storage and complete metadata return as implemented; real legacy backend capture and remote SSH proof remain open.
- Added four dependency-free compact-v1 transport tests first: exact self-contained 14-tool projection, session-bound artifact defaults, screenshot/action wire decoding, and structured invalid/unsupported failures. The intended RED stops on the absent `src.termuinator.mcp_v1` module.
- Implemented dependency-free `CompactV1Router`: it consumes the authoritative self-contained 14-tool projection, decodes viewport/revision/action values into typed contracts, dispatches the seven implemented service operations, applies frozen defaults, and fails closed with stable envelopes for invalid or not-yet-implemented capabilities. The focused router suite is GREEN at 4/4.
- Added two MCP-optional low-level server tests before implementation. In the preserved MCP 1.29.0 venv, the intended RED stops on the absent `src.mcp_v1_server` module before testing exact tool listing, structured artifact chunks, and `isError` envelopes.
- Implemented the MCP 1.29 low-level compact server with exact reviewed input/output schemas, generated annotations, SDK validation, structured success content, stable `isError` envelopes, host-derived owner scope, validated config composition, and a stdio runner. Its optional-dependency suite is GREEN at 2/2 in the preserved MCP venv.
- Completed an actual MCP stdio initialize/tools-list round trip against `python -m src.mcp_v1_server`: server identity `termu-inator 0.1.0a1`, exactly the reviewed 14 tools in order, and a present artifact output schema. Marked the chunked MCP artifact-read implementation complete; default `tbp-mcp` still intentionally points at legacy until the migration gate.
- Added legacy-adapter screenshot tests first for viewport/full byte capture, observation embedding, partial capability fidelity, element refusal before backend I/O, and malformed-PNG failure. The intended RED has two failures and one error because screenshot is still wholly unsupported; four prior adapter tests remain GREEN.
- Migrated path-less legacy screenshot bytes into the typed adapter. Chromium now advertises viewport/full, Firefox advertises viewport only, observation can include a validated PNG payload, element/full fidelity gaps fail explicitly, and malformed bytes normalize to `backend_crashed`. The legacy adapter suite is GREEN at 7/7.
- Added and passed a production-composition screenshot round trip: validated runtime limits flow through the legacy adapter and service into durable storage, and a configured 4-byte chunk returns the PNG prefix without early EOF. The runtime-composition suite is GREEN at 2/2.
- Added three read-only permission service tests first for active-session decision listing, server-owned confirmation status, exact operation/challenge union validation, and wrong-session refusal. The intended RED stops at the missing runtime `PermissionsResult` model.
- Added the closed `PermissionsResult` runtime model and exports. The next RED moved to two missing `BrowserService.permissions()` errors and exposed one genuine typed-contract drift: `SessionStatus.page_revision` was populated with a raw string instead of `PageRevision`.
- Added active-session `BrowserService.permissions(list/status)` and corrected `SessionStatus.page_revision` to retain its declared typed object until wire serialization. After updating two stale string-oriented assertions, permission/core/runtime composition tests are GREEN at 16/16.
- Added `browser_permissions` to the compact router using only the frozen read-only list/status union. Mutation and approval verbs remain absent. The router/service permission suites are GREEN at 8/8.
- Added three local-takeover service tests first. The intended RED was three missing-method errors for `local_takeover_start/resume`.
- Implemented the local-only `USER_TAKEOVER_REQUIRED → USER_TAKEOVER_ACTIVE → ACTIVE` protocol. MCP actions stay paused during takeover; resume captures no text/accessibility/screenshot, rotates page ID/document epoch/refs before activation, and backend failure leaves local control active. The focused suite is GREEN at 3/3.
- Ran action/takeover/core-service/observation/permission/compact-router/runtime regressions after the transition work: 30/30 passed on Python 3.11.
- Added two host-decision service tests first; the intended RED was the missing local permission/confirmation methods while all three read-only permission tests stayed GREEN.
- Added service-owned local permission recording and approve/deny-only confirmation mutation. Session grants bind to the active session internally, persistent decisions cannot inherit a caller-supplied session, and challenge authority remains in `ConfirmationEngine`. The permission service suite is GREEN at 5/5.
- Added a dependency-free v1 `HostControlRouter` and three tests. It accepts only four exact request shapes (`permission_record`, `confirmation_decide`, `takeover_start`, `takeover_resume`), decodes closed policy/decision unions, reuses the stable error envelope, and is not present in the compact MCP manifest.
- Added adversarial list-valued policy/decision cases, observed two raw-`TypeError` REDs, then moved bounded string validation before hash lookup. The host-control router suite is GREEN at 3/3.
- Added four Unix host-control transport tests first; the intended RED was the absent server class.
- Implemented the owner-private local socket: canonical portable path, private parent, synchronous restrictive bind, 0600 same-owner verification, optional peer-UID checks, one bounded strict-JSON request per connection, stable error envelopes with internal-message suppression, and inode-safe cleanup. Existing file/symlink and replacement-path regressions pass; the socket suite is GREEN at 4/4.
- Added a shared-authority runtime composition test first; the intended RED was the absent `CompactRuntime` builder. Implemented a trusted composition object that injects one `BrowserService` into compact MCP, host router, and host socket. A host-recorded session grant is immediately visible through MCP read-only permissions; the runtime suite is GREEN at 3/3.
- Added two optional MCP lifecycle tests first; both RED assertions showed that the old `_run_stdio` did not start or close host control. Switched stdio startup to `CompactRuntime`: host socket starts before stdio and closes in `finally`, including MCP failure. The pinned MCP 1.29 suite is GREEN at 4/4.
- Added four host-control CLI/client tests first; the intended RED was the missing module. Implemented `tbp-control` with four closed commands, shared config/data-root resolution, strict bounded JSON, pre-connect 0600 same-owner socket validation, stable JSON results, and distinct server/client failure exit codes. Added its console entry point; the focused suite is GREEN at 4/4.
- Ran the complete action/takeover/permission/host-router/host-socket/host-CLI/runtime/compact-router regression set: 31/31 passed on Python 3.11.
- Refreshed the code graph after structural changes (2,320 nodes / 12,262 edges); new runtime/control classes and the correct `ErrorEnvelope` span are indexed.
- `git diff --check` passed after the host-control integration. Scope inspection still shows the expected modernization work only; nothing was staged, committed, or pushed.
- Built a fresh offline wheel (`termux_browser_pilot-0.1.0a1-py3-none-any.whl`, 225,306 bytes, SHA-256 `b86cd7b0de95c2191bf7833a4fac76fff694a649c34c395f69b17d999df119cd`), installed it without dependencies into an isolated Python 3.11 venv, and verified the installed `tbp-control --help` surface and distribution version.
- Added one full confidential-read-boundary test first. The RED exposed the cached login URL in paused status before reaching the other assertions.
- Added a common remote-active guard before observe/screenshot/artifact/permission/action data access and before action journal reservation. Both takeover states now redact URL/title/ready-state in status; local resume rotates refs before restoring access. The expanded takeover/service/transport regression set is GREEN at 48/48.
- Reconfirmed explicit 0700 profile, 0600 artifact, symlink/traversal, and 0600 same-owner socket tests and closed the combined filesystem permission checklist.
- Added four durable trace-store tests first; the intended RED was the missing module.
- Implemented `DurableTraceRecorder` with owner/project namespace hashing, current-session authorization, idempotent append-only trace IDs, strict digest/type decoding, 0700/0600 storage, atomic fsync publication, bounded list/get, retention/quota eviction, conflict/tamper/symlink refusal, and restart persistence. The focused suite is GREEN at 4/4.

### Verification

- `git ls-remote`: `origin/main` = local HEAD; `upstream/main` = pinned baseline.
- S22U raw hashes: benchmark script `2f364c2e...`, report `c4b36e5a...`, stdout `d2541854...`.
- Firefox smoke and Chromium smoke: URL/title/body/backend/PNG/clean-stop PASS.
- Firefox medians: cold 11,019.197 ms; status 4,270.495 ms; text 2,137.565 ms; screenshot 1,654.342 ms.
- Chromium medians: cold 7,505.045 ms; status 10.982 ms; text 8.836 ms; screenshot 216.396 ms.

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
## 2026-08-24 — Durable trace service integration (implementation)

- Added exact runtime result types for the frozen trace list/get versus export union.
- Attached a project-scoped `DurableTraceRecorder` to each active service session and forwarded configured trace retention/quota limits through the trusted runtime composition root.
- Added secret-free action trace creation between backend completion and durable terminal-journal commit, plus active-session list/get/export-as-artifact reads protected by the common takeover guard.
- Verification: focused durable trace service test GREEN (1/1) and edited modules compile cleanly on Python 3.11.
- Added regression coverage requiring both takeover states to block trace reads and defining the compact trace list/get/export transport as an exact closed union; transport implementation remains intentionally RED before routing changes.
- RED evidence: focused compact trace transport test errors with the expected existing `unsupported_capability`; focused takeover trace-read boundary is GREEN (1/1).
- Implemented compact `browser_trace` routing with exact list versus get/export field sets and no change to the frozen 14-tool public projection; focused verification pending.
- Added service regressions for post-dispatch trace persistence failure, invalid trace operation unions, foreign sessions, and non-string operation confusion; these enforce stable fail-closed errors and exactly-once backend dispatch.
- Trace integration verification is GREEN: service actions 7/7, compact transport 6/6, takeover 4/4, durable traces 4/4, and frozen contract suites 40/40 (61 tests total).
- Marked only the evidence-backed audit/trace-redaction checklist items complete. Full before/after diagnostic artifacts, screenshot redaction, and device/Hermes round-trip remain open.
## 2026-08-24 — Browser wait RED cycle

- Added typed-contract and service-level tests for all five frozen wait conditions, fresh text/ref polling, URL/navigation document rotation, bounded timeout results, and explicit download unsupported behavior.
- Implementation is intentionally absent before the first RED run.
- First RED evidence: module import fails on the expected missing runtime `Download` contract.
- Added exact runtime models for the frozen Download, five-branch WaitCondition union, and WaitResult wire shapes; service polling remains intentionally unimplemented for the next RED.
- Second RED evidence: contract validation is GREEN (2/2); all four service cases stop on the expected missing `BrowserService.wait` method.
- Implemented a closed condition evaluator plus service-owned fresh-observation polling, revision rotation on URL change, bounded timeout results, takeover/state guards, and explicit download-lifecycle unsupported errors.
- Service wait suite is GREEN (6/6). Added the next RED transport test for exact outer fields and all five closed condition branches.
- Transport RED evidence: `browser_wait` stops at the expected existing `unsupported_capability` gate.
- Implemented compact wait routing with exact outer page-precondition fields, bounded timeout decoding, and closed typed decoders for URL/text/ref-state/navigation/download conditions.
- Focused wait transport is GREEN (1/1), while the module run exposed one stale test that still used `browser_wait` as its generic unimplemented-tool sample; service/takeover wait regressions remain GREEN (10/10).
- Moved the generic unsupported-tool assertion to `browser_tabs` and added wait to the confidential takeover read-boundary matrix.
- Added a deadline regression requiring a 1 ms wait to cancel a 50 ms async backend observation instead of merely noticing the timeout after backend return.
- Deadline RED evidence: current wait returns after 60.8 ms, confirming backend observation itself is not yet bounded by the 1 ms budget.
- Wrapped each fresh backend observation in the remaining service deadline and return the last trusted observation when that deadline expires.
- Deadline regression is GREEN: a 1 ms wait cancels the 50 ms async observation before it records a second backend call. Full wait service suite is GREEN (7/7).
- Host MCP test run is GREEN with four expected optional-dependency skips. Pinned MCP 1.29 run reached 10/11 and exposed one stale server fixture still treating `browser_wait` as unimplemented.
- After moving that fixture to `browser_tabs`, the pinned MCP 1.29 server/transport/wait run is GREEN (18/18). The frozen public surface remains exactly 14 tools.
- Marked the wait condition-model and ≤16-tool gates complete; download waiting remains explicitly unsupported under the existing open download-lifecycle item.
- Refreshed the code graph after trace/wait integration: 2,438 nodes and 13,342 edges. Began tab-lifecycle discovery against the fresh index.
# 2026-08-24 — Typed tab lifecycle RED → GREEN

- Added `tests/test_service_tabs.py` to freeze the public `Tab`/`TabsResult` wire shape and require list/open/switch/close identity transitions without leaking private backend handles.
- Ran the test with Python 3.14.7. RED is confirmed at import because runtime `Tab`/`TabsResult` contracts do not exist yet; no production behavior passed accidentally.
- Added the exact compact `browser_tabs` transport cases. Its isolated RED returned the prior structured `unsupported_capability`, confirming routing is still absent before the transport patch.
- Added public `Tab`/`TabsResult` contracts, private `BackendTabSnapshot`/`BackendTabsResult` boundaries, and a configurable deterministic fake tab backend. The legacy adapter remains explicitly unsupported rather than advertising unverified browser behavior.
- Added per-tab observation engines and service-owned public identity reconciliation. List/open/switch/close now preserve private backend handles, reject inactive/stale contexts, forbid accidental final-tab closure, and block all tab reads/mutations during confidential takeover.
- Connected the exact compact transport union without changing the frozen 14-tool surface. Focused service/backend/transport regression is GREEN at 51 tests on Python 3.14.7; the pinned Python 3.11.15 + MCP 1.29 transport/server run is GREEN at 12 tests.
- Refreshed the fast code graph after tab integration: 2,473 nodes and 13,666 edges, with no skipped files in the indexed source/test scope.

### Dialog and sensitive-handoff RED

- Added `tests/test_dialog_handoff.py` first to require stable public dialog IDs, one-shot close events, private-handle redaction, password/OTP handoff challenges, and fail-closed takeover transitions.
- The Python 3.14.7 RED stopped at the expected missing `BackendDialogSnapshot` import; runtime dialog typing and service signaling are not yet present.
- Added a deterministic popup-inventory case after dialog GREEN; its intended RED fails because the tab-capable fake has no popup injection hook yet.
- Added public/private typed dialog contracts, stable dialog open/close tracking, value-free credential/OTP challenges, automatic remote pause, and local-resume suppression. Added a fake-only popup injection hook to verify authoritative tab discovery without widening the production backend protocol.
- The first broader regression exposed two tests that assumed sensitive observation stayed active; updated those fixtures to the new fail-closed handoff contract. The resulting dialog/tab/action/wait/takeover/backend/transport matrix is GREEN at 70 tests on Python 3.14.7.

### Navigation RED

- Added `tests/test_service_navigation.py` for allowed goto, pre-dispatch ask/block, unexpected redirect quarantine, exact union validation, and stale-context blocking. All four tests reached the intended first RED at the absent fake `navigation_results` boundary.
- Added deterministic fake navigation and the typed service policy/identity path; the four service tests reached GREEN. Added an exact compact transport test whose isolated RED confirms `browser_navigate` is still outside the implemented router set.

### Deterministic fixture-site RED

- Added `tests/test_fixture_site.py` to require a loopback-only no-store fixture server, fixed response bytes, download metadata/hash, redirects, 404s, core interaction pages, and at least 25 named scenarios. The intended RED is the absent `tests.fixtures.server` module.
- Implemented the dependency-free loopback fixture server and 27-scenario route inventory; fixed its payload hash and removed reverse-DNS startup latency. The fixture infrastructure suite is GREEN at 4/4, while real-browser scenario execution remains a separate open gate.

### Download lifecycle RED

- Added `tests/test_service_downloads.py` to freeze `DownloadsResult`, reject backend paths, require stable service-owned IDs, publish completed bytes exactly once through the durable artifact store, verify chunked byte recovery, and fail unknown/invalid requests before backend I/O.
- First RED evidence: the module stops at the expected missing private `BackendDownloadSnapshot` export. No production download behavior has been added yet.
- Added the exact public `DownloadsResult` and bounded private backend snapshot/result models. Contract tests are GREEN (3/3); the service tests now stop at the next intended RED, the fake backend's missing `download_sequences` configuration.
- Added configurable private download sequences, lifecycle call recording, and honest fake capability negotiation. The focused RED now reaches the expected absent `BrowserService.downloads` method in all three service cases.
- Implemented session-owned public download identities, transition validation, typed backend normalization, and publish-once durable artifact conversion; the six download service/contract tests are GREEN.
- Added the next REDs for exact compact list/wait routing and `browser_wait` download completion. Both fail at their intended pre-existing unsupported branches before transport/wait implementation.
- Connected exact compact download routing and deadline-bounded download conditions in `browser_wait`, then extended confidential takeover to block download reads before backend I/O. Download/service/wait/transport/takeover/backend-adapter coverage is GREEN at 36 tests on Python 3.12.13.
- Added terminal-payload immutability RED evidence, then bound repeated completed snapshots to the minted artifact SHA-256 and terminal metadata. Added a slow-backend deadline regression; the expanded focused matrix is GREEN at 38 tests.
- Corrected the pinned MCP error fixture to send a schema-valid Developer request after `browser_downloads` became implemented. Python 3.11.15 with MCP 1.29.0 is GREEN at 29 download/wait/transport/server tests.

### Developer Mode RED

- Added `tests/test_service_devtools.py` to freeze all five result branches, require default-OFF availability plus a separate local origin grant, keep private node/request handles off the wire, and reject body/eval/raw or malformed query unions before backend I/O.
- First RED evidence: module import stops at the expected missing private `BackendConsoleEntry` type; no Developer behavior is active yet.
- Added exact public console/network/DOM/style/performance entry/result models plus separate private backend query/result types. The contract branch test is GREEN; all three service cases now stop at the next intended RED, absent fake Developer configuration.
- Added deterministic typed fake Developer results/call recording and honest capability negotiation. The service cases now reach the next intended RED at the absent trusted `developer_mode_available` option.
- Implemented default-false service availability, current-origin local grants, closed query validation, private handle/request ID normalization, and all five typed results; focused service contract tests are GREEN (4/4).
- Added host-only grant and compact read transport REDs. They stop respectively at the existing closed host union and compact unsupported gate, confirming no accidental authority or remote implementation existed beforehand.
- Connected the exact host grant union and compact read-only transport. The combined Developer service/host/router suite is GREEN at 19 tests; all 14 compact tools are now routed.
- Added a CLI parser RED for explicit local enable/disable. It fails at the existing closed command choices, as expected before adding the subcommand.
- Implemented the closed `tbp-control developer-mode ... enable|disable` request mapper.
- Added trusted startup REDs: runtime composition rejects the new explicit option and MCP main rejects argv, proving availability still cannot be enabled before the composition patch.
- Passed the trusted default-false option through runtime composition and added the sole opt-in startup flag, `tbp-mcp-v1 --developer-mode`; per-origin activation still requires `tbp-control developer-mode ... enable`. Config/env authority keys remain rejected.
- Developer service/host/CLI/runtime/transport/config verification is GREEN at 34 tests on Python 3.12.13; the pinned Python 3.11.15 + MCP 1.29 server/transport/service set is GREEN at 20 tests.
- Full Python 3.12 discovery ran 245 tests: 235 passed, 5 optional MCP tests skipped, and only the five known inherited live-CDP imports errored because base Python lacks optional `websockets`. The explicit dependency-free authority selection is GREEN at 240/240 with 5 skips.
- Added Developer result redaction RED evidence: bearer/password console values and URL userinfo/query/fragment currently cross the public result unchanged.
- Implemented deterministic console credential/JWT and network URL userinfo/query/fragment redaction; focused redaction/devtools/takeover tests are GREEN at 11/11.
- Added compact console-script packaging REDs. Both the script declaration and guarded `main_v1` loader are absent, confirming the compact server is not yet installable despite source-level tests.
- Added the guarded `tbp-mcp-v1` console script without replacing legacy `tbp-mcp`. Packaging tests are GREEN at 15/15.
- Built and installed a real wheel into `/tmp/termuinator-v1-wheel.RtcIii/venv`; metadata exposes exactly `tbp`, `tbp-control`, `tbp-mcp`, and `tbp-mcp-v1`. With MCP absent, compact startup exits 2, emits zero stdout bytes, and prints one actionable stderr line. `git diff --check` is clean.

## 2026-08-24 — Legacy DOM observation and click/type adapter

- Added a bounded main-world DOM compatibility probe with a randomized non-enumerable registry, stable private handles, same-origin frame offsets, open-shadow traversal, disconnected-handle eviction, and strict typed normalization capped at 512 interactive elements.
- Connected legacy Firefox/Chromium `observe()` to normalized interactive inventory and fresh ready-state caching without exposing the randomized registry key or private browser handles on the public wire.
- Migrated a first honest `act()` subset: observed-ref-bound click and type. Each action revalidates connection, visibility, enabled state, and non-zero bounds immediately before coordinate dispatch, enforces one overall timeout, and returns normalized before/after URL, value, checked, selected, scroll, visibility, hover, and DOM-change evidence.
- Unsupported action kinds remain structured `unsupported_capability`; inherited exception text and raw page probe payloads remain behind the adapter boundary.
- RED evidence: the initial three new regressions failed on empty interactive inventory and the prior unsupported act gate. The first implementation run then exposed four fixture-probe errors and two stale assertions, all recorded in `task_plan.md`.
- GREEN evidence: `tests.test_legacy_backend_adapter` passes 10/10 on Python 3.12.13 with warnings treated as errors.
- Hardened probe normalization to reject rather than truncate oversized page-returned strings. Added malformed-payload secrecy and full service-wire private-handle non-disclosure regressions; the focused observe/action/service matrix is GREEN at 32 tests.

## 2026-08-24 — Legacy Developer adapter

- Added five caller-script-free page probes for console, Resource Timing network metadata, DOM/layout, computed style, and navigation/resource performance summaries. Raw eval, response bodies, headers, cookies, and authentication data remain unavailable.
- Console capture is explicitly page-scoped from the first Developer console query. Network results are explicitly limited to browser Resource Timing metadata and do not claim full request/response fidelity.
- Added strict closed-envelope normalizers for every private Developer entry type, including finite numeric checks, exact fields, size caps, valid timestamps, and stale observed-handle failure.
- Updated both legacy backend capability records to `partial` with machine-readable limits for the five query types, no raw eval, no network bodies, and the console capture scope.
- RED evidence: the first adapter regression reached the prior structured unsupported gate; the first implementation run exposed a subclass fixture delegation error, which was corrected without weakening production validation.
- GREEN evidence: legacy adapter, Developer service, redaction, runtime composition, and runtime config suites pass 32/32 on Python 3.12.13 with warnings treated as errors. All five generated JavaScript probes pass Node syntax validation.

## 2026-08-24 — Expanded legacy typed actions

- Extended the inherited public Pilot bridge with modifier-aware key dispatch, two-axis scroll, and coordinate hover while preserving the former positional scroll and key call forms.
- Added fixed, caller-script-free select/check probes bound to the randomized observed-node registry. Both validate the current connected element kind, dispatch input/change events, and rely on a fresh post-action state probe for success evidence.
- Unified target and page-state revalidation under one overall action deadline. Key/scroll use page evidence; click/type/select/check/hover use both current target and page evidence. URL/title/DOM inventory are refreshed after every dispatch.
- Capability negotiation now advertises exactly `click,type,key,scroll,select,check,hover`; drag remains explicitly unsupported.
- RED evidence: the new test first stopped at the old click/type-only gate. The initial implementation then caught a test-fixture field/method collision before any production behavior was accepted.
- GREEN evidence: legacy adapter, action executor/service, observation, and element-ref suites pass 34/34 on Python 3.12.13 with warnings treated as errors. All observe/state/select/check generated scripts pass Node syntax validation.
- Added observed source/destination drag with immediate validation of both private handles, bounded interpolated mouse movement, and source/destination/DOM evidence. The low-level input path guarantees a mouse-release attempt after intermediate failures or cancellation.
- Drag RED stopped at the prior seven-action allowlist as intended. The resulting input/legacy/action suite is GREEN at 30 tests, including explicit normal-path and injected-failure mouse-release regressions.

## 2026-08-24 — Host profiles, integrations, and full local regression

- Added server-enforced `observer` and `interactive` compact tool profiles. Observer discovery and dispatch both hide/reject `browser_act` and `browser_tabs`; interactive remains the exact frozen 14-tool contract.
- Added matching Hermes YAML and Codex TOML examples plus a single integration guide covering Tailscale/SSH stdio, Termux Excluding-mode DNS, Developer Mode, shared-view forwarding, bounded artifact reconstruction, and smoke evidence.
- Hermes YAML parsing, Codex TOML/profile/docs contracts, and focused profile tests pass 6/6. The pinned MCP 1.29 focused server/transport/Developer/profile/integration matrix passes 28/28.
- The first 273-test authority run found one documentation-only fixed-phrase regression (`Cache-Control: no-store` split by Markdown wrapping). After recording and normalizing it, Python 3.12.13 passes 273 tests with 7 optional MCP skips; the pinned Python 3.11.15 + MCP 1.29.0 environment passes all 273 with warnings treated as errors.
- Built a fresh wheel at `/tmp/termuinator-final.D0Mvko/dist/termux_browser_pilot-0.1.0a1-py3-none-any.whl`, installed it into an isolated Python 3.12 environment with MCP 1.29.0, and verified all four console scripts plus installed legacy adapter/profile modules. Both observer and interactive `tbp-mcp-v1` processes remained alive for one second with zero stdout and stderr bytes while awaiting stdio input.

## 2026-08-24 — Prompt-injection policy boundary

- Added a deterministic `/prompt-injection` fixture that contains authority-seeking instructions only as inert visible text and no script.
- The first route test produced the intended 404 RED and was recorded before implementation.
- Added a service regression proving the observed text cannot create permission decisions or confirmations, enable Developer Mode, dispatch a Developer query, or authorize navigation to a new origin. Fixture and service-boundary coverage passes 12/12 with warnings treated as errors.

## 2026-08-24 — Installation lifecycle and documentation truthfulness

- Extended the fail-closed installer to verify both `tbp-mcp` and `tbp-mcp-v1`, validate compact CLI construction through `--help`, and print distinct legacy/compact paths. `bash -n setup.sh` is GREEN.
- Added `docs/troubleshooting.md` with evidence-first DNS/ABI/stdio/browser/shared-view diagnosis and recoverable update, rollback, uninstall, and project-data reset boundaries. README and the Termux install guide route to it.
- Reframed architecture, security, migration, and backend-capability documents so normative targets cannot be mistaken for current implementation. Redirect/DNS interception, legacy delegation/default inversion, and real tab/dialog/download lifecycle remain explicit open gates.
- Packaging/lifecycle/design-doc contracts pass 18/18; packaging plus frozen v1 RFC contracts pass 35/35. A local Markdown link audit checked README and 11 documentation files with zero missing or escaping targets.
- Refreshed the fast codebase graph after implementation: 2,850 nodes and 16,723 edges. The graph confirms the compact/core boundaries and also preserves the legacy CLI/148-tool MCP fan-in as an explicit remaining migration hotspot.

## 2026-08-24 — Final local authority and wheel candidate

- Python 3.12.13 passes the final 278-test authority suite with seven optional MCP skips. The pinned Python 3.11.15 + MCP 1.29.0 environment executes and passes all 278 tests. Both runs treat warnings as errors.
- Final static gates pass: `git diff --check`, `bash -n setup.sh`, Hermes YAML safe-load, and warning-as-error `compileall` over source, tests, and scripts.
- Rebuilt the final local wheel at `/tmp/termuinator-release-candidate.foZFXB/dist/termux_browser_pilot-0.1.0a1-py3-none-any.whl` (270,825 bytes, SHA-256 `f43638a4d599541ee7b0f070f32bd47f23e738170d64098b5ba876ac2df180e6`).
- Installed that wheel with MCP 1.29.0 into an isolated Python 3.12 venv and isolated HOME. The four expected entrypoints are present; observer and interactive compact servers each remained alive for one second, then exited cleanly on stdin EOF with rc 0, zero stdout/stderr bytes, and no stale control socket.

## 2026-08-24 — Legacy sensitive-field adapter closure

- Added a full legacy-adapter-to-service regression for password-type and OTP-named inputs. Both cases enter confidential takeover, return a value-free pending challenge, and keep the sentinel value, private node handle, and randomized DOM registry key off the public wire.
- The focused regression passes on Python 3.11.15. This closes the adapter sensitive-semantics and typed credential/OTP masking checklist items while leaving screenshot-region masking explicitly open.
- A first full-discovery rerun accidentally used the base Python 3.11 interpreter rather than the isolated MCP environment. It executed the 279 authority tests but reproduced the five known inherited live-CDP import errors because optional `websockets` is absent; this is recorded as an environment-selection failure, not a GREEN full-suite claim.
- An unfiltered isolated-environment rerun found an existing Chrome CDP listener on port 9222 and therefore entered the five inherited manual browser scripts. The process exited before the explicit termination signal arrived; Chrome itself was not stopped or reconfigured. Final authority validation will use the already documented explicit exclusion instead of treating those external checks as unit tests.
- Moved the three PNGs created by that accidental live run out of the repository into recoverable quarantine at `/tmp/termuinator-live-artifacts.SFHGtU/`; no generated live-browser PNG remains in the worktree.
- The exact authority command excluding those five inherited manual scripts passes 279/279 on the isolated Python 3.12.13 environment with MCP 1.29.0 and websockets 17.0.1. `git diff --check`, `bash -n setup.sh`, warning-as-error `compileall`, and Hermes YAML safe-load also pass.
- Read-only remote readiness found the S22U online over Tailscale (371 ms), but TCP 8022 is closed. No SSH stdio, artifact, soak, or kill-recovery device gate was claimed.
- Added an AST regression for the five inherited live-CDP scripts. Its intended RED reports all five eager `src.*` imports (and the four unguarded runners remain to be fixed), proving standard discovery is not yet inert even though the authority suite can exclude them.
- Deferred all five scripts' project/CDP imports into `main()` and added exact `__main__` guards. The AST boundary is GREEN, base Python 3.11 standard discovery passes 280 tests with seven optional MCP skips, and isolated Python 3.12.13/MCP 1.29 standard discovery passes all 280 without browser/network/file side effects.

## 2026-08-25 — S22U Hermes RC browser-start and observer repair

- Audited the private Hermes report `Hermes 전달.rtf` (SHA-256 `18011f06fd7991b53e6c18fd4e99b66e950ecd52a9eddb3a8f3ac4f7e7e3c294`) against clean tested commit `0007a1e027750a3005a4fced4a7ef48ed7b8eb73`. Installation, 280 device tests, stdio purity, Hermes discovery and the exact 12-tool observer profile passed; Firefox observation and Chromium compact startup failed, so the device correctly skipped the benchmark and returned `PARTIAL`.
- Added Chromium lifecycle tests before implementation. The RED cycles reproduced fixed shared display/port ownership, lack of readiness-driven startup, discarded stderr, retry-before-child-cleanup, unprotected display leases, and failure to inspect Termux's actual temporary X11 root.
- The compact adapter now requests an owned auto display and ephemeral loopback CDP port while the public v0.x `Pilot` defaults remain `:99` and `9222`. Xvfb allocation uses private PID leases, scans both `/tmp` and Python's Termux temporary root, preserves foreign X11 artifacts/processes, avoids global `DISPLAY` mutation, and releases only its own lease.
- Chromium retries from CDP readiness or early exit, terminates and waits for a failed child before relaunch, drains a 64 KiB stderr tail, and stores at most three failed-attempt tails in a private bounded diagnostic. Diagnostic-write failure cannot block fallback.
- Added Firefox native bridge tests before implementation. The RED cycles reproduced clipboard-value logging, stale console state after timeout, unverified second console toggle, navigation accepting an `ERR:Timeout` string, and missing compact-observe retry.
- Firefox now requires an exact randomized console sentinel, probes an already-visible DevTools window before toggling, never executes a synchronization probe without a found/focused DevTools window, invalidates console/focus/JS state on typed timeout without logging clipboard contents, falls back to address-bar navigation, and retries exactly one Firefox DOM observation timeout before returning the existing generic retryable error.
- Final lifecycle REDs proved that a direct `BrowserPilot.start()` failure relied on its caller for cleanup and that a display lease replaced during the final X11 probe could be unlinked. Start now cleans its own owned processes/profile/lease on every exception or cancellation, and claim failure uses PID/inode-checked release so a replacement is preserved.
- Full warning-as-error discovery passes 304 tests with seven optional MCP skips on Python 3.11.15, 3.12.13 and 3.14.7. Focused packaging/integration contracts pass 22/22; `git diff --check`, `bash -n setup.sh`, and warning-as-error `compileall` pass.
- Built `/tmp/termuinator-rc-patch-final2.LbyQeZ/termux_browser_pilot-0.1.0a1-py3-none-any.whl` (272,961 bytes, SHA-256 `9db8ae23df070310b0fb3f5451000928d16036a81269f4e3e43f4ce35b493337`). A fresh Python 3.12 venv installed it with MCP 1.29.0/websockets 17.0.1; `pip check`, all four entrypoints, patched-module imports, and observer/interactive one-second idle stdio purity passed with no stale socket.
- Refreshed the final fast code graph to 2,913 nodes and 17,109 edges and traced the changed Chromium start, Firefox JS bridge, and compact DOM collection paths through their production callers.
- Rechecked the current tailnet after local completion: the S22U is online, but its Termux SSH port 8022 still returns connection refused. The Mac therefore cannot perform the remaining device run directly; the on-device Hermes channel remains the validation path.
- No commit or push was performed. Actual S22U compact Firefox/Chromium smoke, artifact hashes, clean stops, and the intentionally skipped benchmark remain mandatory before RC approval.

## 2026-08-25 — `b5362f9` S22U RC rerun review and recovery plan

- Started from clean `main` matching `origin/main` at `b5362f9414246c7136d94e67505f9713c163f48c` (`v.0.2.01`).
- Re-read the updated private Hermes report and verified its SHA-256 as `8f10ccd8e32e6023b518a60d4439ceaf4ed287ea87468745a11cfe28735c6f2c`; no private report or device artifact was copied into the repository.
- Reconciled the new device result with the current code graph. Chromium's remaining failure is the exact `get_tree_summary()` string versus structured observation mismatch; Firefox still needs a staged device diagnostic because `_collect_dom()` intentionally collapses the underlying exception into a generic public error.
- Updated only the persistent planning records. Production source and tests were not changed, benchmark was not run, and RC remains unapproved.

## 2026-08-26 — Chromium accessibility RED → GREEN

- Changed the legacy adapter fixture to reproduce the real inherited API: summary text from `a11y_tree()` and structured raw nodes from a separate method. The focused device-shaped test failed at the same invalid-accessibility boundary as S22U.
- Added `Pilot.a11y_nodes()` without changing `a11y_tree()` and normalized only bounded role/name data in the compact adapter. Private raw CDP fields are discarded.
- Added RED coverage for 200-node output bounding, ignored generic roles, malformed values, oversized strings, and secret-free errors. The focused four-test matrix and all 19 legacy adapter tests are GREEN on Python 3.11.15 with `-W error`.
- The first attempted RED used macOS system Python 3.9 and never reached product behavior; the valid RED was rerun with the explicit Python 3.11.15 toolchain. No commit or push was performed.

## 2026-08-26 — Firefox DOM source-preservation RED → GREEN

- Compared the exact full DOM probe before and after the Firefox bridge's line join. The original source passed syntax validation; the transformed source failed at an inserted semicolon inside `output.push({...})`.
- Added a native-bridge RED requiring the eval wrapper to preserve the exact JSON-escaped multiline source. It failed against `_safe_join_lines()` and passed after removing that destructive transformation.
- Added a second RED proving an `ERR:` JavaScript result was still returned as ordinary data. Added a secret-free typed evaluation error; the seven-test native bridge suite is GREEN with `-W error`.

## 2026-08-26 — Generic stdio TMPDIR RED → GREEN

- Added child-environment regressions for a generic stdio host that omits `TMPDIR`, first with Termux `PREFIX` and then with only Python's base prefix available.
- Chromium now receives a validated writable absolute temp root without changing the parent process environment. The complete 23-test browser lifecycle suite is GREEN with `-W error`.

## 2026-08-26 — MCP signal cleanup RED → GREEN

- Modified `tests/test_mcp_v1_server.py` first with a real subprocess regression that starts compact observer stdio, waits for its control socket, sends `SIGTERM`, requires cleanup, and starts it a second time on the same data root.
- RED: the first process left `control.sock`; the assertion failed before the restart iteration.
- Modified `src/mcp_v1_server.py` so SIGTERM/SIGINT set an event-loop shutdown request, the MCP task is cancelled, and the existing shared-view/host-control `finally` cleanup runs before signal handlers are restored.
- GREEN: the focused termination regression and all eight MCP server tests pass with warnings treated as errors.

## 2026-08-26 — Full local authority and installed-wheel verification

- Python 3.11.15: 312 discovered, eight optional MCP skips, `-W error` GREEN.
- Python 3.12.13: 312 discovered, eight optional MCP skips, `-W error` GREEN.
- Python 3.14.7: 312 discovered, eight optional MCP skips, `-W error` GREEN.
- Python 3.14.7 + MCP 1.29.0: all 312 executed, no skips, `-W error` GREEN.
- `git diff --check`, `bash -n setup.sh`, and `compileall -W error` pass.
- `python3.11 -m build` was shadowed by the ignored repository `build/` namespace; recorded the failure and used `uv build --wheel` without deleting or changing repository artifacts.
- Built `/tmp/termuinator-wheel-verify.20O4oK/dist2/termux_browser_pilot-0.1.0a1-py3-none-any.whl` (273,464 bytes; SHA-256 `80a62d6f0fa5d684b2e58f38e73ed0caa75fa23c0d2a8bd5b79ffa9c369dcc1c`).
- Installed the wheel into an isolated Python 3.14 venv with `mcp==1.29.0` and `websockets==17.0.1`; `pip check`, installed provenance, all four console scripts, and all 312 tests from outside the checkout pass.
- Installed observer and interactive stdio processes were run sequentially on one isolated data root. Both stayed alive with stdin open, emitted zero stdout/stderr bytes, exited rc 0 on SIGTERM, and removed `control.sock`.
- Refreshed the fast code graph to 2,945 nodes and 17,258 edges and traced all four changed production boundaries through their direct production/test callers.
- Updated `docs/integrations.md` so the Hermes/device gate explicitly requires default accessibility, loopback-first full observation, bounded accessibility records, artifact EOF/hash/mode evidence, same-data-root stdio restart, and benchmark deferral until both backends pass.
- No commit, push, package publication, S22U mutation, or RC approval was performed.

## 2026-08-26 — Canonical device final-verification gate

- Corrected the Chromium/Firefox accessibility normalization to the exact frozen five-field public node shape. Role/name-only mappings are now rejected by verifier tests instead of being mistaken for valid MCP evidence.
- Added repository-owned `scripts/final_verify.py` and 17 focused tests covering exact wheel/commit/tool provenance, full loopback observation, bounded artifact EOF reconstruction, durable hash/mode evidence, both backends, same-data-root stdio restart, private fail-closed reports, accurately named runtime fields, isolated HOME/XDG/TMP, diagnostic-override removal, and helper-process cleanup.
- The canonical verifier always runs Chromium and Firefox, then the 12-tool observer profile. It keeps `benchmark_allowed` false unless both backends, exact MCP identity/protocol/tool inventories, zero stderr, session/process/socket cleanup, and artifact evidence pass.
- Removed the inherited VirGL manager's broad `pkill -f` behavior. Three ownership tests prove it launches and stops only its own optional helper, reuses that live process on repeated start, and returns to SwiftShader when the executable cannot start. The private device survivor audit now also covers VirGL, xclip, and xdotool.
- Replaced README's pattern-based Xvfb/Firefox termination advice with the identity-checked troubleshooting procedure. The Termux guide now gives an explicit commit-suffixed `--system-site-packages` venv and pip wheel installation, preserves the old Hermes entry, and documents the isolated mode 0700 child HOME.
- Python 3.11.15 and 3.12.13 each pass 332 tests with eight optional MCP skips. Python 3.14.7 with MCP 1.29.0 executes and passes all 332 with warnings treated as errors. `git diff --check`, `bash -n setup.sh`, warning-as-error compileall, and line-length checks pass.
- Built `/tmp/termuinator-final-rc.OCglWK/dist/termux_browser_pilot-0.1.0a1-py3-none-any.whl` (273,622 bytes; SHA-256 `85ec62fa15200c689e25044e564642e9b2e505764c2327ed673da77bc24a1299`). All seven changed packaged source files are byte-identical inside the tested wheel, and its ZIP integrity passes.
- A fresh pip-installed Python 3.14 environment passes dependency checks, all three installed VirGL ownership tests, all 19 installed legacy-adapter tests, and all 332 checkout authority tests. Its interactive→observer probe uses one isolated data root and HOME, removes inherited `TBP_SINGLE_PROCESS`, exposes exact 14/12 tools, reports MCP protocol `2025-11-25` and server `0.1.0a1`, emits zero stderr, and removes the private control socket after both exits.
- Installed wheel/hash/entrypoint provenance reaches the exact non-Termux `PREFIX is missing` boundary on macOS. A dirty-checkout CLI smoke exits 1, writes mode 0700/0600 FAIL evidence with `benchmark_allowed: false`, and passes its manifest checksum. Neither result is Android/browser evidence.
- Refreshed the fast code graph to 2,987 nodes and 17,428 edges. The indexed accessibility path reaches `LegacyPilotBackend.observe` and compact dispatch; all three VirGL ownership regressions connect to `VirglManager.start`. The graph's configured fast exclusions omit `scripts/`, so the canonical verifier remains covered by its direct source audit and 17 focused tests rather than a false graph-reachability claim.
- A final read-only tailnet check found the S22U offline (last seen one minute earlier); one ping timed out and TCP 8022 remained closed. No device/Tailscale setting was changed, and no direct Mac device claim was made.
- Preserved the final wheel, a matching checksum file, and an explicit non-pass README outside the repository at `../Termu-inator-device-artifacts/s22u-2026-08-26-rc/`. The directory is mode 0700, all three files are mode 0600, and the stored checksum verifies. It must be rebuilt if candidate source changes before commit.
- No commit, push, package publication, Hermes reconfiguration, S22U mutation, benchmark, or RC approval was performed. The clean-commit S22U canonical manifest remains the open gate.

## 2026-08-26 — Final verifier provenance and portable-path review

- A focused code review found that a caller-supplied wheel hash did not by itself bind the wheel's source or release metadata to the checkout. RED tests reproduced source, entrypoint-field, version, LICENSE, executable-member, and RECORD tampering gaps.
- The verifier now compares all 57 tracked `cli.py` / `src/**/*.py` files with the clean checkout, requires the exact 0.1.0a1 metadata/dependency/entrypoint contract, matches README/LICENSE/NOTICE, verifies safe unique wheel members and every RECORD hash/size, and then compares all installed Python source bytes with the checkout.
- The preserved 273,622-byte wheel remains unchanged and passes the stronger binding with source-tree SHA-256 `9693c07cb450d1da342006a595b8e0a0fb3662dec09a55e7202b0f5ad00e812b`; its candidate SHA-256 remains `85ec62fa15200c689e25044e564642e9b2e505764c2327ed673da77bc24a1299`.
- A checkout-outside Python 3.14 probe imports `src` from the installed site-packages and again reports exact 14/12 tools, MCP protocol `2025-11-25`, server `0.1.0a1`, zero stderr, private live sockets, and socket removal after both profile exits.
- The documented Termux report path would have exceeded the runtime's 100-byte portable Unix-socket contract. Child roots now use short private names, overlong output is rejected before process startup, and the guide uses `~/.cache/tfv/COMMIT12`, whose modeled S22U control socket is 87 bytes.
- Python 3.11.15 and 3.12.13 pass 339 tests with eight optional MCP skips; pinned-MCP Python 3.14.7 executes and passes all 339. Diff, shell syntax, compileall, and touched-file line-length gates pass. The added documentation contract also prevents benchmark execution from falling back to the old venv.
- Refreshed the final fast graph to 2,998 nodes and 17,470 edges. Its configured exclusions still omit `scripts/`; the verifier is covered directly by 22 focused tests and source review.
- No packaged candidate source changed, so the preserved wheel and checksum remain valid. No commit, push, Hermes/device mutation, benchmark, or RC approval was performed; the clean S22U manifest remains the open gate.
- The final read-only tailnet refresh lists the S22U as online, but one Tailscale ping timed out and a bounded TCP 8022 probe returned rc 1. The Mac still has no usable Termux transport; no device or Tailscale setting was changed.

## 2026-08-26 — `d40f4d3` device evidence intake

- Verified all three transferred evidence files independently; the manifest checksum passes and exactly records an `installed-environment` Android identity failure with benchmark disabled.
- Local `main` is at `d40f4d3e3d801643ca0433116d7d951b3ce0c483` (`v.0.2.03`). Only unrelated untracked `.DS_Store` files are present and will be preserved.
- No production source has been changed in this repair cycle yet. The next action is a failing verifier regression for modern Termux's `platform.system() == "Android"` identity before any implementation edit.
- Added two verifier contract tests before implementation. The focused RED fails because `validate_android_termux_identity` does not exist, while its cases explicitly require modern `android/Android`, preserve legacy `linux/Linux`, and reject missing, relative, root-only, traversing, or mismatched Android signals.
- Added `validate_android_termux_identity()` and connected its evidence to the installed-environment report. The focused RED is GREEN, and all 24 canonical-verifier tests pass on Python 3.11 with warnings treated as errors.
- Re-ran the complete authority suite outside the workspace sandbox because it requires loopback TCP and Unix sockets. Python 3.11.15 and 3.12.13 each pass 341 tests with eight optional MCP skips; pinned-MCP Python 3.14.7 executes and passes all 341.
- Static gates pass: `git diff --check`, `bash -n setup.sh`, warning-as-error `compileall` on all three supported interpreters, and the 100-column limit for the changed verifier and test files.
- The preserved 273,622-byte wheel remains SHA-256 `85ec62fa15200c689e25044e564642e9b2e505764c2327ed673da77bc24a1299` and still binds to all 57 packaged checkout sources, source-tree digest `9693c07cb450d1da342006a595b8e0a0fb3662dec09a55e7202b0f5ad00e812b`, exact metadata, entrypoints, license files, member allowlist, and RECORD.
- Refreshed the fast code graph to 3,002 nodes and 17,477 edges. Its configured exclusions still omit `scripts/`; both new identity regression methods are indexed, while the verifier helper remains covered by direct source review and the 24-test verifier suite.
- A fresh read-only tailnet check outside the app sandbox reports `Galaxy S22 Ultra` online and a direct-path pong in 38 ms. The bounded TCP 8022 probe still returns `Connection refused`, so Mac-side SSH cannot replace the on-device Hermes gate. No device or Tailscale setting changed.
- A commit-scope code review found no blocking or important issue: the runtime pair and canonical root checks are constant-time, secret-free, and stricter than the former one-marker check; they execute only after real Termux prefix/pkg and native-cryptography validation. The 24-test focused verifier suite and final diff check remain GREEN.
- No wheel rebuild, commit, push, Hermes/device mutation, benchmark, or RC approval was performed. A clean new commit and on-device canonical PASS manifest remain required.

## 2026-08-29 — `e29320d` S22U portability follow-up

- Reconciled Hermes evidence with local `main` and `origin/main`; both point to clean commit `e29320d35fa836e8fc353c255994902379510637` before this repair.
- Confirmed the commit contains the intended five repair files plus mistakenly tracked `.DS_Store` and `scripts/.DS_Store`.
- Confirmed the two reported test sites hardcode `TemporaryDirectory(dir="/tmp")`; the next TDD cycle will add a portable-test invariant before removing those arguments.
- Added an AST portability contract first; its RED found exactly the two hardcoded calls. Removing both `dir="/tmp"` arguments made that test GREEN.
- The first expanded focused run then exposed a distinct macOS path-length edge: its default temporary path plus the test-only `/output` suffix produced a 102-byte control socket. Using the already-private temporary directory itself reduces it to 95 bytes without weakening the production 100-byte limit; all 25 focused verifier tests then pass.
- The equivalent S22U `$PREFIX/tmp/tmpabcdefgh` model is 82 bytes, so the repaired test remains within the same production limit on both target hosts.
- Added a repository-wide `.DS_Store` ignore rule. The two tracked Finder files are now unstaged deletions and are recoverably preserved at `/tmp/termuinator-dsstore-backup.fxvH4l/` in a mode-0700 directory with mode-0600 files.
- Python 3.11.15 and 3.12.13 each pass 342 tests with eight optional MCP skips. A fresh Python 3.14.7 venv with MCP 1.29.0 and websockets 17.0.1 passes `pip check` and executes all 342 tests successfully.
- Static gates pass: `git diff --check`, `bash -n setup.sh`, warning-as-error compileall on all three interpreters, changed-test 100-column check, and repository-wide `.DS_Store` ignore verification.
- The preserved 273,622-byte wheel remains SHA-256 `85ec62fa15200c689e25044e564642e9b2e505764c2327ed673da77bc24a1299` and passes all 57-source, source-tree digest, metadata, entrypoint, license, member allowlist, and RECORD checks against the current checkout.
- Refreshed the fast code graph to 3,005 nodes and 17,487 edges. `scripts/` remains intentionally excluded; the new portability contract is indexed in the verifier tests.

## 2026-08-29 — `0a4a212` S22U canonical follow-up

- Reconciled Hermes evidence with local `main`/`origin/main` at clean commit `0a4a21298a7aa242f85f0cd783ba51ef681b6a24` (`v.0.2.05`).
- Confirmed runtime artifact layout is `data_root/state/artifacts`, while canonical `verify_backend()` currently validates `data_root/artifacts` and its test fixture reproduces that incorrect layout.
- Confirmed `ProcessSessionLock.release()` preserves its private regular file and releases only the kernel flock/descriptor. Current `_cleanup_summary()` incorrectly requires the pathname to disappear.
- Added backend-layout and released-lock RED tests before implementation. The tests reproduce the S22U artifact-root failure, require exact owner/mode/dead-PID/reacquirable-flock evidence, and reject live, wrong-owner, non-private, symlink-parent, and ENOENT-race states.
- Updated only the canonical verifier to validate `data_root/state/artifacts` and to treat a confirmed-absent or safely released persistent lock as clean without rewriting or unlinking it. Both failure-path and final cleanup pass the commit-bound owner scope.
- Focused verifier authority passes 31/31. Python 3.11.15 and 3.12.13 each pass 348 tests with eight optional MCP skips; pinned-MCP Python 3.14.7 executes and passes all 348.
- Static gates pass: `git diff --check`, `bash -n setup.sh`, warning-as-error compileall on all three interpreters, changed-Python 100-column checks, and pinned Python 3.14 `pip check`.
- The preserved 273,622-byte wheel remains SHA-256 `85ec62fa15200c689e25044e564642e9b2e505764c2327ed673da77bc24a1299` and passes the unchanged 57-source tree digest `9693c07cb450d1da342006a595b8e0a0fb3662dec09a55e7202b0f5ad00e812b`, metadata, entrypoint, license, allowlist, and RECORD checks.
- Refreshed the fast code graph to 3,015 nodes and 17,535 edges. `scripts/` remains intentionally excluded; the new verifier regression methods are indexed.
- No device setting, existing venv, browser process, benchmark, wheel rebuild, package mutation, commit, or push was performed. The next authority is a new clean commit followed by the S22U canonical gate.

## 2026-08-29 — `v0.2.06` S22U canonical follow-up

- Reconciled the independent review with clean local and remote HEAD `1bec1b0fbac2c57ddb9fe6b9f3824cc85774a5f4` (`v.0.2.06`).
- Recorded the three open repair groups: live trusted MCP PID during intermediate cleanup, unsafe absent-lock parent handling, and Firefox loopback timeout plus incorrect crash normalization.
- Added lock-lifecycle regressions before implementation. The focused RED has exactly five expected failures: two missing active-PID contracts, two unsafe absent-parent cases, and one missing exec-preserving trusted MCP launcher.
- Added a verifier-owned private O_EXCL PID launcher that immediately `exec`s the exact validated MCP command, preserving the trusted child PID without changing the server protocol. Intermediate cleanup now requires that active PID; final cleanup still requires inactivity.
- Absent-lock cleanup now validates a stable owner-owned mode-0700 real runtime parent when present and rejects symlink or non-private parents. The 11 focused lock/launcher regressions are GREEN.
- Added four Firefox navigation regressions before implementation. The RED independently proves crash misclassification, missing native address-bar metadata, unwanted post-navigation console polling, and adapter loss of verified redirect metadata.
- No package install, device, Tailscale, venv, browser process, benchmark, commit, or push has been changed in this follow-up.
- Passed the four Firefox REDs by returning bounded actual URL/title metadata from native Firefox navigation, forwarding it through `PageCommands`/`Pilot`, consuming it only in the Firefox legacy adapter, and mapping built-in navigation timeouts to the stable retryable `TIMEOUT` code.
- Added a second security RED for unchanged stale clipboard content. Native Firefox now primes and verifies a unique X11 clipboard marker, requires `Ctrl+C` to replace it, restores address-bar focus, and terminates only the marker xclip process it created.
- The complete warning-as-error authority now passes 359 tests on Python 3.11.15, 3.12.13, and pinned-MCP Python 3.14.7; the dependency-minimal 3.11/3.12 runs retain only the eight expected MCP skips. `git diff --check`, `bash -n setup.sh`, three-interpreter `compileall`, changed-line 100-column, and pinned `pip check` gates pass.
- Built the final candidate wheel at `/private/tmp/termuinator-v0207-final.kaP7Uq/dist/termux_browser_pilot-0.1.0a1-py3-none-any.whl`: 274,739 bytes, SHA-256 `45b7198135163f95c590fef84a5fc8c97131cac4029e6d3c4286f5412421eb05`, 57-source digest `13d3a1e035bcba49148bbc92c62f55f224ee3a37614e8779cde0129826eb8972`.
- Wheel ZIP, RECORD, member allowlist, metadata, licenses, all four entrypoints, checkout binding, and a fresh Python 3.14 installed-source binding pass. The fresh venv has MCP 1.29.0/websockets 17.0.1, reports no broken requirements, and runs observer then interactive stdio on one private data root with rc 0, zero output, and no residual control socket.
- Preserved the wheel, checksum, and non-approval README under private sibling directory `../Termu-inator-device-artifacts/s22u-2026-08-29-post-v0206-candidate/` (directory 0700, files 0600); its checksum verifies. This replaces the earlier pre-clipboard candidate bytes.
- Refreshed the fast code graph to 3,037 nodes and 17,692 edges. The graph traces native navigation through `PageCommands`, `Pilot`, the legacy adapter, compact router, and `BrowserService`; `scripts/` remains intentionally excluded and is covered by its 36 focused verifier tests plus direct review.
- No device/Tailscale setting, existing Termux venv, Hermes registration, benchmark, commit, or push was changed. A new clean commit and S22U canonical `status=PASS`, both backend PASS, and `benchmark_allowed=true` remain required.

## 2026-08-29 — `v0.2.08` S22U canonical follow-up

- Reconciled the transferred evidence with clean local HEAD `0bc2e0191de439ae1cee8879361850f67cd56f46` (`v.0.2.08`). The supplied manifest checksum verifies exactly; its wheel and 57-source digests match the release candidate.
- Confirmed Chromium is a full PASS and final process/socket/lock cleanup is safe. Firefox is a navigation-stage FAIL with only the stable public `backend_crashed` code, so benchmark authority remains closed and the previous timeout is not inferred as the cause.
- Preserved owner-private, byte-identical evidence copies under `../Termu-inator-device-artifacts/s22u-2026-08-29-v0208-fail-1/`; directory mode is 0700 and all three files are 0600.
- Began a new TDD cycle around two independently useful contracts: bounded Firefox navigation stage evidence and retry-safe X11 clipboard replacement. Production source, wheel, device settings, Hermes registration, benchmark, commit, and push are unchanged at this checkpoint.
- The corrected Python 3.11 focused RED ran 16 tests and produced the expected five failures plus one error: marker ownership and address-bar copy have no retry, `NativeNavigationError` does not exist, and the canonical caller discards allowlisted MCP error context. Existing unrelated cases remained green.
- A second two-test RED proved unknown Pilot failures still escaped with their private exception text and adapter metadata failures had empty details. These paths are now reserved for fixed `pilot_dispatch` and `adapter_metadata` stages while built-in timeouts and existing typed errors remain distinct.
- Graph review exposed a cleanup edge in the retry path: cancellation of an owned `xclip -o` read did not reap that child. A dedicated RED reproduced it; the read now kills/waits only its own subprocess and re-raises cancellation unchanged.
- Completed the navigation repair with bounded clipboard-marker and address-bar-copy retries, per-attempt Firefox focus restoration, typed native stages, secret-free legacy adapter translation, and an allowlisted canonical MCP error envelope. Built-in timeouts and existing typed errors retain their original semantics.
- The final related suite passes 89 tests with eight expected optional-MCP skips. Full warning-as-error discovery passes 368 tests on Python 3.11.15 and 3.12.13 with those eight skips, while pinned-MCP Python 3.14.7 executes all 368 with no skips. The focused canonical verifier passes exactly 37 tests.
- Final static authority passes `git diff --check`, `bash -n setup.sh`, warning-as-error compileall on Python 3.11/3.12/3.14, and the changed-line 100-column gate.
- Built `/private/tmp/termuinator-v0208-authority.7pVXyH/dist-final/termux_browser_pilot-0.1.0a1-py3-none-any.whl` (275,462 bytes, SHA-256 `f14d7fdc00a22523994b35e7bdb415fcb32b87066f2e715896f2ab144e87b6cc`). It binds to all 57 sources with digest `4f8e027ad1f8ec8d0f2880f3dc0378dc78c1da6a4e77b8a0a2aafa051c878c12` and passes metadata, license, member, RECORD, and entrypoint checks.
- A fresh Python 3.14 install imports `src` exclusively from the wheel venv, passes installed-source binding and `pip check`, and reports MCP 1.29.0/websockets 17.0.1. Observer and interactive stdio expose exact 12/14 tools, negotiate MCP `2025-11-25`, emit zero stderr, use a private control socket, and remove it after exit.
- Refreshed the fast graph to 3,052 nodes and 17,818 edges. The graph indexes the typed native error, native metadata method, PageCommands, Pilot and legacy adapter boundaries; `scripts/` remains excluded and is covered by its 37 focused tests and direct review.
- Preserved the final wheel, checksum, non-approval README, and placeholder-gated Hermes rerun template under private sibling directory `../Termu-inator-device-artifacts/s22u-2026-08-29-post-v0208-candidate/` (directory 0700, files 0600); its checksum passes.
- No commit, push, S22U/Tailscale mutation, existing Termux environment change, Hermes registration change, benchmark, or release approval was performed. A clean pushed commit and on-device canonical PASS remain mandatory.

## 2026-08-30 — `v0.2.08` adversarial completion audit

- Traced the repaired native failure through `Pilot.goto`, `LegacyPilotBackend.navigate`, `BrowserService.navigate`, the compact error envelope, and the canonical caller. The allowlisted stage survives end to end without serializing its exception cause.
- Added a malformed-envelope RED proving an arbitrary lowercase `code` could enter canonical private evidence. The verifier now accepts only the frozen 18 public error codes and converts every other value to `mcp_error` while retaining only allowlisted backend/operation/stage values.
- Added two timeout REDs proving normal and network-idle `Page.navigate` calls discarded the caller's limit. Both paths now pass the exact validated timeout to the CDP/native transport.
- Added four helper REDs proving cancelled `xdotool`/`xclip` children survived and timeout/error logs exposed command or exception values. Both helpers now reap only their owned child and use value-free logs; the original cancellation remains unchanged.
- Added malformed-copy, focus-order, and missing-window REDs. URL parser failures now map to `address_bar_copy`, while fallback navigation activates and validates the Firefox main WID before the first `Ctrl+L` or URL input.
- The related 98-test service/MCP/verifier suite passes. Full warning-as-error discovery passes 377 tests on Python 3.11.15 and 3.12.13 with eight expected optional-MCP skips; pinned-MCP Python 3.14.7 executes all 377. The focused canonical verifier passes exactly 38 tests.
- Static authority passes `git diff --check`, `bash -n setup.sh`, changed-line 100-column checks, and warning-as-error compileall on Python 3.11, 3.12, and 3.14.
- Built `/private/tmp/termuinator-post-v0208-final.JxBkVq/dist/termux_browser_pilot-0.1.0a1-py3-none-any.whl` (275,475 bytes, SHA-256 `0963b8f7cc64e57c724b6caabd764302bfcd47e693f5fcb1f12a10c143e34547`). It binds all 57 packaged sources with digest `79edda0435f2ca18264a150db8e4a51f47ed1ad70be409973ea5570162c2252e` and passes member, metadata, license, entrypoint, ZIP, and RECORD checks.
- Discarded the first fresh-install authority claim because omitting the Termux constraint selected websockets 17.1. A second untouched venv installed the same wheel with MCP 1.29.0/websockets 17.0.1, passes `pip check` and installed-source binding, imports only from site-packages, and completes exact 12/14-tool stdio with protocol `2025-11-25`, zero stderr, private socket, and clean socket removal.
- Marked the earlier `f14d7fdc...` handoff as superseded without deleting it. Preserved the new wheel, checksum, non-approval README, and placeholder-gated Hermes template under `../Termu-inator-device-artifacts/s22u-2026-08-30-post-v0208-final-candidate/` with directory mode 0700 and files mode 0600; checksum verification passes.
- Refreshed the fast graph to 3,061 nodes and 17,884 edges. `scripts/` remains excluded and is directly covered by the 38 focused verifier tests and source review.
- No commit, push, device/Tailscale mutation, existing Termux venv change, Hermes registration, benchmark, or release approval was performed. Only a clean pushed commit and new S22U canonical evidence can close the remaining gate.
- A final read-only MagicDNS TCP probe to `galaxy-s22-ultra:8022` timed out after five seconds. The Mac therefore still has no direct Termux transport; no Tailscale or device setting was changed, and Hermes remains the available on-device execution path after commit.

## 2026-08-30 — `v0.2.11` S22U clipboard-prime follow-up

- Verified the downloaded manifest against its supplied checksum and reconciled it with clean local/remote HEAD `1e55237e9e9672ed983f668d68ff761acb1b25e8` (`v.0.2.11`).
- Confirmed Chromium PASS, Firefox-only `clipboard_prime` FAIL, safe final cleanup, and `benchmark_allowed=false`; benchmark and Hermes registration remain untouched.
- Preserved normalized owner-private evidence under `../Termu-inator-device-artifacts/s22u-2026-08-30-v0211-fail-1/` with directory mode 0700, file mode 0600, and a passing manifest checksum.
- Traced marker priming through the native navigation metadata path and reconciled it with upstream xclip's default fork/exit behavior. The next TDD step is a foreground-owner lifecycle RED covering both marker priming and normal clipboard paste cleanup.
- The first preservation command used the not-yet-created destination as `workdir` and failed before process creation. Retrying from the existing parent directory succeeded without overwriting or deleting any prior evidence.
- Added two foreground-owner lifecycle tests first and observed two expected failures on the unmodified runtime. The marker case failed at `clipboard_prime`; the paste case proved its returned parent could not be terminated or awaited.
- Added `-quiet` only to marker and paste xclip writers. Both REDs are now GREEN, so the retained subprocess object is the foreground X11 selection owner that cleanup can terminate and wait by exact PID.
- Passed 92 related native/legacy-adapter/service/canonical-verifier tests.
- Passed all 379 warning-as-error tests on Python 3.11.15 and 3.12.13 with eight expected optional-MCP skips; pinned-MCP Python 3.14.7 executes all 379 with no skips.
- The first full Python 3.11 run was constrained by the managed workspace and reported 15 TCP/Unix-socket bind permission errors. The identical approved run passed; no source change was made in response to the environmental failure.
- Passed `git diff --check`, `bash -n setup.sh`, changed-line 100-column checks, and warning-as-error compileall on Python 3.11/3.12/3.14.
- Disqualified the first wheel after its build log showed ignored `build/` reuse. Copied every current tracked file byte-for-byte to a fresh private staging tree and rebuilt offline from an empty build directory.
- The final 275,499-byte wheel is SHA-256 `be21992fbf4f9f1aa452678df27766253f0e0bb5833010727fe56b40277026a0`, with 57-source digest `76393e55949ad99d5e8ccc2ae7b56fab3f4377dcaaf79579e2821df67a8c978b` and complete wheel/source/metadata/RECORD/license/entrypoint validation.
- Fresh pinned-MCP Python 3.14 installation passes `pip check`, provenance and installed-source binding. Interactive and observer stdio pass exact 14/12-tool inventory, MCP `2025-11-25`, zero stderr, private socket, and socket-removal checks.
- Preserved the wheel, exact-name checksum, non-approval README, and placeholder-blocked Hermes rerun template at `../Termu-inator-device-artifacts/s22u-2026-08-30-post-v0211-foreground-candidate/` with directory mode 0700 and file mode 0600.
- Rechecked upstream xclip control flow after the build: `-quiet` selects `OQUIET`, while only `OSILENT` enters the background-fork branch. This independently confirms that both retained writer handles now identify the foreground selection owner governed by exact-PID cleanup.
- A final bundle audit was first launched from the artifact directory with a repository-only `git status` prefix and stopped at the expected “not a git repository” error before checking files. A later checksum invocation from the repository resolved the wheel path but correctly could not resolve the checksum file's relative payload name. Repeating repository and artifact checks in their respective directories passed: exactly five intended modified files, clean diff whitespace, 275,499-byte wheel SHA-256 `be21992fbf4f9f1aa452678df27766253f0e0bb5833010727fe56b40277026a0`, and an exact-name checksum result of `OK`. The first progress-log patch also used stale wording as context and was retried against the exact current line without changing source behavior.
- Strengthened the blocked Hermes handoff template without changing the wheel: before venv creation it now requires the S22U xclip help to expose `-quiet` and runs the two exact foreground-owner regression methods under warning-as-error. Missing option or either failed test stops before installation and must return raw command evidence; package substitution or mutation remains forbidden.
- Confirmed and sealed user commit `4af303d90780c67bc73ca8d62b93b65d98d24761` (`v.0.2.12`): clean local checkout, exact live GitHub `main`, intended five-file scope, 57-source wheel binding, 38 focused verifier tests, two foreground-owner regressions, checksum, and Hermes shell syntax all passed before handoff.

## 2026-08-30 — `v0.2.12` S22U address-bar-copy follow-up

- Verified the downloaded canonical manifest against its supplied checksum and reconciled it with the exact `v.0.2.12` commit, wheel, and source digest. Chromium and all cleanup gates pass; Firefox alone reports the sanitized `address_bar_copy` stage and `benchmark_allowed=false`.
- Preserved normalized owner-private evidence under `../Termu-inator-device-artifacts/s22u-2026-08-30-v0212-fail-1/` with directory mode 0700, file mode 0600, manifest SHA-256 `b2dcf97eae342f985e73b7435a7ad0e72e5434b64101cefeadba8fd3e3757c19`, and raw-error SHA-256 `2bac2349fc59d53556f25ea025246f1dd83e40c93f5699b2ed295469cb65f1f2`.
- The first post-copy preservation check accidentally remained in Downloads and validated an older same-name file. Re-running from the explicit new evidence directory verified the intended normalized bytes; no original or prior evidence was overwritten or removed.
- Graph tracing narrowed the failing boundary to `_navigation_metadata()`: it retains the foreground marker owner until all copy attempts finish and caps each Firefox-backed clipboard read at one second. Two independent TDD regressions will test owner handoff and slow valid selection delivery before production changes.
- Added the two behavior regressions before production changes. The first run produced the expected native exceptions but counted them as unittest errors; after a test-only assertion correction and one repeated-context patch retry, the exact two cases fail as assertions at `address_bar_copy`.
- The owner-handoff RED returns only the marker until the exact owner is released, proving the current outer-finally lifetime is too long. The slow-delivery RED takes 1.2 seconds per valid Firefox clipboard response, proving the fixed one-second read window cancels all three otherwise valid reads.
- Applied the minimal GREEN in `src/native.py`: release and await the verified foreground marker owner before Firefox claims CLIPBOARD, retain fallback cleanup for any owner not yet released, and raise the per-read ceiling from one to three seconds without changing the three-attempt bound or URL validation.
- Both exact REDs now pass in 1.517 seconds. The expanded 94-test native execution, legacy adapter, service navigation, and canonical verifier suite passes under warning-as-error.
- After the third regression, full warning-as-error discovery passes all 382 tests on Python 3.11.15, 3.12.13, and pinned-MCP 3.14.7; only the established eight optional-MCP skips remain in the dependency-minimal 3.11/3.12 environments. Static diff, shell, width, compileall, and 38 focused verifier gates pass.
- The first staging command used relative directory creation from the repository, so its three generated directories were inspected and moved intact to the task temp root before any build. A second creation attempt stopped on an existing uv cache, and the first offline backend attempt selected a Python 3.14 environment without setuptools. Absolute staging plus explicit setuptools-equipped Python 3.11 produced the clean wheel without network access.
- Built `/private/tmp/termuinator-v0212-address-copy.UEqzyD/dist-authority/termux_browser_pilot-0.1.0a1-py3-none-any.whl`: 275,536 bytes, SHA-256 `a412d4d6e4e6988a4f8638662893bdae4e9662ba6af5843aca90815dbf85e43c`, 57-source digest `d3da47a00c961eb8b0dc3c7fc2c0ab96f509e55dc4ba7491ed2fdd4f90423a3a`, with complete wheel/source/metadata authority.
- A fresh Python 3.14 install selected MCP 1.29.0 and websockets 17.0.1 and passes `pip check`. The first provenance command ran from the repository and found its ignored `.egg-info`; the neutral-cwd retry found the installed `.dist-info` and passed exact local-wheel hash, 57 installed sources, four entrypoints, and site-packages import origins.
- Installed interactive→observer stdio passes exact 14/12 tool inventories, protocol `2025-11-25`, server `0.1.0a1`, zero stderr, private live socket, and same-data-root socket removal.
- Build authority errors were retained: default uv cache permission denial, sandboxed PyPI DNS failure, disqualified ignored-build reuse, missing bare `cmp`, and zsh `path` variable collision. Each retry changed the relevant condition and the final clean-stage chain is GREEN.
- Added a third behavior RED for a persistent marker-owner release failure. It failed as intended because the outer retry replaced the bounded navigation error with the private `OSError`; the minimal cleanup guard now preserves `address_bar_copy`, and all three focused regressions pass in 1.523 seconds.
- A three-interpreter rerun used an incorrect discovery top-level (`-s tests -t .`) and stopped before product tests because `tests/` is not a regular package. The explicit top-level was removed to restore the established `discover -s tests` authority rather than treating this as a regression.
- The final fresh-install attempt first stopped before resolution because the managed sandbox denied uv's user-cache `.git` access. The venv remains isolated; the exact install is retried with approved cache access rather than changing artifacts or pins.
- The approved uv install resolved the exact pins and passed `pip check`, but its PEP 610 record omitted the verifier-required `archive_info.hashes`; that environment is retained but disqualified. A second untouched venv will use canonical pip installation so provenance semantics match the device gate.
- Rebuilt from a byte-compared 145-file tracked staging tree after the third fix. The final wheel is 275,596 bytes, SHA-256 `f4d0ccfb02071b6d823336d91d7b8818cfeffc35ef20ece8a4e28e218fde2948`, and its 57-source digest is `e199e147b8f2ac11db32499f1e86c83df40bd8c980a24df0572773bddb9ba840`; the earlier 275,536-byte artifact is superseded.
- A fresh canonical-style pip venv passes `pip check`, MCP 1.29.0, websockets 17.0.1, hash-bearing local-wheel provenance, 57 installed-source checks, four entrypoints, and site-packages import origins. Interactive→observer stdio again passes 14/12 tools, protocol `2025-11-25`, zero stderr, private live socket, and cleanup.
- Created and validated the owner-private pre-commit handoff at `../Termu-inator-device-artifacts/s22u-2026-08-30-post-v0212-address-copy-candidate/`. The checksum, byte identity, 0700/0600 modes, four-file inventory, Bash syntax, and four exact on-device regressions pass; commit placeholders deliberately keep it non-executable until a clean push.
- Refreshed the code graph after the final source/test change (3,072 nodes, 17,943 edges). Final audit confirms base `4af303d90780...`, exactly the intended five modified paths, no tracked `.DS_Store`, clean diff whitespace, and wheel/source/bundle checks unchanged.
- Continuation check confirmed both local HEAD and live remote `main` remain `4af303d90780...` (`v.0.2.12`), while the exact five intended paths remain uncommitted locally. The candidate wheel and placeholder-sealed handoff remain unchanged pending the user-owned clean commit.
- A combined continuation audit initially invoked the repository diff check from the sibling artifact directory and stopped as non-repository before checksum execution. The checks were separated by explicit working directory; no source or artifact bytes were affected.
- A third consecutive continuation check again found local and live remote `main` at `4af303d90780...` with the same exact five uncommitted files. All safe in-scope implementation, validation, and handoff preparation is complete; sealing and S22U execution now require the user-owned commit/push identity.

## 2026-08-30 — `v0.2.13` repeated Firefox address-bar-copy follow-up

- Verified clean commit and live remote `2ee0a0ab25f75fc020963e801d043ae540657348` (`v.0.2.13`), exact five-file scope, 38/38 verifier tests, 4/4 device-bound regressions, and the 275,596-byte wheel's 57-source binding before sealing the owner-private handoff.
- Verified the returned manifest checksum `acc4fdd3b75ff5c3892ea72e78ef485120dea4f99f6d49e620f9dfe651979656` and raw-error SHA-256 `2bac2349fc59d53556f25ea025246f1dd83e40c93f5699b2ed295469cb65f1f2`, then preserved normalized 0700/0600 evidence at `../Termu-inator-device-artifacts/s22u-2026-08-30-v0213-fail-1/`.
- Canonical status remains FAIL with Chromium PASS, Firefox `address_bar_copy`, safe final cleanup, and benchmark skipped. The previous marker-release and longer-read hypotheses are not promoted as fixes because the same on-device stage and byte-identical raw error remain.
- Opened a new diagnostic-first cycle: split the coarse copy stage into fixed secret-free outcomes or gather equivalent private evidence, prove each contract RED before production changes, and keep benchmark closed.
- Code-graph inspection found three collapsed boundaries: xclip return status/stderr are discarded; focus/xdotool activation failures are suppressed; and a primary post-navigation metadata failure is swallowed before a second fallback. These findings define the next value-free diagnostic REDs and replace further timing guesses.
- Upstream xclip source confirms UTF8_STRING→XA_STRING fallback and nonzero failure on unavailable conversion, so the implementation will inspect status rather than changing targets speculatively. Defined a seven-value, secret-free reason allowlist and a focus-verification probe for TDD.
- Added reason, xclip-status, empty-selection, timeout, active-window, adapter propagation, and canonical allowlist tests before production changes. The corrected RED run produced 11 expected assertion failures and one pass.
- Implemented the seven-value reason contract across `src/commands.py`, `src/native.py`, `src/termuinator/backends/legacy.py`, and `scripts/final_verify.py`; updated only the three directly corresponding test modules.
- The exact 12-test reason/security set, all 34 native execution tests, the 100-test native/adapter/service/verifier suite, and the 38-test focused verifier are GREEN under warning-as-error.
- Full warning-as-error discovery passes all 387 tests on Python 3.11.15 and 3.12.13 with eight established optional-MCP skips. Pinned-MCP Python 3.14.7 executes all 387 tests with no skips. Diff whitespace, shell syntax, changed-line width, and three-interpreter compileall gates pass.
- The first Python 3.11 discovery inside the managed workspace returned only the known 15 local socket-bind permission errors; the identical approved run passed. `uv python find 3.12` also hit the known cache sandbox boundary, so the already-installed exact interpreter path was used directly.
- Copied all 145 tracked files byte-for-byte into a fresh private staging tree and built the wheel offline with a task-local uv cache. The 275,908-byte artifact is SHA-256 `3a5568acfb0ce09206cfab59d19f2847185205d524811f41ff99f29b3684c98f` and binds 57 sources with digest `c1c90306aec5fff4b53e0d7f6b102b76313f8a4d4424b5fb2a506630b1d76607`.
- The first fresh pip install stopped at the managed DNS boundary before installing dependencies. A second untouched Python 3.14 venv installed the exact wheel with the Termux constraint under approved network access, passes `pip check`, PEP 610 hash/path provenance, all 57 installed-source checks, four entrypoints, and site-packages-only import origins.
- Fresh-wheel interactive→observer stdio passes exact 14/12 inventories, protocol `2025-11-25`, zero stderr, private live control socket, same-data-root restart, and socket removal after each exit. Approved process inspection found no candidate process after the probe.
- Refreshed the fast code graph to 3,080 nodes and 17,995 edges. Direct review covers the excluded verifier script, and its 38 focused tests remain GREEN after the final allowlist ordering change.
- Preserved the exact wheel, checksum, non-approval README, and placeholder-gated Hermes instruction at `../Termu-inator-device-artifacts/s22u-2026-08-30-post-v0213-diagnostics-candidate/` with directory mode 0700 and file modes 0600. Checksum, byte identity, four-file inventory, and extracted Bash syntax pass.
- Reopened the completion audit instead of treating the diagnostic wheel as the final repair. Graph tracing confirmed `_navigate()` can accept protocol-supplied native metadata before the X11 fallback, and the existing dependency already pins a compatible `websockets` runtime.
- Reviewed Mozilla's current direct WebDriver BiDi and security contracts plus the Termux Firefox mozconfig. Remote Agent is explicit and loopback-only; Termux does not configure Firefox with `--disable-webdriver`.
- Created a repository-external bounded probe at `/private/tmp/termuinator-bidi-probe.py`. Its first run exposed a probe-only one-second stderr wait bug, which is logged in `task_plan.md`; the corrected run created a real Firefox 154 BiDi session and returned the final navigation URL.
- Extended the same isolated probe to evaluate `document.title`; the real result was `BiDi Proof`, and the final tree URL matched the navigation result. This validates a clipboard-free metadata design locally but is not S22U authority.
- Added three behavior tests before the BiDi production branch. All three failed as assertions against the old runtime: prepared BiDi was ignored in favor of GUI cleanup, a BiDi timeout became `NativeNavigationError`, and a protocol failure was reported as `address_bar_navigation`.
- Implemented only the prepared-session dispatch boundary: BiDi navigation returns native metadata directly, cancellation is preserved, timeout is rewritten without private text, and other protocol failures become the fixed `bidi_navigation` stage without any GUI retry.
- Added five protocol tests before the transport module. All five failed as explicit assertions because `src.firefox_bidi` did not exist, proving the new tests do not pass on the legacy clipboard runtime.
- Implemented a small sequential BiDi client with deferred websockets import, exact browser-emitted `127.0.0.1` endpoint parsing, bounded message/event sizes, a shared navigation deadline, fixed-value errors, HTTP(S) final-URL validation, typed title validation, and best-effort session/socket closure.
- The first lifecycle test attempt hung before product assertions because patching the module's shared `threading.Thread` object also replaced the executor implementation used by `asyncio.to_thread()`. Removed that invalid mock; the corrected test failed once at the intended missing BiDi attachment assertion.
- Added the browser-owned port-0 flag, a value-discarding stderr monitor, endpoint-to-client attachment, fixed fallback warning, and BiDi-before-Firefox cleanup. Added `bidi_navigation` to canonical's independent stage allowlist only after its focused test failed without the value.
- Ran `/private/tmp/termuinator-bidi-product-probe.py` with the current checkout and pinned websockets 17.0.1 against real Firefox 154 plus a private local redirect fixture. Exit code was 0; redirected final URL and title both matched exactly. No external network or repository artifact was used.
- Re-read the complete BiDi/native diffs and passed the expanded related integration suite at 110/110 plus the focused canonical verifier at 39/39 under warning-as-error.
- Ran a second local-only Firefox probe after proving the fixture page had loaded before `session.new`; both ephemeral port 0 and a nonzero loopback port exposed `navigator.webdriver=true`. The result is documented as an explicit reliability tradeoff, not hidden as an anti-detection path.
- Explored a WebDriver-free `places.sqlite` metadata alternative outside the repository. Ordinary read-only connections remained locked while Firefox ran; an `immutable=1` probe could see the redirect but violates the live-writer assumption, so no production code adopted it.
- Added cancellation regressions before implementation. The BiDi client first swallowed `CancelledError`, and native close first skipped Firefox termination when BiDi cleanup was cancelled. Both exact REDs are GREEN after bounded resource cleanup followed by cancellation re-delivery.
- The post-fix full matrix passes 398/398 tests on Python 3.11.15 and 3.12.13 with eight established optional-MCP skips; pinned-MCP Python 3.14.7 runs and passes all 398 tests. Final artifact validation remains pending after documentation and static review.
- After the final native cancellation cleanup and capability wording, the authority matrix passes 399/399 on Python 3.11.15 and 3.12.13 with the same eight optional-MCP skips; pinned-MCP Python 3.14.7 executes all 399. The 133-test related set, 39 focused verifier tests, diff/shell/width checks, and three-interpreter compileall also pass.
- Built from an empty private staging tree containing exactly 147 current tracked-or-intended files. The 279,236-byte wheel has SHA-256 `ef8b3d059429b68c3491c69606d017cd6f0d704887504ee5301f7bd9ab17cd1d`; canonical source binding verifies 58 packaged sources with digest `7f303900158b69e96cb02d521dfac8c5114dc1485fb0e0a972e544bd596e99e9`, plus ZIP/RECORD/metadata/license/member/entrypoint checks.
- Direct pre-commit binding against the dirty checkout failed closed because the new source is intentionally untracked. A private staging-only Git index produced the valid authority without touching the user's index; the clean-commit checkout must be verified again before device handoff.
- A fresh canonical pip Python 3.14 venv installs the exact wheel with MCP 1.29.0 and websockets 17.0.1, passes `pip check`, hash-bearing local-wheel provenance, all 58 installed sources, four entrypoints, and site-packages-only origins. The sandboxed first install stopped at DNS and is retained separately.
- Installed interactive→observer stdio passes 14/12 tools, protocol `2025-11-25`, server `0.1.0a1`, zero stderr, private live control sockets, and socket removal. The first sandboxed run was denied at Unix bind; the approved retry passed and an approved process query found no candidate survivor.
- Preserved the exact wheel, checksum, non-approval README, and placeholder-gated Hermes instruction under `../Termu-inator-device-artifacts/s22u-2026-08-30-post-v0213-bidi-candidate/` with directory mode 0700 and files 0600. Byte identity, checksum, four-file inventory, and extracted Bash syntax pass.
- Completion review found a startup race after that candidate: if Firefox emitted the BiDi endpoint just after the initial six-second wait but while the main window was being discovered, the monitor retained it but connect never consumed it. The updated lifecycle test reproduced this as one assertion failure.
- Added one two-second post-window grace on the same shielded future and raised only the BiDi handshake command bound from five to ten seconds. The exact delayed-endpoint RED is GREEN without changing builds that close stderr without an endpoint. The earlier 279,236-byte candidate is preserved but superseded pending a new build.
- Rebuilt from a second empty 147-file private staging tree after the delayed-endpoint fix. The authoritative pre-commit wheel is 279,258 bytes with SHA-256 `1d4095575db095f4f71a9f90aa76367b0c1d7db121f9b4feb9d941472c6008bd`; all 58 packaged and freshly installed sources bind to digest `cb5e0d565e0e6e2703f44d31e2e0e993798a8e90c6d591c70d386e8cf3f4caab`.
- The final fresh Python 3.14 install passes `pip check`, exact local-wheel provenance, four entrypoints, and site-packages origins with MCP 1.29.0/websockets 17.0.1. Installed interactive→observer stdio again passes 14/12 tools, protocol `2025-11-25`, zero stderr, private sockets, removal, and zero candidate survivors.
- Preserved the post-race interim candidate at `../Termu-inator-device-artifacts/s22u-2026-08-30-post-v0213-bidi-grace-candidate/` with 0700/0600 modes. It is now superseded by the hardened build and must not be sent to Hermes.
- Audited the service call boundary through the code graph: `BrowserService.navigate()` keeps one mutex across the complete backend operation, so no extra BiDi transaction lock is required.
- Added exact response-ID and duplicate-connect regressions. Both failed on Python 3.11.15 before implementation (`FirefoxBidiError not raised`, connector calls `2 != 1`) and pass after strict integer identity plus an early connected-state guard; the complete BiDi module is 8/8 GREEN on Python 3.14.
- The first focused command accidentally used macOS system Python 3.9.6 and stopped during module import on supported union syntax. No product assertion ran; the exact tests were immediately rerun with Python 3.11.15 to obtain valid RED evidence.
- Added a leading-junk endpoint case to the existing parser contract. It failed by returning a loopback URL before implementation, then passed after the parser changed from suffix search to exact full-line matching.
- The final full matrix now contains 401 tests. The managed sandbox reproduced only its established 15 socket-bind errors (plus the dependent MCP SIGTERM assertion); identical approved runs pass all 401 on Python 3.11.15 and 3.12.13 with eight optional-MCP skips, and all 401 on pinned-MCP Python 3.14.7.
- Three-interpreter warning-as-error compileall, `git diff --check`, `bash -n setup.sh`, and changed Python 100-column checks pass after the final endpoint hardening.
- Rebuilt from a third empty 147-file staging tree whose tracked and intended bytes matched the working checkout. The hardened wheel is 279,287 bytes, SHA-256 `67d2b6b97c7c116da98a50aba955429f58a0b04e0383ccbd25e6939dbff353b0`, and passes canonical 58-source binding at digest `880d3a6853f5bbd30d18a1019867d81258cb0850fe0509d2f3e0cf51ca144f6d` plus ZIP/RECORD/metadata/license/member/entrypoint checks.
- The first fresh venv installed only the wheel's base dependency and was retained but disqualified because MCP was not requested. A second untouched Python 3.14 venv installed the exact `[mcp]` wheel under the Termux constraint and passes `pip check`, PEP 610 hash provenance, 58 installed-source bytes, four entrypoints, and site-packages origins with MCP 1.29.0/websockets 17.0.1.
- Installed interactive→observer stdio passes 14/12 tools, protocol `2025-11-25`, server `0.1.0a1`, zero stderr, private control sockets, socket removal, and zero candidate survivors.
- Created the owner-private final pre-commit bundle at `../Termu-inator-device-artifacts/s22u-2026-08-30-post-v0213-bidi-hardened-candidate/`. Its checksum, wheel byte identity, exact four-file inventory, 0700/0600 modes, extracted Bash syntax, and deliberate commit placeholders pass.
- Re-ran the exact Hermes device-focused module command after the final parser change: 48/48 native/BiDi/adapter tests pass under warning-as-error. The final post-change full matrix again passes 401/401 on Python 3.11, 3.12, and pinned-MCP 3.14.

## 2026-08-30 — `v0.2.15` Firefox observe follow-up

- Verified both newly transferred manifest/checksum/raw-error sets are byte-identical and checksum-valid. Preserved one normalized copy plus the neutral fixture JPEG with 0700/0600 permissions; originals remain untouched in Downloads.
- Reconfirmed the repository is clean at `072831a3324a7169a57faec41d137920e38777e1` (`v.0.2.15`) before starting the next patch.
- Traced canonical `browser_observe` through `BrowserService.observe()` and `LegacyPilotBackend.observe()` into DOM, text, accessibility, and screenshot collection. Navigation uses BiDi, but every JavaScript-backed observation still enters the console/clipboard compatibility path.
- Ran the 70-test BiDi/native/adapter baseline under pinned-MCP Python 3.14.7: all tests passed.
- Added five behavior tests before production changes. The exact RED run produced two missing-method errors for `FirefoxBidiClient.evaluate()` and three failures proving `_exec_js_inner()` is still called for BiDi success, timeout, and protocol failure.
- Implemented `FirefoxBidiClient.evaluate()` with strict remote-value decoding and switched `NativeFirefoxSession._exec_js()` to BiDi whenever the owned session exists. All five original REDs are GREEN; timeout and protocol failures do not touch the console fallback.
- Extended the repository-external Firefox 154 fixture to call the exact DOM observation, body-text, and synthetic-accessibility paths. It returned `complete`, four interactive elements, matching text, and ten accessibility nodes with exit code 0.
- Added observation-stage diagnostics test-first. The adapter RED produced two failures and two raw errors; the verifier RED omitted the requested stage. Both are GREEN after fixed stage details and an independent canonical allowlist, with private exception text still absent.
- Added an invalid-Unicode expression boundary test. The valid RED exposed `UnicodeEncodeError`; the client now converts it to the fixed `FirefoxBidiError`. The complete BiDi/native/adapter/verifier set passes 117 tests under Python 3.14 warning-as-error.
- Updated README and backend architecture/capability documentation to state the actual split: loopback WebDriver BiDi for navigation and JavaScript-backed observation, X11 for native input/window capture, and console/clipboard only when Remote Agent attachment is unavailable.
- Full warning-as-error discovery passes 409/409 tests on Python 3.11.15 and 3.12.13 with the established eight optional-MCP skips, and all 409 on pinned-MCP Python 3.14.7. The managed sandbox first reproduced only its known 15 socket-bind errors and dependent SIGTERM assertion; the identical approved runs passed.
- Three-interpreter compileall, `git diff --check`, `bash -n setup.sh`, changed Python 100-column checks, the 40-test verifier suite, and the 77-test device-focused set pass. A final real Firefox probe also passed and left no matching browser process.
- Built from an exact 147-file private staging copy. The 280,566-byte wheel has SHA-256 `9aeee2c8ffc3a8c4d678527b1de8d1957a2a99a47c0b8f38f7f0cb7c1cc61d3b`, binds 58 sources at digest `6301967d5bb50857a01f9c3e0999832599fdd47dfea43bec084faab90179cab9`, and passes ZIP/RECORD/metadata/license/member/entrypoint checks.
- The first fresh pip venv stopped at managed DNS and was retained but disqualified. A second untouched Python 3.14 venv installed the exact wheel's MCP extra under the Termux constraint, passes `pip check`, exact PEP 610 wheel provenance, all 58 installed-source bytes, four entrypoints, and site-packages-only imports.
- Installed interactive→observer stdio passes 14/12 tools, protocol `2025-11-25`, server `0.1.0a1`, zero stderr, private live sockets, clean removal, and zero candidate survivors.
- Preserved the exact wheel, checksum, non-approval README, and placeholder-gated Hermes instruction at `../Termu-inator-device-artifacts/s22u-2026-08-30-post-v0215-observe-bidi-candidate/` with 0700/0600 modes. Checksum, byte identity, four-file inventory, and extracted Bash syntax pass.
