# Progress: Termu-inator

현재 상태는 [STATUS.md](STATUS.md)가 기준이다. 이 파일에는 **최근 작업 항목**과 **기기 회차 원장**만 둔다.
2026-11-06까지의 전체 기록은
[docs/history/progress-through-2026-11-06.md](docs/history/progress-through-2026-11-06.md)에 원문 그대로 있다.

작성 규칙

- 새 항목을 "최근 작업"의 맨 위에 쓴다. 한 항목은 10줄 이내다.
- 해시, 전체 경로, 원시 로그는 저장소 밖 `../Termu-inator-device-artifacts/`의 파일에 두고 이름만 적는다.
- 기기에서 실행했다면 차선(L1·L2)을 적고 원장에 한 줄을 추가한다.
- 400줄을 넘으면 오래된 항목을 `docs/history/`로 옮긴다.

## 최근 작업

### 2026-11-10 — 방향 점검, 권장안 채택, 문서 체계 재구성

- 사용자 요청으로 진척과 검증 방향을 점검했다. 결과는 [방향 점검](docs/direction-review-2026-11-10.ko.md)에 있다.
- 사용자가 권장안을 채택했다. 세 차선(L0·L1·L2), 합성 실행의 원문 로그 전달, alpha 게이트 v1 동결,
  기기 preflight unit 실행의 비차단화, alpha 범위 축소다. `task_plan.md`의 Decisions Made에 기록했다.
- 새 파일: `STATUS.md`, `docs/verification-lanes.ko.md`, `docs/s22u-l1-chromium-probe.ko.md`,
  `scripts/l1_chromium_probe.sh`, `docs/history/`의 원본 세 개.
- 재구성: `task_plan.md`(2,188줄 → 1,031줄), `progress.md`, `findings.md`.
  `acceptance/`의 설명은 L0 로컬 게이트로 고쳤다. 판정 로직은 바꾸지 않았다.
- 확인: unit 659개 OK(opt-in skip 1), `acceptance_gate.py` PASS(실제 Chrome fixture 10개 포함),
  history 세 파일의 SHA-256이 `feb7bd8`의 blob과 일치.
- `scripts/l1_chromium_probe.sh`는 Mac에서 가짜 실행 파일로 판정 로직만 확인했다. Termux에서는 실행하지 않았다.
- runtime(`src/`), 검수기(`final_verify.py`, `benchmark_device.py`), `tests/`는 변경하지 않았다. commit·push 없음.
- 다음: S22U에서 L1 Chromium 단독 진단.

### 2026-11-06 — r4 preflight 수신, tests namespace 수정

- r4(`1b1e4eb`)는 기기 preflight에서 끝났다. named suite import 실패, full discovery 648/657 수집,
  오류·실패 14건. canonical·benchmark·브라우저는 시작하지 않았다.
- `tests/__init__.py`가 없어 site-packages의 다른 `tests` 패키지가 checkout을 가리는 조건을 로컬에서
  재현했다. 같은 648개, failures 5, errors 9가 나왔다. 기기 정적 추출과 14건의 위치가 모두 일치한다.
- `tests/__init__.py`와 회귀 2개를 추가했다. 로컬 전체 659개 OK. 사용자가 `feb7bd8`로 commit했다.
- 기기에서 실제로 선택된 `tests` 경로는 기록되지 않아 기기 원인은 미확정이다.
- 상세: [r4 보강](docs/s22u-r4-test-discovery-followup.ko.md).

### 2026-10-28 — r3 정적 진단 수신, 시작 시도 기록 보강

- r3의 정적 진단 두 파일을 받았다. Chromium 로그 전체가 검사됐지만 종료 원인은 기록되지 않았다.
- 실패 시점의 종료 코드와 cleanup 뒤의 코드를 분리하고, 최대 3회 시작 시도의 고정 진단을 보존하게 했다.
- 사용자가 `c0e463f`, `1b1e4eb`로 commit했다. Chromium 시작 원인은 해결되지 않았다.
- 상세: [r3 보강](docs/s22u-r3-confidential-followup.ko.md).

### 2026-10-23 — r2, r3 수신과 로컬 수정

- r2(`d348616`): Chromium `session_start` 실패, Firefox SKIPPED. 시작 단계 label, 소유권이 입증된
  singleton 정리, RPC 중 프로세스 관측을 추가했다. 상세: [r2 보강](docs/s22u-r2-startup-followup.ko.md).
- r3(`5cc585d`): Chromium `cdp_ready` 전 종료(코드 -5). Firefox는 `confidential_boundaries`에서 실패.
  실제 adapter의 `navigate()`가 `interactive_elements`를 비워 탐색 직후 민감 필드 감지가 작동하지 않는
  제품 결함을 재현하고 수정했다.
- 사용자가 S22U 필수 기준 유지를 결정했다. `acceptance/`의 로컬 게이트는 이를 대체하지 않는다.

## 기기 회차 원장

S22U에서 실제로 실행한 회차만 적는다. 2026-11-10 이전은 모두 봉인 회차(지금의 L2에 해당)다.
날짜는 결과를 받아 검토한 날 기준이다.

| 날짜 | commit | 결과 | 첫 실패 지점 | 원인 분류 |
|---|---|---|---|---|
| 08-25 | `0007a1e` | PARTIAL | Firefox observe `backend_crashed`, Chromium session start | 제품 |
| 08-25 | `b5362f9` v0.2.01 | FAIL | 양 backend 기본 observe (Chromium a11y 형식, Firefox DOM probe 구문) | 제품 |
| 08-26 | `d40f4d3` v0.2.03 | FAIL | Android identity 판정 | 검수기 |
| 08-29 | `e29320d` v0.2.04 | FAIL, 브라우저 미시작 | 테스트 2개가 `/tmp` 고정 | 테스트 |
| 08-29 | `0a4a212` v0.2.05 | FAIL | artifact root와 lock 기대값 | 검수기 |
| 08-29 | `1bec1b0` v0.2.06 | FAIL | Chromium PASS. Firefox loopback 탐색 timeout, lock PID 계약 | 제품, 검수기 |
| 08-29 | `0bc2e01` v0.2.08 | FAIL | Chromium PASS. Firefox 탐색 `backend_crashed` | 제품 |
| 08-30 | `1e55237` v0.2.11 | FAIL | Firefox `clipboard_prime` | 제품 |
| 08-30 | `4af303d` v0.2.12 | FAIL | Firefox `address_bar_copy` | 제품 |
| 08-30 | `2ee0a0a` v0.2.13 | FAIL | Firefox `address_bar_copy` 반복. BiDi로 전환 | 제품 |
| 08-30 | `072831a` v0.2.15 | FAIL | Firefox observe | 제품 |
| 08-31 | `30eaa4a` v0.2.16 | FAIL | 양 backend PASS. interactive stdio stderr 38 bytes | 제품 |
| 08-31 | `c4f5802` v0.2.17 | **PASS** | canonical 양 backend, benchmark 기준 충족 | — |
| 09-04~10 | `379b0e9` v0.2.18 | canonical PASS, benchmark FAIL | benchmark screenshot 0/5 | benchmark harness |
| 09-22 | `22155ee` v0.2.20 | **PASS** | canonical, benchmark. 게이트 밖 추가 readback은 exit 1(원인 미확인) | — |
| 09-23 | `98f4174` v0.2.39 | FAIL | 양 backend 첫 `type` | 검수기, fixture |
| 09-24 | `ff62c30` v0.2.42 | FAIL | 양 backend `action_boundaries` | 검수기, fixture |
| 10-23 | `d348616` r2 | FAIL | Chromium `session_start`. Firefox SKIPPED | 미진단 (환경 변화 의심) |
| 10-23 | `5cc585d` r3 | FAIL | Chromium `cdp_ready` 전 종료 -5. Firefox `confidential_boundaries` | 미진단, 제품 |
| 11-06 | `1b1e4eb` r4 | preflight FAIL | 테스트 import 충돌. canonical 미실행 | 테스트 패키징 |

- Termux 리셋(10-23 이전) 뒤의 환경은 Chromium 155.0.8059.79, Firefox 158.0.1이다. 그 전의 PASS는
  Chromium 149.0.7827.155, Firefox 154.0.1에서 나왔다.
- 리셋 뒤 Chromium이 기기에서 시작된 회차는 없다. Firefox는 r3에서 마지막 기능 단계 전까지 통과했다.
- 회차별 수신 자료는 `../Termu-inator-device-artifacts/`에 있다.
