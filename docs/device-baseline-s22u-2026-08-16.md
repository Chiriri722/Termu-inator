# S22U Device Baseline — 2026-08-16

This document records the sanitized on-device evidence used to close the
browser-smoke and performance-measurement portions of Phase 1. Raw benchmark
reports and process listings remain outside the repository because they contain
device-local paths, process arguments, and Hermes runtime details.

The compact release-candidate comparison is recorded in
[`device-benchmark-s22u-v0217-2026-08-31.md`](device-benchmark-s22u-v0217-2026-08-31.md).

## Evidence Level

- Device: Samsung Galaxy S22 Ultra, Android 16, aarch64
- Termux: 0.118.3
- Python: 3.14.6
- Package under test: `tbp 0.1.0a1`
- Firefox: 153.0.4
- Chromium: 149.0.7827.155
- Measurement time: `2026-08-15T16:00:02.043658+00:00`
- MCP environment: `~/.venvs/termuinator-mcp-v1`
- Network prerequisite: Tailscale Android split tunneling was in Excluding
  mode with the Termux application toggle **OFF**.

This is real-device evidence, but it is not clean-install evidence. The device
had an existing Hermes and Termu-inator setup. `crawl4ai` had been removed from
that ambient environment; its removal is not considered a cause of success.

## Network Root Cause and Recovery

Before the Termux split-tunneling toggle was disabled, direct HTTPS access to
`1.1.1.1` worked while `curl` and Python `getaddrinfo()` could not resolve
`example.com`. Disabling that toggle restored both IPv4 HTTP access and
IPv4/IPv6 name resolution without changing the resolver, packages, MCP venv, or
Tailscale DNS settings.

The evidence therefore attributes the outage to the Tailscale Android
split-tunneling path, not to MCP, Python, `cryptography`, or `crawl4ai`.

## Browser Smoke

Both backends passed the same `example.com` smoke in fresh Hermes sessions.

| Check | Firefox | Chromium |
|---|---|---|
| Backend identity | `firefox` | `chromium` |
| Final URL | `https://example.com/` | `https://example.com/` |
| Title | `Example Domain` | `Example Domain` |
| Body contains `Example Domain` | pass | pass |
| Screenshot | valid non-empty PNG | valid non-empty PNG |
| Screenshot dimensions | 1916 × 868 | 1911 × 803 |
| Screenshot bytes | 28,768 | 18,340 |
| Clean stop | pass | pass |

## Local-Socket Performance Baseline

Hermes round-trip time was excluded. Measurements wrap
`src.client.send_command()` with `time.perf_counter()`.

| Operation | Target | Firefox median | Firefox | Chromium median | Chromium |
|---|---:|---:|---|---:|---|
| Cold startup | baseline only | 11,019.197 ms | recorded | 7,505.045 ms | recorded |
| Warm status | ≤300 ms | 4,270.495 ms | fail | 10.982 ms | pass |
| Text | ≤2,000 ms | 2,137.565 ms | fail | 8.836 ms | pass |
| Screenshot | ≤4,000 ms | 1,654.342 ms | pass | 216.396 ms | pass |

No measured operation sample was classified as an error. The Firefox status
and text budgets remain unchanged; the overages are optimization targets rather
than reasons to relax the product budget.

## RSS After Page Load Plus 10 Seconds

| Process group | Firefox | Chromium |
|---|---:|---:|
| Daemon Python | 28,000 KiB | 32,128 KiB |
| Browser processes | 1,129,788 KiB | 250,340 KiB |
| Xvfb | 38,160 KiB | 32,944 KiB |
| openbox | 21,268 KiB | 19,664 KiB |

The browser figures are sums of per-process RSS and may double-count shared
memory. Termux `ps` rejected uppercase output specifiers, so the benchmark
preserved that failure and used `ps -A -o pid,ppid,rss,comm,args` as its
effective command.

## Raw Artifact Integrity

The private raw artifact directory is:

`../Termu-inator-device-artifacts/s22u-2026-08-16/`

The following device and Mac hashes matched before this document was produced:

| Artifact | SHA-256 |
|---|---|
| `baseline_benchmark.py` | `2f364c2e778fd568ff78ec237ae76fcf991eb9b411846b9fc101faab7395bb59` |
| `baseline-report.json` | `c4b36e5a0711152909a2153fc7d8af53a4c32b68b11ceabf918ea1d018d67eb7` |
| `run-output-final.json` | `d254185403132dbf55ed95879c89d0c9ef04598ee6d7987f156f0e47e857b630` |

Do not copy the raw JSON or process captures into the public repository. A
future portable benchmark must parameterize checkout, executable, output,
socket, and profile paths and emit a sanitized summary separately from raw
diagnostics.
