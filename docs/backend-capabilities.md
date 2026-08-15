# Backend capabilities: current implementation

> [!IMPORTANT]
> **This is a static source audit, not on-device validation.** The entries below
> describe what the current Python code implements or exposes as of 2026-08-15.
> They do not prove that Firefox, Chromium, Xvfb, xdotool, ImageMagick, proxying,
> downloads, or public websites work on a particular Termux/Android device.
> Complete the device checklist before changing any entry to release-verified.

This document records the legacy surface that Termu-inator must preserve,
replace, or reject explicitly while introducing backend capability negotiation.
It intentionally distinguishes a real implementation from an emulation and from
a tool that returns success without performing the requested operation.

## Status legend

| Status | Meaning |
| --- | --- |
| **Supported** | The backend has a direct implementation with the expected basic semantics. Device validation is still required. |
| **Emulated** | The feature is translated through JavaScript, DevTools-console automation, X11, or another compatibility layer. |
| **Partial** | Only a documented subset of the advertised behavior is implemented. |
| **Unsupported** | The backend has no implementation for the capability. |
| **Broken** | The public surface is present, but source inspection proves that it fails, silently does nothing, or returns materially incorrect success data. |

## Current surface context

The current code has three entry points: [`cli.main`](../cli.py#L430),
[`src.daemon.main`](../src/daemon.py#L5302), and
[`src.mcp_server.main`](../src/mcp_server.py#L2002). The installed console
scripts are `tbp` and `tbp-mcp`.

Static AST inventory finds:

- 77 top-level CLI commands, 25 command-group containers, 86 nested parser
  entries, 138 executable leaf command paths, and 24 aliases;
- 148 functions decorated with `@mcp.tool()`;
- 140 daemon actions in [`_HANDLERS`](../src/daemon.py#L5124) and exactly 140
  corresponding `_handle_*` functions, with no missing or unregistered handler;
- all 140 daemon actions exposed through MCP, while the CLI reaches 129 of them.

The 148 MCP tools therefore describe a compatibility surface, not the planned
compact v1 surface. Sensitive and developer-oriented tools are not separated by
a mode or permission boundary today.

## Firefox and Chromium matrix

The table describes the behavior of the current public CLI/MCP/daemon paths.
“Emulated” and “Partial” are not interchangeable with parity.

| Capability | Firefox native backend | Chromium CDP backend | Evidence and current limitation |
| --- | --- | --- | --- |
| Process launch | **Supported**: Firefox under Xvfb | **Supported**: Chromium under Xvfb with a local CDP endpoint | [`BrowserPilot.start`](../src/browser.py#L107) branches before Chromium setup; Chromium launch and CDP polling are in [`_start_chromium`](../src/browser.py#L227) and [`_wait_for_cdp`](../src/browser.py#L330). |
| Session transport | **Emulated**: `NativeFirefoxSession` presents a CDP-shaped API | **Supported**: `CDPSession` forwards arbitrary commands to `CDPClient` | Backend selection is in [`Pilot._init_session`](../src/pilot.py#L134). Generic CDP send is implemented in [`CDPClient.send`](../src/cdp.py#L106). |
| CDP command coverage | **Partial**: 16 translated methods plus five enable/override no-ops; other methods raise `NotImplementedError` | **Supported** for commands accepted by the connected Chromium target | Firefox dispatch is in [`NativeFirefoxSession.send`](../src/native.py#L800), and its literal method map is [`_NATIVE_HANDLERS`](../src/native.py#L1387). |
| Navigation, URL, title, text, HTML, and JavaScript evaluation | **Emulated** through native navigation and DevTools-console/clipboard JavaScript execution | **Supported** through CDP `Page` and `Runtime` methods | Shared page commands call the CDP-shaped session interface; Firefox maps `Page.navigate` and `Runtime.evaluate` in [`native.py`](../src/native.py#L1387). |
| Selector-based click, type, key, scroll, hover, select, check, and drag | **Emulated** through JavaScript and translated X11/input operations | **Supported/Partial** through CDP input plus JavaScript helpers | Both use the shared input and daemon handlers. Neither backend currently provides the planned ref/revision precondition or automatic post-action verification. |
| Raw-coordinate click | **Partial**: requires a preceding `mouse_move`/`mouse_locate` at the same coordinates | **Broken**: the arming tools call Firefox-only private X11 methods | The guard and Firefox-only click branch are in [`_handle_click`](../src/daemon.py#L375); `mouse_move` calls `_xdt` in [`_handle_mouse_move`](../src/daemon.py#L606). |
| Accessibility observation | **Partial**: heuristic DOM walk, maximum depth 8 and roughly 200 nodes | **Supported** through the CDP accessibility tree | The Firefox approximation is [`_get_ax_tree`](../src/native.py#L1342); it is not semantically equivalent to Chromium's AX tree. |
| Viewport screenshot | **Supported/Emulated**: ImageMagick captures the Firefox X11 window | **Supported** through `Page.captureScreenshot` | Firefox implementation is [`_capture_screenshot`](../src/native.py#L922); it may include browser chrome, unlike a CDP content capture. |
| Full-page screenshot | **Broken**: accepts the request but ignores the calculated CDP clip and captures the same browser window | **Supported**: obtains layout metrics and supplies a clip | Clip construction is in [`ScreenshotCommands.capture`](../src/screenshot.py#L17), while the Firefox handler ignores `params` in [`_capture_screenshot`](../src/native.py#L922). |
| Element screenshot | **Emulated**: capture then crop with ImageMagick and a Firefox viewport offset | **Emulated**: capture then crop with ImageMagick | [`_handle_screenshot_element`](../src/daemon.py#L1511) conditionally applies the Firefox offset, so this requires the external `convert` binary on either backend. |
| PDF export | **Broken**: returns empty base64 data, causing a zero-byte PDF to be written and reported as successful | **Supported** through `Page.printToPDF` | The Firefox stub is [`_print_to_pdf`](../src/native.py#L1103); the shared writer trusts `result["data"]` in [`ScreenshotCommands.capture_pdf`](../src/screenshot.py#L58). |
| Cookie read/write | **Partial**: current-origin `document.cookie`; HttpOnly and unrelated-domain cookies are invisible | **Supported** through CDP Network cookie methods | Firefox reads cookies in [`_get_cookies`](../src/native.py#L1045) and writes them in [`_set_cookie`](../src/native.py#L1059). Identical public result shapes currently hide this semantic difference. |
| Native browser/CDP events | **Unsupported**: `on()` stores callbacks, but the native backend never emits them | **Supported**: the CDP listener dispatches events | Compare [`NativeFirefoxSession.on`](../src/native.py#L817) with [`CDPClient._listen`](../src/cdp.py#L59). `Pilot` only starts `NetworkTracker` for Chromium in [`Pilot._init_session`](../src/pilot.py#L171). |
| Public `browser_network_*` tools | **Partial**: page-side `PerformanceObserver` shim | **Partial**: the same shim, not the available CDP tracker | [`_handle_network_start`](../src/daemon.py#L1354) injects [`_inject_network_capture`](../src/daemon.py#L1402). It does not provide full headers, status, bodies, or all navigation/subresource events. |
| Console, response, DOM mutation, and page-event capture tools | **Partial**: page monkey-patches | **Partial**: the same page monkey-patches | For example, console capture replaces `console` methods in [`_inject_console_capture`](../src/daemon.py#L1302). Events before injection and browser-internal events are not captured. |
| Tab new/close/next/previous/goto | **Emulated** through xdotool keyboard shortcuts | **Broken**: handlers return success without changing tabs | The handlers only act inside `hasattr(session, "_xdt")` branches and have no Chromium alternative; see [`_handle_tab_new`](../src/daemon.py#L1031) and [`_handle_tab_close`](../src/daemon.py#L1050). On Chromium, `tab_new(url)` navigates the current tab instead of opening a new one. |
| Focus-by-tabbing and selector focus | **Emulated** | **Supported/Emulated** | `tab_to` and `focus` use the shared key/evaluate paths rather than the broken tab-management branch; see [`_handle_tab_to`](../src/daemon.py#L4784) and [`_handle_focus`](../src/daemon.py#L4858). |
| OS window list/switch/close | **Emulated** through Firefox PID discovery and xdotool | **Unsupported/Broken**: exposed handlers require Firefox-only process and session fields | [`_get_browser_wid`](../src/daemon.py#L3349), [`_handle_window_list`](../src/daemon.py#L3435), and [`_handle_window_close`](../src/daemon.py#L3484) are Firefox-specific. |
| Viewport set/get | **Emulated** through xdotool window geometry plus JavaScript inner dimensions | **Unsupported/Broken** despite CDP having relevant APIs | Both handlers call the Firefox PID/window helper; see [`_handle_viewport_set`](../src/daemon.py#L3515) and [`_handle_viewport_get`](../src/daemon.py#L3552). |
| Mouse move/locate and swipe | **Emulated** through xdotool | **Unsupported/Broken**: `_display`, `_xdt`, `_get_viewport_offset`, and related fields do not exist on `CDPSession` | Evidence: [`_handle_mouse_locate`](../src/daemon.py#L634) and [`_handle_swipe`](../src/daemon.py#L1664). |
| Iframe list/eval/text and same-origin click | **Partial** through JavaScript | **Partial** through JavaScript | Same-origin operations use `contentDocument`; cross-origin DOM access remains unavailable. |
| Cross-origin iframe coordinate click | **Emulated** with Firefox viewport/X11 helpers | **Broken**: fallback calls Firefox-only `_close_console` and `_xdt` | [`_handle_iframe_click`](../src/daemon.py#L1824). |
| Named multi-tab session save/load | **Partial**: keyboard scan of tabs 1 through 9 | **Broken**: direct `_xdt` calls fail | [`_handle_session_save`](../src/daemon.py#L2955) and [`_handle_session_load`](../src/daemon.py#L3004). File-only list/delete operations are backend-neutral. |
| Download destination and listing | **Partial**: Firefox profile preferences point downloads at `~/.tbp/downloads` | **Broken/Unwired**: Chromium launch does not configure the directory that `browser_downloads` scans | Firefox preferences are written in [`_cleanup_profile_locks`](../src/native.py#L123); Chromium arguments are built in [`_launch_chromium`](../src/browser.py#L303); listing only scans a fixed directory in [`_handle_downloads`](../src/daemon.py#L1329). |
| Download retrieval | **Unsupported** beyond local name, size, and mtime | **Unsupported** beyond local name, size, and mtime | There is no completion event contract, MIME/hash result, artifact URI, or remote byte-reading tool. |
| HTTP/SOCKS proxy | **Emulated** through Firefox `user.js` preferences | **Supported** through `--proxy-server` | Firefox proxy preferences are produced in [`_cleanup_profile_locks`](../src/native.py#L204); Chromium adds the launch flag in [`_launch_chromium`](../src/browser.py#L303). Device verification is required. |
| User-agent, geolocation, headers, throttling, and response mocking tools | **Partial** JavaScript/fetch/XHR shims | **Partial** JavaScript/fetch/XHR shims | `browser_useragent_set` is explicitly JS-side in [`_handle_useragent_set`](../src/daemon.py#L2005); headers and throttle only wrap fetch/XHR in [`_handle_headers_set`](../src/daemon.py#L2309) and [`_handle_throttle_set`](../src/daemon.py#L3851). They do not imply full network-stack overrides. |
| Cloudflare-specific navigation | **Partial/Experimental**: navigate and wait for automatic resolution | **Partial/Experimental**: custom Turnstile handler | The branch is in [`Pilot.goto_cf`](../src/pilot.py#L243). Public anti-bot behavior is non-deterministic and must not be presented as a supported release capability. |
| Browser selection through CLI | **Supported** at daemon startup | **Supported** at daemon startup | Once a daemon is running, later `--browser` values do not replace it automatically. |
| Browser selection through MCP | **Partial**: implicit auto-start defaults to Firefox | **Partial**: only usable if Chromium was started separately first | MCP `_send` does not accept a backend in [`mcp_server.py`](../src/mcp_server.py#L29), while [`send_command`](../src/client.py#L75) defaults to Firefox. |
| MCP restart | **Supported** when Firefox is intended | **Broken**: restarting a Chromium daemon silently starts Firefox | [`browser_restart`](../src/mcp_server.py#L1984) sends `shutdown`, then calls `status`; the latter auto-starts the default Firefox daemon. |
| Backend profile isolation | **Partial** | **Partial/Broken design** | [`Daemon.run`](../src/daemon.py#L67) passes `FIREFOX_PROFILE_DIR` as `user_data_dir` regardless of backend, so profiles are not separated by engine. |
| Capability negotiation and structured unsupported errors | **Unsupported** | **Unsupported** | [`_handle_status`](../src/daemon.py#L807) returns only process/browser/page metadata. [`Daemon._dispatch`](../src/daemon.py#L198) reduces failures to strings, and [`_result`](../src/mcp_server.py#L35) returns them as ordinary tool data. |

## Prioritized silent-success defects

These defects are more dangerous than a clear unsupported error because an
agent can continue from a false assumption about browser state or evidence.

### P0: fix or explicitly reject before backend parity claims

1. **Chromium tab commands report success without performing the operation.**
   `tab_close`, `tab_next`, `tab_prev`, and `tab_goto` have no Chromium branch.
   `tab_new(url)` changes the current page rather than opening a new tab.
   Evidence: [`daemon.py:L1031-L1118`](../src/daemon.py#L1031).
2. **Firefox PDF export reports a path after writing empty data.** The native
   `Page.printToPDF` translation returns `{"data": ""}` instead of raising an
   unsupported-capability error. Evidence:
   [`native.py:L1103-L1105`](../src/native.py#L1103).
3. **Firefox full-page screenshot reports success but is not full-page.** The
   shared layer calculates a full-page clip, but the native capture ignores all
   supplied parameters. Evidence: [`screenshot.py:L17-L56`](../src/screenshot.py#L17)
   and [`native.py:L922-L1015`](../src/native.py#L922).

### P1: correct semantics or return an explicit limitation

4. **MCP restart does not preserve Chromium.** Its follow-up status request
   auto-starts the default Firefox backend. Evidence:
   [`mcp_server.py:L1984-L1999`](../src/mcp_server.py#L1984).
5. **Firefox cookie and accessibility results look equivalent to Chromium but
   are materially narrower.** The public response contains no fidelity or
   capability marker.
6. **Firefox event registration accepts callbacks that can never fire.** Direct
   consumers can treat registration as success even though there is no native
   event source. Evidence: [`native.py:L817-L829`](../src/native.py#L817).
7. **Developer shims imply broader effects than they provide.** User-agent,
   headers, throttling, mocks, and network observation are page-side shims and
   do not cover the whole browser network stack.
8. **Chromium downloads can succeed outside the directory returned by
   `browser_downloads`.** The listing can therefore report no files without
   explaining the backend wiring gap.

### P1: currently exposed but hard-failing on Chromium

The following tools must either gain Chromium implementations or be omitted
from Chromium capabilities with a structured `unsupported_capability` result:

- `browser_mouse_move`, `browser_mouse_locate`, and `browser_swipe`;
- `browser_window_list`, `browser_window_switch`, and `browser_window_close`;
- `browser_viewport_set` and `browser_viewport_get`;
- `browser_session_save` and `browser_session_load`;
- the cross-origin fallback of `browser_iframe_click`.

## Missing negotiation and security primitives

The current source has no capability registry or handshake. A client can learn
the backend name from status, but cannot discover supported actions, semantic
fidelity, required binaries, limits, or known degraded behavior. The v1 status
contract should expose versioned capability records with at least:

- `backend`, backend version, browser version, and transport;
- per-capability `supported`, `emulated`, `partial`, `unsupported`, or `broken`;
- semantic limits such as AX depth, cookie visibility, screenshot scope, tab
  count, upload size, and event fidelity;
- required external binaries and runtime probes;
- a stable structured error code for unsupported and temporarily unavailable
  operations.

The following planned security primitives are also absent:

- origin-level `ask`, session allow, persistent allow, and block decisions;
- risk classes and one-time confirmation tokens for consequential actions;
- a distinction between core tools and Developer/legacy tools;
- default denial or explicit approval for raw JavaScript, cookie/storage
  mutation, clipboard access, upload, custom headers, mocks, and set-content;
- stable element refs, page revision checks, stale-ref rejection, and automatic
  post-action verification;
- artifact IDs and controlled remote reads instead of device-local paths;
- trace IDs, before/after state, approval decisions, and credential/header/cookie
  redaction;
- client/session ownership that prevents multiple agents from concurrently
  mutating the same browser state.

Until those controls exist, the 148-tool MCP server must be treated as a
trusted local compatibility interface, not a least-privilege agent interface.

## On-device validation checklist

Record the device model, Android version, Termux source/version, architecture,
Python version, Firefox/Chromium versions, Xvfb display, installed binaries,
free memory, and commit before running the checks. Use deterministic local
fixtures for release gates; public Cloudflare, OAuth, and fingerprint sites are
non-gating observations only.

### Install and lifecycle

- [ ] Reproduce installation in a clean Termux environment for Firefox.
- [ ] Reproduce installation in a separate clean environment for Chromium.
- [ ] Verify all required binaries and optional Python dependencies before
  starting a browser.
- [ ] Start, query status, stop, restart, and recover from stale PID/socket and
  profile-lock states for each backend.
- [ ] Verify that requesting Chromium through MCP either starts Chromium or
  returns an explicit backend-selection error; verify restart preserves it.
- [ ] Confirm Firefox and Chromium use separate profile directories and can be
  alternated without lock or state contamination.

### Deterministic observation and action fixture

- [ ] Navigate, reload, go back/forward, read URL/title/text, and evaluate a
  bounded expression on both backends.
- [ ] Compare accessibility observations against fixture expectations and
  record Firefox truncation or role differences explicitly.
- [ ] Exercise selector click, type, press, scroll, hover, select, check, drag,
  and focus; verify the DOM/URL/state after every action.
- [ ] Confirm raw-coordinate actions are rejected unless explicitly enabled and
  armed from a fresh screenshot/revision.
- [ ] Test same-origin and cross-origin iframe paths separately.

### Tabs, windows, and viewport

- [ ] Open at least three tabs, list them, switch in both directions, select by
  identity, and close a non-active and active tab on each backend.
- [ ] Assert that an unsupported tab operation returns a structured error and
  never a false success result.
- [ ] Validate OS-window operations separately from browser-tab operations.
- [ ] Set and read viewport dimensions, then compare reported inner/outer size
  with screenshot pixel dimensions.
- [ ] Save and restore a multi-tab session and verify URL order and active tab.

### Screenshots, PDF, and artifacts

- [ ] Capture viewport, full-page, and element screenshots and verify file
  signature, non-zero size, expected dimensions, crop bounds, and browser-chrome
  inclusion for each backend.
- [ ] Export PDF and require a non-zero file beginning with `%PDF-`; unsupported
  backends must return `unsupported_capability` without creating a file.
- [ ] Verify annotated screenshots do not expose stale coordinates.
- [ ] Retrieve screenshot and download bytes over the intended SSH/MCP path and
  validate MIME, size, and hash rather than relying on a device-local path.

### Cookies, storage, downloads, and proxy

- [ ] Test regular, Secure, SameSite, domain/path-scoped, and HttpOnly cookies;
  record which classes each backend can list, save, restore, and delete.
- [ ] Verify local/session storage behavior across navigation and restart.
- [ ] Download known fixture files, wait for completion, and verify directory,
  filename, MIME, size, and hash on both backends.
- [ ] Validate HTTP and SOCKS5 proxying with a controlled endpoint, including DNS
  behavior and restart persistence.

### Developer-mode fidelity

- [ ] Compare the page-side network log with controlled server logs and, for
  Chromium, with CDP Network events.
- [ ] Verify console, response, mutation, and DOM-event capture before and after
  navigation, iframe changes, and reinjection.
- [ ] Measure the actual scope of UA, geolocation, header, throttle, offline, and
  mock overrides; distinguish navigation, fetch/XHR, and subresource behavior.
- [ ] Verify every Developer operation is hidden or rejected until Developer
  Mode and origin approval are active.

### Safety, failure, and performance

- [ ] Verify origin policy and R3/R4 confirmation paths with allow, deny, expiry,
  navigation change, replay, and concurrent-client cases.
- [ ] Confirm traces and errors redact passwords, OTPs, cookies, authorization
  headers, clipboard contents, and uploaded file content.
- [ ] Kill the browser, Xvfb, or socket mid-command and require a bounded,
  structured recovery result without duplicate state-changing actions.
- [ ] Measure cold browser startup, warm status latency, text-only observation,
  screenshot time/size, RSS, and a 100-action or one-hour soak on both backends.
- [ ] Repeat deterministic core scenarios enough times to report success rate;
  do not promote a one-off public-site success to a capability claim.
