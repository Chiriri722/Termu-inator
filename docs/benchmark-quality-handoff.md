# Benchmark quality follow-up after v0.2.18

> Historical preparation record: the v0.2.19 commit-wait instructions below
> were superseded by the v0.2.20 run. The active post-v0.2.20 hardening work is
> tracked in [the current plan](../task_plan.md#current-phase) and is not yet a
> sealed candidate. Do not execute the historical hold/run text as a new order.

This is a preparation checklist, **not an authorization to rerun v0.2.18**.
Its canonical and benchmark identities have already been consumed. Keep the
old checkout, wheel, venv, reports, and sealed ZIP unchanged.

## Next post-v0.2.20 candidate: not sealed

The current local base is `22155ee1d7536dbf7f1fcd1d98507323b6db96ce`.
The hardening work is uncommitted; this SHA does not identify the new candidate.
Before sending an executable Hermes instruction, obtain the user's new clean
commit, verify its exact tree/path scope, then bind a newly built wheel and its
byte count/hash/source provenance. No old wheel filename or test count substitutes
for those identities. Preserve the current native cryptography version at the
device run; past 50.0.0/50.0.1 evidence does not establish today's environment.

The newly sealed instruction must authorize canonical once, followed only on
complete PASS by one isolated benchmark in the same environment. The local
canonical now also exercises form effects, confirmation/replay, stale/unavailable
targets, waits, and takeover boundaries. These have not yet passed on S22U.
Active-browser interruption, 100-action runs, and one-hour idle/resume remain
separate planned checks: declare their candidate ownership, run counts, new
output identities, and approval before execution. Do not append them to a
consumed canonical/benchmark run or enable production after a partial PASS.

Completed sanitized JSON is the final response for a run. Generate the Korean
summary from it; do not request another run or wait for a second prose response.

## Handoff status checked on 2026-09-22

The local HEAD and GitHub `origin/main` both resolve to
`0a295fe4cdf94bc185e7f75f932043b017beac78` (`v.0.2.19`), tree
`278c0b44c40703d24ca2052692b72d1656960ed6`. This is the **base commit**, not
the new candidate: the twelve-path follow-up is still uncommitted.
No candidate commit, canonical output identity, or execution authorization
can be inferred from this checklist or the pre-commit wheel hash.

Copyable correction for Hermes while the new commit is pending:

```text
검수 지시 정정 — 지금은 실행 보류입니다.

제작팀이 확인한 로컬/GitHub 기준 commit:
0a295fe4cdf94bc185e7f75f932043b017beac78 (v.0.2.19)
이 SHA는 기존 기준점이며, 이번 12개 파일 보강을 포함한 검수 대상 SHA가 아닙니다.
보강본은 아직 미커밋 상태이므로 새 candidate commit은 미확정입니다.

앞서 전달한 benchmark-quality-handoff.md는 준비 체크리스트였습니다.
기존 SHA나 latest/main을 임의의 검수 대상으로 사용하지 말고,
pre-commit wheel만으로 새 환경을 설치하거나 canonical/benchmark를 실행하지 마세요.

제작팀이 새 commit의 전체 SHA, Git tree, 정확한 변경 범위,
일치하는 wheel과 SHA-256, 새 실행 경로를 확정한 지시서를 보내겠습니다.
그때까지 기존 환경과 증거를 보존하고 대기해주세요.
```

## What the evidence establishes

The v0.2.18 canonical manifest SHA-256 is
`9af8cc2e61bab26b38f08f33cfa78c53087b5912800c13514d1ad785ad9cf3fe`.
It binds commit `379b0e97431ac2c25fb6a5d1b0a9d287caa70fa4`, native
cryptography 50.0.1, both browser PASS results, and successful cleanup.
The subsequent sanitized benchmark reports five screenshot errors and zero
successful screenshots for each browser, despite command exit 0.

The old handoff supplied screenshot paths outside the isolated HOME. The
existing daemon rejects those paths before capture. This mismatch is reproduced
locally; the private device error strings have not been received. Do not claim
that the raw device logs were inspected or that browser replacement is needed.

## Seal a new candidate before device execution

1. Obtain the user's new clean commit SHA. Verify remote HEAD, tree, exact
   changed paths, no tracked `.DS_Store`, and `git diff --check`.
2. Bind the candidate wheel and checksum to that checkout using the canonical
   verifier. Record the exact byte count, SHA-256, and source/install identities.
   Do not choose a wheel by its filename or a historical size alone.
3. Seal new commit-suffixed checkout, venv, canonical output, and benchmark
   runtime paths. Existing paths must abort the preparation, not be overwritten.
4. Run the focused benchmark/packaging, verifier, native/BiDi/adapter, and full
   suites. Use the test counts recorded for the final candidate, not v0.2.18's
   old counts. Keep native cryptography and all environment versions exact.
5. Execute canonical once. Only its complete PASS, checksum, zero-stderr,
   artifact, provenance, and cleanup conditions permit the immediately following
   isolated benchmark in the same execution block.

## Keep screenshot output inside the child HOME

Use the executable isolation option in the next sealed handoff. Keep this
command immediately after its new canonical PASS; do not run it against a
historical PASS after the environment has changed:

```bash
umask 077
"$TFV_VENV/bin/python" scripts/benchmark_device.py \
  --project-root "$TFV_PROJECT" \
  --tbp "$TFV_VENV/bin/tbp" \
  --wheel "$TFV_WHEEL" \
  --canonical-manifest "$TFV_OUTPUT/final-verify-manifest.json" \
  --isolated-runtime "$HOME/.cache/tfb/$TFV_SHORT" \
  --tailscale-termux-state "Excluding mode; Termux OFF" \
  --network-kind "$TFV_NETWORK_KIND"
```

The `TFV_*` values must come from the new sealed instruction. This command
rechecks canonical authority before creating the runtime, then launches exactly
one child with private HOME/XDG/TMP paths and umask 077. The child independently
rechecks authority before and after measurement. Parent HOME is unchanged.
Do not combine `--isolated-runtime` with `--output`, `--socket`, or `--pidfile`.

The derived paths are:

```bash
umask 077
TFV_BENCH_RUNTIME="$HOME/.cache/tfb/$TFV_SHORT"
TFV_BENCHMARK="$TFV_BENCH_RUNTIME/h/benchmark"
```

Here `TFV_SHORT` must come from the newly sealed commit, not the consumed
v0.2.18 identity. Internally the canonical helper `_child_environment(runtime, ...)`
creates the isolated `h` directory. Its returned `paths['home']` must satisfy:

```python
assert output == paths['home'] / 'benchmark'
assert environ['HOME'] == str(paths['home'])
```

The launcher passes that output and derives the child's socket/pidfile from
the same HOME. Existing runtime identities or daemon state are rejected before
any stop command; old profiles and running services are not benchmark targets.
Keep the short runtime path to avoid Unix socket length limits. Do not change
the operator's global HOME or the daemon's `validate_path()` boundary.

Each browser writes its PNGs below `h/benchmark/<backend>/`. Raw and sanitized
reports are under `h/benchmark/`. Directory modes remain 0700; file modes 0600.

## Judge quality separately from execution

`quality.status` records the measurement result. Exit 0 additionally requires
successful return-file publication; neither value grants production approval.

| Exit | Meaning | Action |
|---|---|---|
| 0 | Quality and return-file publication both PASS | Review the summary and independent cleanup evidence |
| 1 | Quality or publication failed | Preserve the separate results; no retry or promotion |
| 2 | Authority or output preflight rejected | Preserve the used identity; report the bounded error |
| Other / missing report | Unexpected execution failure | Preserve evidence; no retry or promotion |

PASS requires the configured counts (default cold 3, status 20, text 10,
screenshot 5 per backend), zero sample errors, successful startup/navigation,
and valid screenshot artifacts. A successful screenshot response without a
valid owner-private PNG is an error, not a latency sample. Validation checks
regular-file identity, permissions, bounded size, PNG chunks/CRC, dimensions,
compressed-stream completion, and exact IEND/EOF; it does not prove the page's
semantic content, which remains the canonical browser gate's responsibility.

Median budgets remain status ≤300 ms, text ≤2000 ms, screenshot ≤4000 ms.
Cold startup is recorded without inventing a new latency threshold. All
requested backends must be present. The harness verifies final socket/pidfile
absence; the device operator must still independently check process survivors,
control sockets, display leases, and session locks as in the canonical handoff.

Return `baseline-summary.json` for either quality PASS or quality FAIL when
it exists, plus canonical manifest/checksum. Keep raw reports, process arguments,
private stdio/stderr, and screenshot paths private. Do not install packages,
change network/Hermes configuration, register MCP, or switch production.

Intermediate cleanup is mandatory before every cold/warm launch and backend
transition. `execution_failure.reason` reports `unsafe_cleanup_state`,
`cold_start_failed`, or `warm_start_failed`; the remaining backends are not
attempted and the final cleanup still runs. Warm measurements disable the
legacy client's implicit daemon startup: a dead daemon remains a failed sample,
not an unrecorded replacement process.
Startup/cleanup command details remain in the private raw report's
`execution_failure.evidence`; the public summary exposes only fixed labels.

The sanitized summary also reports per-operation counts of `artifact_invalid`
and `command_failed`. These fixed categories do not disclose private exception
strings, response payloads, filesystem paths, or page content. They classify the
observed boundary, not an inferred Firefox/Chromium crash cause.

## Post-v0.2.20 reporting hardening — local, not yet device-verified

The public `cleanup` section now records `scope: daemon_files_only`, a status,
and the observed socket/pidfile absence booleans. A metadata access failure is
`null`/`UNKNOWN`; an observed remaining entry is `false`/`FAIL`. The first
unavailable observation is preserved rather than retried into a clean result.
An existing or uninspectable runtime is rejected before output creation or a
stop command. These file checks alone do not prove browser/helper process termination,
display-lease release, session-lock release, or global Unix socket absence.

The local benchmark now authenticates the daemon through its connected Unix
socket peer PID/UID, private pidfile, and process start ticks. The CLI launcher
double-forks, so its PID is not treated as the daemon PID. An unavailable
pre-launch process census prevents launch. After launch, incomplete ancestry
does not discard an already authenticated daemon's shutdown authority.

Shutdown uses that same authenticated connection and rechecks its recorded
generation, rather than reconnecting through an unchecked CLI stop. No
unowned daemon receives shutdown and no census-derived PID receives a signal.
Before/finally observations around warm commands retain visible descendants,
including on failure/cancellation, outside the measured command interval.
Cold latency still ends at socket readiness, before identity inspection.

The additive `process_cleanup` record reports fixed counts and a status for
`visible_same_uid_processes` separately from daemon-file absence. Confirmed
observed survivors are FAIL; unattributed new processes or incomplete evidence
remain UNKNOWN/UNAVAILABLE. Either blocks the next cold/warm/backend launch
and `quality.status: PASS`. Numeric identities remain in the private raw report.
This is sampled ancestry, not proof of invisible or never-observed descendants.
Canonical now checks both successful and failed backend transitions through
`post_stop`, allowing only the same live MCP root/control socket. Failed or
incomplete cleanup blocks the next backend and observer restart. Interactive
MCP exit is checked again without the live-root exception before the observer
launch. Benchmark authorization rejects a declared non-PASS `post_stop`, even
if the surrounding report claims PASS. Legacy reports without this additive
field remain readable; this does not authorize reusing an old execution identity.
No new device execution or production approval follows from these local tests.

The same sanitized JSON produces a private `baseline-summary.ko.txt` with the
run's completion, quality result, limited cleanup scope, and remaining review.
Return this note with the JSON instead of treating the JSON-only response as
an unfinished job. Neither note grants production approval. New evidence fields
apply to new sealed executions, not to rewriting earlier PASS/FAIL reports.

After measurement, environment authorization, Git identity/cleanliness, and
every expected PNG are checked independently. `post_run` exposes fixed
environment/checkout statuses and PNG status counts. A read denial is not a
missing file, and a valid but changed PNG is not the captured sample. A symlinked
PNG parent or unsafe file mode fails validation. Missing sample metadata stays
unbound instead of being promoted from a later file read.

Unlike the historical harness, closing authority/cleanup failures preserve the
measurements and quality-FAIL report. Unexpected measurement errors also stop
further browser work, preserve completed backends, and continue independent
readback. Report writing refuses existing files and symlinks. Preflight rejection
still happens before browser work and returns exit 2; a recorded run failure
returns exit 1. No failure triggers an automatic rerun or production approval.
Canonical now performs the equivalent independent closing Git/environment/PNG
checks. Cancellation and post-run process evidence write failures preserve the
completed backend results and continue independent cleanup checks. If one
private diagnostic cannot be saved, the public failure report is still written
when its own output path remains usable.

Return `final-verify-files.json` with its canonical manifest, checksum, and Korean
note; return `baseline-files.json` with the benchmark summary and Korean note.
These owner-private records compare each file with the exact bytes supplied by
its writer and include its hash, size, mode, and current-owner check. The reader
is bounded and nonblocking, rejects unsafe file/parent identities, and checks
for changes during reading. The integrity record does not hash itself.

A publication failure never rewrites the saved run result to make the two agree.
Canonical exits 1 with stdout FAIL and benchmark permission false; the benchmark
loader also requires any declared canonical return-file record to pass and
match current bytes. Benchmark publication failure exits 1 with a fixed
`report_publication=FAIL` message even if its saved quality result is PASS.
Missing integrity output is not approval. Returned-file checks do not establish
browser-descendant termination; use the separately scoped process evidence.

Camofox and Lightpanda remain deferred options, outside this repair.
