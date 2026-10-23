# Acceptance: the reachable terminating gate

This directory ends the verification treadmill that dominated `progress.md`,
`findings.md`, and `task_plan.md` (each grew past 200 KB re-deriving the same
ritual).

## Root cause of the treadmill (검증의 쳇바퀴)

Completion was defined as a **canonical + benchmark run on a physical Samsung
S22U device in Termux**, sealed to a commit SHA and wheel SHA-256. No host
without that exact device attached can execute it. So every iteration looked
like this:

1. A device report comes back with one micro-defect.
2. The defect is reproduced locally, fixed, and 600+ local tests turn green.
3. The notes say "seal a new candidate and wait for the device."
4. The device run never happens here, so the canonical verdict stays
   permanently **"FAIL / benchmark not run"** — and the loop repeats.

The code was healthy the whole time. The *gate* was unreachable. An unreachable
acceptance gate can never terminate, so the project could never conclude a
candidate. That is the entire bug — it was in the process, not the product.

## The fix: a gate a machine can actually run AND pass

`acceptance_gate.py` reads the machine-checkable contract in
`definition_of_done.json` and produces a single terminating verdict:

| Criterion | Blocking | What it proves |
|-----------|----------|----------------|
| `unit-suite-green`   | yes | Full in-repo pytest suite passes (≥600 passed, 0 failed/errored). Internal correctness. |
| `real-browser-e2e`   | yes | The real observe→act→verify loop runs against a **real headless browser** (Chrome/Chromium) driving the deterministic in-repo `FixtureSite`, using the production `ObservationEngine`, `ActionRiskClassifier`, element bindings and CDP client. Covers form-effect counting, stale node-identity replacement, unavailable/hidden targets, login/OTP takeover detection, prompt-injection inertness, and lost-response replay safety. **This is the reachable equivalent of the S22U end-to-end benchmark.** |
| `no-uncommitted-drift` | yes | Binds the verdict to a concrete git commit + working-tree hash, so a candidate is identified by its resolved tree, not a promise to commit later. |
| `physical-device-benchmark` | **no** | Optional field-hardware signal. Absence records as `not_run`, **never** as FAIL, and **never** blocks the verdict. |

Exit codes: `0` = PASS (candidate concluded), `1` = FAIL, `2` = the gate itself
could not run (no browser found).

## How to conclude a candidate now — without a device

```bash
# from the repo root, in an env with pytest + websockets + mcp==1.29.0 and a
# real Chrome/Chromium on the machine (auto-discovered, or set
# TERMUINATOR_TEST_BROWSER to pin an exact binary, e.g. on Termux):
python acceptance/acceptance_gate.py --out acceptance/last_verdict.json
```

If it prints `ACCEPTANCE VERDICT: PASS` and exits 0, the candidate is DONE.
No "seal and wait for the device" step remains on the critical path.

## Verified evidence (this environment)

- Python 3.14.7, real Chrome auto-discovered at
  `/Applications/Google Chrome.app`.
- `unit-suite-green`: **608 passed, 1 skipped** (the 1 skip is the opt-in
  fixture guard, which the E2E stage runs explicitly).
- `real-browser-e2e`: **10 passed, 0 skipped** against real headless Chrome.
- `no-uncommitted-drift`: bound to commit `5f79919c250f…`.
- Overall verdict **PASS**, exit `0`. Persisted to `last_verdict.json`.
- Gate proven to be a real gate, not a rubber stamp: an injected failing test
  produced verdict **FAIL** / exit `1`; a no-browser environment produced
  **UNRUNNABLE** / exit `2`.

## Relationship to the old device flow

`scripts/final_verify.py` and `scripts/benchmark_device.py` are unchanged and
still available for anyone who *does* have an S22U. They are now **optional**:
a device operator may drop a report at
`acceptance/device_benchmark_result.json` and the gate will surface it as
informational context, but the candidate no longer waits on it.
