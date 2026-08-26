# Task Plan: Termu-inator — AI-First Browser Use for Termux/Android

<!--
  WHAT: Termux Browser Pilot 포크를 AI 에이전트용 브라우저 런타임으로 재설계하는 전체 작업 로드맵.
  WHY: 장기 구현 중 목표 표류와 중복 실패를 막고, Codex/Hermes가 세션을 넘어 작업을 이어갈 수 있게 한다.
  WHEN: 구현 시작 전에 생성하며, 각 단계 완료·결정 변경·오류 발생 시 즉시 갱신한다.
-->

- **Project codename:** Termu-inator
- **Upstream:** `salviz/termux-browser-pilot`
- **Planning baseline:** upstream `main` @ `b95eccd3d1abc188c3aa488a23c519ebacc99fcf`
- **Plan created:** 2026-08-15
- **Plan status values:** `pending` → `in_progress` → `complete` / `blocked`
- **Companion working-memory files:** `findings.md`, `progress.md`

## Goal

Termux/Android에서 실제 Firefox·Chromium을 제어하되, 기존의 방대한 명령 집합을 핵심 기능으로 축소하고 **공유 가능한 브라우저 관찰, 안정적인 observe–act–verify 루프, 원격 아티팩트 전달, 사이트·행동별 승인, 선택적 CDP 개발자 모드**를 갖춘 Codex Browser Use형 AI 브라우저 런타임 **Termu-inator**를 구축한다.

## Next Step

`b5362f9`의 Chromium accessibility 반환형, Firefox DOM probe 구문 손상, generic stdio의
Chromium `TMPDIR` 누락을 실제 실패형 RED 뒤에 복구했다. 검증 중 발견한 compact MCP의
`SIGTERM` stale control socket도 종료 후 identity-safe cleanup과 동일 data-root 재시작
회귀로 닫았다. canonical verifier의 HOME/XDG/TMP 격리와 diagnostic override 제거,
VirGL 소유권 경계도 RED/GREEN으로 보강했다. verifier는 wheel/checkout/installed source,
release metadata, license, RECORD와 portable control-socket 경로까지 묶는다. Python
3.11/3.12/3.14의 warning-as-error 339-test suite, pinned MCP 전체 suite, fresh pip wheel
install/check, 네 entrypoint, interactive→observer 연속 stdio purity가 모두 GREEN이다.
다음은 이 uncommitted candidate를 새 commit으로 만든 뒤 S22U에 side-by-side 설치하여
checkout의 `scripts/final_verify.py`를 실행하는 것이다. 현재 S22U는 tailnet map에서
online이지만 ping 무응답이고 TCP 8022도 닫혀 있어 Mac 직접 실행은 불가능하다. 양 backend
PASS와 `benchmark_allowed: true` 전에는 benchmark나 RC 승인을 진행하지 않는다.

## Current Phase

Phase 7 — S22U RC Observer Recovery

## Planning-with-Files Operating Rules

1. 구현 또는 조사 시작 전에 이 파일을 다시 읽는다.
2. **조회·검색·코드 탐색 작업을 2회 수행할 때마다** 핵심 발견을 `findings.md`에 기록한다.
3. 코드·설정·문서·테스트를 변경할 때마다 `progress.md`에 파일명과 결과를 기록한다.
4. 오류는 해결 여부와 무관하게 즉시 `Errors Encountered`에 기록한다.
5. 같은 실패 접근을 그대로 반복하지 않는다. 실패 원인을 기록하고 다음 시도에서 조건이나 방법을 변경한다.
6. 단계 상태가 바뀔 때마다 `Current Phase`와 `Next Step`을 함께 갱신한다.
7. 각 Phase의 **Exit Gate**가 충족되기 전에는 `complete`로 표시하지 않는다.
8. 계획 변경이 범위·보안·API 호환성에 영향을 주면 `Decisions Made`에 근거를 남긴다.
9. 외부 사이트 기반 테스트는 보조 증거로만 사용하고, 릴리스 게이트는 결정론적 로컬 fixture 테스트로 판단한다.
10. 사용자가 승인하지 않은 비가역 작업, 자격 증명 입력, 결제, 삭제, 권한 변경은 자동화하지 않는다.

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

Termu-inator MVP는 다음 조건을 모두 만족해야 한다.

### Functional

- [x] Firefox와 Chromium이 동일한 v1 observation/action 계약을 구현한다.
- [x] backend별 미지원 기능은 명시적 capability와 구조화 오류로 반환된다.
- [x] observe 결과의 ref로 click/type/select/check가 가능하다.
- [x] stale ref 또는 page revision mismatch가 실제 행동 전에 차단된다.
- [x] 모든 행동 후 자동 verification 결과가 반환된다.
- [ ] 탭 전환, dialog 감지, 사용자 sign-in handoff, 다운로드 회수가 동작한다.
- [ ] screenshot과 다운로드를 WSL2/Hermes에서 원격 회수할 수 있다.
- [x] 기본 MCP 도구 수가 16개 이하이다.

### Safety

- [x] 새 origin 접근 정책이 `ask/session allow/always allow/block`을 지원한다.
- [x] R4 행동은 유효한 server-held one-shot approval 없이는 실행되지 않는다.
- [x] full CDP는 기본 비활성화이며 별도 승인 없이는 접근할 수 없다.
- [x] 페이지 텍스트가 권한 정책·도구 노출·승인 상태를 변경할 수 없다.
- [x] credential·OTP·cookie value·authorization header가 일반 trace에 기록되지 않는다.
- [x] artifact와 profile 파일에 제한 권한과 path traversal 방어가 적용된다.

### Reliability

- [ ] 결정론적 로컬 fixture E2E 시나리오 25개 이상을 구축한다.
- [ ] 핵심 fixture 시나리오 반복 성공률 95% 이상을 달성한다.
- [ ] 1시간 또는 100개 연속 action soak test에서 daemon이 비정상 종료하지 않는다.
- [ ] 브라우저 crash·stale socket·profile lock에서 명확한 복구 경로를 제공한다.
- [ ] status 명령은 warm daemon에서 목표 300ms 이내, text-only observe는 목표 2초 이내다.

### Compatibility & Delivery

- [ ] 기존 `tbp` 주요 읽기·탐색·클릭 명령에 compatibility adapter가 존재한다.
- [x] Hermes SSH stdio 예제와 Codex MCP 예제가 검증된다.
- [x] architecture, tool contracts, security model, migration 문서가 완성된다.
- [x] 설치·업데이트·삭제·데이터 초기화 절차가 문서화된다.
- [x] MIT 원저작자 고지와 포크 변경 내역이 보존된다.

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
- [ ] 현행 설치 절차를 깨끗한 Termux 환경에서 재현
- [x] example.com 기반 baseline smoke test 실행
- [x] 현재 daemon warm latency, browser startup, RSS, screenshot 크기 측정
- [x] 확인된 결함과 문서 불일치를 `findings.md`에 기록
- **Status:** in_progress

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

- [ ] Python package namespace를 `termuinator`로 이전
- [x] 공통 typed models, structured errors, config loader 구현
- [x] `BrowserBackend` protocol/ABC 정의
- [x] Firefox native와 Chromium CDP를 backend adapter로 래핑
- [x] session manager와 single-session lock 구현
- [ ] daemon transport와 business logic 분리
- [ ] handler registry를 기능별 모듈로 분할
- [x] artifact store와 trace recorder 기본 골격 구현
- [x] permission engine interface 구현
- [ ] legacy `tbp` command를 새 service 호출로 연결
- [ ] 기존 로직과 신규 로직의 중복 구현 제거
- [x] fake backend와 unit test harness 구축
- [x] pyproject version, optional dependencies, Pillow/MCP dependency 정리
- [x] openbox 중복 실행, Chromium binary detection 등 baseline 결함 수정
- **Status:** in_progress

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

- [ ] DOM·accessibility·rendered state를 통합하는 `browser_observe` 구현
  - [x] Firefox/Chromium legacy adapter의 bounded same-origin DOM·open-shadow inventory
  - [x] legacy observed-ref click/type/select/check/hover/drag, page key/scroll와 typed before/after evidence
  - [ ] cross-origin frame의 native adapter 지원
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
- [ ] 탭·팝업·dialog 수명주기 통합
  - [x] typed tab list/open/switch/close와 active page identity 전이
  - [x] typed popup inventory·dialog lifecycle과 deterministic fake 연결
  - [ ] Firefox/Chromium legacy adapter의 popup·dialog event 연결
- [x] challenge/OTP 감지를 action 차단·handoff 신호로 연결
  - [x] credential/OTP element 감지와 confidential takeover 신호
  - [x] Firefox/Chromium adapter의 sensitive-field semantics 추출
- [ ] raw coordinate action은 arm + visual verification 조건으로 격리
- [ ] 각 action의 before/after trace와 진단 artifact 저장
  - [x] secret-free action metadata를 durable trace로 저장·조회·export
  - [ ] before/after 진단 artifact 연결
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
- **Status:** in_progress

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
- [ ] 다운로드 완료 감지와 원격 파일 회수 구현
  - [x] typed lifecycle, stable public ID, MIME/size/hash와 artifact publication
  - [x] compact MCP list/wait와 chunked artifact 회수
  - [ ] Firefox/Chromium adapter의 실제 download event/bytes 연결
  - [ ] SSH/Hermes 원격 round-trip
- [ ] SSH stdio 환경에서 screenshot/download round-trip 검증
- [x] 최소 shared-view dashboard 구현
  - [x] 현재 cached screenshot
  - [x] redacted URL/title/tab
  - [x] value-free pending permission/confirmation summary
  - [x] recent action trace
  - [x] takeover/resume state indicator (mutation controls remain CLI/host-only)
- [x] artifact expiry·quota·cleanup 구현
- [x] audit log와 secret redaction test 추가
- **Status:** in_progress

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
- [ ] optional performance trace export 구현
- [ ] response body·cookie·header·raw eval의 추가 승인 규칙 구현
- [ ] raw CDP passthrough는 실험 플래그 뒤에 격리
- [x] 최종 MCP v1 도구를 16개 이하로 고정
- [x] tool descriptions를 observe-first·ref-first 흐름에 맞게 작성
- [x] Hermes용 기본 read-only tool allowlist 제공
- [x] Hermes용 interactive tool profile 제공
- [x] Codex MCP 예제 설정 제공
- [ ] SSH wrapper가 stdout에 MCP 외 텍스트를 출력하지 않도록 검증
  - [x] installed-wheel local observer/interactive idle stdio purity
  - [ ] 실제 Tailscale `ssh -T` remote stdout purity
- [ ] CLI를 session/observe/act/devtools/artifacts 중심으로 재구성
- [ ] 기존 `tbp` alias와 migration warnings 제공
- [x] 설치·업데이트·데이터 초기화·문제 해결 문서 작성
  - [x] fail-closed 설치와 compact/legacy/Developer 선택 문서
  - [x] 업데이트·삭제·데이터 초기화·최종 troubleshooting
- **Status:** in_progress

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

- [ ] unit·contract·fixture E2E 전체 실행
  - [x] local unit·contract·HTTP fixture authority suite (304 tests)
  - [ ] 실제 Firefox·Chromium fixture browser E2E
    - [x] `b5362f9` 양쪽 backend의 session start, navigation, screenshot, artifact EOF/hash, clean stop
    - [x] Chromium `include_accessibility=false` text observation
    - [ ] Chromium 기본 accessibility 포함 observation
    - [ ] Firefox DOM observation
- [ ] Firefox·Chromium backend별 capability test 실행
  - [x] shared typed legacy adapter/fake capability contract
  - [ ] 실제 장치 backend별 capability probe (`b5362f9`는 launcher만 통과하고 observe capability는 양쪽 실패)
- [ ] 100-action soak test와 1시간 idle/resume test 실행
- [ ] browser crash, daemon crash, stale socket, stale lock 복구 test 실행
  - [x] local durable outcome/stale lock/private socket/X display lease와 Chromium readiness-retry recovery contracts
  - [ ] 실제 device browser/daemon kill recovery
- [ ] Android background process kill 이후 복구 test 실행
- [ ] SSH disconnect/reconnect test 실행
- [x] permission bypass·token replay·path traversal·artifact traversal test 실행
- [x] prompt-injection fixture에서 policy boundary test 실행
- [x] secret redaction test 실행
- [ ] performance budget 측정 및 baseline 비교
  - [x] 2026-08-15 S22U Firefox/Chromium baseline·budget 판정
  - [ ] compact release candidate 재측정·비교
- [ ] 최소 1대의 실제 Android/Termux 장치에서 release candidate 검증
  - [x] `b5362f9` side-by-side 설치, native cryptography, pinned MCP, 304 tests, observer stdio/discovery
  - [ ] 양쪽 backend의 full observer와 실제 `final_verify.py` 실행
- [ ] 선택적으로 2번째 장치 또는 Android VM에서 호환성 검사
- [x] 외부 사이트 smoke test는 non-gating 보고서로 분리
- [ ] README, architecture, security, migration, troubleshooting 최종 검토
  - [x] current-vs-target truthfulness, lifecycle, local-link audit
  - [ ] device/release evidence 반영 후 최종 승인
- [ ] version을 `0.1.0-alpha`로 정리하고 changelog 작성
- [ ] GitHub release artifact와 설치 명령 검증
- [ ] post-alpha backlog를 v0.2 milestone으로 이전
- **Status:** in_progress

#### Phase 7A: `b5362f9` Observer Recovery Plan

1. [x] **Chromium accessibility 계약을 먼저 복구한다 (P0, deterministic).**
   - 실제 `Pilot.a11y_tree()`의 문자열 반환을 사용하는 RED를 추가해 현재
     `invalid accessibility data`를 재현한다.
   - legacy `browser_a11y`의 문자열 wire shape는 변경하지 않는다.
   - `AccessibilityCommands.get_tree()`를 사용하는 별도 structured Pilot 경로를
     만들고, adapter는 role/name 중심의 bounded mapping 목록만 받도록 정규화한다.
     raw CDP node, private backend id, unbounded nested payload는 public observation에
     그대로 전달하지 않는다.
   - public mapping은 frozen `AccessibilityNode`의 `ref/role/name/text/depth`를 모두
     채우며, backend ref가 없는 summary node는 `ref: null`, `text: ""`, `depth: 0`으로
     고정한다. role/name 두 필드만 반환하는 내부 mapping은 MCP output gate에서 거부한다.
   - mapping/list 정상형, legacy 문자열 오입력, malformed/unbounded node를 각각
     회귀 검사하고 실패 메시지에 페이지 데이터가 섞이지 않음을 확인한다.

2. [x] **Firefox DOM probe 구문 손상을 분류·복구한다 (P0, deterministic).**
   - 원본 `observe_script()`는 JavaScript syntax를 통과했지만 legacy 단일행 변환본은
     `shadow_path:shadowPath; });`를 만들어 `Unexpected token ';'`로 실패함을 재현했다.
   - primary `eval(JSON_STRING)`에 원본 multiline source를 그대로 보존하고, 위험한
     `_safe_join_lines()` 변환과 불필요한 `re` 의존성을 제거했다.
   - JavaScript expression 실패는 raw browser message를 노출하지 않는
     `JavascriptExecutionError(reason="evaluation")`로 구분하고, timeout과 invalid DOM
     payload는 기존 별도 경계를 유지한다.
   - timeout 확대나 text-only fallback 없이 정확한 source corruption만 수정했다.

3. [x] **TMPDIR 재현성을 별도 P1 계약으로 고정한다.**
   - Hermes native 환경에서는 통과했으므로 observer 실패의 직접 원인으로 취급하지
     않는다.
   - generic MCP stdio harness에서도 validated `TMPDIR`가 child Chromium까지
     전달되는지 검사하고, 누락 시 Android의 writable Termux temp root를 명시적으로
     선택한다. 사용자가 Tailscale, DNS, crawl4ai 또는 전역 Python 환경을 바꾸게 하지 않는다.

4. **로컬 검증 후 새 커밋을 side-by-side로만 배포한다.**
   - [x] focused RED/GREEN → warning-as-error 전체 suite on Python 3.11/3.12/3.14 →
     wheel install/pip check → observer/interactive stdio purity 순서로 검증한다.
   - [x] `SIGTERM` 뒤 control socket 제거와 같은 data-root의 두 번째 stdio 기동을
     fresh wheel에서 검증한다.
   - [x] optional VirGL은 외부 process를 pattern-kill하지 않고 own-process launch 실패 시
     SwiftShader로 복귀하며, verifier는 VirGL/xclip/xdotool survivor도 판정한다.
   - [x] repository-owned `scripts/final_verify.py`가 clean commit/local wheel,
     checkout/installed source와 release metadata provenance, exact 14/12 tools,
     portable socket path, loopback full observation, EOF/hash/mode와 process/socket
     cleanup을 fail-closed로 판정하도록 22개 회귀 테스트로 고정한다.
   - [ ] 기존 Hermes 항목과 venv를 보존하고 새 commit-suffixed server를 등록한다.

5. **S22U release gate를 순서대로 닫는다.**
   - loopback deterministic fixture에서 Firefox와 Chromium 모두 기본
     `include_accessibility=true` observation, text, ready state, interactive ref,
     screenshot, EOF artifact read, local/metadata hash, mode 0600, clean stop를 검증한다.
   - 그 다음 `example.com`은 DNS를 포함한 non-gating 외부 smoke로만 실행한다.
   - 양쪽 full smoke가 통과한 뒤에만 compact cold/observe/screenshot/RSS benchmark와
     기존 baseline delta를 기록하며 기존 budget을 조용히 완화하지 않는다.
   - 마지막에 보존된 `final_verify.py`를 실제 실행하고 manifest 검증 결과와 exit code를
     함께 남긴다.
   - [x] ad-hoc 장치 파일이 아니라 checkout의 canonical verifier와 private manifest,
     checksum 형식을 구현하고 local fail-closed/installed-wheel stdio를 검증했다.
   - [ ] 새 commit-suffixed Termux venv에서 canonical verifier를 실제 실행해 양 backend
     PASS, `benchmark_allowed: true`, checksum OK를 확보한다.

**Phase 7A Exit Gate**

- Chromium observation이 legacy summary 문자열에 의존하지 않고 bounded structured
  accessibility를 반환한다.
- Firefox observation이 `ready_state`, text와 최소 한 개의 fixture interactive ref를
  반환하며 generic `backend_crashed`로 종료되지 않는다.
- 양쪽 backend 모두 artifact 무결성·권한과 process/socket cleanup을 통과한다.
- benchmark와 RC 승인 기록은 위 세 조건 이후에만 생성한다.

**Deliverables**

- release test report
- security review report
- performance report
- `v0.1.0-alpha`

**Exit Gate**

- Definition of Done의 모든 필수 항목이 충족되고, 미해결 제한사항이 README와 release notes에 명시되어야 한다.

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
| M6 — Alpha | DoD·문서·release test 충족 | release report |

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

- clean Termux install
- Firefox/Chromium startup
- Xvfb/openbox focus routing
- screenshot and artifact transfer
- phone sleep/wake
- Android process reclamation
- low-memory behavior
- proxy mode
- SSH stdio reconnection

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

---

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| None at plan creation | 0 | 구현 중 모든 오류를 즉시 추가한다. |
| 필수 companion 파일 `findings.md`, `progress.md`가 존재하지 않아 최초 조회가 실패함 | 1 | 두 파일을 생성하고 초기 발견·진행 상태를 기록했다. |
| 저장소 파생 이름으로 architecture graph를 조회했으나 전용 graph가 아직 없었음 | 1 | 현재 checkout을 fast mode로 인덱싱해 988 nodes/4,550 edges를 생성했고 architecture 재조회에 성공했다. |
| CLI/MCP 전체 함수 graph 조회가 연결 노드까지 포함해 14만 토큰 규모로 과다 출력·절단됨 | 1 | 이후 조회는 Cypher 집계와 AST 기반 inventory로 이름·개수만 산출하도록 좁힌다. |
| 복합 Cypher 집계에서 parser가 `expected token type 85` 오류를 반환함 | 1 | CASE/STARTS WITH를 제거한 단순 count 쿼리로 분리하고, 최종 산출은 Python AST inventory로 교차 검증한다. |
| Inventory RED test가 구현 모듈 부재로 import error를 반환함 | 1 | 의도한 미구현 실패를 확인했다. 최소 import 골격을 추가해 assertion failure를 확인한 뒤 구현한다. |
| 로컬 기본 `python3`가 3.9로, 선언된 프로젝트 최소 버전 `>=3.10`보다 낮음 | 1 | 정적 inventory는 3.9에서도 검증 가능한 문법으로 유지하되, 지원 버전 검증은 별도 3.10+ 런타임에서도 수행한다. |
| 기존 `unittest discover`가 5개 파일 모두 `websockets` 미설치 import error로 실패함 | 1 | 현 파일은 자동 unit suite가 아닌 on-device 스크립트로 분리 대상이며, 새 정적 테스트는 base dependency 없이 별도 실행한다. |
| 기본 wheel 설치의 `tbp-mcp`가 optional `mcp` 미설치로 `ModuleNotFoundError` 발생 | 1 | Phase 1 결함으로 기록하고 package entry-point/extra 계약 수정 전 회귀 테스트를 추가한다. |
| Inventory 구현용 대형 `apply_patch` 입력이 JavaScript escape 오타로 실행 전 SyntaxError 발생 | 1 | 파일은 최소 골격 그대로 보존되었으며, 패치를 더 작은 단위와 올바른 인용으로 다시 적용한다. |
| `apply_patch`가 동일 파일의 Delete+Add 동시 연산을 거부함 | 1 | 기존 골격은 손상되지 않았다. Delete와 Add를 별도 패치로 분리해 적용한다. |
| Markdown formatter인 Prettier가 로컬에 설치되어 있지 않음 | 1 | 문서는 수동 검토하고 `git diff --check`와 링크 대상 검증으로 대체했다. |
| zsh가 인용되지 않은 `git tag --format=%(...)` 괄호를 glob qualifier로 해석함 | 1 | format 인자를 작은따옴표로 감싸 재실행한다. Git ref는 변경되지 않았다. |
| baseline 문서·계획 동시 패치가 줄 경계 context 불일치로 거부됨 | 1 | 태그 자체는 검증 완료 상태다. 문서의 현재 줄을 다시 확인하고 더 작은 패치로 나눠 반영한다. |
| 현재 shell PATH에서 `python3.12` 실행 파일을 찾지 못함 | 1 | uv-managed 3.12.13의 명시 경로로 재실행해 새 inventory tests 2개가 통과했다. |
| capability 감사 결과를 `findings.md`에 합치는 패치가 section context 불일치로 거부됨 | 1 | 현재 heading 위치를 다시 검색하고 독립적인 작은 패치로 나눠 반영한다. |
| 최종 inventory 리뷰에서 MCP 이름이 내부 위험 action을 숨기고 동적 CLI `required`/`aliases`가 조용히 누락되는 3개 회귀가 확인됨 | 1 | 세 회귀 테스트의 의도된 RED를 확인했으며, 도구·action 결합 분류와 literal keyword 검증으로 fail-closed 처리한다. |
| CLI parser의 `**kwargs`가 literal `required`/`aliases` 검증을 우회해 group·alias를 누락할 수 있었음 | 1 | 두 우회 fixture의 RED를 확인한 뒤 모든 parser keyword unpacking을 fail-closed 처리했다. |
| S22U baseline 요약용 첫 `jq`가 `.backends`를 객체로 가정해 `Cannot index array with string \"firefox\"`를 반환함 | 1 | top-level schema를 확인해 `.backends[]` 배열로 수정하고 집계값을 재검증했다. |
| 후속 schema 확인에서 존재하지 않는 `.results`를 순회해 `Cannot iterate over null`을 반환함 | 1 | 실제 top-level key가 `environment`, `backends`뿐임을 확인하고 `.backends`만 사용했다. |
| Packaging contract의 첫 RED run이 9 failures와 누락된 `requirements-termux.txt` error 1건을 반환함 | 1 | 모두 기존 결함을 직접 가리키는 의도된 RED임을 확인하고 metadata, constraints, guarded entrypoint, fail-closed dual-venv installer를 구현했다. |
| MCP version 검증 patch가 두 heredoc 중 첫 블록에 `metadata` import를 적용해 두 번째 GREEN run이 1 failure를 반환함 | 1 | MCP venv 검증 heredoc으로 import를 이동하고 중첩 quote 없는 `mcp_version` 변수로 조회하도록 수정했다. |
| 로컬 Python 3.11에 `build` 모듈이 없어 `python3.11 -m build --version`이 실패함 | 1 | 저장소 환경을 변경하지 않고 임시 venv에 build 도구를 설치해 wheel/sdist 검증을 수행한다. |
| 임시 packaging venv 정리용 `rm -rf` trap이 안전 정책에 의해 명령 실행 전에 거부됨 | 1 | 자동 삭제를 제거하고 `mktemp` 경로와 산출물을 보존하는 검증 명령으로 재실행한다. |
| MCP stdio 회귀·기록을 묶은 `apply_patch`가 hunk 경계 형식 오류로 적용 전 거부됨 | 1 | 파일이 불변임을 확인하고 테스트·계획·진행 기록을 작은 patch로 나눠 적용한다. |
| 단일 packaging unittest 경로에 slash를 사용해 test loader가 module을 찾지 못함 | 1 | `tests.test_packaging_contract...` 점 표기법으로 같은 RED를 재실행한다. |
| Portable benchmark 첫 RED가 `scripts.benchmark_device` 모듈 부재로 import error를 반환함 | 1 | 기존 장치 script를 parameterized raw/sanitized harness로 재구현하고 순수 함수 회귀 테스트를 추가한다. |
| Termux install 문서 RED가 누락된 guide error와 README manual-path assertion failure를 반환함 | 1 | authoritative install guide를 추가하고 README가 fail-closed installer와 exact MCP 경로만 안내하도록 수정한다. |
| S22U는 Tailscale ping에 응답했지만 SSH 22/8022 probe가 모두 connection refused를 반환함 | 1 | 장치 설정은 변경하지 않고 clean-install gate를 open으로 유지하며, on-device 경로가 제공될 때 검증 bundle로 재개한다. |
| v1 contract 첫 RED가 `src.termuinator` namespace 부재로 import error를 반환함 | 1 | Python 3.10-compatible stdlib contract models, revision policy, schema generator, 14-tool manifest를 추가한다. |
| RFC boundary test가 `Project-scoped` 대문자 표기와 고정 소문자 phrase 차이로 1 failure를 반환함 | 1 | architecture RFC에 canonical `project-scoped persistent profiles` 문구를 명시한다. |
| Backend/migration contract RED가 누락된 `migration-from-tbp.md`로 error를 반환함 | 1 | capability negotiation target과 v0.1-v0.3 legacy lifetime, 별도 v1 naming migration을 문서화한다. |
| Migration 문서의 canonical phrase가 Markdown line wrap으로 분리돼 1 assertion이 실패함 | 1 | `separate v1 migration`을 한 줄의 고정 문구로 정규화한다. |
| 첫 MCP stdio probe가 `communicate()`로 stdin을 닫아 server가 rc 0으로 즉시 종료함 | 1 | stdin pipe를 열린 채 `wait(timeout=3)`하는 probe로 교체해 server가 3초 이상 정상 대기함을 확인했다. |
| 올바른 MCP stdio probe에서 MCP 1.29.0 `Settings.lifespan` forward reference 경고가 stderr 431 bytes로 출력됨 | 1 | FastMCP 생성 전에 pinned MCP의 `Settings.model_rebuild()`를 호출하는 회귀 테스트와 초기화 수정으로 stdout/stderr purity를 복구한다. |
| Phase 2 보안·조건부 schema 회귀 4건이 2 failures/2 errors로 RED를 반환함 | 1 | caller-owned risk downgrade, session없는 artifact read, 대상 ref 및 multiplexed operation 조건이 현 계약에 없음을 확인했다. 서버 권위 risk와 JSON Schema 조건으로 구현한다. |
| 조건부 schema 구현 후 기존 permission enum 테스트가 단일 `properties` 형상을 가정해 error, 두 snapshot이 예상대로 fail함 | 1 | permission operation 검증을 `oneOf` branch 전체의 enum 합집으로 바꾸고, 구조·문서 검토 후 두 JSON snapshot을 기계적으로 재생성한다. |
| workstation Python 3.11에 `jsonschema`가 없어 schema meta-validation import가 실패함 | 1 | 저장소 환경을 변경하지 않고 이미 보존된 disposable MCP venv의 `jsonschema 4.26.0`으로 검증한다. |
| disposable venv 확인 명령이 deprecated `jsonschema.__version__`을 읽어 warning을 출력함 | 1 | 버전은 확인되었고 이후 schema 검증은 deprecated attribute 조회 없이 실행한다. |
| schema meta-validation one-liner의 f-string 표현식에 escaped quote를 사용해 SyntaxError가 발생함 | 1 | 이전 installer 검증에서도 나온 패턴이므로 반복하지 않고, tool count를 별도 변수에 저장한 다음 일반 `print` 인자로 출력한다. |
| Phase 3 core service 첫 RED가 `src.termuinator.backends` 모듈 부재 import error로 종료됨 | 1 | typed backend protocol, deterministic fake backend, structured error, single-session service가 아직 없음을 확인했다. 테스트의 lifecycle·no-fallback·hashed-profile 계약을 구현한다. |
| `agbrowse web-ai watch` pretends terminal complete after an individual 30s poll deadline, with empty `answerText` and `provider.poll-timeout` | 1 | provider tab/session는 보존됐고 retry hint가 `poll-or-resume`다. 재전송하지 않고 동일 session ID를 긴 timeout으로 poll/resume해 회수한다. |
| watcher timeout 후 snapshot JSON을 `jq`로 줄이려했으나 CLI 출력이 중간에 끝나 `Unfinished string at EOF` parse error가 남 | 1 | 큰 snapshot을 재파싱하지 않고 persisted session의 전용 `poll`/`sessions resume` 경로로 바로 재연결한다. |
| Pro 리뷰 기반 contract-freeze RED 10건이 6 failures/4 errors로 모두 미충족 경계를 확인함 | 1 | generic output 9개, manifest/MCP generator, action union, error retryability, capability fidelity, artifact/permission lifecycle, observation capability revision을 독립적 구현 단위로 나눈다. |
| `contracts.py` 대형 patch에 동일 파일 `Update File` 연산이 여러 번 포함돼 검증 전 거부됨 | 1 | 파일은 변경되지 않았다. 하나의 Update hunk 그룹으로 합치거나 작은 patch로 분리한다. |
| 새 ActionRequest 분기 요약 스크립트가 판별자를 `const`로 가정해 `KeyError: 'const'`로 종료됨 | 1 | 생성기는 strict 단일값 `enum`을 사용한다. 첫 branch 원형을 확인하고 테스트도 공개 스키마의 실제 `enum` discriminator를 검증하도록 바꾼다. |
| Cycle 3 계약 변경 후 v1 suite가 stale snapshot 2 failures와 새 manifest-schema fixture 누락 1 error를 반환함 | 1 | 동결 테스트가 먼저 GREEN임을 확인했다. 세 생성물을 Draft 2020-12와 instance validation으로 검증한 뒤 생성기 출력에서 기계적으로 다시 만든다. |
| Cycle 3 tool-contract RFC 통합 patch가 hunk 줄 prefix 누락으로 적용 전 거부됨 | 1 | 문서는 불변이다. 계약 섹션별 작은 patch로 분리하고 각 적용 뒤 canonical phrase regression을 실행한다. |
| Typed-model/schema 정렬 RED 3건이 Verification·ActionResult field drift와 CapabilityLimit model 부재를 확인함 | 1 | 공개 schema field 집합을 권위로 삼아 dependency-free dataclass를 최소 수정하고 wire-shape 테스트를 GREEN으로 만든다. |
| Typed runtime-validation RED 6개 테스트가 11개 의도된 failure로 ID, action parameter, capability limit, verification kind와 causal success 검증 부재를 확인함 | 1 | 공개 schema의 pattern/type/enum/bounds와 성공의 causal evidence 규칙을 각 dataclass `__post_init__`에 구현한다. |
| 엄격한 ID validation GREEN 후 기존 v1 fixture 2건이 짧은 `act_1`/`page_1` 값 때문에 1 failure/1 error를 반환함 | 1 | 테스트 의도는 target/scroll 규칙이므로 fixture ID만 공개 schema pattern을 만족하는 값으로 갱신하고 동작 assertion은 유지한다. |
| Page-sensitive precondition RED가 `browser_act` 8개 branch 모두에서 `tab_id` 누락을 8 failures로 확인함 | 1 | ActionRequest model과 공통 schema required/property에 `tab_id`를 추가하고 모든 valid fixture에 명시한다. 다른 5개 page-sensitive 도구는 이미 조건을 만족했다. |
| Backend/profile-schema 격리 RED 2건이 Chromium·Firefox가 같은 `<digest>/profile`을 공유함을 확인함 | 1 | profile path를 `<digest>/profiles/<backend>/v1/profile`로 바꾸고 전체 component의 symlink/0700/root containment 검증을 유지한다. |
| Provisional contract 동기화 patch가 현재 ActionRequest 목록과 context 불일치로 적용 전 거부됨 | 1 | 계획은 불변이다. 해당 범위의 정확한 줄을 다시 읽고 모델·tool table·security checklist를 작은 patch로 나눈다. |
| MCP annotation RED가 durable idempotency 계약과 달리 `browser_act.idempotentHint=false`임을 확인함 | 1 | 동일 key/digest 재호출이 저장 결과를 반환하는 동결 계약에 맞춰 actual MCP projection의 hint를 true로 고정한다. |
| Phase 3 session model RED가 frozen schema의 `SessionStartResult`, `SessionStatus`, `SessionStopResult` dataclass 3종 부재를 확인함 | 1 | core 내부 중복 결과형 대신 계약 package에 exact-field dataclass를 추가하고 service가 이를 직접 반환하게 한다. |
| Service-result 첫 RED가 누락 속성 직접 접근으로 assertion이 아닌 `AttributeError` 4건을 반환함 | 1 | 공개 계약 타입 `isinstance` assertion을 각 접근 앞에 두어 내부 중복 타입 반환을 명확한 failure로 만든 뒤 다시 RED를 확인한다. |
| Service-result 구현 후 GREEN run이 `core/__init__.py`의 삭제된 `SessionStatusResult` re-export로 import error를 반환함 | 1 | core는 `BrowserService`만 소유하고 frozen 결과 타입은 `contracts`에서 re-export하도록 경계를 정리한다. |
| Owner-scope API RED가 `BrowserService` 생성자에 transport-established owner context가 없음을 확인함 | 1 | owner scope를 필수 생성자 입력으로 추가해 tool argument와 분리하고, 다음 RED에서 저장 경로 격리를 검증한다. |
| Owner-profile 행동 RED가 다른 owner 두 개의 동일 project ID가 같은 digest/profile을 공유함을 확인함 | 1 | domain-separated hash에 trusted owner scope와 project ID를 함께 포함하고 원문 owner/project 문자열은 경로에 노출하지 않는다. |
| Runtime config 첫 RED가 `src.termuinator.config` 모듈 부재를 확인함 | 1 | 빈 dependency-free migration boundary를 먼저 추가한 뒤 별도 RED에서 API와 fail-closed 동작을 정의한다. |
| Runtime config API RED가 `RuntimeConfig`와 `load_runtime_config` 부재를 확인함 | 1 | safe static resource field만 가진 frozen dataclass와 loader signature를 추가하고 동작은 다음 RED에서 구현한다. |
| Runtime config default RED가 placeholder `NotImplementedError`를 명시적 assertion failure로 변환해 기본값 부재를 확인함 | 1 | HOME/XDG_DATA_HOME에서 portable data root를 유도하고 frozen resource/retention/chunk 기본값을 반환한다. |
| Runtime config file RED 4건이 override 무시, unknown authority key 허용, 0644 파일 허용, chunk 상한 미검증을 확인함 | 1 | O_NOFOLLOW regular 0600 bounded JSON read, closed key set, absolute data root, public backend/profile version과 정수 범위를 fail-closed 검증한다. |
| Real-backend adapter 첫 RED가 backend package의 `LegacyPilotBackend` export 부재를 확인함 | 1 | inherited `Pilot` lifecycle를 감쌀 typed migration boundary를 추가하고 동작은 주입형 fake를 사용하는 후속 RED로 정의한다. |
| Legacy adapter API RED가 explicit backend와 injectable `pilot_factory` 생성자 부재를 확인함 | 1 | 두 입력만 가진 최소 constructor를 추가해 backend auto/fallback 선택을 구조적으로 금지한다. |
| Legacy adapter lifecycle RED가 typed `start` method 부재를 확인함 | 1 | explicit browser/profile/viewport kwargs로 inherited Pilot 하나만 생성하고 start/stop, cached status, honest capability records를 구현한다. |
| Legacy adapter protocol RED가 lifecycle-only class가 `BrowserBackend`를 만족하지 않고 navigate method도 없음을 확인함 | 1 | 아직 이식하지 않은 protocol method 전부를 구조화 `unsupported_capability`로 구현해 silent success/NotImplemented를 금지한다. |
| Xvfb lifecycle RED가 `_start_xvfb()`의 openbox launch 두 건(`/usr/bin/openbox`, `openbox`)을 재현함 | 1 | 검증·로그·핸들을 보존하는 첫 launch만 남기고 뒤의 중복 block을 제거한다. |
| Chromium resolver RED가 `BrowserPilot`에 runtime binary resolution method가 없음을 확인함 | 1 | default는 Termux `chromium` 우선 후보를 start 시점 PATH에서 찾고, explicit binary는 실패 시 다른 엔진/경로로 fallback하지 않게 한다. |
| Firefox status-cache RED가 `_handle_status()`가 여전히 `pilot.url()` page I/O를 호출함을 확인함 | 1 | daemon lifecycle/navigation이 monotonic cache를 갱신하고 status는 cache/freshness만 반환하도록 바꿔 warm control-plane 경로를 O(1)로 만든다. |
| Firefox text 경로 테스트 탐색 중 code graph `search_code`에 잘못된 `query` 인자를 사용해 `pattern is required` 오류가 발생함 | 1 | 그래프 API의 `pattern` 인자로 좁힌 검색을 사용하고, 이미 확인한 qualified name은 `get_code_snippet`으로 직접 조회한다. |
| Firefox native callback RED가 즉시 준비된 결과에도 sleep 기록 `[0.1, 0.2, 0.5]`를 남겨 첫 poll 전 고정 500ms 대기를 확인함 | 1 | 실행 키 입력 뒤의 무조건 500ms sleep을 제거하고 callback/clipboard를 즉시 검사하며, 결과가 없을 때만 기존 bounded poll interval을 사용한다. |
| Runtime composition RED가 `src.termuinator.runtime` 모듈 부재로 import error를 반환함 | 1 | 검증된 config, trusted owner scope, explicit Chromium/Firefox legacy factories를 하나의 composition 함수로 묶고 service가 config의 default backend/profile schema를 사용하게 한다. |
| Artifact/trace/permission core-boundary RED가 schema-only `ArtifactChunk`와 `TraceRecord` runtime model 부재로 import error를 반환함 | 1 | frozen field 집합의 typed models를 추가하고, session-authorized bounded in-memory artifact/trace harness 및 canonical-origin permission engine을 구현한다. |
| Legacy navigate/observe RED가 service-owned `Observation`을 대체할 `BackendPageSnapshot` export 부재로 import error를 반환함 | 1 | backend-owned raw snapshot type으로 protocol을 정정한 뒤 explicit `goto`와 bounded text/a11y만 이식하고 service가 public identity를 발급하게 한다. |
| Legacy snapshot 구현 후 기존 lifecycle test 1건이 stale `navigate=unsupported` assertion으로 실패함 | 1 | 새 fidelity 계약대로 navigate/observe는 제한을 명시한 `partial`, 아직 미이식한 나머지는 `unsupported`인지 함께 검증하도록 assertion을 갱신한다. |
| Process session-lock RED가 `src.termuinator.core.sessions` 모듈 부재로 import error를 반환함 | 1 | private 0600 `O_NOFOLLOW` lock file과 non-blocking kernel `flock` lease를 구현해 crash 시 자동 해제하고 원문 owner scope를 저장하지 않는다. |
| Service lease integration RED가 `BrowserService.__init__()`의 `session_lock` 인자 부재로 error를 반환함 | 1 | session start 전 lease를 취득하고 start 실패·capability mismatch·stop에서 반드시 해제하며, 성공 세션 동안에는 계속 보유하게 한다. |
| Stable-ref registry RED가 backend-owned `RawInteractiveElement` export 부재로 import error를 반환함 | 1 | raw backend handle/semantics와 public `InteractiveElement.ref`를 분리하고 service registry가 opaque ref 발급·회수·semantic change/epoch rotation 폐기를 담당한다. |
| Observation-engine RED가 `src.termuinator.core.observation` 모듈 부재로 import error를 반환함 | 1 | service-owned session/page/tab identity, sequence, page epoch/mutation revision, origin, viewport fallback과 ref registry 조립을 단일 engine에 구현한다. |
| Service observe RED가 session-start status의 active tab/page/revision이 모두 `None`임을 확인함 | 1 | session 시작 시 ObservationEngine을 생성해 초기 page context를 status에 공개하고, observe는 context 검증 후에만 backend snapshot을 요청한다. |
| Service observe 구현 후 cached-status test 1건이 이전 nullable page context assertion으로 실패함 | 1 | status가 I/O 없이 service-owned page/tab/revision을 반환하는 새 계약을 검증하도록 opaque ID와 revision round-trip assertion으로 갱신한다. |
| Action-executor RED가 private-handle `BackendAction`/raw evidence contract 부재로 import error를 반환함 | 1 | public ref/idempotency/risk는 service에 남기고 backend에는 resolved handle만 전달하며, raw evidence를 service-side causal verifier가 `ActionResult`로 변환한다. |
| Current-revision stale-ref 회귀가 선행 차단에는 성공했지만 예상 `stale_observation` 대신 실제 계약의 `target_not_found`를 반환해 1 failure가 발생함 | 1 | 폐기된 ref는 현재 observation registry에 존재하지 않으므로 `target_not_found`가 더 구체적이다. 오류 assertion만 계약에 맞추고 backend 무호출 assertion은 유지한다. |
| stale-ref 오류 assertion의 작은 patch가 동일 문맥의 앞선 stale-revision assertion을 먼저 변경함 | 1 | 두 테스트 메서드명을 포함한 고유 context로 stale revision은 `stale_observation`, stale ref는 `target_not_found`가 되도록 즉시 교정한다. |
| Durable idempotency RED 7건이 `src.termuinator.core.idempotency` 모듈 부재로 import error를 반환함 | 1 | canonical semantic digest, private atomic journal, strict terminal decoder, reserved/waiting/dispatched/terminal 전이와 conflict/outcome-unknown recovery를 구현한다. |
| Download schema 확인용 `jq '.$defs.Download'`가 `$defs`를 jq 변수 문법으로 해석해 compile error를 반환함 | 1 | 특수 키를 bracket 표기 `.[$name]`가 아닌 `.["$defs"].Download`로 조회한다. 파일은 변경되지 않았다. |
| Journal adversarial RED에서 type-confused download는 fail-closed했지만 `idempotency` 경로가 일반 파일일 때 raw `FileExistsError`가 1 error로 누출됨 | 1 | directory create/lstat의 모든 `OSError`를 stable `internal_error`로 정규화하고 symlink/0700 검사는 그대로 유지한다. |
| One-shot confirmation RED 6건이 schema-only `Challenge` runtime model 부재로 import error를 반환함 | 1 | exact Challenge enums/model과 server-held nonce/proof, 120초 expiry, binding invalidation, approve/deny/atomic consume 엔진을 구현한다. |
| Action risk classifier RED 6건이 `core.action_policy` 모듈 부재로 import error를 반환함 | 1 | per-kind minimum보다 낮추지 않는 explicit ranking, submit/delete/Enter R4 elevation, credential/OTP takeover, destination-aware drag preview를 구현한다. |
| Service-action RED가 테스트에서 비공개 `FakeBackend`를 package root로 import해 collection error를 반환함 | 1 | production export를 불필요하게 넓히지 않고 테스트가 명시적 `backends.fake` migration seam을 import하도록 수정한 뒤 실제 missing API RED를 재실행한다. |
| Service-action 정책 RED 4건이 injectable fake action outcome/error seam 부재로 모두 constructor error를 반환함 | 1 | FakeBackend capability fidelity를 함께 고쳐 configured action만 supported로 광고·기록하고, 이후 BrowserService act/policy/journal integration RED를 계속 진행한다. |
| Fake action seam GREEN 후 service-action RED 4건이 BrowserService의 project-scoped permission/confirmation factory 부재로 이동함 | 1 | safe default factories와 injectable seams, active-session journal/policy authority, ordered `act()` orchestration을 구현한다. |
| Fake capability fidelity RED 1건이 미구현 `navigate`를 여전히 `supported`로 광고함을 확인함 | 1 | fake는 실제 구현된 observe/cached-status와 configured act만 supported로 광고하고 navigate에는 explicit unsupported reason을 부여한다. |
| Durable permission RED 4건이 `core.durable_permissions` 모듈 부재로 import error를 반환함 | 1 | hashed owner/project scope, atomic 0600 policy file, cross-instance locked merge, strict decoder와 memory-only session decisions를 구현한다. |
| 전체 Python 3.11 discovery 151건 중 legacy live-CDP 5개가 base interpreter의 optional `websockets` 부재로 기존 import error를 유지함 | 1 | 신규/계약 146건은 통과했다. 저장소 환경을 변경하지 않고 legacy 5개를 제외한 dependency-free 권위 suite를 명시 실행하며 live-CDP는 device gate로 유지한다. |
| Dependency-free module 목록용 zsh 변수명 `modules`가 shell의 read-only special parameter와 충돌해 테스트 실행 전 종료됨 | 1 | common shell 이름을 재사용하지 않고 task-specific `termuinator_test_modules` 배열로 동일 명시 suite를 실행한다. |
| Durable artifact RED 4건이 `core.durable_artifacts` 모듈 부재로 import error를 반환함 | 1 | session-first authorization, project-scoped 0600 data/metadata, atomic publication, strict metadata/digest verification, expiry·LRU quota·bounded range read를 구현한다. |
| Service screenshot/artifact RED 2건이 backend-owned raw `BackendArtifactPayload` contract 부재로 import error를 반환함 | 1 | backend public Artifact ownership을 raw bytes/MIME로 정정하고 snapshot→service store→Observation URI→chunk read 경로를 연결한다. |
| Screenshot 통합 multi-file patch가 legacy adapter의 실제 `_unsupported()` 호출 signature와 context가 달라 전체 적용 전 거부됨 | 1 | 파일은 불변이다. base contract, fake, legacy, observation, service, runtime을 현재 문맥에 맞춘 작은 patch로 나눠 적용한다. |
| Frozen tool manifest 조회가 추측한 `schemas/tool-manifest.json`을 열어 `FileNotFoundError`로 종료됨 | 1 | 스키마 디렉토리의 실제 파일 목록을 문자열 검색한 뒤 검증된 경로만 사용한다. |
| Standalone screenshot RED 3건이 `BrowserService.screenshot` 메서드 부재로 `AttributeError`를 반환함 | 1 | frozen mode union·page precondition·private handle 해석·Artifact metadata 저장을 단일 service 메서드로 구현한다. |
| Standalone screenshot 구현용 multi-file patch가 base protocol docstring context 불일치로 전체 적용 전 거부됨 | 1 | 변경은 없다. 각 signature와 service 삽입 지점을 짧게 재조회한 뒤 파일별 작은 patch로 적용한다. |
| Compact MCP v1 router RED가 `src.termuinator.mcp_v1` 모듈 부재로 import error를 반환함 | 1 | reviewed 14-tool projection, wire decoder, implemented service dispatch, structured error envelope를 optional MCP dependency 없이 구현한다. |
| MCP 1.29 low-level server RED 2건이 `src.mcp_v1_server` 모듈 부재로 import error를 반환함 | 1 | exact Tool list, SDK input/output validation, stable `isError` envelope, stdio runner를 옵션 MCP 모듈에 구현한다. |
| Legacy raw screenshot RED 7건 중 3건이 screenshot `unsupported` 유지로 2 failure/1 error를 반환함 | 1 | Pilot의 path-less PNG bytes를 viewport/full에 이식하고 observe screenshot을 연결하며, element는 명시적 unsupported로 유지한다. |
| Read-only permission service RED가 schema-only `PermissionsResult` runtime model 부재로 import error를 반환함 | 1 | closed result model과 active-session `list/status` service orchestration을 구현하고 MCP router에는 읽기 작업만 연결한다. |
| `PermissionsResult` 추가 후 RED 3건은 service method 부재 2건과 `SessionStatus.page_revision`이 타입 선언과 달리 raw string인 오류 1건으로 진행됨 | 1 | status runtime은 `PageRevision` 객체를 유지하고 wire 직렬화에서만 string으로 변환하며, permissions method를 추가한다. |
| Typed `page_revision` 교정 후 core service test가 기존 string을 다시 `PageRevision.parse()`하려 하며 `AttributeError` 발생 | 2 | 첫 patch가 동일 test의 첫 호출만 교정해 뒤의 stale-context 호출 1건이 남았다. 해당 method 전체를 재검색해 모든 사용을 typed 값으로 교정한다. |
| Read-only permissions MCP RED 1건이 router의 기존 `unsupported_capability`로 종료됨 | 1 | `browser_permissions` list/status union만 typed service에 전달하고 grant/block/approve/deny는 router에 추가하지 않는다. |
| takeover 테스트 fixture를 찾으며 존재하지 않는 `tests/helpers.py`를 조회해 `sed`가 종료 코드 2를 반환함 | 1 | 공용 helper를 추정하지 않고 실제 `tests/test_service_actions.py` 내부 fixture와 `FakeBackend`를 재사용한다. |
| Local takeover RED 3건이 `BrowserService.local_takeover_start/resume` 부재로 `AttributeError`를 반환함 | 1 | 로컬 전용 required→active 전이와 secret-free fresh observation→epoch rotation→active 재개를 구현한다. resume 실패 시 active takeover 상태를 유지한다. |
| 최근 미재색인 변경 뒤 graph `get_code_snippet(ErrorEnvelope)`가 인접 `PermissionsResult` span을 잘못 반환함 | 1 | 해당 계약은 checkout 원문으로 확인하고, 다음 구조 변경 묶음 이후 graph를 재색인해 drift를 해소한다. |
| Host decision RED 2건이 `BrowserService.local_permission_record/local_confirmation_decide` 부재로 `AttributeError`를 반환함 | 1 | service가 session binding을 강제하는 permission record와 approve/deny only confirmation mutation을 구현한다. |
| Host-control router RED가 `src.termuinator.host_control` 모듈 부재로 import error를 반환함 | 1 | exact version/operation/field union, typed policy decoding, stable shared error envelope를 갖는 dependency-free local router를 구현한다. |
| Host-control type-confusion RED 2건에서 list policy/decision이 hash lookup 전에 검증되지 않아 raw `TypeError`가 발생함 | 1 | 두 union discriminator를 bounded string으로 검증한 뒤 closed mapping/set을 조회해 항상 `invalid_request`로 정규화한다. |
| Unix host-control RED가 `UnixHostControlServer` 부재로 import error를 반환함 | 1 | owner-private AF_UNIX bind, bounded one-request JSON protocol, structured error normalization, inode-safe cleanup을 구현한다. |
| graph `trace_path(build_default_router)`가 최근 추가 파일의 미색인 상태로 `function not found`를 반환함 | 1 | checkout의 exact test/string 검색으로 caller를 확인하고 composition 묶음 뒤 graph를 재색인한다. |
| Shared-authority composition RED가 `CompactRuntime/build_legacy_compact_runtime` 부재로 import error를 반환함 | 1 | 단일 BrowserService를 MCP router·host router·Unix server에 주입하는 trusted composition model을 구현한다. |
| MCP stdio lifecycle RED 2건이 host socket start/close 이벤트 부재로 assertion failure를 반환함 | 1 | `_run_stdio`가 CompactRuntime을 받아 MCP open 전에 host server를 시작하고 `finally`에서 항상 닫도록 전환한다. |
| Host-control CLI RED가 `src.termuinator.host_control_cli` 모듈 부재로 import error를 반환함 | 1 | closed argparse surface, private-socket revalidation, bounded strict response parser, stable JSON output과 console entry point를 구현한다. |
| Confidential takeover read-boundary RED가 paused status에 실제 login URL을 반환해 첫 assertion에서 실패함 | 1 | 두 takeover 상태의 status URL/title을 blank, ready_state를 `takeover`로 redaction하고 모든 remote data-plane method를 공통 state guard로 차단한다. |
| Durable trace RED가 `core.durable_traces` 모듈 부재로 import error를 반환함 | 1 | project-scoped 0700/0600 append store, strict digest decoding, restart list/get, retention/quota, idempotent trace ID와 symlink refusal을 구현한다. |
| Service trace integration RED가 `TraceExportResult` runtime model 부재로 `tests.test_service_actions` import error를 반환함 | 1 | frozen `browser_trace` output schema와 정확히 일치하는 records/export 결과 타입을 먼저 추가한 뒤 service action 기록과 조회를 연결한다. |
| Compact trace transport RED가 `browser_trace`를 기존 `unsupported_capability`로 반환함 | 1 | public 14-tool projection은 유지하고 router 구현 집합과 exact list/get/export argument union에만 trace dispatch를 추가한다. |
| Trace 변경 후 graph `get_code_snippet(_prepare_state_root)`가 갱신 전 줄 번호의 `_status_result` 일부를 잘못 반환함 | 1 | graph 결과를 신뢰하지 않고 checkout의 exact symbol 위치를 확인했으며, trace 통합 묶음이 안정화된 뒤 fast reindex한다. |
| Trace 완료상태 문서 통합 patch가 체크리스트 context 불일치로 적용 전 거부됨 | 1 | 파일은 불변이다. 현재 각 section의 exact 줄을 다시 읽고 Next Step·Phase 4·Phase 5·Safety 항목을 작은 hunk로 나눠 적용한다. |
| 축소한 trace 완료상태 patch도 같은 Safety 줄에서 context 불일치로 거부됨 | 2 | UTF-8 바이트와 줄 번호가 정상임을 확인했다. 동일 결합 patch는 중단하고 각 section을 독립 적용하며 이 줄은 주변 ASCII heading을 포함한 전용 hunk로 처리한다. |
| Wait 설계 중 graph `get_code_snippet(contracts.Download)`이 runtime symbol 부재로 `symbol not found`를 반환함 | 1 | frozen schema에는 Download가 있지만 runtime contract에는 아직 없음을 결함으로 기록하고, download wait는 해당 모델/transport 구현 전 명시적 unsupported branch로 격리한다. |
| Browser wait 첫 RED가 runtime `Download` model 부재로 test-module import error를 반환함 | 1 | frozen Download·five-branch WaitCondition·WaitResult runtime types를 먼저 추가해 wire validation을 고정한 뒤 service polling RED로 진행한다. |
| Wait contract 추가 후 RED가 contract 2건 GREEN, service 4건 `BrowserService.wait` 부재 `AttributeError`로 진행됨 | 1 | backend mapping `wait()`를 호출하지 않는 typed evaluator와 bounded fresh-observation polling을 service에 구현한다. |
| Compact wait transport RED가 `browser_wait`를 기존 `unsupported_capability`로 반환함 | 1 | implemented set에 wait를 추가하고 outer page preconditions 및 five-branch condition의 closed field/type decoder를 연결한다. |
| Wait GREEN 후 transport module의 기존 “unimplemented tool” 회귀가 `browser_wait`를 계속 사용해 expected unsupported 대신 새 `invalid_request`로 1 failure 발생 | 1 | malformed wait는 새 계약대로 invalid가 맞다. 해당 회귀의 미구현 표본만 여전히 unsupported인 `browser_tabs`로 교체한다. |
| Slow-backend deadline RED에서 1ms wait가 50ms `observe()` 완료까지 기다려 wall 60.8ms로 failure | 1 | 남은 deadline을 계산해 `asyncio.wait_for`로 각 backend observation을 제한하고 timeout 시 마지막 observation을 unsatisfied로 반환한다. |
| Pinned MCP 1.29 server suite가 기존 error-mapping fixture의 `browser_wait` 사용으로 expected unsupported 대신 stub method 부재 `internal_error` 1 failure 발생 | 1 | 실제 미구현 `browser_tabs`를 표본으로 바꿔 MCP ToolExecutionError의 structured unsupported mapping 의도를 유지한다. |
| Wait 완료상태·MCP count 결합 문서 patch가 실제 checklist 문구와 일치하지 않는다고 적용 전 거부됨 | 1 | 파일은 불변이다. exact `rg` 결과를 기준으로 Next Step, wait, tool-count 항목과 findings/progress를 독립 patch로 적용한다. |
| Tab lifecycle 통합 graph discovery 출력이 한도를 초과해 결과가 잘림 | 1 | 동일한 광역 조회를 반복하지 않고 `TABS_RESULT_SCHEMA`, backend method, legacy handler를 각각 좁은 조회로 분리한다. |
| Tab RED 실행에서 macOS checkout에 `python` 명령이 없어 종료 코드 127을 반환함 | 1 | 저장소가 사용해 온 host interpreter인 `python3`로 동일 test module을 실행한다. |
| 기본 `python3`가 Apple Python 3.9여서 PEP 604 runtime union 정의에서 import `TypeError`가 발생함 | 1 | 기존 검증 기록의 modern interpreter/venv 경로를 확인하고 Python 3.12+ 실행기로 RED를 재실행한다. |
| interpreter 탐색에 사용한 `command -v -a python3`가 zsh builtin 문법 오류로 실패함 | 1 | zsh의 `whence -a python3`와 명시적 후보 `--version`으로 Python 3.14.7 경로를 확인했다. |
| Tab lifecycle RED가 runtime `Tab`/`TabsResult` model 부재로 test-module import error를 반환함 | 1 | frozen schema와 정확히 일치하는 public result model 및 typed private backend boundary를 먼저 구현한다. |
| Compact tab transport RED가 `browser_tabs`를 기존 `unsupported_capability`로 반환함 | 1 | reviewed 14-tool surface를 유지한 채 exact list/open/switch/close decoder와 typed service dispatch만 연결한다. |
| Popup natural-language graph query가 36개 광역 결과와 `has_more=true`를 반환해 관련 symbol을 특정하지 못함 | 1 | popup 단어를 반복 조회하지 않고 frozen dialog schema와 `BackendActionEvidence` exact symbol부터 좁혀 데이터 경계를 추적한다. |
| Dialog/handoff RED가 typed private `BackendDialogSnapshot` 부재로 test-module import error를 반환함 | 1 | frozen public `Dialog`, bounded private dialog snapshot, stable lifecycle registry를 구현한 뒤 service takeover 신호를 연결한다. |
| Popup inventory RED가 deterministic fake의 `inject_popup` hook 부재로 `AttributeError`를 반환함 | 1 | protocol을 넓히지 않고 tab-capable fake 전용 popup event hook을 추가해 authoritative list reconciliation을 검증한다. |
| Handoff 통합 회귀에서 기존 takeover tests 2건이 “민감 필드 observe 후에도 ACTIVE”라는 옛 가정 때문에 failure/error를 반환함 | 1 | 새 fail-closed 요구에 맞춰 observe 즉시 `USER_TAKEOVER_REQUIRED`를 기대하고, 사전 artifact는 최초 observation 전 control context에서 생성하도록 fixture를 교정한다. |
| Navigation RED 4건이 fake backend의 `navigation_results` configuration 부재로 동일 `TypeError`를 반환함 | 1 | typed operation/URL→snapshot map과 call log를 fake에 추가한 뒤 service와 transport RED를 순서대로 진행한다. |
| Fake navigation boundary 추가 후 RED 4건이 `BrowserService.navigate` 부재 `AttributeError`로 진행됨 | 1 | exact union, page precondition, pre-dispatch origin policy, post-redirect quarantine, identity rotation을 service에 구현한다. |
| Compact navigation transport RED가 `browser_navigate`를 기존 `unsupported_capability`로 반환함 | 1 | 14-tool manifest는 유지하고 exact goto/history union decoder와 typed service dispatch를 연결한다. |
| Local fixture RED가 `tests.fixtures.server` 모듈 부재로 import error를 반환함 | 1 | loopback-only bounded HTTP server, deterministic route bodies, 25+ scenario manifest를 dependency-free test fixture로 구현한다. |
| Fixture GREEN 첫 실행이 download hash 1건 불일치했고 loopback `HTTPServer.server_bind()`의 reverse-DNS 대기로 37.2초 소요됨 | 1 | 실제 newline payload hash로 assertion을 교정하고 `TCPServer.server_bind()` 기반 loopback subclass로 DNS lookup을 제거하며 HTTPError responses를 명시적으로 닫는다. |
| Download 설계 중 graph `get_code_snippet(contracts.Download, include_neighbors=true)` 출력이 context 한도를 초과해 절단됨 | 1 | 광역 인접 조회를 반복하지 않고 checkout의 `Download` exact 줄과 개별 backend/service symbol만 좁게 확인한다. |
| Download lifecycle 첫 RED가 private `BackendDownloadSnapshot` export 부재로 test-module import error를 반환함 | 1 | frozen public result와 별도의 typed private snapshot/result 경계를 먼저 추가한 뒤 service 및 transport RED로 진행한다. |
| Download contract/private boundary 추가 후 RED가 contract 3건 GREEN, service 3건은 fake `download_sequences` 구성 부재 `TypeError`로 진행됨 | 1 | 결정론적 private lifecycle sequence와 call log를 fake에 추가한 뒤 서비스 부재 RED를 분리해 확인한다. |
| Fake download lifecycle 추가 후 RED가 contract/fake 3건 GREEN, service 3건은 `BrowserService.downloads` 부재 `AttributeError`로 진행됨 | 1 | 세션 소유 identity registry, typed backend call normalization, 완료 bytes 단일 artifact publication을 서비스에 구현한다. |
| Download service GREEN 뒤 transport/wait RED 2건이 각각 기존 `unsupported_capability` gate와 download-wait 격리 branch에서 종료됨 | 1 | exact list/wait router를 연결하고 wait 내부에서 public ID를 private handle로 해석해 남은 deadline으로 typed backend lifecycle을 대기한다. |
| Terminal download immutability RED에서 같은 private ID의 두 번째 completed snapshot이 다른 bytes인데도 기존 artifact URI를 재사용하며 성공함 | 1 | 공개 artifact URI의 SHA-256과 새 payload digest 및 terminal metadata를 비교해 불일치를 stable `internal_error`로 차단한다. |
| Pinned MCP 1.29 회귀에서 generic unsupported 표본을 `browser_devtools`로 바꾼 server fixture가 input schema 단계에서 거부되어 JSON envelope decode error 1건 발생 | 1 | frozen devtools input의 exact required fields를 확인해 유효한 요청으로 교정하고 router의 structured unsupported mapping을 다시 검증한다. |
| Developer Mode 첫 RED가 private `BackendConsoleEntry` export 부재로 test-module import error를 반환함 | 1 | frozen five-branch public 결과와 별도의 private backend query/entry/result 모델을 먼저 추가한 뒤 feature/grant/service RED로 진행한다. |
| Developer public/private contracts 추가 후 RED가 wire contract 1건 GREEN, service 3건은 fake `devtools_results` 구성 부재 `TypeError`로 진행됨 | 1 | closed typed query/result map과 call log를 fake에 추가하고 capability negotiation을 실제 구성 상태와 일치시킨다. |
| Fake Developer boundary 추가 후 RED가 contract/fake 1건 GREEN, service 3건은 trusted `developer_mode_available` constructor option 부재 `TypeError`로 진행됨 | 1 | default-false availability와 session/origin grant registry를 BrowserService에 추가하고 query validation/identity normalization을 구현한다. |
| Developer service 첫 GREEN run이 disabled fake의 unresolved viewport error 1건과 unknown ref의 올바른 `target_not_found`를 누락한 test expectation failure 1건을 반환함 | 1 | 공용 start helper에 명시 viewport를 주고 invalid-ref 허용 오류 집합에 `target_not_found`를 추가한다. 서비스 fail-closed 동작은 유지한다. |
| Developer host/MCP RED 2건이 각각 closed host union의 unsupported operation과 compact router의 기존 unsupported gate에서 종료됨 | 1 | `developer_mode_set`은 local host-control에만 추가하고, exact frozen page/query union은 compact read router에 연결한다. |
| Developer routing GREEN run에서 generic “unimplemented tool” transport fixture가 이제 구현된 `browser_devtools`의 malformed request를 보내 expected unsupported 대신 `invalid_request` 1 failure를 반환함 | 1 | 14개 compact 도구가 모두 routed된 상태에 맞춰 fixture를 unknown-tool invalid와 injected service-level unsupported mapping으로 분리한다. |
| Host-control CLI Developer RED가 닫힌 기존 command choices에서 `developer-mode`를 거부해 `SystemExit(2)`로 종료됨 | 1 | 명시적 enable/disable choices만 가진 subcommand와 exact `developer_mode_set` JSON mapping을 추가한다. |
| Trusted startup RED 2건이 runtime builder의 developer option 부재와 MCP `main(argv)` 부재 `TypeError`로 각각 종료됨 | 1 | availability bool을 composition chain에 명시 전달하고 `tbp-mcp-v1 --developer-mode`만 이를 true로 설정하도록 한다. config/env authority key는 계속 거부한다. |
| 전체 Python 3.12 discovery 245건 중 inherited live-CDP 5개가 base interpreter의 optional `websockets` 부재로 import error를 유지함 | 2 | 신규/계약 경로 235건 통과·optional 5건 skip을 확인했다. 저장소 환경은 변경하지 않고 5개 장치 스크립트를 제외한 권위 suite와 pinned MCP suite를 별도 실행한다. |
| Developer redaction RED에서 console bearer/password와 network URL userinfo/query/fragment가 public result에 원문 그대로 남아 failure | 1 | 공통 bounded redaction helper를 추가해 console credential patterns와 URL authority/query/fragment를 결과 정규화 전에 제거한다. |
| Compact packaging RED 2건이 `tbp-mcp-v1` console script와 guarded `main_v1` 부재를 각각 확인함 | 1 | legacy `tbp-mcp`를 보존하면서 compact v1 별도 entrypoint를 추가하고 동일 optional-MCP 오류 경계를 재사용한다. |
| Compact entrypoint 구현 후 packaging 15건 중 missing-MCP guard subprocess가 예상 rc 2 대신 rc 1을 반환함 | 1 | subprocess stderr를 확인해 lazy import guard가 아닌 test import-hook 범위 문제인지 식별하고, 실제 missing dependency를 traceback 없이 정규화한다. |
| Shared-view 첫 RED에서 confirmation pending-list와 `src.termuinator.shared_view` 모듈이 없어 각각 `AttributeError`와 import error를 반환함 | 1 | bounded value-only pending 목록을 confirmation authority에 추가하고, service-provider protocol을 사용하는 loopback-only read server를 새 모듈로 구현한다. |
| Shared-view RED 기록용 결합 patch가 `progress.md`의 실제 제목과 달라 전체 적용 전 거부됨 | 1 | 파일은 불변이다. 실제 `# Progress: Termu-inator Modernization` 제목을 기준으로 task-plan 오류와 progress 기록을 작은 독립 patch로 나눈다. |
| Shared-view 첫 GREEN 실행이 HTML bytes literal의 비 ASCII ellipsis 때문에 import-time `SyntaxError`로 종료됨 | 1 | 정적 HTML은 Unicode 문자열로 선언한 뒤 UTF-8 bytes로 명시 인코딩하고 같은 targeted suite를 재실행한다. |
| Shared-view 14-test GREEN 실행이 JavaScript bytes literal의 `\\u` escape에 대한 `SyntaxWarning`을 출력함 | 1 | JS asset을 raw bytes literal로 바꿔 JavaScript Unicode escape를 Python이 해석하지 않게 하고 warning-as-error로 재검증한다. |
| Shared-view runtime composition RED 2건이 `CompactRuntime.shared_view_server`와 `shared_view_enabled` builder option 부재로 실패함 | 1 | default-disabled optional server를 single service authority에 구성하고 MCP stdio lifecycle 및 explicit CLI flag에 연결한다. |
| Pinned MCP 1.29 shared-view startup RED 2건이 새 flag 전달 부재와 stdio lifecycle의 view start/close 부재로 실패함 | 1 | default loopback port를 명시 전달하고 host-control 이후 시작, stdio 종료 전 닫기, URL은 stderr로만 안내하도록 구현한다. |
| Shared-view URL/title redaction RED 2건에서 service state와 HTTP JSON이 credential/query/fragment 및 token assignment를 그대로 노출함 | 1 | cached service projection과 HTTP serialization 양쪽에 기존 deterministic URL/text redaction을 적용해 provider 변경에도 fail-safe하게 한다. |
| Shared-view pending-permission RED가 `PERMISSION_REQUIRED` 후에도 empty collection을 반환함 | 1 | ASK origin별 stable value-only permission challenge를 active session에 보관하고 local allow/block 결정이 같은 origin prompt를 제거하게 한다. |
| Pending-permission 결합 구현 patch가 `local_permission_record`의 실제 들여쓰기 문맥과 달라 전체 적용 전 거부됨 | 1 | 파일은 불변이다. imports/session state/startup, snapshot/action/local decision, navigation helper를 현재 exact 문맥의 작은 hunk로 나눈다. |
| Shared-view summary minimization RED가 pending challenge의 opaque ID를 HTTP JSON에 포함함 | 1 | dashboard projection을 kind/state/redacted preview/expiry만으로 축소해 approval 식별자조차 읽기 전용 화면에 불필요하게 노출하지 않는다. |
| Shared-view 문서·계획 결합 patch가 Termux 가이드의 실제 줄 결합과 달라 전체 적용 전 거부됨 | 1 | 파일은 불변이다. task-plan, README, 설치 가이드, architecture, security를 각각 exact heading 기준의 독립 patch로 적용한다. |
| DOM replacement fixture RED 2건이 `/stale-replacement` 404를 반환했고 실패 응답 socket ResourceWarning이 뒤따름 | 1 | deterministic same-semantics node replacement route와 manifest entry를 추가한다. 성공 경로로 전환되면 HTTPError socket 경고도 제거되는지 warning-as-error로 확인한다. |
| Legacy stable-observe/action RED 3건이 empty interactive inventory, resulting `IndexError`, and existing act unsupported gate로 실패함 | 1 | bounded DOM probe normalization, private-handle state revalidation, click/type dispatch, typed evidence와 capability limits를 adapter에 구현한다. |
| Legacy observe/action 첫 구현 run이 test marker spelling mismatch와 missing base probe로 4 errors, stale capability assertion 1 failure, 그에 따른 disconnected error mapping 1 failure를 반환함 | 1 | fixture marker를 실제 `TERMUINATOR_*_V1` sentinel과 일치시키고 base pilot에 빈 structured probe를 추가하며 capability expectation을 새 partial 계약에 맞춘다. |
| Legacy Developer adapter RED가 five-query typed fixture까지 도달한 뒤 기존 `unsupported_capability` gate로 종료됨 | 1 | caller-script 입력이 없는 closed console/network/DOM/style/performance probe와 strict normalizer를 추가하고 capability를 제한 명시한 partial로 갱신한다. |
| Legacy Developer 첫 GREEN run이 generated probe marker를 subclass test fixture가 식별하지 못해 `backend_crashed` 1 error로 종료됨 | 1 | 생성 sentinel은 정상임을 확인했다. Structured fixture의 unknown probe를 base fixture로 위임해 five-query 응답을 재사용한다. |
| Legacy remaining-actions RED가 첫 key 요청에서 기존 click/type-only `unsupported_capability` gate로 종료됨 | 1 | public Pilot key/scroll/hover bridge, fixed select/check probes, page/target revalidation과 kind-specific evidence를 추가하되 drag는 unsupported로 유지한다. |
| Remaining-actions 첫 GREEN run에서 test fixture의 `scroll` tuple field가 새 async `scroll()` method를 shadow해 `backend_crashed` 1 error를 반환함 | 1 | fixture state field를 `scroll_position`으로 이름 변경해 실제 Pilot method shape와 일치시킨다. |
| Legacy drag RED가 seven-action allowlist 밖의 기존 structured `unsupported_capability`로 종료됨 | 1 | shared Chromium/Firefox mouse dispatch에 bounded source→destination drag primitive를 추가하고 양쪽 private handle을 즉시 재검증한 뒤 typed movement/DOM evidence를 반환한다. |
| Compact host-profile RED가 missing `src.termuinator.tool_profiles` import error로 종료됨 | 1 | frozen 14-tool manifest의 strict subset인 observer와 exact interactive profile을 정의하고 MCP list/call 양쪽에서 명시 CLI profile을 강제한다. |
| Hermes/Codex integration RED가 four profile examples와 `docs/integrations.md` 부재로 expected `FileNotFoundError` 5건을 반환함 | 1 | official host field names로 observer/interactive examples를 작성하고 Tailscale SSH stdio, split-tunnel gate, bounded artifact reconstruction을 단일 guide에 고정한다. |
| Integration example 첫 GREEN run이 absolute remote executable을 exact list item `tbp-mcp-v1`로 잘못 비교한 test assertion 2건으로 실패함 | 1 | executable item의 basename/suffix를 검사하도록 assertion을 교정하고 TOML/profile 검증은 그대로 유지한다. |
| 273-test 전체 회귀에서 RFC contract 1건이 `Cache-Control: no-store` 고정 문구를 찾지 못함 | 1 | 보안 문서의 Markdown 줄바꿈으로 헤더 문구가 분리된 문서-only regression이므로 canonical phrase를 한 줄로 정규화한 뒤 전체 스위트를 재실행한다. |
| Prompt-injection fixture 첫 RED가 `/prompt-injection` 404로 종료됨 | 1 | 스크립트 없는 inert page-data fixture를 추가하고, 페이지 문구가 permission·Developer·confirmation authority를 변경하지 못하는 service regression으로 이어간다. |
| Lifecycle documentation RED가 compact entrypoint 검증 누락 1 failure와 `docs/troubleshooting.md` 부재 1 error를 반환함 | 1 | installer가 legacy/compact 진입점을 둘 다 검증·안내하게 하고, 비파괴적 업데이트·롤백·제거·project-data reset과 주요 진단을 별도 문서로 고정한다. |
| Lifecycle 문서 첫 GREEN run 17건 중 1건이 heading 대소문자 차이로 canonical `Update without overwriting` 문구를 찾지 못함 | 1 | 문서 heading을 계약 문구와 동일하게 정규화하고 전체 packaging 계약을 재실행한다. |
| Design-doc current/target distinction RED가 architecture의 `Normative target` 표시 부재에서 첫 failure로 종료됨 | 1 | architecture/security/migration/backend-capability 문서에 현재 alpha 상태와 규범적 목표, 특히 redirect/DNS·legacy MCP·real lifecycle gap을 명시하여 미구현 기능을 현재 보장으로 읽지 못하게 한다. |
| Design-doc 첫 GREEN run이 줄바꿈으로 나뉘 `does not yet intercept redirects`와 이전 RFC 고정 문구 `before following every redirect` 누락으로 2 failures를 반환함 | 1 | 전자는 current gap으로 한 줄에, 후자는 규범적 release requirement로 명시해 현재/목표 구분과 contract 모두를 보존한다. |
| Installed-wheel idle probe 후 default data-root 존재 확인용 `ls` 명령이 모든 대상 부재로 rc 1을 반환함 | 1 | 출력은 probe가 `~/.local/share/termuinator` 또는 stale control socket을 남기지 않았음을 확인한 긍정적 진단 증거로 기록하고 파일을 변경하지 않는다. |
| Legacy 민감-field 회귀 첫 실행에서 현재 셸 PATH에 `python3.12`가 없어 rc 127 `command not found`로 종료됨 | 1 | 저장소에서 사용한 명시적 Python 3.11 경로를 확인해 같은 focused test를 재실행하며, 소스 실패로 오인하지 않는다. |
| Legacy 민감-field 회귀 재실행에서 존재하지 않는 test class `LegacyBackendActionTests`를 지정해 loader `AttributeError`로 종료됨 | 1 | 실제 소속인 `LegacyBackendLifecycleTests`의 qualified test name으로 교정해 재실행한다. |
| 279-test 최종 discovery를 pinned MCP venv가 아닌 base Python 3.11로 실행해 inherited live-CDP 모듈 5개가 optional `websockets` 부재 import error를 재현함 | 1 | 새 기능 회귀가 아니라 기존 환경 분리 게이트다. 보존된 MCP 1.29 isolated venv를 찾아 같은 전체 discovery를 재실행하고, base authority는 5개 장치 스크립트를 제외해 판정한다. |
| Isolated MCP venv에서 무필터 discovery를 실행하자 로컬 Chrome의 기존 `127.0.0.1:9222` CDP에 inherited 수동 스크립트 5개가 연결되어 non-gating 외부 브라우저 검사를 시작함 | 1 | 해당 프로세스는 종료 요청 직전에 자체 종료했다(`kill`: no such process). Chrome은 변경·종료하지 않고 생성물 여부를 감사하며, 최종 authority 명령은 다섯 수동 파일을 명시 제외한다. |
| 최종 결합 정적 검사에서 wheel 격리 venv에 선택적 PyYAML이 없어 Hermes YAML safe-load가 import 단계 `ModuleNotFoundError`로 종료됨 | 1 | 앞선 `git diff --check`, `bash -n`, warning-as-error compileall은 통과했다. YAML 검사는 PyYAML이 있는 기존 호스트 인터프리터로 분리 재실행한다. |
| Mac에서 S22U Tailscale ping은 371ms로 성공했지만 문서화된 Termux SSH port 8022 probe가 rc 1을 반환함 | 1 | 장치는 tailnet에서 online이나 sshd가 현재 수신 중이지 않다. SSH stdio/artifact/device gate는 Termux에서 sshd를 시작하고 key/host-key trust를 준비한 뒤 재개한다. |
| Manual live-CDP discovery-boundary RED가 다섯 스크립트 모두의 top-level `src.*` import를 검출해 5 subtest failures를 반환함 | 1 | optional browser imports를 각 `main()` 내부로 지연하고 네 개 무조건 `asyncio.run(main())` 호출을 exact `__main__` guard 아래로 옮긴다. |
| 2026-08-25 S22U Hermes RC smoke에서 Firefox `browser_observe`가 `backend_crashed`, Chromium session start가 multi/single-process 모두 실패함 | 1 | benchmark를 실행하지 않은 PARTIAL 판정을 보존했다. Firefox typed timeout/state reset/one retry와 Chromium owned display·ephemeral CDP·readiness retry·private bounded stderr 진단을 TDD로 구현하고 실제 장치 재검증은 open gate로 둔다. |
| 현 RC 감사의 첫 code graph 조회에 짧은 project 이름 `Termu-inator`를 사용해 `project not found`가 반환됨 | 1 | graph가 제시한 canonical project `Users-chiriri722-Documents-GitHub-Termu-inator`로 즉시 교정하고 이후 code discovery에 사용했다. |
| Termux X display 경로 RED가 `/tmp`만 검사해 `$PREFIX/tmp/.X11-unix/X99` 점유를 놓침 | 1 | `/tmp`와 Python의 실제 temporary root를 중복 없이 모두 검사하고, 기존 X11 lock/socket은 삭제하지 않은 채 다음 display lease로 진행한다. |
| graph impact trace에 class-qualified short name을 넘겨 세 함수가 `function not found`로 반환됨 | 1 | 최신 fast index에서 `search_graph`로 exact fully-qualified name을 찾은 뒤 동일 세 경로의 inbound production/test caller trace를 완료했다. |
| Firefox 기존-DevTools RED가 검증 가능한 창이 이미 열려 있어도 `_sync_console_state()`가 먼저 `Ctrl+Shift+K`를 눌러 닫을 수 있음을 재현함 | 1 | visible DevTools를 exact sentinel로 먼저 검증하고, 창을 찾고 focus한 경우에만 probe를 실행한다. 필요할 때만 최대 두 번 toggle하며 page/address bar에는 probe를 실행하지 않는다. |
| compact tool schema 조회에서 존재하지 않는 `contract_manifest` 모듈과 manifest top-level list 형상을 차례로 가정해 import/type error가 발생함 | 2 | code graph에서 실제 `schema.build_tool_manifest` 정의를 찾고 `manifest["tools"]`의 14개 항목 중 장치 smoke 도구 8개의 exact schema를 확인했다. |
| final graph/reachability 기록을 progress와 task-plan에 한 patch로 섞어 적용해 context mismatch로 거부됨 | 1 | 파일은 불변이었다. progress와 task-plan patch를 분리해 각각의 정확한 현재 문맥에 적용했다. |
| 장치 검증 계약을 확인하려고 transport test/core schema와 자연어 graph 검색을 넓게 출력해 응답이 context 한도를 넘어 절단됨 | 2 | 파일은 불변이었다. 검색 결과에서 확인된 exact qualified name만 단건 조회하고, checkout 원문도 좁은 줄 범위로 나누어 확인한다. |
| JSON Schema의 `$defs`를 jq dot identifier(`.$defs`)로 조회해 16개 compile error가 발생함 | 1 | 파일은 불변이었다. `$`가 포함된 키는 `.\"$defs\"` 또는 `.[$key]` 형태의 명시적 bracket lookup으로 다시 읽는다. |
| MCP SDK probe가 존재하지 않는 `mcp.__version__` 속성을 읽어 `AttributeError`로 종료됨 | 1 | 파일은 불변이었다. SDK 버전은 `importlib.metadata.version(\"mcp\")`로 확인하고 public client API만 사용한다. |
| final verifier 첫 backend-flow GREEN에서 SessionStatus의 `active_page_id`/`active_tab_id`를 Observation의 `page_id`/`tab_id`처럼 읽어 1 error와 1 failure가 발생함 | 1 | status와 observation의 frozen wire 이름을 별도 context decoder로 분리하고 같은 흐름·cleanup 테스트를 재실행한다. |
| verifier fail-closed CLI 산출물의 SHA 파일을 저장소 cwd에서 검사해 basename `final-verify-manifest.json`을 찾지 못함 | 1 | 산출물과 권한은 정상이었다. SHA 파일의 의도대로 report directory를 cwd로 삼아 재검사하고 문서에도 같은 명령을 사용한다. |
| MCP server identity 조건을 stdio PASS 식에 추가하면서 다음 기존 조건 앞의 `and`를 누락해 `py_compile` SyntaxError가 발생함 | 1 | 실행 전 정적 검사에서 발견됐다. 누락 연산자만 보완하고 focused verifier suite와 warning-as-error compile을 다시 수행한다. |
| installed-environment probe를 checkout cwd에서 실행하자 `importlib.metadata.distribution()`이 venv wheel보다 repository egg-info를 먼저 골라 `direct_url.json` 부재로 오판함 | 1 | 명시적 venv purelib/platlib 경로에서 distribution을 유일하게 선택하는 RED를 추가하고, checkout metadata가 installed-wheel provenance를 가리지 못하게 한다. |
| explicit-runtime-distribution GREEN의 임시 metadata fixture에서 version이 `None`으로 파싱됨 | 2 | 첫 교정으로 RFC822 빈 줄을 보완했지만 assertion 전에 TemporaryDirectory가 정리되어 lazy metadata가 사라진 것이 실제 원인이었다. 검증을 fixture 생존 범위 안으로 이동한다. |
| `uv venv`로 만든 local fresh-wheel 환경에서 `python -m pip check`가 pip module 미시드로 실패함 | 1 | 이것은 `python -m venv`를 사용하는 Termux 설치 계약과 다른 local harness 특성이다. local 검증은 `uv pip check --python`으로 수행하고, 장치 verifier는 설치 가이드의 venv 내 pip check를 계속 요구한다. |
| fresh-wheel same-data-root probe one-liner가 세미콜론 뒤에 `async def` compound statement를 선언해 실행 전 SyntaxError가 발생함 | 1 | 제품과 산출물은 불변이었다. 별도 coroutine 선언 없이 `_run_mcp_profile()`을 두 번 `asyncio.run()`해 동일 env/data-root 순서를 검증한다. |
| Termux 설치 문서에 RC gate를 삽입한 첫 patch가 실제 줄바꿈과 다른 context라 적용 전 거부됨 | 1 | 문서는 불변이었다. Browser Smoke 말미와 benchmark heading의 정확한 현재 줄을 다시 읽고 작은 문맥으로 재적용한다. |
| BrowserPilot start-cleanup 첫 RED가 로컬에 없는 explicit Chromium 경로 검증에서 먼저 실패함 | 1 | binary resolver를 주입해 실패 지점을 의도한 `_start_chromium`으로 좁혔고, 두 번째 RED에서 `stop()` 미호출을 직접 확인했다. |
| BrowserPilot start-cleanup RED가 Chromium 실패 뒤 owned Xvfb/lease 정리를 상위 caller에만 의존함을 확인함 | 1 | `BrowserPilot.start()`가 예외·취소 시 자체 `stop()`을 시도하고 cleanup 오류는 원래 시작 오류를 가리지 않도록 제한 로그만 남긴다. |
| display claim final-probe RED가 동시 교체된 lease를 무조건 unlink함을 재현함 | 1 | 생성 직후 PID/inode ownership을 먼저 기록하고 기존 identity-safe release 경로를 사용해 교체된 lease를 보존한다. |
| `b5362f9` S22U Chromium full observe가 실제 `a11y_tree()` 요약 문자열을 structured accessibility로 거부함 | 1 | legacy summary wire shape를 보존하고 별도 bounded structured node 경로와 실제 반환형 RED를 추가한 뒤 adapter가 그 경로만 사용하게 한다. |
| `b5362f9` S22U Firefox full observe가 underlying cause를 숨긴 generic `backend_crashed`로 다시 종료됨 | 1 | scalar, ready-state, small JSON, full DOM script, normalization을 단계별로 분리하는 private secret-free diagnostic으로 최초 실패 단계를 확정하기 전에는 timeout 확대나 fallback을 적용하지 않는다. |
| Chromium accessibility 첫 RED 실행이 macOS system `python3` 3.9의 PEP 604 union import `TypeError`에서 중단됨 | 1 | 제품 동작 실패로 계산하지 않고, 저장소가 지원·검증하는 명시적 Python 3.11+ 인터프리터를 찾아 같은 focused test를 재실행한다. |
| Pilot structured-a11y RED patch가 실제 첫 lifecycle test 이름과 맞지 않는 context로 거부됨 | 1 | 파일은 불변이었다. class 경계를 다시 확인하고 `LegacyBackendLifecycleTests` 선언 직후의 정확한 현재 문맥에 작은 patch로 재적용한다. |
| Firefox 원본 DOM probe는 syntax-valid였지만 `_safe_join_lines()` 결과가 `shadow_path:shadowPath; });`를 생성해 Node syntax check에서 `Unexpected token ';'`를 반환함 | 1 | eval wrapper가 JSON-escaped 원문을 byte-for-byte 보존하는 RED를 추가하고 destructive line join helper를 제거한다. raw JS error는 secret-free typed cause로 바꾼다. |
| 최종 wheel build에서 `python3.11 -m build`가 저장소의 ignored `build/` namespace에 가려져 `No module named build.__main__`으로 종료됨 | 1 | 저장소 산출물을 삭제하거나 호스트 환경을 변경하지 않고, 기존 `uv build --wheel`로 동일 PEP 517 wheel을 별도 임시 dist에 생성했다. |
| 첫 fresh-wheel 연속 stdio probe에서 observer를 `SIGTERM`으로 종료한 뒤 `control.sock`이 남아 interactive가 rc 1/stderr 2,180 bytes로 조기 종료함 | 1 | 실제 subprocess RED를 추가하고 SIGTERM/SIGINT를 async shutdown으로 전환해 `finally` cleanup을 보장했다. 동일 data-root에서 observer와 interactive가 연속으로 rc 0, zero stdout/stderr, socket 제거를 통과한다. |
| 최종 findings/progress 결합 patch가 두 문서의 서로 다른 section 표기와 일치하지 않아 적용 전 거부됨 | 1 | 두 파일 모두 불변임을 확인하고 각 EOF의 정확한 현재 heading/context를 읽은 뒤 독립 hunk로 재적용했다. |
| progress 말미를 한 번에 읽는 진단 출력이 현재 응답 context 한도를 넘어 절단됨 | 1 | 파일은 불변이었다. `wc -l`로 범위를 확인하고 마지막 30여 줄만 좁게 다시 읽어 이어서 기록한다. |
| platform-report RED가 존재하지 않는 `runtime_platform_summary` import error로 종료됨 | 1 | 예상한 RED다. 커널 버전을 Android 릴리스로 오표기하지 않는 작은 순수 helper를 구현하고 installed-environment 보고서에서 사용한다. |
| 최종 인터프리터 확인을 `&&`로 묶어 현재 PATH에 없는 `python3.12`에서 rc 1로 조기 종료함 | 1 | 제품과 환경은 불변이다. 기존 uv Python 경로를 `uv python find 3.12`로 개별 조회하고 각 authority run을 독립 실행한다. |
| final-verifier HOME 격리 RED가 예상대로 `paths["home"]` KeyError로 실패함 | 1 | child 환경이 XDG/TMP만 격리하고 inherited `$HOME/.tbp` 쓰기를 허용했다. 전용 mode 0700 HOME을 같은 output namespace에 만들고 자식에게만 주입한다. |
| VirGL ownership RED가 기존 선행 `pkill -f virgl_test_server_android`를 실행해 fake process를 종료 상태로 만들고 `started=False`로 실패함 | 1 | 예상한 안전성 RED다. 무소유 프로세스 종료 단계를 제거하고 이 manager가 직접 만든 단일 subprocess만 보관·종료한다. 시작 실패는 기존 SwiftShader fallback으로 처리한다. |
| final-verifier helper-survivor RED가 VirGL/xclip/xdotool을 process filter에서 찾지 못해 1 failure로 종료됨 | 1 | 브라우저 본체·Xvfb뿐 아니라 optional GPU와 Firefox 입력 helper도 baseline 대비 새 생존 프로세스가 있으면 benchmark를 닫도록 filter를 확장한다. |
| optional VirGL launch-failure RED가 `create_subprocess_exec`의 `OSError`를 그대로 전파해 Chromium 전체 시작을 중단함 | 1 | 설치되어 보이지만 실행할 수 없는 optional accelerator는 secret-free warning 후 `False`를 반환해 기존 SwiftShader fallback을 사용하고 소유 process를 남기지 않는다. |
| final-verifier deterministic-env RED가 inherited `TBP_SINGLE_PROCESS=1`을 그대로 보존해 1 failure로 종료됨 | 1 | 이전 장치 진단용 override가 RC gate를 바꾸지 못하도록 `PYTHONHOME/PYTHONPATH/TERMUINATOR_CONFIG`와 함께 자식 환경에서 제거한다. |
| README ownership-safety RED가 legacy troubleshooting의 broad `pkill -f Xvfb/firefox` 문구를 찾아 1 failure로 종료됨 | 1 | 예상한 문서 RED다. 임의 프로세스 종료·socket 삭제를 지시하지 않고 전용 troubleshooting의 identity 확인과 graceful stop 절차로 연결한다. |
| README 전체를 포함한 `assertNotIn` failure 표현이 tool output 한도를 넘어 절단됨 | 1 | 소스 파일은 불변이었다. 실패 원문은 불필요하게 크므로 후속 실행은 안전 문구 수정 후 focused test의 요약만 확인한다. |
| VirGL repeated-start RED가 같은 manager에서 live owned process를 두 번째로 생성해 launch await count 2로 실패함 | 1 | 기존 own process가 살아 있으면 idempotent success를 반환해 handle 유실과 helper leak을 막고, 종료된 process일 때만 새로 시작한다. |
| final wheel fresh-venv install harness가 `/tmp` cwd에서 상대 constraint를 찾지 못한 선행 pip 실패를 즉시 중단하지 않아, `pip check` 뒤 installed tests가 `No module named src` 2건으로 종료됨 | 1 | 제품 wheel과 checkout은 불변이다. absolute repository constraint와 `set -e`를 사용해 설치·dependency·installed import를 하나의 fail-fast gate로 재실행한다. |
| 최종 로컬 후보 후 S22U read-only 재확인에서 tailnet 상태가 `offline, last seen 1m ago`, ping timeout, TCP 8022 rc 1로 종료됨 | 1 | 장치·Tailscale 설정은 변경하지 않았다. 현재 Mac에서 직접 device gate를 실행할 수 없으므로 새 commit과 wheel을 보존한 뒤 on-device Hermes 절차 또는 장치 online+sshd 재개를 기다린다. |
| `code-review-excellence`가 나열한 `references/common-bugs-checklist.md`를 읽으려 했지만 skill package에 해당 경로가 없어 rc 1로 중단됨 | 1 | 저장소 파일은 불변이다. skill 디렉터리의 실제 파일 목록을 좁게 확인하고, 누락된 선택 reference 없이 완전히 읽은 SKILL 본문의 체크리스트로 감사를 계속한다. |
| wheel↔checkout binding RED가 존재하지 않는 `validate_wheel_source_binding` import error로 종료됨 | 1 | 예상한 blocking RED다. tracked Python source byte equality, exact console entrypoint metadata, safe unique wheel member allowlist를 검증하고 installed-environment preflight에 연결한다. |
| wheel entrypoint 증거 필드 회귀 test patch 직후 도구 출력이 모델 한도를 넘어 절단됨 | 1 | 파일 변경 여부를 `rg`로 재확인해 assertion이 정상 적용된 것을 확인했다. 제품·wheel은 불변이며, 후속 실행은 좁은 focused test 출력만 수집한다. |
| focused RED에 이전 기록과 다른 `/usr/local/bin/python3.11` 경로를 사용해 shell rc 127이 발생함 | 1 | 저장소·제품은 실행되지 않았다. 현재 host의 실제 `/Users/chiriri722/.local/bin/python3.11`을 확인해 같은 focused test를 재실행한다. |
| wheel binding 증거 필드 RED가 `wheel_entrypoints_verified` KeyError로 실패해 boolean이 설치 entrypoint 개수 필드를 덮는 충돌을 재현함 | 1 | wheel 고유 boolean을 `wheel_entrypoints_verified`로 이름 붙이고 설치 환경의 `entrypoints_verified=4`와 독립적으로 보존한다. |
| release-metadata binding RED가 변조 version, LICENSE, RECORD 세 표본을 모두 허용해 3 failures로 종료됨 | 1 | clean checkout README/LICENSE/NOTICE, exact release metadata/WHEEL contract, every-member RECORD hash·size를 wheel source binding에 추가한다. |
| 결합 static gate가 long-line `awk` 성공 조건에 불필요한 shell `!`를 붙여 출력 없이 rc 1로 종료됨 | 1 | 앞선 diff/bash/compile 단계는 순서상 통과했다. long-line 검사를 올바른 exit 조건으로 독립 재실행하고 각 static gate도 다시 확인한다. |
| checkout 밖 installed-wheel profile harness가 비패키지 `scripts.final_verify`를 import하지 못해 `ModuleNotFoundError`로 종료됨 | 1 | installed `src`를 먼저 절대 site-packages 경로로 확인한 뒤 verifier는 파일 경로 기반 별도 module로 로드해 checkout package가 import precedence를 바꾸지 않게 한다. |
| installed profile 재시도가 macOS의 긴 임시 경로 때문에 control socket portable Unix 길이 제한에서 `ValueError`로 종료됨 | 1 | stderr 원문으로 제품 startup 이전의 harness 경로 문제를 확인했다. 장치 문서 경로 길이도 계산하고, 검증용 data root는 짧은 mode-0700 `/tmp` 경로로 재실행한다. |
| ASCII socket 경로 길이 계산에 V8 isolate에 없는 `TextEncoder`를 사용해 `ReferenceError`가 발생함 | 1 | 입력 경로는 ASCII만 포함하므로 문자열 길이와 UTF-8 byte 길이가 같다. 지원되는 `String.length`로 즉시 재계산한다. |
| documented S22U output path가 control socket 106 bytes로 100-byte runtime contract를 초과했고 compact-path RED 2건도 기존 `home`/무차단 동작을 재현함 | 1 | isolated child directory 이름을 private one-letter roots로 줄이고, 100 bytes를 넘는 사용자 output은 subprocess 시작 전에 명시적으로 거부한다. 전체 문서 명령의 추가 suffix는 다음 회귀에서 별도로 교정한다. |
| 첫 문서 경로 재계산에서 실제 명령의 `/COMMIT12` suffix를 누락해 99 bytes로 잘못 판정함 | 1 | 전체 명령을 다시 대입한 실제 길이는 compact root에서도 108 bytes다. 문서 output을 짧은 `~/.cache/tfv/COMMIT12`로 바꾸고 Termux 절대 경로 회귀를 추가한다. |
| portable-output documentation RED가 기존 `~/.cache/termuinator/final-verify/COMMIT12` 명령을 찾아 1 failure로 종료됨 | 1 | 예상한 문서 계약 실패다. parent/output/hash-check 경로를 모두 `~/.cache/tfv`로 통일하고 87-byte S22U socket path assertion을 유지한다. |
| Termux/install 및 integration 문서 결합 patch가 integration의 실제 `/forms` 문맥과 달라 적용 전 거부됨 | 1 | 두 문서 모두 불변임을 확인했다. 현재 정확한 문맥을 기준으로 각각 작은 patch로 분리한다. |
| 확대된 long-line static gate가 기존 packaging assertion 1줄(106자)을 찾아 rc 1로 종료됨 | 1 | 의미를 바꾸지 않고 assertion 인자를 여러 줄로 나눈 뒤 동일한 전체 정적 검사를 재실행한다. |
| archive 검증 결합 명령이 실제 `SHA256SUMS.txt` 대신 `SHA256SUMS`를 사용하고 변경된 cwd에서 Git 검사를 이어 rc 128로 종료됨 | 1 | archive 파일 권한은 정상 확인됐다. checksum은 실제 파일명과 archive cwd로, Git 검사는 repository workdir에서 독립 재실행한다. |
| read-only tailnet 재확인에서 `tailscale`이 현재 shell PATH에 없어 rc 127로 종료됨 | 1 | 장치나 네트워크는 변경되지 않았다. 설치된 macOS 앱 bundle의 CLI 절대 경로를 확인해 동일한 status 조회를 재실행한다. |
| macOS `nc -z -w 5` TCP 8022 probe가 10초 후에도 종료되지 않아 owned PID 13343이 남음 | 1 | exact argv를 `pgrep -fl`로 확인한 뒤 해당 probe PID만 TERM하고 종료를 확인했다. 후속 TCP 확인은 macOS connect-timeout 옵션 `-G`를 사용한다. |
| candidate benchmark documentation RED가 기존 `termuinator-mcp-v1` venv 경로를 찾아 1 failure로 종료됨 | 1 | verifier가 통과한 commit-suffixed `RC_VENV`의 Python과 tbp만 benchmark에 사용하도록 예시를 교정한다. |

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

- 단계 상태는 반드시 `pending → in_progress → complete` 순서로 갱신한다.
- 주요 결정 전 이 파일을 다시 읽는다.
- 조사 결과는 채팅에만 남기지 말고 `findings.md`에 기록한다.
- 테스트 결과와 변경 파일은 `progress.md`에 기록한다.
- 오류를 숨기지 않는다. 실패한 접근을 기록한 뒤 다른 접근으로 전환한다.
- 기능 수보다 **관찰 정확도, 행동 검증, 승인 경계, 원격 가시성**을 우선한다.
- Termu-inator의 성공 기준은 “페이지를 많이 조작한다”가 아니라 “사용자가 상태와 위험을 확인하면서 신뢰할 수 있게 조작한다”이다.
