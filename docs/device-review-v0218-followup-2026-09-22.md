# S22U evidence review and local follow-up — 2026-09-22

The supplied browser evidence remains **v0.2.18 canonical PASS / benchmark
quality FAIL**. It is not a v0.2.19 device result. Local HEAD was clean at
`0a295fe4cdf94bc185e7f75f932043b017beac78` (`v.0.2.19`) before this follow-up;
that commit contains the previous nine-file benchmark repair.

## Keep the four documents' scopes separate

| Attachment | Scope | Effect on this work |
|---|---|---|
| `S22U-v0218-RESULT.ko.md` | Termu-inator device evidence | Preserve canonical PASS and screenshot quality FAIL; no rerun of its identity |
| `results.json` | Separate study_checker plugin probes | Not browser evidence; no changes to that project |
| `S22U-STEPS1-4-REPORT.ko.md` | Buzz TLS build and public profile verification | Not a browser gate or SSH/channel connection result |
| `S22U_Termux_Hermes_Safe_Access_Guide.md` | Proposed remote recovery design | Reference only; not authorization or proof of installed SSH/Tailscale services |

The downloaded canonical manifest still hashes to
`9af8cc2e61bab26b38f08f33cfa78c53087b5912800c13514d1ad785ad9cf3fe`, matching
the report. Both canonical browser artifacts and cleanup passed. The benchmark
has zero successful screenshots and five screenshot errors per backend.
No private device error logs were inspected in this follow-up.

Attachment SHA-256 values, recorded without copying private service state:

```text
d878ba53dc2d05fa65c612d54fbb315daf21b7756e0e6fbb8cd902cc46a7f99a  S22U-v0218-RESULT.ko.md
da5438d33db7d686034a70c4ba7cd07fddbc4893dd5cc02beff1444847484dd5  results.json
df9d912bbff3cbb07fde129a218123f491d6a4d503bf63c43fee8012b2b5fb23  S22U-STEPS1-4-REPORT.ko.md
2e617b637d52945d5ce71a64f0f9e45c32f6ac8656b541d96fee3b0aa65ea133  S22U_Termux_Hermes_Safe_Access_Guide.md
```

## Locally reproduced gaps after v0.2.19

- Measurements used the legacy client's implicit auto-start. A dead daemon
  could be replaced during a supposedly warm sample. The benchmark now opts out;
  ordinary CLI callers retain their existing default behavior.
- Intermediate stop results were ignored. Failed cleanup or cold/warm startup
  now ends the remaining measurement path, preserves a fixed FAIL reason, and
  still performs final cleanup.
- Probe socket/pidfile options did not select the CLI/client's actual target.
  The harness now requires all paths to match the current HOME and refuses
  pre-existing daemon state before any stop command. Dangling paths are not
  treated as absent cleanup.
- Manual isolation instructions could diverge from the screenshot boundary.
  `--isolated-runtime` now derives child HOME/XDG/TMP and output together, sets
  private creation permissions, and launches only once.
- Public summaries omitted the error category. Fixed `artifact_invalid` and
  `command_failed` counts now accompany the aggregate without raw private text.

These findings are local source/test evidence, not a new explanation extracted
from S22U private logs. The safe-access guide's remote commands were not run.
No package, network, key, registration, or production change was made on S22U.

## Local verification

Fourteen new lifecycle regressions were added test-first. The focused
benchmark/lifecycle/packaging suite passes 70/70. The full warning-as-error suite
passes 457/457 on Python 3.14.7 with MCP 1.29.0 and websockets 17.0.1.
Python 3.11.15 and 3.12.13 also pass the 457-test suite with the existing eight
optional-MCP skips each. Compile checks, setup shell syntax, and diff-check pass.

A pre-commit wheel built from tracked source was installed in a fresh local
venv with pip. Its 58 wheel/installed-source files, entrypoints, metadata,
license/RECORD checks, PEP 610 archive hash, CLI version, and pip check pass.
Local wheel: 280661 bytes, SHA-256
`d308358ef02670286c01e2041b3b82a495b47b64356909bd05f465c2e1780f36`.
Source-tree digest:
`9be6acf4d12d1850823ef2f0051c64ad7af6cc6b627fe0accc9d5609d8c727a1`.
This is build/install evidence, **not a sealed release or Android ABI proof**.

The intended commit scope is exactly twelve paths:

```text
scripts/benchmark_device.py
src/client.py
tests/test_benchmark_device.py
tests/test_benchmark_lifecycle.py
tests/test_packaging_contract.py
docs/benchmark-quality-handoff.md
docs/device-review-v0218-followup-2026-09-22.md
docs/integrations.md
docs/termux-install.md
task_plan.md
findings.md
progress.md
```

## Next device step

Use the updated [benchmark handoff](benchmark-quality-handoff.md) only after
the next user-owned clean commit and exact wheel/source binding are sealed.
This patch changes `src/client.py`, so the v0.2.18 wheel is not the candidate.
Keep the native cryptography/Python/MCP identity current at execution time;
do not assume September 7's environment is still unchanged. Canonical and the
conditional isolated benchmark must use fresh identities and run once each.

Remote SSH installation, Buzz channel access, Camofox, and Lightpanda remain
separate optional work. A passing local suite is not device approval.
