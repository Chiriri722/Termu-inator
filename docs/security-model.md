# Security Model — Termu-inator v1

Status: M1 contract-freeze candidate, 2026-08-24.

This document is the **Normative target** security model. The current compact
alpha implements the typed authority, origin decisions, one-shot confirmation,
idempotency, takeover, durable storage, redaction, Developer gates, and
loopback shared-view boundaries covered by local tests.
It does not yet intercept redirects or pin DNS/peer addresses in the real legacy adapters,
and it does not claim real tab/dialog/download lifecycle support, download
quarantine, or completed device/SSH recovery gates.

## Assets and Trust Boundaries

Protected assets include browser profiles, credentials and OTPs, cookies and
storage, downloads, screenshots, trace data, approval authority, and the Termux
host. The MCP host transport, Termu-inator service, selected browser backend and
browser process/profile are privileged parts of the trusted computing base:
they can observe browser secrets and must not be described as sandboxed from
one another. Web content, remote origins, downloaded content, and shared-view
clients remain untrusted boundaries. Backend adapters must preserve that
distinction when returning page-derived data.

Page text, DOM attributes, accessibility labels, downloaded filenames, console
messages, and network content are always untrusted input. They cannot alter tool
availability, origin policy, risk classification, Developer Mode, approval
state, retention, or redaction rules.

## Origin Policy

Only `http` and `https` navigation URLs are accepted. Origin is canonical
scheme, IDNA-normalized host, and effective port. The implemented service checks
that canonical origin and its permission before initial backend dispatch, then
quarantines an unexpected resulting origin. The legacy adapter does not yet
intercept redirects before following them, resolve and classify every address,
or pin DNS answers to the actual peer. The normative release requirement is to
reject loopback, link-local, multicast, unspecified, private, carrier-grade
NAT, metadata, and other non-public destinations unless an exact owner-local
policy authorizes them, and to repeat that validation before every redirect.
In normative terms, validation occurs before following every redirect.

New origins default to `ask`; `block` wins over all allows. Session permission
is memory-only. Persistent policy is stored in service-owned state with mode
0600, outside the browser-writable profile.

Origin access approval and consequential-action approval are independent. An
allowed site cannot submit, send, purchase, delete, change permissions, expose
secrets, or enable Developer Mode without the relevant action policy.

## Risk and Human Confirmation

- R0: read-only observation and trace access.
- R1: navigation, focus, scrolling, and tab movement.
- R2: ordinary state changes such as typing, selecting, checking, or starting a
  download.
- R3: credentials, OTP, clipboard, files, history, cookies, and other sensitive
  data.
- R4: submit, send, purchase, delete, permission changes, and similarly
  consequential effects.
- Developer: browser-internal console, network, DOM/style, performance, raw
  eval, or CDP access.

R4 and sensitive R3 operations require a human preview and a server-held
cryptographically random 256-bit nonce. The model receives only a non-secret
opaque `confirmation_id`, never an authorization bearer. Approval expires after
120 seconds, is consumed atomically once, and binds transport owner scope,
project ID, session, origin, document epoch, mutation revision, canonical action
digest, and idempotency key. Any redirect, mutation, payload change, crash, or
replay invalidates it.

MCP elicitation is preferred when supported. Otherwise the tool returns a
challenge identifier and the user approves through a local `tbp approve`
fallback. Form elicitation must not collect secrets; credentials, OTPs, API
keys, access tokens, and payment data use confidential local takeover or an
out-of-band URL flow. The agent-facing `browser_permissions` tool never grants
itself authority, and the read-only shared view cannot approve anything.

## Profiles and Local Files

Project-scoped persistent profiles use a SHA-256-derived directory under the
Termu-inator data root. The original project path is never interpolated into a
filesystem path. Browser profile storage is additionally separated by backend
and profile schema, for example
`projects/<project-digest>/profiles/<backend>/v1/profile`. Service-owned policy,
approval, idempotency, artifact, and trace state lives in a sibling state tree
that the browser profile cannot write. Directories are 0700 and files are 0600.
Symlinks, `..`, absolute user paths, and post-resolution escape from the
selected root are rejected.

Browser profile data, including cookies, storage, and history, persists until a
user invokes an explicit project-data reset; it has no silent time-based purge
and is never exposed through the compact tools. Session-only permissions and
takeover state are memory-only. Artifacts use the bounded retention policy
below. Redacted traces retain at most seven days or 100 MiB per project with LRU
eviction, and an explicit host/CLI purge removes them sooner.

The service supports a single active session to prevent concurrent writers from
corrupting one profile. Profile locks include ownership and liveness checks;
stale locks are recovered only after the owning process is proven absent.

Project identity supplied in a tool argument is only a label. The MCP/CLI
transport establishes the authenticated owner scope, and the service binds the
project digest, session, refs, permissions, artifacts, traces, approvals, and
idempotency records to it. A caller cannot select another tenant merely by
guessing its project ID, session ID, or content hash.

Credential or OTP detection transitions the session through
`user_takeover_required` to `user_takeover_active`. While either state is
present, agent navigation, observation, action, screenshot, artifact, trace,
and Developer reads fail with `session_paused`; only bounded redacted session
status is available. Resume is a local host/CLI operation, rotates the page
epoch, invalidates refs and approvals, and requires a fresh observation.

## Artifacts and Remote View

Artifacts are named by SHA-256 and addressed as `artifact://sha256/<digest>`.
The URI digest and `sha256` field must match, and expiry must be later than
creation. Every read also requires an active session and verifies transport
owner, project, and session authorization; the digest is not treated as
sufficient authority. Reads are bounded to 512 KiB, offset-checked, and base64
encoded for stdio. Default retention is 24 hours with a 500 MiB per-project LRU
quota. Metadata includes MIME, size, digest, timestamps, and download completion
state.

The static read-only shared view is default OFF and accepts only literal
loopback binding in the current alpha. Every response uses `Cache-Control: no-store`,
a restrictive CSP, strict Host validation, no embedding, and bounded
redacted fields. There are no mutation routes and no takeover, resume, policy,
confirmation-decision, raw artifact, cookie, header, response-body, or secret
views. Pending prompts omit authority identifiers, proof, and nonces;
shared-view page output stops during confidential takeover. Direct Tailnet
binding is not implemented. Any future Tailnet listener must be a separate host
operation and require encrypted tailnet transport plus a high-entropy bearer
in an authorization header, never in a URL.

## Secret Handling and Audit

Credential and OTP values, cookie values, authorization/proxy headers, request
and response bodies, clipboard content, form values marked sensitive, and
approval nonces and confirmation identifiers are excluded from normal logs.
Screenshots are not assumed safe; the caller controls capture and artifact
expiry.

Traces record action kind, ref identity, risk, revision, permission decision,
verification, timing, and a redacted diagnostics ID. They do not record raw
eval source or secret field values. Export re-applies redaction.

## Idempotency and Crash Recovery

The service records owner scope, idempotency key, canonical action digest, and
state durably before backend dispatch. Valid transitions are `reserved` (or
`waiting_confirmation`) to `dispatched` to one terminal result. The same key
with a different digest is `idempotency_conflict`; a terminal same-digest retry
returns the recorded result. A process restart that finds `dispatched` without
a terminal result returns `outcome_unknown` and never silently dispatches the
effect again. The journal is service-owned and outside browser-writable profile
storage.

## Developer and Legacy Isolation

Developer Mode is default OFF and enabled per session and per origin. The
compact tool exposes a closed union of bounded read-only console, network
metadata, DOM, style, and performance queries. Every query is bound to tab,
page, and expected revision and returns a query-specific closed output. Raw
response bodies, cookie/header values, raw eval, and raw CDP are absent from the
compact surface; a future separate experimental transport would require its own
threat review and cannot inherit compact-mode authority.

Availability requires the explicit `tbp-mcp-v1 --developer-mode` startup flag;
runtime JSON and environment authority keys are rejected. The current origin
then requires a separate owner-local `tbp-control developer-mode` grant. Grants
are session-scoped, are never derived from page text, and are discarded when
the session stops. Console credential patterns are redacted, and network URLs
drop userinfo, fragments, and query values before crossing the public wire.

The v0.x legacy interface cannot bypass these checks. Upload is absent from the
compact MVP and default-disabled in legacy mode. Legacy tools are never exposed
in the default Hermes/Codex configuration.

## Required Security Tests

Release tests cover pre-follow redirect checks, IDN normalization, DNS
rebinding/private-address denial, stale refs, approval expiry/replay/race,
idempotency mismatch and crash recovery, takeover confidentiality, prompt
injection, secret redaction, artifact hash/lifetime/traversal, symlink escape,
oversized chunk requests, backend/profile-schema separation, profile lock
recovery, shared-view authentication/cache/CSP behavior, stdout purity, and
Developer/legacy default isolation.
