# Task Plan: Termu-inator — AI-First Browser Use for Termux/Android

<!--
  WHAT: Termux Browser Pilot 포크를 AI 에이전트용 브라우저 런타임으로 재설계하는 작업 계획.
  WHY: 범위, 설계, 완료 기준, 결정을 한곳에 두어 세션이 바뀌어도 목표가 표류하지 않게 한다.
  HOW: 이 파일에는 계획만 둔다. 현재 상태는 STATUS.md, 경과는 progress.md, 사실은 findings.md에 쓴다.
-->

- **Project codename:** Termu-inator
- **Upstream:** `salviz/termux-browser-pilot`
- **Planning baseline:** upstream `main` @ `b95eccd3d1abc188c3aa488a23c519ebacc99fcf`
- **Plan created:** 2026-08-15
- **Plan restructured:** 2026-11-10. 그 전의 전체 원문은
  [docs/history/task_plan-through-2026-11-06.md](docs/history/task_plan-through-2026-11-06.md)에 있다.
- **Plan status values:** `pending` → `in_progress` → `complete` / `blocked`
- **Companion files:** [STATUS.md](STATUS.md), [progress.md](progress.md), [findings.md](findings.md),
  [검증 차선과 alpha 게이트](docs/verification-lanes.ko.md)

## Goal

Termux/Android에서 실제 Firefox·Chromium을 제어하되, 기존의 방대한 명령 집합을 핵심 기능으로 축소하고 **공유 가능한 브라우저 관찰, 안정적인 observe–act–verify 루프, 원격 아티팩트 전달, 사이트·행동별 승인, 선택적 CDP 개발자 모드**를 갖춘 Codex Browser Use형 AI 브라우저 런타임 **Termu-inator**를 구축한다.

## Next Step

**다음 한 가지 작업은 [STATUS.md](STATUS.md)에만 적는다.** 이 절에 회차별 기록을 쌓지 않는다.

2026-11-10 기준 다음 작업은 S22U에서의 Chromium 단독 진단(L1)이다.
절차는 [Chromium 단독 진단](docs/s22u-l1-chromium-probe.ko.md)에 있다.

## Current Phase

2026-11-10 — **검증 루프 재정렬 완료. L1 Chromium 진단 대기.**

alpha까지 남은 경로다. 세부 상태는 [STATUS.md](STATUS.md)가 기준이다.

- [x] 방향 점검과 문서 체계 재구성 ([방향 점검](docs/direction-review-2026-11-10.ko.md))
- [ ] L1: Chromium 155 단독 진단과 원인 수정
- [ ] L1: 현재 HEAD의 canonical이 양 backend PASS
- [ ] L2: 봉인 인수 1회 (canonical → benchmark)
- [ ] alpha 릴리스 정리 (문서 최종 검토, 알려진 제한 명시, 버전·changelog, release artifact)

## Milestones

2026-11-10에 alpha 범위를 핵심 루프로 줄였다. Phase 체크리스트의 미완 항목에는
**[alpha]** 또는 **[alpha.2]** 표시가 붙어 있다.

| Milestone | 범위 | 판정 |
|---|---|---|
| alpha (`v0.1.0-alpha`) | 읽기(Flow A), 안전한 조작(Flow B), 민감 입력 감지·일시 중지·owner 재개(Flow C), 승인이 필요한 행동(Flow D). 양 backend, compact MCP 14/12 도구, 기기 로컬 stdio, screenshot artifact 회수 | [alpha 게이트 v1](docs/verification-lanes.ko.md) |
| alpha.2 | 탭·popup·dialog·다운로드의 실제 backend 연결(Flow F), SSH 원격 round-trip, soak·crash 복구, Developer Mode 추가 승인 규칙(Flow E 보강), CLI 재구성, Phase 3 구조 정리 | 게이트 v2로 별도 정의 |

alpha는 **합성 fixture와 명시적으로 통제한 환경**에서의 사용으로 제한한다. redirect 사전 검사와
DNS/peer enforcement가 없기 때문이다. 이 제한은 README와 release notes에 적는다.

## Operating Rules

1. 작업을 시작할 때 [STATUS.md](STATUS.md)를 먼저 읽는다. 이 파일은 필요한 절만 읽는다.
2. 상태가 바뀌면 `STATUS.md`를 먼저 고친다. `Current Phase`는 단계가 바뀔 때만 고친다.
3. 코드·설정·문서·테스트를 바꾸면 `progress.md`에 10줄 이내의 항목을 남긴다.
4. 지금도 유효한 사실만 `findings.md`에 적는다. 회차별 경과는 `progress.md`에 둔다.
5. 같은 실패 접근을 그대로 반복하지 않는다. 같은 상태에서 같은 실행을 세 번째 하게 되면 멈추고 가설을 바꾼다.
6. 기기 실패의 원인은 L1에서 찾는다. L2에는 L1에서 통과한 commit만 올린다
   ([검증 차선](docs/verification-lanes.ko.md)).
7. alpha 게이트 v1에 항목을 추가하지 않는다. 새 검사 아이디어는 `Alpha.2 Backlog`에 적는다.
8. 각 Phase의 **Exit Gate**가 충족되기 전에는 `complete`로 표시하지 않는다.
9. 계획 변경이 범위·보안·API 호환성에 영향을 주면 `Decisions Made`에 근거를 남긴다.
10. 외부 사이트 기반 테스트는 보조 증거로만 사용하고, 릴리스 게이트는 결정론적 fixture로 판단한다.
11. 사용자가 승인하지 않은 비가역 작업, 자격 증명 입력, 결제, 삭제, 권한 변경은 자동화하지 않는다.
12. commit과 push는 사용자가 한다. 이 파일들에 Historical·Superseded 층을 쌓지 않는다.

---

## Product Definition

### Product Positioning

Termu-inator는 다음 중 **두 번째 영역**을 담당한다.

| 영역 | 담당 도구 | Termu-inator의 역할 |
|---|---|---|
| 공개 정보 검색·정적 수집 | 웹 검색, HTTP 클라이언트, Crawl4AI | 기본 경로가 아님 |
| 로그인·동적 렌더링·상호작용·웹 QA | **Termu-inator** | 핵심 영역 |
| 수백~수천 페이지 병렬 크롤링 | Scrapy, Crawl4AI, Playwright 클러스터 | 범위 밖 |
| Android 네이티브 앱 자동화 | ADB/UIAutomator 계열 | 범위 밖 |

### Codex Browser Use에서 차용할 핵심 경험

- 사용자와 에이전트가 동일한 페이지 상태를 확인할 수 있는 **공유 관찰 화면**
- 페이지 열기, 클릭, 입력, 스크롤, 렌더링 상태 검사, 스크린샷, 결과 재검증의 일관된 루프
- 일반 브라우저와 분리된 전용 프로필 및 명확한 세션 수명주기
- 여러 탭과 다운로드 지원
- 새 사이트 접근에 대한 호스트 단위 권한
- 제출·구매·삭제·권한 변경 등 결과가 큰 행동 전 명시적 승인
- 페이지 내용은 항상 신뢰할 수 없는 입력으로 취급
- DOM·스타일·콘솔·네트워크·성능을 조사하는 **별도 Developer Mode**
- 전체 작업을 한 번에 맡기지 않고 페이지·상태·목표를 좁혀 검토 가능한 단위로 실행

### Core Principles

1. **Observe first:** 행동 전에 현재 URL, 페이지 revision, 요소 ref, 스크린샷 또는 구조화 관찰을 확보한다.
2. **Stable references:** 에이전트가 임의 CSS selector를 추측하지 않고, 관찰 결과에서 발급된 요소 ref를 사용한다.
3. **Verify after act:** 모든 행동은 실행 성공이 아니라 페이지 변화·요소 상태·URL·다운로드 등 기대 효과로 검증한다.
4. **Least privilege:** 기본 모드는 읽기 중심이며, 사이트 접근·민감 행동·전체 CDP는 각각 별도 권한이다.
5. **Remote first:** WSL2·Hermes·Codex가 SSH stdio 또는 후속 원격 transport로 휴대폰의 브라우저를 관찰할 수 있어야 한다.
6. **Capabilities, not assumptions:** Firefox와 Chromium의 기능 차이를 숨기지 않고 capability negotiation으로 공개한다.
7. **Deterministic core:** 안티봇·CAPTCHA 우회 성공 여부를 제품의 품질 기준으로 삼지 않는다.
8. **Small tool surface:** MCP 기본 도구는 최대 16개를 목표로 하며, 고급 기능은 Developer Mode 또는 legacy namespace로 분리한다.
9. **Traceable actions:** 모든 도구 호출에는 step ID, 전후 상태, 승인 상태, 결과가 기록된다.
10. **Backward-compatible migration:** 초기 릴리스에서는 기존 `tbp` 사용자를 위한 호환 계층을 유지하되 새 코드 경로와 중복 구현하지 않는다.

---

## Scope

### Keep in Core

- 영속 데몬과 빠른 명령 재사용
- Firefox native backend와 Chromium CDP backend
- 세션·탭·페이지 탐색
- 텍스트·접근성·interactive element 관찰
- 클릭·입력·키·스크롤·select·check
- 스크린샷과 주석 가능한 시각 관찰
- 별도 브라우저 프로필과 쿠키·스토리지 지속성
- 다운로드 목록과 원격 전달
- proxy 설정
- challenge·OTP·dialog 감지와 사용자 handoff
- 구조화된 JSON 결과와 MCP transport

### Consolidate Behind Unified APIs

- `find`, `elements`, `a11y`, `bounding-box`, `element-state` → `browser_observe`
- `click`, `dblclick`, `hover`, `type`, `press`, `scroll`, `select`, `check`, `drag` → typed `browser_act`
- `console`, `network`, `responses`, `perf`, `DOM/style` → `browser_devtools`
- screenshot·annotate·element screenshot → artifact-backed `browser_screenshot`
- cookie/profile/session 관리 → 기본 toolset 밖의 `browser_profile` 또는 CLI 관리면
- macro → trace 기반 workflow/record-replay 후보로 재설계

### Move to Developer/Experimental Namespace

- 임의 JavaScript 평가
- request/response mocking
- custom header 주입
- CSS 주입
- geolocation·UA override
- throttle/offline simulation
- raw storage/cookie mutation
- set-content
- 전체 CDP command passthrough
- fingerprint·stealth 실험 기능

### Remove or Disable by Default

- “Cloudflare bypass 보장”, “undetectable” 같은 제품 약속
- 자동 CAPTCHA 해결
- 검증 없는 원시 좌표 클릭
- 에이전트가 자격 증명을 채팅으로 받는 흐름
- 사용자 승인 없는 제출·결제·삭제·권한 변경
- 무제한 HTML·응답 body·스크린샷을 JSON에 직접 포함하는 방식
- 여러 에이전트가 같은 브라우저 세션을 동시에 조작하는 동작

### Deferred Beyond MVP

- 다중 독립 브라우저 세션 동시 실행
- Android 시스템 Chrome 프로필 직접 연결
- 브라우저 확장 프로그램·비밀번호 관리자 연동
- 완전한 Record & Replay 편집기
- 클라우드 호스팅 브라우저 팜
- 모바일 앱 UI 자동화
- 대규모 병렬 크롤링

---

## Target User Flows

### Flow A — Read and Inspect

`session_start → navigate → observe → screenshot(optional) → report`

- 새 사이트일 경우 호스트 권한 확인
- 읽기 작업은 사용자가 허용한 범위에서 자동 수행
- 결과에 URL, title, page revision, 근거 요소 ref 포함

### Flow B — Safe Interaction

`observe → act(ref) → automatic verification → observe(after)`

- action은 관찰 시 발급된 ref와 page revision을 요구
- stale ref면 실행하지 않고 재관찰 요청
- 결과가 기대와 다르면 자동 재시도보다 진단 정보를 반환

### Flow C — Sign-in Handoff

`navigate → detect sign-in → pause → user takes over → resume → verify signed-in state`

- 자격 증명은 브라우저에서만 입력
- password·OTP를 trace나 로그에 저장하지 않음
- CAPTCHA는 감지와 사용자 handoff까지만 담당

### Flow D — Consequential Action

`prepare action → preview payload/target → confirmation_required → user approval token → execute once → verify`

- 제출·구매·메시지 전송·삭제·권한 변경은 항상 별도 승인
- 승인 token은 action hash, origin, expiry와 결합
- 페이지가 바뀌면 승인 token 무효화

### Flow E — Web Development / QA

`navigate(local route) → observe + screenshot → devtools query → code change(outside browser) → reload → verify → trace export`

- 콘솔·네트워크·DOM·스타일·성능 접근은 Developer Mode에서만 허용
- 전체 CDP는 사이트별 명시 승인을 요구

### Flow F — Download and Analyze

`navigate → act(download) → download event → artifact URI → remote client retrieves file`

- 다운로드 완료·파일명·MIME·크기·hash를 반환
- WSL2/Hermes에서도 파일 bytes를 안전하게 회수 가능해야 함

---

## Target Architecture

```text
Hermes / Codex / CLI / future UI
              │
              │ MCP stdio over local or SSH
              ▼
       Transport & Tool Layer
  ┌──────────────┬───────────────┐
  │ compact MCP  │ compatibility │
  │ v1 tools     │ tbp adapter   │
  └──────────────┴───────────────┘
              │
              ▼
       Browser Orchestrator
  ┌────────────────────────────────────┐
  │ session manager                    │
  │ observation + element ref registry │
  │ action executor + verifier         │
  │ permission / confirmation engine   │
  │ artifact store + trace recorder    │
  │ capability negotiation             │
  └────────────────────────────────────┘
              │
       Backend Interface
        ┌─────┴─────┐
        ▼           ▼
 Firefox Native   Chromium CDP
 xdotool/console  WebSocket CDP
```

### Proposed Package Layout

```text
termu-inator/
├── pyproject.toml
├── task_plan.md
├── findings.md
├── progress.md
├── src/termuinator/
│   ├── app/
│   │   ├── config.py
│   │   ├── models.py
│   │   ├── errors.py
│   │   └── capabilities.py
│   ├── core/
│   │   ├── service.py
│   │   ├── sessions.py
│   │   ├── observation.py
│   │   ├── element_refs.py
│   │   ├── actions.py
│   │   ├── verification.py
│   │   ├── permissions.py
│   │   ├── artifacts.py
│   │   └── trace.py
│   ├── backends/
│   │   ├── base.py
│   │   ├── firefox_native.py
│   │   └── chromium_cdp.py
│   ├── devtools/
│   │   ├── console.py
│   │   ├── network.py
│   │   ├── dom.py
│   │   ├── styles.py
│   │   └── performance.py
│   ├── transports/
│   │   ├── daemon.py
│   │   ├── client.py
│   │   ├── mcp_server.py
│   │   └── artifact_resources.py
│   ├── compatibility/
│   │   ├── tbp_cli.py
│   │   └── legacy_actions.py
│   └── cli.py
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── fixtures/sites/
│   ├── e2e/
│   └── device/
├── docs/
│   ├── architecture.md
│   ├── tool-contracts.md
│   ├── security-model.md
│   ├── backend-capabilities.md
│   ├── migration-from-tbp.md
│   └── troubleshooting.md
└── examples/
    ├── hermes-mcp.yaml
    ├── codex-mcp.toml
    └── ssh-stdio-wrapper.sh
```

### Core Data Contracts

#### Observation

```text
Observation
- session_id
- page_id / tab_id
- sequence
- page_revision
- url / origin / title
- ready_state
- viewport
- timestamp
- interactive_elements[]
  - ref
  - role / accessible_name / text
  - tag / type
  - bounds
  - visible / enabled / editable / checked
  - frame_path / shadow_path
- dialogs / challenges / downloads_delta
- screenshot_artifact_uri (optional)
- bounded text / text_truncated / accessibility
- capability_revision
```

#### Action

```text
ActionRequest
- action_id / idempotency_key
- session_id / tab_id / page_id
- expected_page_revision
- kind
- target_ref (when applicable)
- closed typed parameters
- timeout_ms
- confirmation_id (nullable, non-secret server approval handle)

ActionResult
- status: succeeded | failed
- before_revision / after_revision
- executed_method
- causal typed verification records
- changed_url / changed_elements / download
- artifact_uri (optional)
- diagnostics_id (optional)

Domain outcomes such as permission/confirmation/stale/outcome-unknown are Tool
Execution Errors with a stable `ErrorEnvelope`; they are not overlapping
`ActionResult` statuses.
```

### Provisional MCP v1 Surface

목표는 **기본 14개 이하**, 절대 상한은 16개다.

| Tool | Purpose | Default Risk |
|---|---|---:|
| `browser_session_start` | project·backend·viewport를 지정해 세션 시작 | R1 |
| `browser_session_status` | 브라우저·세션·capability 상태 조회 | R0 |
| `browser_session_stop` | 세션 정상 종료 | R1 |
| `browser_navigate` | URL 이동, 뒤로·앞으로·reload 포함 | R1 |
| `browser_observe` | 텍스트·a11y·interactive refs·상태·선택적 screenshot | R0 |
| `browser_act` | click/type/key/scroll/select/check/hover/drag의 typed union | R1–R4 |
| `browser_wait` | URL/text/ref-state/navigation/download 조건 대기 | R0 |
| `browser_tabs` | list/open/switch/close | R1 |
| `browser_screenshot` | viewport/full/element 캡처 후 artifact URI 반환 | R0 |
| `browser_downloads` | 다운로드 목록·상태·artifact URI | R0/R2 |
| `browser_artifact_read` | 원격 환경에서 screenshot/download bytes 회수 | R2 |
| `browser_permissions` | 사이트 결정 목록·pending confirmation 상태 조회 | R0 |
| `browser_devtools` | console/network/DOM/style/perf의 승인된 read-only 질의 | Developer |
| `browser_trace` | bounded redacted action trace 목록·조회·내보내기 | R0 |

> `browser_eval`, raw CDP, cookie/storage mutation, upload는 기본 v1 surface에서 제외하고 Developer/legacy namespace로 분리한다.

### Risk Classes

| Class | Meaning | Examples | Confirmation |
|---|---|---|---|
| R0 | 읽기 전용 | observe, screenshot, status, trace | 사이트 권한만 |
| R1 | 낮은 영향 | navigate, scroll, tab switch, focus | 일반적으로 없음 |
| R2 | 상태 변경 | type, select, check, download 시작 | 정책에 따라 |
| R3 | 민감 정보·파일 | credential field, clipboard, upload, history, cookies | 명시적 승인 |
| R4 | 결과가 큰 행동 | submit, send, purchase, delete, permission change | 매번 명시적 승인 |
| Developer | 브라우저 내부 접근 | full CDP, raw DOM/style/network body, eval | 기능 활성화 + 사이트별 승인 |

---

## Definition of Done

2026-11-10에 alpha와 alpha.2로 나눴다. alpha의 판정 절차는
[alpha 게이트 v1](docs/verification-lanes.ko.md)이다.

### Alpha (`v0.1.0-alpha`)

**Functional**

- [x] Firefox와 Chromium이 동일한 v1 observation/action 계약을 구현한다.
- [x] backend별 미지원 기능은 명시적 capability와 구조화 오류로 반환된다.
- [x] observe 결과의 ref로 click/type/select/check가 가능하다.
- [x] stale ref 또는 page revision mismatch가 실제 행동 전에 차단된다.
- [x] 모든 행동 후 자동 verification 결과가 반환된다.
- [x] 기본 MCP 도구 수가 16개 이하이다.
- [x] screenshot을 artifact URI와 chunked read로 회수할 수 있다. (기기 로컬 stdio, v0.2.20 canonical)
- [ ] 민감 입력(login·OTP) 감지 시 원격 제어가 일시 중지되고 owner만 재개할 수 있다.
  로컬 검증은 끝났다. r3에서 찾은 탐색 직후 감지 누락은 로컬 수정했고 기기 확인을 기다린다.

**Safety**

- [x] 새 origin 접근 정책이 `ask/session allow/always allow/block`을 지원한다.
- [x] R4 행동은 유효한 server-held one-shot approval 없이는 실행되지 않는다.
- [x] full CDP는 기본 비활성화이며 별도 승인 없이는 접근할 수 없다.
- [x] 페이지 텍스트가 권한 정책·도구 노출·승인 상태를 변경할 수 없다.
- [x] credential·OTP·cookie value·authorization header가 일반 trace에 기록되지 않는다.
- [x] artifact와 profile 파일에 제한 권한과 path traversal 방어가 적용된다.

**Reliability**

- [ ] S22U에서 alpha 게이트 v1을 통과한다. (L0 + L2 canonical 양 backend + L2 benchmark)
- [ ] status는 warm daemon에서 300 ms 이내, text-only observe는 2초 이내다.
  v0.2.20 benchmark에서는 충족했다(status 1.4–1.6 ms, text 4.5–7.0 ms). 그 뒤 `observe`에
  metadata 호출 두 번이 추가됐으므로 L2 benchmark에서 다시 측정한다.

**Compatibility & Delivery**

- [x] Hermes SSH stdio 예제와 Codex MCP 예제가 검증된다.
- [x] architecture, tool contracts, security model, migration 문서가 완성된다.
- [x] 설치·업데이트·삭제·데이터 초기화 절차가 문서화된다.
- [x] MIT 원저작자 고지와 포크 변경 내역이 보존된다.
- [ ] alpha의 알려진 제한(alpha.2로 미룬 기능, redirect·DNS 사전 검사 부재, 통제된 환경 한정)이
  README와 release notes에 명시된다.

### Alpha.2

- [ ] 탭 전환, popup·dialog 감지, 다운로드 회수가 실제 backend에서 동작한다.
- [ ] SSH 원격 host(WSL2/Hermes)에서 screenshot과 다운로드를 회수할 수 있다.
- [ ] 결정론적 로컬 fixture E2E 시나리오 25개 이상을 구축한다.
- [ ] 핵심 fixture 시나리오 반복 성공률 95% 이상을 달성한다.
- [ ] 1시간 또는 100개 연속 action soak test에서 daemon이 비정상 종료하지 않는다.
- [ ] 브라우저 crash·stale socket·profile lock에서 명확한 복구 경로를 제공한다.
- [ ] 기존 `tbp` 주요 읽기·탐색·클릭 명령에 compatibility adapter가 존재한다.

---

## Phases

### Phase 1: Fork Baseline & Discovery

**Objective:** 포크의 기준점을 고정하고, 현재 기능·결함·성능을 재현 가능한 상태로 기록한다.

- [x] `salviz/termux-browser-pilot`을 포크하고 저장소 이름을 `Termu-inator`로 설정
- [x] upstream remote와 baseline commit/tag 고정
- [x] MIT LICENSE, 원저작자 고지, fork notice 확인
- [x] `findings.md`와 `progress.md` 생성
- [x] 현재 CLI command, MCP tool, daemon handler를 자동 집계하는 inventory script 작성
- [x] 모든 기능을 `core / developer / legacy / remove` 후보로 분류
- [x] Firefox·Chromium capability matrix 초안 작성
- [ ] 현행 설치 절차를 깨끗한 Termux 환경에서 재현 **[alpha.2]**
- [x] example.com 기반 baseline smoke test 실행
- [x] 현재 daemon warm latency, browser startup, RSS, screenshot 크기 측정
- [x] 확인된 결함과 문서 불일치를 `findings.md`에 기록
- **Status:** in_progress — alpha 범위의 미완 항목 없음. 남은 항목은 alpha.2

**Deliverables**

- `findings.md`, `progress.md`
- `scripts/inventory_current_surface.py`
- `docs/upstream-baseline.md`
- `docs/device-baseline-s22u-2026-08-16.md`
- 초기 capability·performance baseline

**Exit Gate**

- baseline 설치·실행 절차가 재현되고, 현재 tool/handler 인벤토리와 backend capability 차이가 문서화되어야 한다.

---

### Phase 2: Product Contract & Tool Surface Reduction

**Objective:** 구현 전에 제품 경계, API 계약, 보안 모델과 축소된 도구 표면을 확정한다.

- [x] 핵심 사용자 흐름 6개를 acceptance scenario로 변환
- [x] v1 MCP 도구별 JSON schema와 error code 정의
- [x] `Observation`, `ActionRequest`, `ActionResult`, `Artifact`, `PermissionDecision` 모델 정의
- [x] element ref 발급·수명·stale 판정 규칙 정의
- [x] page revision 계산 전략 정의
- [x] action별 기본 verification 전략 정의
- [x] risk class와 server-held confirmation protocol 정의
- [x] origin permission store 형식과 기본값 정의
- [x] 별도 profile, history, cookie, artifact retention 정책 정의
- [x] Firefox/Chromium capability negotiation 계약 확정
- [x] legacy command mapping과 deprecation 범위 정의
- [x] anti-bot·challenge 기능의 제품 문구와 비목표 확정
- [x] architecture RFC와 security RFC 리뷰
- **Status:** complete

**Deliverables**

- `docs/architecture.md`
- `docs/tool-contracts.md`
- `docs/security-model.md`
- `docs/backend-capabilities.md`
- schema test fixtures

**Exit Gate**

- 신규 tool surface가 16개 이하이고, 각 도구의 권한·입력·출력·검증·backend 지원 여부가 문서와 schema test로 고정되어야 한다.

---

### Phase 3: Typed Core Refactor & Compatibility Layer

**Objective:** 거대한 `daemon.py`, `mcp_server.py`, `cli.py`를 새 서비스 계층으로 분리하면서 기존 동작을 단계적으로 보존한다.

- [ ] Python package namespace를 `termuinator`로 이전 **[alpha.2]**
- [x] 공통 typed models, structured errors, config loader 구현
- [x] `BrowserBackend` protocol/ABC 정의
- [x] Firefox native와 Chromium CDP를 backend adapter로 래핑
- [x] session manager와 single-session lock 구현
- [ ] daemon transport와 business logic 분리 **[alpha.2]**
- [ ] handler registry를 기능별 모듈로 분할 **[alpha.2]**
- [x] artifact store와 trace recorder 기본 골격 구현
- [x] permission engine interface 구현
- [ ] legacy `tbp` command를 새 service 호출로 연결 **[alpha.2]**
- [ ] 기존 로직과 신규 로직의 중복 구현 제거 **[alpha.2]**
- [x] fake backend와 unit test harness 구축
- [x] pyproject version, optional dependencies, Pillow/MCP dependency 정리
- [x] openbox 중복 실행, Chromium binary detection 등 baseline 결함 수정
- **Status:** in_progress — alpha 범위의 미완 항목 없음. 남은 항목은 alpha.2

**Deliverables**

- `src/termuinator/` 신규 구조
- fake backend
- compatibility adapter
- core unit tests

**Exit Gate**

- 기존 smoke test가 compatibility adapter를 통해 통과하고, 신규 core 모듈이 daemon/CLI/MCP에 독립적으로 unit test 가능해야 한다.

---

### Phase 4: Observe–Act–Verify Engine

**Objective:** Codex Browser Use형 핵심 루프를 구현하고 selector 추측·무검증 행동 의존을 제거한다.

- [ ] DOM·accessibility·rendered state를 통합하는 `browser_observe` 구현 **[alpha.2 — 남은 하위 항목만]**
  - [x] Firefox/Chromium legacy adapter의 bounded same-origin DOM·open-shadow inventory
  - [x] legacy observed-ref click/type/select/check/hover/drag, page key/scroll와 typed before/after evidence
  - [ ] cross-origin frame의 native adapter 지원 **[alpha.2]**
- [x] interactive element 정규화와 stable ref registry 구현
- [x] iframe·shadow DOM 경로를 ref metadata에 포함
- [x] screenshot artifact와 observation sequence 연결
- [x] typed `browser_act` executor 구현
- [x] click/type/key/scroll/select/check/hover/drag의 공통 결과 계약 구현
- [x] stale ref와 revision mismatch 차단
- [x] 행동별 verification 구현
  - [x] URL/navigation 변화
  - [x] input value 변화
  - [x] checked/selected 상태
  - [x] dialog 발생
  - [x] download 시작/완료
  - [x] target visibility/DOM 변화
- [x] `browser_wait` 조건 모델 구현
- [ ] 탭·팝업·dialog 수명주기 통합 **[alpha.2 — 남은 하위 항목만]**
  - [x] typed tab list/open/switch/close와 active page identity 전이
  - [x] typed popup inventory·dialog lifecycle과 deterministic fake 연결
  - [ ] Firefox/Chromium legacy adapter의 popup·dialog event 연결 **[alpha.2]**
- [x] challenge/OTP 감지를 action 차단·handoff 신호로 연결
  - [x] credential/OTP element 감지와 confidential takeover 신호
  - [x] Firefox/Chromium adapter의 sensitive-field semantics 추출
- [ ] raw coordinate action은 arm + visual verification 조건으로 격리 **[alpha.2]**
- [ ] 각 action의 before/after trace와 진단 artifact 저장 **[alpha.2 — 남은 하위 항목만]**
  - [x] secret-free action metadata를 durable trace로 저장·조회·export
  - [ ] before/after 진단 artifact 연결 **[alpha.2]**
- [x] local fixture 사이트 구축
  - [x] forms
  - [x] SPA navigation
  - [x] dynamic list
  - [x] shadow DOM
  - [x] same/cross-origin iframe
  - [x] dialogs
  - [x] download
  - [x] stale element replacement
  - [x] inert prompt-injection policy boundary
- **Status:** in_progress — alpha 범위의 미완 항목 없음. 남은 항목은 alpha.2

**Deliverables**

- observation/action/verification engine
- deterministic fixture suite
- trace schema

**Exit Gate**

- 에이전트가 CSS selector를 직접 생성하지 않고도 핵심 fixture 작업을 ref 기반으로 완료하며, 모든 action이 검증 결과 또는 명시적 실패 진단을 반환해야 한다.

---

### Phase 5: Permissions, Remote Artifacts & Shared View

**Objective:** 원격 Hermes/Codex 환경에서도 사용자가 페이지를 확인하고 위험 행동을 통제할 수 있게 한다.

- [x] origin allow/block/ask policy 구현
- [x] session-only와 persistent permission store 구현
- [x] action risk classifier 구현
- [x] confirmation preview와 server-held one-shot approval 구현
- [x] 페이지 revision/origin/action hash 변경 시 token 무효화
- [x] credential field·OTP value를 typed observation·challenge·trace에서 redaction
- [x] 사용자 takeover/resume protocol 구현
- [x] 페이지 지시를 untrusted data로 취급하는 policy boundary 구현
- [x] artifact content-addressed storage 구현
- [x] screenshot을 PNG/WebP로 저장하고 크기·hash·MIME metadata 반환
- [x] MCP resource 또는 chunked `browser_artifact_read` 구현
- [ ] 다운로드 완료 감지와 원격 파일 회수 구현 **[alpha.2 — 남은 하위 항목만]**
  - [x] typed lifecycle, stable public ID, MIME/size/hash와 artifact publication
  - [x] compact MCP list/wait와 chunked artifact 회수
  - [ ] Firefox/Chromium adapter의 실제 download event/bytes 연결 **[alpha.2]**
  - [ ] SSH/Hermes 원격 round-trip **[alpha.2]**
- [ ] SSH stdio 환경에서 screenshot/download round-trip 검증 **[alpha.2]**
- [x] 최소 shared-view dashboard 구현
  - [x] 현재 cached screenshot
  - [x] redacted URL/title/tab
  - [x] value-free pending permission/confirmation summary
  - [x] recent action trace
  - [x] takeover/resume state indicator (mutation controls remain CLI/host-only)
- [x] artifact expiry·quota·cleanup 구현
- [x] audit log와 secret redaction test 추가
- **Status:** in_progress — alpha 범위의 미완 항목 없음. 남은 항목은 alpha.2

**Deliverables**

- permission/confirmation engine
- artifact transport
- shared-view MVP
- SSH remote integration tests

**Exit Gate**

- WSL2/Hermes가 휴대폰 screenshot·download를 회수할 수 있고, R4 action과 full CDP가 사용자 승인 없이 실행되지 않아야 한다.

---

### Phase 6: Developer Mode, MCP & CLI Productization

**Objective:** 일반 Browser Use와 민감한 browser internals 접근을 분리하고, Hermes/Codex가 작은 tool surface로 안정적으로 사용하게 한다.

- [x] Developer Mode feature flag와 사이트별 승인 구현
- [x] read-only console query 구현
  - [x] typed service/fake/MCP query와 credential redaction
  - [x] Firefox/Chromium adapter 연결 (first-query 이후 page-scoped capture)
- [x] network request/response metadata query 구현
  - [x] typed service/fake/MCP metadata와 URL redaction
  - [x] Firefox/Chromium adapter 연결 (Performance Resource Timing metadata only)
- [x] DOM·computed style·layout query 구현
  - [x] observed-ref-bound DOM/style typed service/fake/MCP query
  - [x] Firefox/Chromium adapter 연결
- [x] performance/navigation/resource timing query 구현
  - [x] bounded typed service/fake/MCP query
  - [x] Firefox/Chromium adapter 연결
- [ ] optional performance trace export 구현 **[alpha.2]**
- [ ] response body·cookie·header·raw eval의 추가 승인 규칙 구현 **[alpha.2]**
- [ ] raw CDP passthrough는 실험 플래그 뒤에 격리 **[alpha.2]**
- [x] 최종 MCP v1 도구를 16개 이하로 고정
- [x] tool descriptions를 observe-first·ref-first 흐름에 맞게 작성
- [x] Hermes용 기본 read-only tool allowlist 제공
- [x] Hermes용 interactive tool profile 제공
- [x] Codex MCP 예제 설정 제공
- [ ] SSH wrapper가 stdout에 MCP 외 텍스트를 출력하지 않도록 검증 **[alpha.2 — 남은 하위 항목만]**
  - [x] installed-wheel local observer/interactive idle stdio purity
  - [ ] 실제 Tailscale `ssh -T` remote stdout purity **[alpha.2]**
- [ ] CLI를 session/observe/act/devtools/artifacts 중심으로 재구성 **[alpha.2]**
- [ ] 기존 `tbp` alias와 migration warnings 제공 **[alpha.2]**
- [x] 설치·업데이트·데이터 초기화·문제 해결 문서 작성
  - [x] fail-closed 설치와 compact/legacy/Developer 선택 문서
  - [x] 업데이트·삭제·데이터 초기화·최종 troubleshooting
- **Status:** in_progress — alpha 범위의 미완 항목 없음. 남은 항목은 alpha.2

**Deliverables**

- compact MCP server
- new CLI
- Developer Mode
- Hermes/Codex examples
- migration guide

**Exit Gate**

- Hermes와 Codex에서 동일한 v1 contract test가 통과하고, 기본 tool profile에는 raw eval·cookie mutation·full CDP가 노출되지 않아야 한다.

---

### Phase 7: Verification, Hardening & Alpha Release

**Objective:** 실제 Termux 장치에서 신뢰성·보안·호환성을 검증하고 문서화된 alpha를 배포한다.

- [x] unit·contract·fixture E2E 전체 실행
  - [x] local unit·contract·HTTP fixture authority suite (304 tests)
  - [x] 실제 Firefox·Chromium fixture browser E2E
    - [x] `b5362f9` 양쪽 backend의 session start, navigation, screenshot, artifact EOF/hash, clean stop
    - [x] Chromium `include_accessibility=false` text observation
    - [x] Chromium 기본 accessibility 포함 observation
    - [x] Firefox DOM observation
- [ ] Firefox·Chromium backend별 capability test 실행 **[alpha — 남은 하위 항목만]**
  - [x] shared typed legacy adapter/fake capability contract
  - [ ] 실제 장치 backend별 capability probe (`b5362f9`는 launcher만 통과하고 observe capability는 양쪽 실패) **[alpha]** — alpha 게이트 v1의 L2 canonical로 판정한다.
- [ ] 100-action soak test와 1시간 idle/resume test 실행 **[alpha.2]**
- [ ] browser crash, daemon crash, stale socket, stale lock 복구 test 실행 **[alpha.2 — 남은 하위 항목만]**
  - [x] local durable outcome/stale lock/private socket/X display lease와 Chromium readiness-retry recovery contracts
  - [ ] 실제 device browser/daemon kill recovery **[alpha.2]**
- [ ] Android background process kill 이후 복구 test 실행 **[alpha.2]**
- [ ] SSH disconnect/reconnect test 실행 **[alpha.2]**
- [x] permission bypass·token replay·path traversal·artifact traversal test 실행
- [x] prompt-injection fixture에서 policy boundary test 실행
- [x] secret redaction test 실행
- [x] performance budget 측정 및 baseline 비교
  - [x] 2026-08-15 S22U Firefox/Chromium baseline·budget 판정
  - [x] compact release candidate 재측정·비교
- [x] 최소 1대의 실제 Android/Termux 장치에서 release candidate 검증
  - [x] `b5362f9` side-by-side 설치, native cryptography, pinned MCP, 304 tests, observer stdio/discovery
  - [x] 양쪽 backend의 full observer와 실제 `final_verify.py` 실행
- [ ] 선택적으로 2번째 장치 또는 Android VM에서 호환성 검사 **[alpha.2, 선택]**
- [x] 외부 사이트 smoke test는 non-gating 보고서로 분리
- [ ] README, architecture, security, migration, troubleshooting 최종 검토 **[alpha — 남은 하위 항목만]**
  - [x] current-vs-target truthfulness, lifecycle, local-link audit
  - [ ] device/release evidence 반영 후 최종 승인 **[alpha]**
  - [ ] 리셋 후 준비에서 확인된 선행 조건(pydantic-core 소스 빌드에 `rust` 필요, r2)의 설치 문서 반영 **[alpha]**
- [ ] version을 `0.1.0-alpha`로 정리하고 changelog 작성 **[alpha]**
- [ ] GitHub release artifact와 설치 명령 검증 **[alpha]**
- [ ] post-alpha backlog를 v0.2 milestone으로 이전 **[alpha]**
- **Status:** in_progress — alpha 게이트 v1 통과 대기 (현재 L1 진단 단계)

#### Phase 7A: `b5362f9` Observer Recovery Plan — 종료

2026-08-25부터 08-31까지의 기기 복구 계획이다. `v0.2.17`(2026-08-31)과 `v0.2.20`(2026-09-22)의
S22U canonical PASS로 Exit Gate를 충족했다. 항목별 기록은
[이력](docs/history/task_plan-through-2026-11-06.md)의 같은 제목 절에 있다.

남아 있던 미체크 항목 다섯 개 가운데 "새 commit에서 canonical gate 재실행" 네 개는 이후의 PASS로
대체됐다. "commit-suffixed server 등록"은 production 전환에 속하므로 `Alpha.2 Backlog`로 옮겼다.

**Deliverables**

- release test report
- security review report
- performance report
- `v0.1.0-alpha`

**Exit Gate**

- Alpha Definition of Done의 모든 항목이 충족되고, 미해결 제한사항이 README와 release notes에 명시되어야 한다.

---

## Milestone Gates

| Milestone | Gate | Evidence |
|---|---|---|
| M0 — Baseline | upstream 동작과 기능 표면 재현 | inventory, baseline logs |
| M1 — Contract Freeze | v1 schema·risk·capability 확정 | RFC, schema tests |
| M2 — Core Migration | 새 service를 통해 legacy smoke 통과 | unit + compatibility tests |
| M3 — Browser Loop | ref 기반 observe–act–verify 통과 | fixture E2E traces |
| M4 — Safe Remote Use | 승인·artifact·shared view 동작 | SSH integration + security tests |
| M5 — Product Surface | MCP ≤16, Developer Mode 격리 | contract tests, tool inventory |
| M6 — Alpha | Alpha DoD와 alpha 게이트 v1 충족, 문서·release 정리 | L2 manifest, benchmark 요약, release report |
| M7 — Alpha.2 | Alpha.2 DoD, 게이트 v2 | 게이트 v2 정의 시 확정 |

M2의 legacy `tbp` 연결과 M4의 SSH integration 증거는 alpha.2 범위다.

---

## Testing Strategy

### Unit Tests

- typed model validation
- permission decisions
- server-held approval expiry/replay
- risk classification
- element ref registry and stale detection
- page revision calculation
- artifact path·quota·expiry
- trace redaction
- backend capability negotiation

### Contract Tests

- 모든 MCP tool의 schema snapshot
- CLI/MCP/daemon이 동일한 service result를 반환하는지 검증
- Firefox/Chromium의 unsupported capability 오류 형식 일치
- legacy `tbp` mapping 회귀 검사

### Deterministic Browser Fixtures

- text/link/button/input extraction
- input and submit preview
- SPA route change
- loading/empty/error/success state
- DOM replacement and stale ref
- Shadow DOM
- iframe
- dialog
- download
- multiple tabs/popups
- malicious page instruction/prompt injection
- cross-origin navigation permission

### On-Device Tests

차선과 절차는 [검증 차선](docs/verification-lanes.ko.md)을 따른다. L1에서 확인한 뒤 L2에서 판정한다.

- alpha: Firefox/Chromium startup, Xvfb/openbox focus routing, screenshot과 artifact 회수,
  양 backend canonical, benchmark
- alpha.2: clean Termux install, phone sleep/wake, Android process reclamation, low-memory behavior,
  proxy mode, SSH stdio reconnection

### Non-Gating External Smokes

- public dynamic page
- representative Cloudflare page
- OAuth popup page
- bot-detection/fingerprint diagnostics

> 외부 사이트 결과는 환경과 정책 변화에 따라 달라지므로 릴리스 통과 조건으로 사용하지 않는다.

---

## Performance Budgets

| Operation | Target | Notes |
|---|---:|---|
| `session_status` on warm daemon | ≤ 300ms | local socket 기준 |
| text-only `observe` | ≤ 2s | 일반 문서 페이지 |
| screenshot observe | ≤ 4s | 1080p급 |
| ref click + verification | ≤ 5s | 일반 버튼 |
| artifact metadata lookup | ≤ 300ms | local store |
| remote screenshot retrieval | ≤ 5s | Wi-Fi SSH 기준 |
| daemon idle RSS | baseline 대비 증가 ≤ 20% | backend별 측정 |
| 100-action soak | crash 0회 | memory trend 기록 |

성능 목표가 실제 Termux 장치에서 비현실적이면 임의 완화하지 말고 baseline과 원인을 `findings.md`에 기록한 뒤 이 표를 승인된 수치로 갱신한다.

---

## Security and Privacy Checklist

- [x] site access와 consequential action 승인 분리
- [x] permission 기본값 least-permissive
- [x] origin 정규화와 IDN/punycode 검사
- [ ] redirect를 따라가기 전에 origin/IP 재검사
- [x] page revision과 server-held approval 결합
- [x] trace secret redaction
- [x] credential fields의 typed observation·action evidence 자동 마스킹
- [ ] screenshot 민감 영역 정책 검토
- [x] cookie/storage/history는 기본 toolset 밖
- [x] full CDP 기본 off
- [x] path traversal·symlink escape 방어
- [x] Unix socket·profile·artifact 권한 제한
- [ ] SSH wrapper stdout purity
  - [x] packaged local stdio EOF cleanup and zero-output probe
  - [ ] actual remote `ssh -T` probe
- [x] malicious page text가 policy engine을 호출하지 못함
- [ ] downloads에 MIME·size·hash·quarantine metadata 부여
  - [x] MIME·size·content-addressed SHA-256 metadata
  - [ ] quarantine decision/metadata
- [ ] audit log는 append-only 또는 tamper-evident 옵션 검토

---

## Resolved Design Questions

1. Ref는 document/tab/origin 변경 시 즉시 stale이다. DOM-only 변경에서는 R0/R1만 동일 node fingerprint 재검증을 허용하고 R2 이상은 새 observation을 요구한다.
2. Page revision은 document epoch와 DOM mutation counter를 결합한다.
3. Artifact 전송은 MCP resource 지원 여부와 무관하게 chunked read를 보장한다.
4. Shared-view MVP는 2초 주기의 정적 읽기 전용 dashboard로 시작한다.
5. v0.1은 단일 활성 session과 복수의 프로젝트별 지속 profile을 지원한다.
6. Upload는 compact MVP에서 제외하고 legacy에서도 기본 비활성화한다.
7. Raw JavaScript eval과 raw CDP는 Developer Mode 전용이다.
8. Chromium을 기본 backend로 사용하고 Firefox는 명시 선택하는 호환 backend로 유지한다. 자동 fallback은 하지 않는다.
9. `termux-browser-pilot`, `tbp`, `tbp-mcp` 공개 이름은 v0.x 동안 유지하고 v1 rename은 별도 migration으로 승인받는다.
10. Challenge 감지는 core handoff signal로 유지하지만 stealth·Cloudflare 우회 성공은 제품 보장이나 gating 기준으로 사용하지 않는다.
11. Confirmation은 MCP host elicitation을 우선하고 미지원 시 CLI prompt/approve를 사용한다. Shared view는 승인 기능을 갖지 않는다.
12. Profile은 명시적 project ID를 hash한 저장 경로로 격리한다.

---

## Decisions Made

| Decision | Rationale |
|---|---|
| 표시명은 `Termu-inator`, Python namespace는 `termuinator`를 사용한다. | 하이픈이 포함된 프로젝트명과 import 가능한 package 이름을 분리한다. |
| 핵심 제품은 안티봇 우회기가 아니라 AI 브라우저 런타임으로 정의한다. | 외부 탐지 정책은 변동성이 크고 품질 보장이 불가능하다. |
| 기본 MCP tool surface는 최대 16개로 제한한다. | 도구 선택 오류와 schema context 비용을 줄인다. |
| observe 결과의 stable ref를 selector보다 우선한다. | 모델의 selector 추측과 잘못된 클릭을 줄인다. |
| 모든 action은 before/after verification을 반환한다. | transport 성공을 실제 작업 성공으로 오인하지 않게 한다. |
| full CDP와 raw eval은 기본 비활성화한다. | 쿠키·토큰·응답 body 등 민감한 브라우저 내부가 노출될 수 있다. |
| 사이트 접근 승인과 consequential action 승인을 분리한다. | 사이트 허용이 제출·삭제까지 포괄하지 않게 한다. |
| 페이지 내용은 항상 untrusted input으로 취급한다. | 웹 prompt injection이 권한·도구·정책을 변경하지 못하게 한다. |
| MVP transport는 local/SSH stdio MCP로 시작한다. | 현재 Hermes WSL2 ↔ Android Termux 구성을 가장 적은 공격면으로 지원한다. |
| screenshot/download는 artifact URI로 전달한다. | 큰 binary를 일반 JSON tool response에 반복 포함하지 않는다. |
| legacy `tbp`는 adapter로 유지하되 새 로직을 중복 구현하지 않는다. | 점진적 migration과 유지보수성을 함께 확보한다. |
| external anti-bot 사이트 테스트는 non-gating으로 둔다. | 외부 정책 변화가 내부 릴리스 품질 판정을 왜곡하지 않게 한다. |
| CLI와 MCP는 별도 venv로 설치하고 MCP venv만 Termux system site packages를 사용한다. | Android ABI가 필요한 `cryptography`를 Termux native package로 사용하면서 CLI와 MCP dependency failure를 격리한다. |
| Chromium을 기본 backend로, Firefox를 명시 선택 호환 backend로 둔다. | S22U baseline에서 Chromium은 모든 warm latency budget을 통과했고 Firefox는 status/text가 초과했다. |
| v0.x 공개 distribution/command 이름은 기존 `termux-browser-pilot`, `tbp`, `tbp-mcp`를 유지한다. | 내부 구조 변경과 사용자-facing rename을 분리해 migration 위험을 줄인다. |
| 프로젝트별 지속 profile과 단일 활성 session을 사용한다. | 로그인 상태를 보존하면서 프로젝트 간 cookie/storage 노출을 차단한다. |
| Shared view MVP는 읽기 전용 정적 dashboard로 시작한다. | 원격 가시성을 먼저 제공하고 별도의 승인·조작 공격면을 만들지 않는다. |
| Raw device process output은 저장소 밖에 두고 sanitized aggregate와 hash만 추적한다. | device path, process argument, Hermes runtime detail의 공개를 막으면서 결과 무결성을 검증한다. |
| RC verifier의 MCP child는 전용 HOME/XDG/TMP와 고정 owner scope를 사용하고 진단 override를 상속하지 않는다. | 기존 `~/.tbp`, config, `TBP_SINGLE_PROCESS`가 release candidate를 오염하거나 사용자 상태를 변경하지 못하게 한다. |
| optional VirGL은 manager가 직접 시작한 process만 종료하며 외부 server를 선행 종료하지 않는다. | 동시 Termux 세션과 다른 앱의 GPU helper를 보호하고, 충돌·실행 실패는 안전한 SwiftShader fallback으로 처리한다. |
| Device benchmark는 checksum-valid canonical manifest와 현재 runtime identity가 정확히 일치할 때만 시작한다. | `--system-site-packages`의 native package가 canonical 이후 갱신될 수 있으므로 과거 PASS를 변경된 환경의 성능 승인으로 재사용하지 않는다. |
| v0.2.20과 socket-r1은 완료된 증거로 보존하고 다음 작업은 소유 자원 증거와 실제 작업·복구 검증으로 제한한다. | 전역 목록의 관측 불가를 제품 실패나 전체 PASS로 바꾸지 않으며 같은 진단의 반복을 끝낸다. 새로운 인수 기준과 production 승인은 별도 결정이다. |
| S22U 실기기 인수는 필수이며 `acceptance/`의 로컬 게이트로 대체하지 않는다. (2026-10-23 사용자 결정) | 제품의 가치는 Termux/Android에서의 실제 동작이다. 기기 회차는 Mac에서 보이지 않는 결함을 실제로 찾아냈다. |
| 검증을 L0 로컬, L1 기기 진단, L2 기기 인수 세 차선으로 나눈다. (2026-11-10) | 봉인 인수 회차를 디버깅에 쓰면 한 회차에 사실 하나만 얻는다. 원인은 비봉인·반복 가능·원문 로그의 L1에서 찾고, L2는 L1에서 통과한 commit의 확인 절차로 둔다. |
| 합성 실행(임시 프로필, `about:blank`·loopback fixture)의 원문 stderr와 assertion 값은 Mac 쪽에 전달한다. (2026-11-10) | 보호할 실제 데이터가 없다. 범주 label만으로는 r2–r3의 Chromium 원인을 찾지 못했다. 실제 계정·프로필 자료의 비공개 원칙은 그대로다. |
| alpha 게이트를 v1으로 동결한다. (2026-11-10) | v0.2.20 PASS 뒤 게이트가 확장되면서 통과 조건이 회차마다 달라졌다. alpha까지 필수 항목을 추가하지 않고 검수기 변경은 L1에서 재현된 결함 수정으로 제한한다. |
| 기기 preflight의 unit suite 전체 실행을 비차단 정보로 낮춘다. (2026-11-10) | r4는 브라우저를 띄우기 전에 테스트 패키징 문제로 끝났다. 기기가 필요한 이유는 Android의 실제 브라우저 동작이다. binding과 import origin 확인은 차단 항목으로 남긴다. |
| alpha 범위를 핵심 루프로 줄이고 나머지를 alpha.2로 옮긴다. (2026-11-10) | Phase 3–6의 미완 23개 항목을 구현할 때마다 source digest가 바뀌어 기기 인수를 다시 해야 한다. 좁은 범위를 먼저 닫는다. |
| environment epoch가 바뀌면 코드보다 브라우저 단독 시작을 먼저 확인한다. (2026-11-10) | Termux 리셋으로 Chromium 149→155, Firefox 154→158이 됐는데 이를 분리하지 않고 세 회차를 썼다. |
| 계획·기록의 이력은 `docs/history/`로 옮기고 `STATUS.md`를 현재 상태의 기준으로 둔다. (2026-11-10) | 세 파일이 합계 688 KB가 되어 현재 위치를 찾기 어려웠고 맨 위 상태가 실제와 어긋났다. |

---

## Risks and Mitigations

| Risk | Impact | Mitigation | Trigger for Re-plan |
|---|---|---|---|
| Firefox DevTools/clipboard/focus 불안정 | action 실패·지연 | exact sentinel, timeout state invalidation, one bounded observe retry, secret-free diagnostics | fixture 성공률 <90% |
| giant daemon refactor 회귀 | 광범위 기능 손상 | strangler adapter, 작은 module 단위 migration, contract tests | legacy smoke 연속 실패 |
| element ref가 SPA에서 빠르게 stale | 잘못된 클릭 | page revision, mutation sequence, fail-closed | stale false-negative 발생 |
| MCP binary resource 호환성 부족 | 원격 screenshot 불가 | artifact URI + chunked read fallback | Hermes/Codex 중 한쪽에서 resource 실패 |
| Android background kill | 세션 유실 | health watchdog, reconnect, explicit resume state | 30분 idle 후 복구 실패 |
| Chromium/Termux 패키지 변화 | startup 실패 | binary discovery, capability probe, version matrix | 새 stable Termux에서 실패 |
| prompt injection | 권한 오남용 | page data/policy 분리, confirmation gate, security fixtures | 페이지 텍스트로 tool policy 변화 |
| permission UX가 번거로움 | 사용자 우회 설정 | session allow, scoped presets, clear pending queue | 사용자가 Always allow를 기본 요구 |
| screenshot에 민감 정보 포함 | 정보 노출 | user-visible indicator, redaction options, retention limits | 로그인·결제 화면 저장 발견 |
| stealth 기능 유지 요구 | 범위 팽창 | experimental namespace와 비보장 문구 | core 릴리스가 stealth 성공에 의존 |
| 단일 세션 bottleneck | 동시 작업 제한 | MVP 명시, queue/lock, v0.2 multi-session 설계 | 실제 사용에 동시 세션 필수 |
| 환경 drift와 코드 변경이 겹침 | 원인 분리 불가, 회차 낭비 | environment epoch 규칙, L1 브라우저 단독 진단, `STATUS.md` 버전 표 | **발생.** 2026-10-23 리셋 뒤 Chromium 155 미시작 |
| Chromium 155가 패키지 수준에서 동작하지 않음 | Chromium backend의 alpha 불가 | 버전 고정 또는 Firefox 단독 alpha를 사용자와 결정 | L1 단독 진단에서 최소 구성도 실패 |
| 검수기·fixture 자체 결함 | 기기 회차 소모 | 게이트 동결, L1에서 같은 검수기를 먼저 통과시킨 뒤 L2 | L2가 검수기 원인으로 1회 실패 |
| 계획·기록 비대 | 현재 상태 유실, 낡은 지시 실행 | `STATUS.md` 100줄 상한, 이력 분리, 한 사실 한 곳 | `STATUS.md`가 실제와 다름 |

---

## Errors Encountered

2026-11-06까지의 항목 400여 개는 [이력](docs/history/task_plan-through-2026-11-06.md)의 같은 제목 절에
보존했다. 이 표는 더 쌓지 않는다.

- 작업 중 오류는 해당 `progress.md` 항목에 한 줄로 적는다.
- 같은 종류의 오류가 세 번 나오면 원인과 회피 방법을 `findings.md`에 사실로 올린다.
- 반복해서 나온 작업 환경 오류는 [findings.md](findings.md)의 "작업 환경" 절에 정리했다.

---

## Expected Deliverables

- [x] `task_plan.md`
- [x] `findings.md`
- [x] `progress.md`
- [x] Termu-inator fork repository
- [x] compact MCP v1 server
- [x] typed browser core and two backend adapters
- [x] permission/confirmation engine
- [x] artifact store and bounded retrieval
- [x] shared-view MVP
- [x] Developer Mode
- [x] Hermes and Codex integration examples
- [x] deterministic fixture test suite
- [x] architecture/security/migration documentation
- [ ] `v0.1.0-alpha` release

---

## Alpha.2 Backlog

Phase 체크리스트에서 **[alpha.2]** 로 표시한 항목이 alpha.2의 구현 범위다. 여기에는 게이트 동결로
미룬 검사와 그 밖의 후속 작업을 적는다.

- 게이트 v2 후보: 활성 backend·MCP 중단 복구, 100-action soak, 1시간 idle/resume, Android background kill.
- 게이트 v2 후보: 탭·popup·dialog·다운로드의 기기 canonical 단계.
- 기기 fault 주입 검사의 범위, 소유 자원, 승인 절차 정의.
- redirect를 따라가기 전 origin/IP 재검사와 DNS/peer enforcement. 일반 웹 사용 승인의 선행 조건이다.
- 깨끗한 Termux 환경에서 문서화된 설치 절차 재현.
- Mac에서 S22U Termux로의 직접 SSH 경로. 네트워크 설정 변경이므로 사용자 승인이 필요하다.
- `scripts/final_verify.py`의 분할과 단순화. 게이트 동결이 끝난 뒤에 한다.
- 기존 Hermes 등록을 보존한 side-by-side 등록과 production 전환. 별도 승인 대상이다.

---

## Post-MVP Backlog

- Record & Replay용 action trace → reusable workflow 변환
- visual annotation을 코드 변경 task와 연결하는 comment model
- 다중 독립 session/profile 및 session별 Xvfb display
- HTTP/WebSocket remote transport와 token authentication
- low-bandwidth screenshot delta streaming
- Android notification을 통한 approval prompt
- optional Chrome/Android browser bridge
- workflow scheduler와 Telegram command presets
- trace replay viewer와 실패 단계 재실행
- browser action evaluation benchmark

---

## Notes

- 단계 상태는 `pending → in_progress → complete` 순서로 갱신한다.
- 조사 결과는 채팅에만 남기지 말고 `findings.md`(사실)나 `progress.md`(경과)에 기록한다.
- 오류를 숨기지 않는다. 실패한 접근을 기록한 뒤 다른 접근으로 전환한다.
- 기능 수보다 **관찰 정확도, 행동 검증, 승인 경계, 원격 가시성**을 우선한다.
- Termu-inator의 성공 기준은 “페이지를 많이 조작한다”가 아니라 “사용자가 상태와 위험을 확인하면서 신뢰할 수 있게 조작한다”이다.
