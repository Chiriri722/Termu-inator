# Compact MCP v1 Tool Contracts

Status: M1 contract-freeze candidate, 2026-08-24. Machine-readable snapshots
live under `schemas/v1/` and are authoritative when prose and implementation
drift. Contract, manifest, backend-protocol, and MCP protocol revisions are
independent. The initial values are `1.0`, `1.0`, `1.0`, and `2025-11-25`.

## Default Surface

The default MCP server exposes exactly 14 tools and has a hard ceiling of 16.

| Tool | Input focus | Output focus | Risk |
|---|---|---|---:|
| `browser_session_start` | project, backend, viewport | session, capabilities | R1 |
| `browser_session_status` | session | cached status and freshness | R0 |
| `browser_session_stop` | session | stopped state | R1 |
| `browser_navigate` | goto/back/forward/reload | observation | R1 |
| `browser_observe` | text/a11y/screenshot options | observation and refs | R0 |
| `browser_act` | typed `ActionRequest` | verified `ActionResult` | R1–R4 |
| `browser_wait` | structured condition | satisfied state | R0 |
| `browser_tabs` | list/open/switch/close | tab state | R1 |
| `browser_screenshot` | viewport/full/ref | artifact metadata | R0 |
| `browser_downloads` | list/wait | download/artifact metadata | R0–R2 |
| `browser_artifact_read` | URI, offset, limit | base64 chunk | R2 |
| `browser_permissions` | list/status | policies and pending challenge | R0 |
| `browser_devtools` | approved read-only query | redacted result | Developer |
| `browser_trace` | list/get/export | redacted trace/artifact | R0 |

There is no compact upload tool, raw eval tool, cookie/storage mutation tool, or
raw CDP passthrough. Chromium is the default backend in
`browser_session_start`; Firefox must be requested explicitly.

## Common Results and Errors

Every successful tool returns its own closed output object; there is no generic
`{result, error}` response. The internal manifest uses `input_schema` and
`output_schema`, while the deterministic MCP projection emits only MCP Tool
fields: `name`, `description`, `inputSchema`, `outputSchema`, and annotations.
All projected schemas are self-contained Draft 2020-12 documents.

Input/value validation and expected domain failures are MCP Tool Execution
Errors (`isError: true`). Their text content is a bounded JSON representation
of the stable `ErrorEnvelope`; successful structured content alone is checked
against the tool's `outputSchema`. Unknown tool names, malformed `tools/call`
envelopes, and server/transport failures use MCP protocol errors instead.

The stable envelope contains `code`, `message`, code-owned `retryable`, a closed
set of redacted `details`, and an optional `diagnostics_id`. Callers cannot
override retryability.

The v1 error set is `invalid_request`, `session_not_found`, `session_busy`,
`unsupported_capability`, `permission_required`, `permission_denied`,
`confirmation_required`, `session_paused`, `ownership_denied`,
`idempotency_conflict`, `outcome_unknown`, `stale_observation`,
`target_not_found`, `timeout`, `action_failed`, `backend_crashed`,
`artifact_not_found`, and `internal_error`. Only `session_busy`,
`stale_observation`, `target_not_found`, `timeout`, and `backend_crashed` are
retryable, and a retry still requires the documented preconditions.

Unknown fields are rejected in public schemas. A backend limitation is
`unsupported_capability`, not a no-op success.

## Observation and Ref Lifetime

`page_revision` is `<document_epoch>:<mutation_counter>`. The epoch changes on
top-level document replacement, tab identity change, browser recovery, or
origin transition. The counter increases for normalized DOM mutations.

Refs are opaque `ref_...` tokens bound server-side to owner scope, session,
page, document epoch, frame/shadow path, and a node fingerprint. Agents must not
parse refs or substitute CSS selectors. Every page-sensitive tool carries
`session_id`, `tab_id`, `page_id`, and `expected_page_revision`; an identifier
from another owner, page, or revision is rejected before backend dispatch.

Each `Observation` binds one versioned `capability_revision` and contains
bounded text plus an explicit `text_truncated` flag, bounded accessibility
nodes, interactive refs, dialogs, challenges, download deltas, and an optional
screenshot artifact. Backend features are fidelity records (`supported`,
`emulated`, `partial`, `unsupported`, or `broken`) with reason, limits,
dependencies, and probe time—not booleans.

- Equal revision: action may continue.
- Changed epoch: always `stale_observation`.
- Same epoch, changed counter: R0/R1 may revalidate an identical fingerprint.
- R2, R3, R4, or Developer action after any mutation: new observation required.

## Typed Actions and Verification

`browser_act` accepts click, type, key, scroll, select, check, hover, and drag.
Click/type/select/check/hover/drag require a ref. Each request carries an
`action_id`, `idempotency_key`, exact page preconditions, typed parameters,
timeout, and nullable `confirmation_id`. There is no caller-supplied risk class,
risk context, confirmation token, selector, or arbitrary parameter bag.

Risk context is untrusted evidence, not a caller-selected classification. The
service owns the effective risk and may raise the action-kind minimum after
inspecting the target and expected effect; caller input can never lower it.
Operation-specific schemas also require the corresponding URL, tab/ref, or
challenge/trace identifier instead of accepting a request that can only fail
after dispatch.

| Action | Minimum verification |
|---|---|
| click | target event plus URL, dialog, download, visibility, or DOM change |
| type | resulting editable value, with secret values redacted |
| key | focus plus key-specific navigation/dialog/value outcome |
| scroll | viewport offset or target visibility change |
| select | selected option/value |
| check | checked state |
| hover | hover/focus state or declared visible effect |
| drag | source/target position or application state change |

Every verification item identifies the action, observation revision and time,
expected and actual summaries, target when applicable, and whether the evidence
is causal. Transport success without a causally verified effect returns
`failed`, not `succeeded`; `ActionResult.status` has only `succeeded` and
`failed`.

Idempotency is a durable service journal, not a five-minute cache. Before
dispatch the service atomically records the owner scope, key, canonical action
digest, and state. The state machine is `reserved` (or
`waiting_confirmation`) → `dispatched` → terminal result. The same key and
digest returns the stored terminal result. A different digest returns
`idempotency_conflict`. Recovery of a nonterminal `dispatched` entry returns
`outcome_unknown` and never guesses that repeating a consequential effect is
safe.

## Permissions and Confirmation

`browser_permissions` can list policy and inspect a challenge; it cannot grant
itself new authority. New origins default to `ask`. Persistent decisions are
`block` or `always_allow`; `session_allow` expires with the active session.

R4 and sensitive R3 actions return `confirmation_required` with an exact
preview and a non-secret opaque `confirmation_id`. Approval occurs through MCP
host elicitation or the local CLI fallback. The usable authorization state and
random nonce remain server-side; no bearer token is placed in model-visible
arguments. The approval is valid for 120 seconds, consumed atomically once, and
binds transport-established owner scope, project, session, origin, document
revision, canonical action digest, and idempotency key. The exact action is
retried with the same key and returned `confirmation_id`.

Form elicitation never asks for passwords, API keys, access tokens, payment
credentials, or other secrets. Sensitive entry and sign-in use user takeover or
an out-of-band URL flow instead.

## Artifact Transport

Artifact metadata includes URI, content hash, size, MIME type, creation time,
and expiry. The URI is exactly `artifact://sha256/<digest>` and its digest must
equal `sha256`; expiry must be later than creation. `browser_artifact_read`
requires the active session plus an artifact URI, verifies transport owner,
project and session authorization, and accepts an offset and at most 512 KiB
per call. It returns a closed base64 chunk with current/next offsets and EOF. It
never accepts filesystem paths.

Default retention is 24 hours or 500 MiB per project, whichever causes LRU
eviction first. Downloads and screenshots use the same storage boundary.

## Acceptance Scenarios

1. **Read and inspect:** start project session, approve origin, navigate,
   observe text/refs, optionally retrieve a screenshot artifact, stop cleanly.
2. **Safe interaction:** observe, act on a ref, verify the actual state change,
   then observe the new revision.
3. **Sign-in handoff:** detect credential/OTP state, enter confidential takeover
   state, block agent observation/action/artifact/Developer reads, let the user
   take over locally, resume explicitly, invalidate old refs, and observe again.
4. **Consequential action:** prepare an exact R4 preview, require a fresh
   one-shot server-held approval, execute once, and return verification plus a
   redacted trace.
5. **Web QA:** enable Developer Mode for an allowed origin, perform read-only
   console/network/DOM/style/performance queries, and export a redacted trace.
6. **Download and analyze:** initiate or observe a download, wait for completion,
   return hash/MIME/size, and read it remotely in bounded chunks.

Each scenario runs against deterministic local fixtures on both advertised
backends. External anti-bot behavior is never a release gate.

Developer availability and authorization are separate. The compact server must
start with `--developer-mode`, then the owner grants the currently observed
origin through `tbp-control developer-mode SESSION_ID ORIGIN enable`. Neither
ordinary origin permission nor page content can perform this mutation. The
compact query union contains no response-body, header-value, cookie, eval, or
raw-CDP branch.
