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

포크 저장소를 생성하고 upstream 기준 커밋을 고정한 뒤 `findings.md`·`progress.md`와 현재 기능·도구 인벤토리를 작성한다.

## Current Phase

Phase 1 — Fork Baseline & Discovery

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
- capability_flags
```

#### Action

```text
ActionRequest
- action_id / idempotency_key
- session_id / page_id
- expected_page_revision
- kind
- target_ref (when applicable)
- parameters
- timeout
- risk_context
- confirmation_token (when required)

ActionResult
- status: succeeded | failed | blocked | confirmation_required | stale
- before_revision / after_revision
- executed_method
- verification
- changed_url / changed_elements / download
- artifact_uri (optional)
- diagnostics
```

### Provisional MCP v1 Surface

목표는 **기본 14개 이하**, 절대 상한은 16개다.

| Tool | Purpose | Default Risk |
|---|---|---:|
| `browser_session_start` | backend·profile·viewport를 지정해 세션 시작 | R1 |
| `browser_session_status` | 브라우저·세션·capability 상태 조회 | R0 |
| `browser_session_stop` | 세션 정상 종료 | R1 |
| `browser_navigate` | URL 이동, 뒤로·앞으로·reload 포함 | R1 |
| `browser_observe` | 텍스트·a11y·interactive refs·상태·선택적 screenshot | R0 |
| `browser_act` | click/type/key/scroll/select/check/hover/drag의 typed union | R1–R4 |
| `browser_wait` | selector/ref/state/navigation/download 조건 대기 | R0 |
| `browser_tabs` | list/open/switch/close | R1 |
| `browser_screenshot` | viewport/full/element 캡처 후 artifact URI 반환 | R0 |
| `browser_downloads` | 다운로드 목록·상태·artifact URI | R0/R2 |
| `browser_artifact_read` | 원격 환경에서 screenshot/download bytes 회수 | R2 |
| `browser_permissions` | 사이트 권한·pending confirmation 상태 조회/관리 | R2–R4 |
| `browser_devtools` | console/network/DOM/style/perf의 승인된 read-only 질의 | Developer |
| `browser_trace` | action trace 조회·내보내기·replay용 기록 | R0 |

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

- [ ] Firefox와 Chromium이 동일한 v1 observation/action 계약을 구현한다.
- [ ] backend별 미지원 기능은 명시적 capability와 구조화 오류로 반환된다.
- [ ] observe 결과의 ref로 click/type/select/check가 가능하다.
- [ ] stale ref 또는 page revision mismatch가 실제 행동 전에 차단된다.
- [ ] 모든 행동 후 자동 verification 결과가 반환된다.
- [ ] 탭 전환, dialog 감지, 사용자 sign-in handoff, 다운로드 회수가 동작한다.
- [ ] screenshot과 다운로드를 WSL2/Hermes에서 원격 회수할 수 있다.
- [ ] 기본 MCP 도구 수가 16개 이하이다.

### Safety

- [ ] 새 origin 접근 정책이 `ask/session allow/always allow/block`을 지원한다.
- [ ] R4 행동은 유효한 confirmation token 없이는 실행되지 않는다.
- [ ] full CDP는 기본 비활성화이며 별도 승인 없이는 접근할 수 없다.
- [ ] 페이지 텍스트가 권한 정책·도구 노출·승인 상태를 변경할 수 없다.
- [ ] credential·OTP·cookie value·authorization header가 일반 trace에 기록되지 않는다.
- [ ] artifact와 profile 파일에 제한 권한과 path traversal 방어가 적용된다.

### Reliability

- [ ] 결정론적 로컬 fixture E2E 시나리오 25개 이상을 구축한다.
- [ ] 핵심 fixture 시나리오 반복 성공률 95% 이상을 달성한다.
- [ ] 1시간 또는 100개 연속 action soak test에서 daemon이 비정상 종료하지 않는다.
- [ ] 브라우저 crash·stale socket·profile lock에서 명확한 복구 경로를 제공한다.
- [ ] status 명령은 warm daemon에서 목표 300ms 이내, text-only observe는 목표 2초 이내다.

### Compatibility & Delivery

- [ ] 기존 `tbp` 주요 읽기·탐색·클릭 명령에 compatibility adapter가 존재한다.
- [ ] Hermes SSH stdio 예제와 Codex MCP 예제가 검증된다.
- [ ] architecture, tool contracts, security model, migration 문서가 완성된다.
- [ ] 설치·업데이트·삭제·데이터 초기화 절차가 문서화된다.
- [ ] MIT 원저작자 고지와 포크 변경 내역이 보존된다.

---

## Phases

### Phase 1: Fork Baseline & Discovery

**Objective:** 포크의 기준점을 고정하고, 현재 기능·결함·성능을 재현 가능한 상태로 기록한다.

- [ ] `salviz/termux-browser-pilot`을 포크하고 저장소 이름을 `Termu-inator`로 설정
- [ ] upstream remote와 baseline commit/tag 고정
- [ ] MIT LICENSE, 원저작자 고지, fork notice 확인
- [ ] `findings.md`와 `progress.md` 생성
- [ ] 현재 CLI command, MCP tool, daemon handler를 자동 집계하는 inventory script 작성
- [ ] 모든 기능을 `core / developer / legacy / remove` 후보로 분류
- [ ] Firefox·Chromium capability matrix 초안 작성
- [ ] 현행 설치 절차를 깨끗한 Termux 환경에서 재현
- [ ] example.com 기반 baseline smoke test 실행
- [ ] 현재 daemon warm latency, browser startup, RSS, screenshot 크기 측정
- [ ] 확인된 결함과 문서 불일치를 `findings.md`에 기록
- **Status:** in_progress

**Deliverables**

- `findings.md`, `progress.md`
- `scripts/inventory_current_surface.py`
- `docs/upstream-baseline.md`
- 초기 capability·performance baseline

**Exit Gate**

- baseline 설치·실행 절차가 재현되고, 현재 tool/handler 인벤토리와 backend capability 차이가 문서화되어야 한다.

---

### Phase 2: Product Contract & Tool Surface Reduction

**Objective:** 구현 전에 제품 경계, API 계약, 보안 모델과 축소된 도구 표면을 확정한다.

- [ ] 핵심 사용자 흐름 6개를 acceptance scenario로 변환
- [ ] v1 MCP 도구별 JSON schema와 error code 정의
- [ ] `Observation`, `ActionRequest`, `ActionResult`, `Artifact`, `PermissionDecision` 모델 정의
- [ ] element ref 발급·수명·stale 판정 규칙 정의
- [ ] page revision 계산 전략 정의
- [ ] action별 기본 verification 전략 정의
- [ ] risk class와 confirmation token protocol 정의
- [ ] origin permission store 형식과 기본값 정의
- [ ] 별도 profile, history, cookie, artifact retention 정책 정의
- [ ] Firefox/Chromium capability negotiation 계약 확정
- [ ] legacy command mapping과 deprecation 범위 정의
- [ ] anti-bot·challenge 기능의 제품 문구와 비목표 확정
- [ ] architecture RFC와 security RFC 리뷰
- **Status:** pending

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
- [ ] 공통 typed models, structured errors, config loader 구현
- [ ] `BrowserBackend` protocol/ABC 정의
- [ ] Firefox native와 Chromium CDP를 backend adapter로 래핑
- [ ] session manager와 single-session lock 구현
- [ ] daemon transport와 business logic 분리
- [ ] handler registry를 기능별 모듈로 분할
- [ ] artifact store와 trace recorder 기본 골격 구현
- [ ] permission engine interface 구현
- [ ] legacy `tbp` command를 새 service 호출로 연결
- [ ] 기존 로직과 신규 로직의 중복 구현 제거
- [ ] fake backend와 unit test harness 구축
- [ ] pyproject version, optional dependencies, Pillow/MCP dependency 정리
- [ ] openbox 중복 실행, Chromium binary detection 등 baseline 결함 수정
- **Status:** pending

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
- [ ] interactive element 정규화와 stable ref registry 구현
- [ ] iframe·shadow DOM 경로를 ref metadata에 포함
- [ ] screenshot artifact와 observation sequence 연결
- [ ] typed `browser_act` executor 구현
- [ ] click/type/key/scroll/select/check/hover/drag의 공통 결과 계약 구현
- [ ] stale ref와 revision mismatch 차단
- [ ] 행동별 verification 구현
  - [ ] URL/navigation 변화
  - [ ] input value 변화
  - [ ] checked/selected 상태
  - [ ] dialog 발생
  - [ ] download 시작/완료
  - [ ] target visibility/DOM 변화
- [ ] `browser_wait` 조건 모델 구현
- [ ] 탭·팝업·dialog 수명주기 통합
- [ ] challenge/OTP 감지를 action 차단·handoff 신호로 연결
- [ ] raw coordinate action은 arm + visual verification 조건으로 격리
- [ ] 각 action의 before/after trace와 진단 artifact 저장
- [ ] local fixture 사이트 구축
  - [ ] forms
  - [ ] SPA navigation
  - [ ] dynamic list
  - [ ] shadow DOM
  - [ ] same/cross-origin iframe
  - [ ] dialogs
  - [ ] download
  - [ ] stale element replacement
- **Status:** pending

**Deliverables**

- observation/action/verification engine
- deterministic fixture suite
- trace schema

**Exit Gate**

- 에이전트가 CSS selector를 직접 생성하지 않고도 핵심 fixture 작업을 ref 기반으로 완료하며, 모든 action이 검증 결과 또는 명시적 실패 진단을 반환해야 한다.

---

### Phase 5: Permissions, Remote Artifacts & Shared View

**Objective:** 원격 Hermes/Codex 환경에서도 사용자가 페이지를 확인하고 위험 행동을 통제할 수 있게 한다.

- [ ] origin allow/block/ask policy 구현
- [ ] session-only와 persistent permission store 구현
- [ ] action risk classifier 구현
- [ ] confirmation preview와 one-shot token 구현
- [ ] 페이지 revision/origin/action hash 변경 시 token 무효화
- [ ] credential field·OTP·민감 데이터 redaction 구현
- [ ] 사용자 takeover/resume protocol 구현
- [ ] 페이지 지시를 untrusted data로 취급하는 policy boundary 구현
- [ ] artifact content-addressed storage 구현
- [ ] screenshot을 PNG/WebP로 저장하고 크기·hash·MIME metadata 반환
- [ ] MCP resource 또는 chunked `browser_artifact_read` 구현
- [ ] 다운로드 완료 감지와 원격 파일 회수 구현
- [ ] SSH stdio 환경에서 screenshot/download round-trip 검증
- [ ] 최소 shared-view dashboard 구현
  - [ ] 현재 screenshot
  - [ ] URL/title/tab
  - [ ] pending permission/confirmation
  - [ ] recent action trace
  - [ ] takeover/resume control
- [ ] artifact expiry·quota·cleanup 구현
- [ ] audit log와 secret redaction test 추가
- **Status:** pending

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

- [ ] Developer Mode feature flag와 사이트별 승인 구현
- [ ] read-only console query 구현
- [ ] network request/response metadata query 구현
- [ ] DOM·computed style·layout query 구현
- [ ] performance/navigation/resource timing query 구현
- [ ] optional performance trace export 구현
- [ ] response body·cookie·header·raw eval의 추가 승인 규칙 구현
- [ ] raw CDP passthrough는 실험 플래그 뒤에 격리
- [ ] 최종 MCP v1 도구를 16개 이하로 고정
- [ ] tool descriptions를 observe-first·ref-first 흐름에 맞게 작성
- [ ] Hermes용 기본 read-only tool allowlist 제공
- [ ] Hermes용 interactive tool profile 제공
- [ ] Codex MCP 예제 설정 제공
- [ ] SSH wrapper가 stdout에 MCP 외 텍스트를 출력하지 않도록 검증
- [ ] CLI를 session/observe/act/devtools/artifacts 중심으로 재구성
- [ ] 기존 `tbp` alias와 migration warnings 제공
- [ ] 설치·업데이트·데이터 초기화·문제 해결 문서 작성
- **Status:** pending

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
- [ ] Firefox·Chromium backend별 capability test 실행
- [ ] 100-action soak test와 1시간 idle/resume test 실행
- [ ] browser crash, daemon crash, stale socket, stale lock 복구 test 실행
- [ ] Android background process kill 이후 복구 test 실행
- [ ] SSH disconnect/reconnect test 실행
- [ ] permission bypass·token replay·path traversal·artifact traversal test 실행
- [ ] prompt-injection fixture에서 policy boundary test 실행
- [ ] secret redaction test 실행
- [ ] performance budget 측정 및 baseline 비교
- [ ] 최소 1대의 실제 Android/Termux 장치에서 release candidate 검증
- [ ] 선택적으로 2번째 장치 또는 Android VM에서 호환성 검사
- [ ] 외부 사이트 smoke test는 non-gating 보고서로 분리
- [ ] README, architecture, security, migration, troubleshooting 최종 검토
- [ ] version을 `0.1.0-alpha`로 정리하고 changelog 작성
- [ ] GitHub release artifact와 설치 명령 검증
- [ ] post-alpha backlog를 v0.2 milestone으로 이전
- **Status:** pending

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
- confirmation token expiry/replay
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

- [ ] site access와 consequential action 승인 분리
- [ ] permission 기본값 least-permissive
- [ ] origin 정규화와 IDN/punycode 검사
- [ ] redirect 후 origin 재검사
- [ ] page revision과 confirmation token 결합
- [ ] trace secret redaction
- [ ] credential fields 자동 마스킹
- [ ] screenshot 민감 영역 정책 검토
- [ ] cookie/storage/history는 기본 toolset 밖
- [ ] full CDP 기본 off
- [ ] path traversal·symlink escape 방어
- [ ] Unix socket·profile·artifact 권한 제한
- [ ] SSH wrapper stdout purity
- [ ] malicious page text가 policy engine을 호출하지 못함
- [ ] downloads에 MIME·size·hash·quarantine metadata 부여
- [ ] audit log는 append-only 또는 tamper-evident 옵션 검토

---

## Key Questions

1. Firefox native backend에서 stable element ref를 DOM mutation 이후 어느 수준까지 재사용할 것인가?
2. page revision은 URL·document lifecycle·DOM mutation counter 중 어떤 조합으로 계산할 것인가?
3. Hermes가 MCP resources의 binary image를 안정적으로 읽는가, 아니면 chunked artifact tool이 필수인가?
4. shared-view MVP를 정적 screenshot dashboard로 시작할지, 저주기 WebSocket stream으로 시작할지?
5. v0.1에서 단일 브라우저 세션만 지원할지, profile만 복수로 둘지?
6. file upload를 v0.1에서 완전히 제외할지, R3 승인 뒤 제한적으로 제공할지?
7. raw JavaScript eval을 compatibility namespace에 유지할지, Developer Mode 전용으로만 이동할지?
8. Firefox를 기본 backend로 유지할지, 일반 Browser Use는 Firefox·Developer Mode는 Chromium으로 자동 분리할지?
9. `tbp` CLI alias를 몇 개 릴리스 동안 유지할지?
10. 기존 stealth·Cloudflare handler 중 challenge 감지 외에 어떤 부분을 experimental로 보존할지?
11. confirmation UI를 Hermes chat approval, shared-view dashboard, CLI prompt 중 어떤 순서로 구현할지?
12. browser profile 데이터를 프로젝트별로 분리할지 사용자 전체 기본 프로필을 둘지?

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

---

## Risks and Mitigations

| Risk | Impact | Mitigation | Trigger for Re-plan |
|---|---|---|---|
| Firefox DevTools/clipboard/focus 불안정 | action 실패·지연 | console 상태 machine, strict serialization, fallback diagnostics | fixture 성공률 <90% |
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

---

## Expected Deliverables

- [ ] `task_plan.md`
- [ ] `findings.md`
- [ ] `progress.md`
- [ ] Termu-inator fork repository
- [ ] compact MCP v1 server
- [ ] typed browser core and two backend adapters
- [ ] permission/confirmation engine
- [ ] artifact store and remote retrieval
- [ ] shared-view MVP
- [ ] Developer Mode
- [ ] Hermes and Codex integration examples
- [ ] deterministic fixture test suite
- [ ] architecture/security/migration documentation
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
