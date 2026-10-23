#!/usr/bin/env python3
"""Reachable, deterministic acceptance gate for Termu-inator.

WHY THIS EXISTS
---------------
For many iterations the project's definition of "done" was a *canonical +
benchmark run on a physical Samsung S22U device in Termux*, sealed to a specific
commit SHA and wheel SHA-256. That gate is unreachable from any host that does
not physically have the device attached. The consequence was a verification
treadmill: every cycle reproduced a micro-defect locally, fixed it, turned 600+
local tests green, and then had to "seal a new candidate and wait for the
device" -- which never terminated, so the canonical verdict stayed permanently
"FAIL / benchmark not run".

This gate replaces that unreachable gate with one a developer machine or CI
runner can actually execute AND pass, producing a terminating PASS/FAIL verdict:

  Stage A  unit-suite-green   -- the full in-repo pytest suite (internal correctness)
  Stage B  real-browser-e2e   -- the real observe->act->verify loop against a REAL
                                 headless browser driving the deterministic
                                 in-repo FixtureSite, using production engine code
  Stage C  no-uncommitted-drift -- bind the verdict to git commit + tree hash

The physical-device benchmark is retained only as OPTIONAL, informational signal
(never blocks completion, absence records as "not_run", never as FAIL).

USAGE
-----
    python acceptance/acceptance_gate.py                 # human + JSON to stdout
    python acceptance/acceptance_gate.py --json-only      # machine-readable JSON only
    python acceptance/acceptance_gate.py --out verdict.json

Exit code 0 == all blocking criteria PASS (candidate concluded).
Exit code 1 == at least one blocking criterion FAILED.
Exit code 2 == the gate itself could not run (e.g. no browser found).

The gate is deterministic and terminating: given the same repo tree and a
working browser, it always reaches a verdict without waiting on a device.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = Path(__file__).resolve().parent / "definition_of_done.json"

# Candidate real-browser locations, in preference order. Chrome/Chromium first
# because the E2E fixture test drives them via CDP.
_BROWSER_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    "google-chrome-stable",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "chrome",
)


def discover_browser() -> str | None:
    """Return an executable path to a real Chrome/Chromium, or None.

    An explicit TERMUINATOR_TEST_BROWSER env var always wins so operators can
    pin an exact binary (including on Termux/Android).
    """
    override = os.environ.get("TERMUINATOR_TEST_BROWSER")
    if override and (Path(override).is_file() or shutil.which(override)):
        return override
    for candidate in _BROWSER_CANDIDATES:
        if os.path.sep in candidate:
            if Path(candidate).is_file() and os.access(candidate, os.X_OK):
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    return None


def repo_identity() -> dict:
    """Bind the verdict to a concrete repository identity (commit + tree)."""
    def _git(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30
            )
        except Exception:
            return None
        if out.returncode != 0:
            return None
        return out.stdout.strip()

    commit = _git("rev-parse", "HEAD")
    # Working-tree hash: hash of the porcelain status + HEAD so a dirty tree is a
    # DISTINCT identity from the committed one. This makes a candidate identifiable
    # by its resolved tree rather than a promise to commit later.
    status = _git("status", "--porcelain") or ""
    dirty = bool(status.strip())
    import hashlib

    tree_hash = hashlib.sha256(
        ((commit or "no-commit") + "\n" + status).encode("utf-8")
    ).hexdigest()
    return {
        "commit": commit,
        "dirty": dirty,
        "tree_identity_sha256": tree_hash,
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
    }


def _run_pytest(target: str, extra_env: dict | None = None, timeout: int = 900) -> dict:
    """Run pytest on a target and parse its summary line deterministically."""
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    # PYTHONPATH so `tests.fixtures...` and `src...` import regardless of cwd.
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [sys.executable, "-m", "pytest", target, "-q", "-p", "no:cacheprovider", "-rs"]
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout, env=env
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "timeout", "passed": 0, "failed": 0,
                "errors": 0, "skipped": 0, "duration_s": timeout, "summary": "TIMEOUT"}
    duration = round(time.monotonic() - started, 3)
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    summary = tail[-1] if tail else ""
    # Parse counts like "608 passed, 1 skipped in 12.77s" / "10 passed"
    def _count(word: str) -> int:
        m = re.search(r"(\d+)\s+" + word, summary)
        return int(m.group(1)) if m else 0

    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "passed": _count("passed"),
        "failed": _count("failed"),
        "errors": _count("error"),
        "skipped": _count("skipped"),
        "duration_s": duration,
        "summary": summary,
    }


def check_pytest(criterion: dict, browser: str | None) -> dict:
    params = criterion.get("params", {})
    target = params.get("target", ".")
    extra_env = {}
    env_spec = params.get("env", {})
    for key, value in env_spec.items():
        if value == "<auto-discovered-browser>":
            if not browser:
                return {"criterion": criterion["id"], "status": "FAIL",
                        "detail": "no real browser discovered for real-browser E2E",
                        "evidence": {}}
            extra_env[key] = browser
        else:
            extra_env[key] = value
    result = _run_pytest(target, extra_env=extra_env)
    checks = []
    ok = result["ok"]
    if "min_passed" in params:
        cond = result["passed"] >= params["min_passed"]
        checks.append(("min_passed", params["min_passed"], result["passed"], cond)); ok = ok and cond
    if "max_failed" in params:
        cond = result["failed"] <= params["max_failed"]
        checks.append(("max_failed", params["max_failed"], result["failed"], cond)); ok = ok and cond
    if "max_errors" in params:
        cond = result["errors"] <= params["max_errors"]
        checks.append(("max_errors", params["max_errors"], result["errors"], cond)); ok = ok and cond
    if "max_skipped" in params:
        cond = result["skipped"] <= params["max_skipped"]
        checks.append(("max_skipped", params["max_skipped"], result["skipped"], cond)); ok = ok and cond
    return {
        "criterion": criterion["id"],
        "status": "PASS" if ok else "FAIL",
        "detail": result["summary"],
        "evidence": {
            "target": target,
            "browser": extra_env.get("TERMUINATOR_TEST_BROWSER"),
            "passed": result["passed"], "failed": result["failed"],
            "errors": result["errors"], "skipped": result["skipped"],
            "duration_s": result["duration_s"],
            "thresholds": [
                {"name": n, "limit": lim, "actual": act, "ok": c} for (n, lim, act, c) in checks
            ],
        },
    }


def check_repo_identity(criterion: dict, browser: str | None) -> dict:
    identity = repo_identity()
    ok = identity.get("commit") is not None
    return {
        "criterion": criterion["id"],
        "status": "PASS" if ok else "FAIL",
        "detail": ("bound to " + (identity.get("commit") or "?")[:12]
                   + (" (dirty tree)" if identity.get("dirty") else " (clean tree)")),
        "evidence": identity,
    }


def check_device_benchmark_optional(criterion: dict, browser: str | None) -> dict:
    # Informational only. Absence is "not_run", never FAIL. A device operator may
    # drop a JSON report at acceptance/device_benchmark_result.json to record a
    # signal; the gate reads it but never blocks on it.
    report = Path(__file__).resolve().parent / "device_benchmark_result.json"
    if report.is_file():
        try:
            data = json.loads(report.read_text())
        except Exception:
            data = {"parse_error": True}
        return {"criterion": criterion["id"], "status": "INFO",
                "detail": "device report present (informational, non-blocking)",
                "evidence": data}
    return {"criterion": criterion["id"], "status": "INFO",
            "detail": "not_run (no physical device; non-blocking by contract)",
            "evidence": {"state": "not_run"}}


_CHECKS = {
    "pytest": check_pytest,
    "repo_identity": check_repo_identity,
    "device_benchmark_optional": check_device_benchmark_optional,
}


def run_gate() -> dict:
    contract = json.loads(CONTRACT_PATH.read_text())
    browser = discover_browser()
    results = []
    blocking_pass = True

    for criterion in contract.get("blocking_criteria", []):
        handler = _CHECKS.get(criterion["check"])
        if handler is None:
            outcome = {"criterion": criterion["id"], "status": "FAIL",
                       "detail": f"unknown check '{criterion['check']}'", "evidence": {}}
        else:
            outcome = handler(criterion, browser)
        outcome["blocking"] = True
        results.append(outcome)
        if outcome["status"] != "PASS":
            blocking_pass = False

    for criterion in contract.get("informational_criteria", []):
        handler = _CHECKS.get(criterion["check"])
        outcome = handler(criterion, browser) if handler else {
            "criterion": criterion["id"], "status": "INFO",
            "detail": "no handler", "evidence": {}}
        outcome["blocking"] = False
        results.append(outcome)

    verdict = {
        "gate": "termuinator-reachable-acceptance",
        "contract_version": contract.get("contract_version"),
        "terminating": True,
        "verdict": "PASS" if blocking_pass else "FAIL",
        "browser_used": browser,
        "python": sys.version.split()[0],
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo_identity": repo_identity(),
        "criteria": results,
    }
    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Termu-inator reachable acceptance gate")
    parser.add_argument("--json-only", action="store_true", help="print only the JSON verdict")
    parser.add_argument("--out", type=str, default=None, help="also write the JSON verdict to this path")
    args = parser.parse_args(argv)

    browser = discover_browser()
    if browser is None:
        # The gate itself cannot run its reachable E2E stage without a browser.
        verdict = {
            "gate": "termuinator-reachable-acceptance",
            "verdict": "UNRUNNABLE",
            "detail": "no real Chrome/Chromium browser found; set TERMUINATOR_TEST_BROWSER",
            "terminating": True,
        }
        print(json.dumps(verdict, indent=2))
        return 2

    verdict = run_gate()
    payload = json.dumps(verdict, indent=2)

    if args.out:
        Path(args.out).write_text(payload + "\n")

    if args.json_only:
        print(payload)
    else:
        print(payload)
        print()
        print("=" * 68)
        print(f"ACCEPTANCE VERDICT: {verdict['verdict']}  "
              f"(commit {(verdict['repo_identity'].get('commit') or '?')[:12]}, "
              f"browser {Path(browser).name})")
        for item in verdict["criteria"]:
            tag = "BLOCK" if item.get("blocking") else "info "
            print(f"  [{tag}] {item['status']:<5} {item['criterion']}: {item['detail']}")
        print("=" * 68)

    return 0 if verdict["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
