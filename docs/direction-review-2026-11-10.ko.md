# 방향 점검 — 검증 루프 진단과 재정렬 (2026-11-10)

대상은 HEAD `feb7bd8` (`v.0.2.36`)이다. 저장소, git 이력,
`../Termu-inator-device-artifacts/`의 수신 증거를 읽고 로컬 테스트를 1회 실행해 작성했다.
작성 시점에는 코드와 기존 문서를 수정하지 않았다.

**2026-11-10 사용자 승인: 6절의 권장안을 모두 채택했다.** 채택한 규칙은
[검증 차선과 alpha 게이트](verification-lanes.ko.md)에, 현재 상태는 [STATUS.md](../STATUS.md)에 있다.
이 문서는 그 결정의 근거로 남긴다. S22U 실기기 필수 기준은 바뀌지 않았다.

## 결론

1. **목표와 "S22U 실기기 필수" 기준은 옳다.** 바꿀 이유가 없다. 제품 코드도 대체로 건강하다.
2. **길어지는 원인은 제품이 아니라 검증 루프의 설계다.** 봉인된 1회용 인수 절차를
   디버깅 수단으로 쓰고 있어서, 사실 하나를 얻는 데 회차 하나(며칠)가 든다.
3. **가장 큰 빈틈은 환경 변화를 분리하지 않은 것이다.** Termux 리셋 뒤 Chromium이
   149 → 155로 바뀌었고, 그 뒤로 기기에서 Chromium은 한 번도 시작되지 않았다.
   세 회차(r2–r4)를 썼지만 원인은 여전히 UNKNOWN이다.
4. **지금 r5를 그대로 봉인해 보내면 같은 지점에서 다시 실패할 가능성이 높다.**
   r3 이후 추가된 것은 원인 수정이 아니라 진단 label이기 때문이다.
   봉인 전에 기기에서 10분짜리 비봉인 진단을 먼저 해야 한다.
5. 필요한 수정은 기준 완화가 아니다. **진단과 인수의 분리, 인수 기준 동결,
   검수기 확장 중단** 세 가지다.

## 1. 현재 진척 상태

### 스냅샷

| 항목 | 상태 |
|---|---|
| HEAD | `feb7bd8` (`v.0.2.36`, 2026-11-07). clean, `origin/main`과 동일 |
| 로컬 테스트 | 659개 실행, OK, opt-in skip 1개, 13.8초. 이번 점검에서 직접 실행 |
| 마지막 S22U PASS | `22155ee` (`v.0.2.20`, 2026-09-22). canonical PASS, benchmark PASS |
| 그 이후 S22U | 5회 실행, PASS 0회 |
| 대기 중인 작업 | `feb7bd8` 기준 r5 자료 봉인. 아직 만들어지지 않았다 |
| 계획 문서 | `task_plan.md`의 Next Step은 "새 clean commit 대기"인데 그 commit은 이미 있다 |

### 계획 대비 진척

Phase 체크박스 기준 174/216 (81%)이다. Phase 2만 완료이고 나머지 여섯 개가 동시에 `in_progress`다.

| Phase | 완료/전체 | 남은 것 |
|---|---|---|
| 1 Baseline | 10/11 | 깨끗한 Termux 설치 재현 |
| 2 Contract | 13/13 | — |
| 3 Typed core | 9/14 | `termuinator` namespace 이전, daemon 분리, handler 분할, legacy 연결, 중복 제거 |
| 4 Observe–Act–Verify | 32/39 | 통합 observe, cross-origin frame, 탭·popup·dialog 실제 연결, 진단 artifact |
| 5 권한·artifact | 21/25 | 실제 다운로드 이벤트, SSH 원격 round-trip |
| 6 Developer·MCP·CLI | 22/29 | trace export, 추가 승인 규칙, CLI 재구성, `tbp` alias |
| 7 검증·alpha | 67/85 | 기기 capability probe, soak, crash 복구, 릴리스 |

Definition of Done은 16/24다. Safety 6/6, Functional 6/8, Compatibility 4/5, **Reliability 0/5**.
Reliability의 지연 시간 항목은 v0.2.20 benchmark에서 이미 충족했는데(status 1.4 ms, text 7 ms)
체크되지 않았다. DoD 표 자체가 관리되지 않고 있다는 뜻이다.

**2026-09-22 이후 7주 동안 닫힌 DoD 항목은 0개다.** 작업은 모두 Phase 7의 검수 보강에 들어갔다.

### 기기 검수 이력

| 기간 | 기기 회차 | 결과 | 특징 |
|---|---|---|---|
| 08-25 ~ 08-31 | 13 | `v0.2.17` 완전 PASS | 하루 최대 4회 왕복. 실패 단계가 바로 돌아왔다 |
| 09-04 ~ 09-22 | 2 | `v0.2.20` PASS | benchmark 품질·권한 보강 |
| 09-23 ~ 11-06 | 5 | PASS 0 | 검수 범위 확장, Termux 리셋, 봉인·예산 체계 도입 |

v0.2.20 이후 다섯 회차의 첫 실패 지점은 다음과 같다.

| 회차 | 기기 결과 | 원인 분류 |
|---|---|---|
| `v0.2.39` (09-23) | 양 backend 첫 `type`에서 실패 | **검수기 결함.** 요청에 `confirmation_id: null` 누락, fixture 이름 불일치 |
| `v0.2.42` (09-24) | 양 backend `action_boundaries` | **검수기·fixture 결함.** 버튼 기본 type과 검수기 기대 불일치 |
| r2 `d348616` (10-23) | Chromium `session_start` 실패, Firefox SKIPPED | **환경 변화 의심, 미진단** |
| r3 `5cc585d` (10-23) | Chromium `cdp_ready` / 종료 코드 -5. Firefox `confidential_boundaries` | Chromium은 **같은 지점, 미진단**. Firefox는 **실제 제품 결함** (로컬 수정 완료) |
| r4 `1b1e4eb` (11-06) | preflight 실패, 브라우저 미시작 | **테스트 패키징 결함.** `tests/__init__.py` 누락 |

다섯 회차 중 세 번은 검수 도구 자체의 결함으로 소모됐고, 두 번은 같은 Chromium 문제에
부딪혔으며, 제품 결함은 하나를 찾았다. 리셋 이후 canonical이 브라우저에 도달한 것은 두 번이고
Chromium이 시작된 것은 0번이다.

좋은 소식도 있다. r3에서 Firefox 158은 session start부터 action boundaries까지 모두 통과하고
마지막 기능 단계에서만 실패했다. 그 원인은 로컬에서 재현·수정됐다. Firefox 쪽은 PASS에 가깝다.

## 2. 유지할 것

- **S22U 필수 기준.** 2026-10-23의 사용자 결정이 옳았다. 기기는 Mac에서 볼 수 없는 실제 결함을
  찾아냈다(Firefox clipboard → BiDi 전환, 탐색 직후 takeover 감지 누락, Chromium 시작).
  `acceptance/README.md`의 "코드는 계속 건강했고 문제는 절차뿐"이라는 진단은 사실과 다르다.
- **RED → GREEN 규율과 빠른 로컬 suite.** 659개가 14초에 끝난다.
- **성공 기준·timeout을 완화하지 않는 원칙**과 증거 무결성 확인.

## 3. 문제

### 3.1 인수 절차를 디버깅 수단으로 쓰고 있다

현재 기기를 관찰하는 유일한 방법은 봉인 회차다. 사용자 commit → wheel 빌드와 source binding →
authority·runbook·ZIP 봉인 → Hermes 실행 → 공개 ZIP 반환 → Mac 무결성 검증 순서를 거친다.
한 identity는 1회 소비되며 같은 상태로 재실행하지 않는다. 돌아오는 것은 allowlist를 통과한
고정 label 몇 개다.

이 엄격함은 **마지막 승인**에는 맞지만 **원인 찾기**에는 맞지 않는다. 디버깅에는 빠르고,
정보가 많고, 반복 가능한 관찰이 필요하다. 8월에는 하루 4회 왕복으로 6일 만에 PASS에 도달했다.
지금은 한 회차가 한 가지 사실만 알려 주고, canonical이 실패하면 뒤 단계는 실행되지 않으므로
결함이 한 번에 하나씩만 드러난다.

### 3.2 환경 변화를 분리하지 않았다

수신 증거에 기록된 버전은 다음과 같다.

| | v0.2.20 PASS (09-22) | 리셋 이후 r2–r4 |
|---|---|---|
| Chromium | 149.0.7827.155 | **155.0.8059.79** |
| Firefox | 154.0.1 | **158.0.1** |
| cryptography | 50.0.1 | 50.0.2 |

Chromium이 마지막으로 기기에서 시작된 것은 `v0.2.42`(09-24)다. 그 이틀 전 v0.2.20 기록의
버전이 149였다. 그 commit과 처음 실패한 r2 후보 사이의 runtime 변경은 `src/cdp.py` 32줄뿐이고,
이 코드는 CDP 연결이 맺어진 **뒤**에만 실행된다(준비 확인은 `/json/version` HTTP polling이다).
반면 r3의 실패는 CDP 준비 **전** 프로세스 종료이고 종료 코드 -5는 SIGTRAP이다.
Chromium은 내부 CHECK 실패로 스스로 중단할 때 보통 이 신호로 종료한다.

따라서 유력한 가설은 "코드 회귀"가 아니라 **"Chromium 155가 현재 시작 플래그 조합이나
Termux 환경에서 스스로 중단한다"**이다. `src/browser.py`는 `--no-zygote`, `--single-process`
fallback, `--use-angle=swiftshader-webgl`처럼 major 버전에 민감한 플래그를 쓴다.

이것은 가설이며 확인된 사실이 아니다. 문제는 이 가설을 **가르는 실험을 한 번도 하지 않았다**는
점이다. 계획 문서 어디에도 149 → 155 변화와 시작 실패를 연결한 기록이 없다. "추정하지 않는다"는
원칙이 가설을 세우고 검증하는 일까지 막았다. 필요한 실험은 기기에서 제품 밖으로 Chromium을
직접 띄워 보는 것 하나이고 10분이면 끝난다.

### 3.3 검수기가 제품보다 빨리 자라고, 스스로 회차를 소모한다

v0.2.20 이후의 추가 줄 수다.

| 대상 | 추가 |
|---|---|
| runtime `src/` | +768 (순증 +545) |
| 검수기 `scripts/` | +1,870 |
| `tests/` | +4,975 |
| 계획·기록·문서 | +3,781 |

`scripts/final_verify.py`는 3,750줄로, 가장 큰 runtime 모듈(`core/service.py` 2,423줄)보다 크다.
검수기가 크고 자주 바뀌면 검수기 결함이 기기 회차를 소모한다. 실제로 다섯 번 중 세 번이 그랬다.
수정마다 새 회귀와 새 label이 붙어 다음 회차의 표면이 다시 넓어진다.

기기 preflight가 unit suite 전체(659개)를 차단 조건으로 실행하는 것도 같은 문제다. r4는
브라우저를 띄우기도 전에 여기서 끝났다. S22U가 필요한 이유는 Android에서의 실제 브라우저
동작이지, Mac에서 14초에 끝나는 unit test의 재실행이 아니다.

### 3.4 PASS 뒤에 결승선이 움직였다

`v0.2.17`과 `v0.2.20`은 canonical과 benchmark를 통과했다. v0.2.20의 완료 판정이 보류된 이유는
게이트 밖의 추가 readback이 exit 1로 끝났고 **그 stderr를 읽지 않아** 원인을 몰랐기 때문이다.
후속 진단(socket-r1)에서 나온 것은 PASS 21개와, 전역 Unix socket 목록을 권한 오류(EACCES)로
읽을 수 없다는 항목 하나였다.

그 보류를 계기로 프로세스 census, action boundary, confidential boundary가 canonical에 추가됐고,
확장된 게이트는 아직 한 번도 통과하지 못했다. 게이트 정의에 버전이 없어서 "무엇을 통과하면
끝인가"가 회차마다 달라진다.

### 3.5 증거 공개 규칙이 진단을 막는다

"stderr·경로·assertion 값은 공개하지 않는다"는 규칙은 실제 계정과 실제 사이트 데이터를
보호하기 위한 것이다. 그런데 canonical은 임시 프로필로 loopback 합성 fixture만 연다.
여기서 나온 5.6 KB짜리 Chromium 시작 로그조차 범주 label로만 전달됐고, 추가 정적 진단을
두 번 주고받은 뒤에도 결론은 `cause=UNKNOWN_NOT_RECORDED`였다. 보호할 내용이 거의 없는
자료에 가장 엄격한 규칙을 적용해 회차를 쓰고 있다.

### 3.6 기능이 열려 있는 중간 commit을 봉인하고 있다

Phase 3–6에 미완 항목이 23개 있다. 이들을 구현하면 source tree digest가 바뀌고, 현재 규칙상
과거 PASS는 재사용할 수 없으므로 기기 검수를 전부 다시 해야 한다. 봉인 인수는 alpha 후보가
기능적으로 닫힌 뒤 한두 번 하면 되는 절차인데, 지금은 중간 commit마다 수행하고 있다.

### 3.7 작업 메모가 작업 기억 역할을 못 한다

- `task_plan.md`, `progress.md`, `findings.md`가 합계 688 KB, 약 20만 token이다.
  새 세션이 현재 상태를 파악하려면 이 분량을 지나야 한다.
- `task_plan.md`의 Next Step 아래에 Historical·Superseded 층이 300줄 쌓여 있고,
  맨 위 상태는 이미 낡았다(1절 스냅샷 참고).
- `acceptance/`와 `progress.md`의 IMPORTANT 배너는 "기기 없이 완료"를 선언하고,
  그 위 문단은 "S22U 필수"를 선언한다. 서로 충돌하는 두 기준이 같이 남아 있다.
  `no-uncommitted-drift`는 `dirty: true`에서도 PASS로 기록된다.
- commit 제목의 버전이 0.2.44 → 0.2.35 → 0.2.36으로 역행한다. SHA로 구분하고는 있지만 혼동의 원인이다.

## 4. 재정렬 원칙

1. **차선을 셋으로 나눈다.**

   | 차선 | 어디서 | 성격 | 인수 증거 여부 |
   |---|---|---|---|
   | L0 로컬 | Mac | unit suite와 실제 Chrome fixture. 모든 변경마다 | 아니오 |
   | L1 기기 진단 | S22U | 비봉인, 반복 가능, 원문 로그 사용, 예산 없음 | **아니오** |
   | L2 기기 인수 | S22U | 봉인, 1회, 공개 자료는 sanitized | 예 |

   `acceptance/acceptance_gate.py`는 버리지 말고 L0의 실행 도구로 의미를 바꾼다.
2. **L1에서 같은 검수기가 끝까지 통과한 commit만 L2에 올린다.** L2는 처음부터 통과할 것으로
   예상되는 확인 절차여야 한다. 이 규칙이 있었다면 `v0.2.39`, `v0.2.42`, r4는 봉인 전에 걸러졌다.
3. **환경이 바뀌면 코드보다 환경을 먼저 확인한다.** 브라우저 major 버전이 바뀐 뒤의 첫 작업은
   제품 밖 단독 실행 smoke다.
4. **alpha 게이트를 버전으로 동결한다.** 통과 조건을 한 번 적고, 새 검사는 다음 버전 게이트로
   미룬다. 플랫폼이 허용하지 않는 관측(`/proc/net/unix` 등)은 사전에 "보조"로 분류한다.
5. **검수기 확장을 멈춘다.** alpha까지 `scripts/`의 변경은 실제 결함 수정으로 제한한다.
6. **메모는 현재 상태 한 장과 이력으로 나눈다.**

## 5. 바로 다음 순서

1. **r5 봉인을 보류한다.** 이미 준비된 수정(`feb7bd8`)은 그대로 둔다.
2. **기기에서 Chromium 단독 진단을 한다 (L1, 약 10분).** 사용자가 Termux에서 직접 실행하거나
   Hermes에 이 범위만 허용한다. 임시 프로필과 `about:blank`만 사용한다.
   최소 플래그, 제품 플래그, 플래그별 실행을 한 번에 수행하는 스크립트와 결과 해석표는
   [Chromium 단독 진단](s22u-l1-chromium-probe.ko.md)으로 옮겼다.

3. **원인을 로컬에서 수정한 뒤 L1에서 canonical을 끝까지 돌린다.** 같은 기기, 비봉인,
   원문 로그 보존. 양 backend가 PASS할 때까지 여기서 반복한다. `observe`에 추가된 metadata
   호출 두 번의 지연 시간도 이때 확인한다.
4. **L1 PASS commit으로 L2를 1회 실행한다.** canonical → benchmark. 여기서 처음으로 봉인한다.
5. **메모를 정리한다.** `STATUS.md`(100줄 이내: 현재 HEAD, 마지막 기기 결과, 다음 한 가지,
   동결된 게이트 정의)를 만들고, 세 파일의 과거 층은 `docs/history/`로 옮긴다.
   `acceptance/README.md`와 `progress.md` 배너는 L0 설명으로 고쳐 충돌을 없앤다.
6. **그 다음에 제품으로 돌아간다.** 6절의 범위 결정에 따라 남은 DoD 항목을 진행한다.

## 6. 사용자 결정이 필요한 것

세 항목 모두 2026-11-10에 권장안대로 채택됐다. `task_plan.md`의 Decisions Made에 기록했다.

| 결정 | 권장 | 이유 |
|---|---|---|
| L1 진단 차선을 두고, 합성 fixture·임시 프로필 실행에 한해 원문 stderr를 Mac 쪽에 전달할지 | 허용 | 보호할 실제 데이터가 없는 실행이다. 이것 없이는 3.1과 3.5가 풀리지 않는다 |
| alpha 게이트를 무엇으로 동결할지 | 현재 canonical 단계 그대로 양 backend PASS + 기존 benchmark 기준. 기기 preflight의 unit 전체 실행은 비차단 정보로 격하 | 이미 구현돼 있고 v0.2.20에서 통과한 범위에 action·confidential 검사를 더한 것이다. 더 넓히지 않는다 |
| alpha 범위 | 핵심 루프(읽기·조작·승인·takeover 감지)로 줄이고, 탭·dialog·다운로드 실제 연결, soak, Phase 3 구조 정리는 다음 milestone으로 이동 | 남은 23개 항목을 모두 넣으면 3.6의 재검수가 반복된다. 줄인 범위를 `task_plan.md`의 DoD에 명시한다 |

Chromium 155가 패키지 수준에서 깨져 있다면 네 번째 결정이 생긴다. Chromium 버전을 고정할지,
Firefox 단독으로 alpha를 낼지다. 5절 2번의 결과를 본 뒤에 정하면 된다.

## 부록 — 확인한 방법

- **직접 실행·계산한 것:** 로컬 unit suite(Python 3.14.10, MCP 1.29.0, websockets 17.1),
  commit별 변경량(`git show --numstat`), 파일 크기, Phase·DoD 체크박스 집계,
  `ff62c30..d348616`의 runtime diff, canonical 단계 순서(`scripts/final_verify.py`).
- **수신 증거에서 읽은 것:** v0.2.20 결과와 환경 버전
  (`s22u-v0220-22155ee1d753-results/REVIEW-RESULT.ko.md`), r2의 환경과 단계별 요약
  (`OPS-20261023-r2-public-evidence-43a254707d.zip`).
- **기존 문서에서 인용한 것:** r2–r4의 실패 지점과 로컬 수정 내용
  ([r2](s22u-r2-startup-followup.ko.md), [r3](s22u-r3-confidential-followup.ko.md),
  [r4](s22u-r4-test-discovery-followup.ko.md)), 8–9월 회차의 결과(`progress.md`).
- **확인하지 못한 것:** Chromium 155의 실제 종료 원인. 3.2는 가설이다. websockets는 고정
  버전 17.0.1이 아닌 17.1로 실행했다. 기기에서는 아무것도 실행하지 않았다.
