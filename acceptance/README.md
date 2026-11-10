# Acceptance: the L0 local gate

**This directory holds the L0 gate. It does not replace S22U device acceptance.**
The lanes are defined in
[docs/verification-lanes.ko.md](../docs/verification-lanes.ko.md); the current
position is in [STATUS.md](../STATUS.md).

| Lane | Where | Purpose | Counts as acceptance |
|------|-------|---------|----------------------|
| **L0 (this gate)** | Mac or CI | Regression check on every change | No |
| L1 | S22U, unsealed | Find causes, confirm fixes, raw logs | No |
| L2 | S22U, sealed | Approve a candidate | Yes |

## What it checks

| Criterion | Blocking | What it proves |
|-----------|----------|----------------|
| `unit-suite-green` | yes | The in-repo pytest suite passes (at least 600 passed, 0 failed or errored). |
| `real-browser-e2e` | yes | The observe→act→verify loop runs against a real headless desktop Chrome/Chromium driving the in-repo `FixtureSite` with the production `ObservationEngine`, `ActionRiskClassifier`, element bindings and CDP client (10 tests, 0 skipped). |
| `no-uncommitted-drift` | yes | Records the commit and working-tree identity the verdict came from. |
| `physical-device-benchmark` | no | Shows a device report if one is present. Device results are judged in L1/L2. |

## Run it

```bash
.venv_verify/bin/python -B acceptance/acceptance_gate.py --out acceptance/last_verdict.json
```

Exit codes: `0` all blocking criteria passed, `1` at least one failed, `2` the
gate could not run (no browser found; set `TERMUINATOR_TEST_BROWSER`).

A PASS means the tree is fit to go to the device. It says nothing about Termux
Chromium or Firefox on Android.

## Limits to keep in mind

- `no-uncommitted-drift` passes on a dirty tree. It is an identity record, not a
  cleanliness check. The clean-commit requirement belongs to L2
  (`scripts/final_verify.py`).
- `physical-device-benchmark: not judged here` is not a statement that the
  device is optional. S22U acceptance is mandatory for alpha.
- `last_verdict.json` is only as fresh as the last run that wrote it. Check its
  `timestamp_utc` and `repo_identity`.

## History

This gate was added on 2026-09-30 as a way to conclude a candidate without the
device, on the reasoning that the product was healthy and only the process was
stuck. That reasoning did not hold: later device rounds found a real product
defect (sensitive fields were not detected right after navigation) and a
Chromium startup failure on the device that no desktop run can show. The user
kept the S22U gate mandatory on 2026-10-23, and on 2026-11-10 this gate was
repositioned as L0. Criteria and thresholds are unchanged; the original README
is in git history at `feb7bd8`.
