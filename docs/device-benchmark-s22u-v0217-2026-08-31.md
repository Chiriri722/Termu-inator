# S22U Compact RC Benchmark — v0.2.17

This report compares the compact release candidate with the initial S22U
baseline. It contains only the sanitized aggregate. The raw benchmark report
remains outside the repository because it contains Android paths, PIDs, process
arguments, and Hermes runtime details.

## Evidence Scope

- Device: Samsung Galaxy S22 Ultra, Android 16, aarch64
- Termux: 0.118.3
- Python: 3.14.6
- Commit: `c4f580217c7f65b14ac635f17fcebc07870ea039` (`v.0.2.17`)
- Firefox: 154.0
- Chromium: 149.0.7827.155
- Tailscale split tunneling: Excluding mode, Termux toggle OFF
- Canonical completion: `2026-08-31T01:43:27.938342+00:00`
- Benchmark measurement: `2026-08-31T01:45:05.614079+00:00`
- Canonical native cryptography: 50.0.0

The checksum-valid canonical manifest records both backends PASS, zero stderr
for interactive and observer MCP profiles, complete cleanup, and
`benchmark_allowed=true`. The benchmark began about 98 seconds later from the
same commit-suffixed checkout and venv. Hermes later reported that the current
system and inherited venv import cryptography 50.0.1; that later environment is
not represented by these measurements.

## Latency Comparison

Hermes round-trip time is excluded. The harness measures local
`src.client.send_command()` calls with `time.perf_counter()`.

### Firefox

| Operation | Target | 2026-08-15 median | v0.2.17 median | Change | v0.2.17 |
|---|---:|---:|---:|---:|---|
| Cold startup | baseline only | 11,019.197 ms | 15,266.793 ms | +38.55% | recorded |
| Warm status | ≤300 ms | 4,270.495 ms | 1.776 ms | -99.96% | pass |
| Text | ≤2,000 ms | 2,137.565 ms | 8.572 ms | -99.60% | pass |
| Screenshot | ≤4,000 ms | 1,654.342 ms | 1,710.200 ms | +3.38% | pass |

The release candidate removes the multi-second Firefox warm status and text
overages. Firefox cold startup regressed by 38.55%; cold startup has no pass
budget and remains an explicit optimization target rather than being hidden by
the warm-command gains.

### Chromium

| Operation | Target | 2026-08-15 median | v0.2.17 median | Change | v0.2.17 |
|---|---:|---:|---:|---:|---|
| Cold startup | baseline only | 7,505.045 ms | 6,894.127 ms | -8.14% | recorded |
| Warm status | ≤300 ms | 10.982 ms | 2.099 ms | -80.89% | pass |
| Text | ≤2,000 ms | 8.836 ms | 8.842 ms | +0.07% | pass |
| Screenshot | ≤4,000 ms | 216.396 ms | 222.512 ms | +2.83% | pass |

Every latency sample in both backends completed without a classified operation
error. Firefox page load was 2,767.133 ms and Chromium page load was
1,127.345 ms; both reached `https://example.com/` with title `Example Domain`.
Five screenshots per backend were valid PNGs. Firefox images were 30,472 bytes
and Chromium images were 18,340 bytes.

## RSS After Page Load Plus 10 Seconds

| Process group | Firefox baseline | Firefox v0.2.17 | Chromium baseline | Chromium v0.2.17 |
|---|---:|---:|---:|---:|
| Daemon Python | 28,000 KiB | 28,632 KiB | 32,128 KiB | 31,524 KiB |
| Browser processes | 1,129,788 KiB | 1,098,156 KiB | 250,340 KiB | 266,628 KiB |
| Xvfb | 38,160 KiB | 34,744 KiB | 32,944 KiB | 33,116 KiB |
| openbox | 21,268 KiB | 21,912 KiB | 19,664 KiB | 20,456 KiB |

Browser figures sum per-process RSS and may double-count shared memory. The
largest increase is Chromium browser RSS at 6.51%, below the existing 20%
baseline-growth guardrail.

## Integrity and Authority Boundary

| Artifact | SHA-256 |
|---|---|
| Canonical manifest | `a080d83112c6f3f8069c1bf17a4a47c170ba62111c9ca6d36bf2dd32ff79f912` |
| Candidate wheel | `420b6702e519a4e6e0705540e3e7421904eda415fa632d51cb4f8a4e6824d328` |
| Raw benchmark report | `2af623f99ae9c33e4c4319370ccb897f7051b8ba0d7a2e50bc6d12ceed86b7fc` |
| Sanitized benchmark summary | `c4bf727942ce4190a42d0d323add2c87bbcd62ae61ed87cd2762fee1676fb393` |

The downloaded summary is an exact semantic derivation of the raw report. The
v0.2.17 benchmark format did not embed the canonical manifest hash, wheel hash,
or cryptography version, so this report is historical measurement evidence,
not authorization to rerun or extend the same output identity. Future runs use
the hardened benchmark gate, which verifies those identities before and after
measurement and refuses stale or reused output paths.

This closes the compact release-candidate performance remeasurement item. It
does not close the separate long soak, forced-crash recovery, clean-install, or
release-publication gates.
