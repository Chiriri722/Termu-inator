# Benchmark quality follow-up after v0.2.18

This is a preparation checklist, **not an authorization to rerun v0.2.18**.
Its canonical and benchmark identities have already been consumed. Keep the
old checkout, wheel, venv, reports, and sealed ZIP unchanged.

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

| Exit | Meaning | Action |
|---|---|---|
| 0 | Version 2 `quality.status` is `PASS` | Review the summary and independent cleanup evidence |
| 1 | `quality.status` is `FAIL`; reports preserved | Return the sanitized summary; no retry or promotion |
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

Camofox and Lightpanda remain deferred options, outside this repair.
