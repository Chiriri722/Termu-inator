# Migration from the Legacy TBP Surface

This migration changes the product model without forcing an immediate public
command rename. The `termux-browser-pilot` distribution and `tbp` / `tbp-mcp`
commands remain throughout v0.x. A new display or command name is a **separate v1 migration** and is not part of the current alpha.

> **Current alpha checkout:** `tbp-mcp` still starts the preserved 148-tool
> legacy server. The compact 14-tool service is the separate `tbp-mcp-v1`
> entrypoint, and the provided Hermes/Codex examples select it explicitly.
> Legacy CLI delegation and the future `tbp-mcp --legacy` inversion below are
> release targets, not claims about this checkout.

## Release Lifetime

- **v0.1:** compact 14-tool MCP becomes the default. The old MCP server remains
  available only through explicit `tbp-mcp --legacy`. Existing high-value CLI
  commands delegate to the new service. Sensitive legacy operations are
  default-disabled.
- **v0.2:** `--legacy` remains available with a deprecation warning on stderr;
  default Hermes/Codex examples continue to expose only the compact surface.
- **v0.3:** the 148-tool legacy MCP server may be removed after usage and
  migration evidence is reviewed. Public `tbp` / `tbp-mcp` command names still
  remain.
- **v1:** naming and distribution changes require a separately approved
  migration, release note, aliases, and removal schedule.

No warning or banner may be printed to stdout by an MCP stdio process.

## Command Mapping

| Existing surface | v1 destination | Compatibility rule |
|---|---|---|
| start/status/stop/restart | `browser_session_*` | one active session; restart preserves backend |
| goto/back/forward/reload | `browser_navigate` | explicit origin policy and observation result |
| text/links/a11y/find/elements/state | `browser_observe` | normalized refs replace selector guessing |
| click/type/press/scroll/select/check/hover/drag | `browser_act` | typed action plus revision and verification |
| wait variants | `browser_wait` | one structured condition union |
| tab commands | `browser_tabs` | unsupported backend paths fail explicitly |
| screenshot/annotate/element screenshot | `browser_screenshot` | content-addressed artifact result |
| downloads | `browser_downloads` + `browser_artifact_read` | completion, MIME, size, hash, remote bytes |
| console/network/DOM/style/perf | `browser_devtools` | read-only and Developer Mode gated |
| macro/mutation logs | `browser_trace` | redacted trace; replay is post-MVP |

## Default-Disabled Legacy Operations

Raw eval, raw CDP, cookie/storage mutation, clipboard access, request/response
body access, custom headers, mocking, throttling, geolocation and UA overrides,
set-content, and stealth experiments never enter the compact surface. The
preserved legacy server still exposes its historical local commands and must be
treated as trusted-local until the compatibility migration is complete. The
release target is that any retained sensitive operation requires an explicit
Developer/legacy mode and origin approval.

Upload is excluded from the compact MVP and default-disabled even in legacy
mode. A future upload feature requires a separate R3 design and approval; the
presence of the old parser command does not grant that authority.

## Compatibility Acceptance

These are future release gates rather than current-alpha assertions.

- Legacy read/navigation/click/type/screenshot smoke calls the same service path
  as compact MCP and returns equivalent structured results.
- An unavailable backend feature returns `unsupported_capability`, never an
  unchanged state presented as success.
- `tbp-mcp` without a mode exposes exactly 14 tools and no eval/upload/cookie
  mutation.
- `tbp-mcp --legacy` is never used in the default Hermes/Codex configuration.
- Stderr deprecation notices do not contaminate stdout protocol frames.
