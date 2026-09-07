# Benchmark quality follow-up after v0.2.18

This is a preparation checklist, **not an authorization to rerun v0.2.18**.
Its canonical and benchmark identities have already been consumed. Keep the
old checkout, wheel, venv, reports, and sealed ZIP unchanged.

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

In the next sealed handoff, derive paths in this order before existence checks:

```bash
umask 077
TFV_BENCH_RUNTIME="$HOME/.cache/tfb/$TFV_SHORT"
TFV_BENCHMARK="$TFV_BENCH_RUNTIME/h/benchmark"
```

Here `TFV_SHORT` must come from the newly sealed commit, not the consumed
v0.2.18 identity. The canonical helper `_child_environment(runtime, ...)`
creates the isolated `h` directory. Its returned `paths['home']` must satisfy:

```python
assert output == paths['home'] / 'benchmark'
assert environ['HOME'] == str(paths['home'])
```

Pass that `output` to `--output`, use the returned child environment for the
benchmark subprocess, and derive its socket/pidfile from the same child HOME.
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

Camofox and Lightpanda remain deferred options, outside this repair.
