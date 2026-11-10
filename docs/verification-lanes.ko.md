# 검증 차선과 alpha 게이트 v1

2026-11-10 사용자 승인으로 채택했다. 배경과 근거는
[방향 점검](direction-review-2026-11-10.ko.md)에 있다. 현재 위치는 [STATUS.md](../STATUS.md)를 본다.

이 문서는 **어떤 검증을 어디서, 어떤 엄격함으로 하는지**를 정한다. S22U 실기기 인수는 계속 필수다.
바뀐 것은 원인을 찾는 일과 승인하는 일을 서로 다른 차선에서 한다는 점이다.

## 1. 세 차선

| | L0 로컬 | L1 기기 진단 | L2 기기 인수 |
|---|---|---|---|
| 목적 | 회귀 방지 | **원인 찾기, 수정 확인** | **승인** |
| 장소 | Mac | S22U Termux | S22U Termux |
| 대상 | 작업 중인 tree | 아무 checkout (미커밋·branch 가능) | 사용자 clean commit + 바인딩된 wheel |
| 봉인·authority | 없음 | **없음** | 있음 |
| 반복 | 변경마다 | 원인을 찾을 때까지 | 후보당 1회 |
| 로그 | 전부 | **원문 그대로** (합성 실행 한정) | sanitized 공개 자료 |
| 인수 증거인가 | 아니오 | **아니오** | 예 |

## 2. 차선별 규칙

### L0 로컬

- 변경마다 실행한다.

  ```bash
  .venv_verify/bin/python -B -W error -m unittest discover -s tests
  ```

  ```bash
  .venv_verify/bin/python -B acceptance/acceptance_gate.py
  ```

- 두 번째 명령은 unit suite와 실제 Chrome fixture 10개를 함께 실행한다.
- L0 PASS는 기기 승인이 아니다. L1에 올릴 자격일 뿐이다.

### L1 기기 진단

- **대상에 제한이 없다.** commit, wheel 재빌드, authority, output identity 봉인을 요구하지 않는다.
  같은 checkout을 고쳐 가며 다시 실행해도 된다.
- **원문을 본다.** 임시 프로필로 `about:blank`나 loopback 합성 fixture만 여는 실행의 stderr, stdout,
  assertion 값, traceback은 Mac 쪽으로 그대로 전달한다. 저장소에 커밋하지 않고
  `../Termu-inator-device-artifacts/` 아래에 둔다.
- **가설을 세우고 가른다.** 실행 전에 "무엇을 확인하려는가"와 "결과별 다음 행동"을 한 줄씩 적는다.
  같은 상태에서 같은 실행을 세 번째 반복하게 되면 멈추고 가설을 바꾼다.
- **한 번에 많이 본다.** 첫 실패에서 멈추지 말고 독립적으로 볼 수 있는 항목은 끝까지 수집한다.
- 결과는 인수 증거로 세지 않는다. `progress.md`에 한 항목으로 남긴다.
- **종료 조건:** 같은 checkout에서 L2와 동일한 검수 명령이 양 backend PASS한다.

L1에서도 바뀌지 않는 금지 사항은 다음과 같다.

- 실제 계정·OTP·외부 사이트 제출, 기존 브라우저 프로필 사용.
- 기존 venv·checkout·Hermes 등록·production 설정 변경. L1은 새 경로만 쓴다.
- Tailscale·DNS·proxy 등 네트워크 설정 변경.
- 스스로 띄우지 않은 프로세스 종료, 소유권이 불명확한 lock·socket 삭제.
- 공유 Termux 패키지의 upgrade·downgrade·제거. 필요하면 목록을 보고하고 승인을 받는다.
- timeout·성공 기준 완화.

### L2 기기 인수

- **진입 조건을 모두 만족해야 봉인한다.**
  1. L0 PASS.
  2. 현재 environment epoch에서 L1 canonical이 양 backend PASS.
  3. 사용자 clean commit이 있고, L1 PASS 시점과 runtime·검수기 소스가 같다. 차이는 문서뿐이다.
- 절차는 기존과 같다. commit·tree·wheel·source binding, authority, 새 output identity,
  canonical → 완전 PASS일 때만 benchmark, sanitized 공개 ZIP 반환.
- L2는 **처음부터 통과할 것으로 예상되는 확인 절차**다. 실패하면 다시 봉인하지 말고 L1으로 돌아간다.

## 3. Alpha 게이트 v1 (동결)

`v0.1.0-alpha`의 통과 조건이다. alpha까지 항목을 추가하지 않는다.

### 필수 (차단)

1. **L0 PASS.**
2. **S22U L2 canonical PASS.** `scripts/final_verify.py`가 Chromium과 Firefox 각각에서 다음 단계를
   모두 통과한다.
   `session_start → permission_grant → navigation → observation → form_actions → screenshot →
   artifact_read → artifact_store → artifact_write → action_boundaries → confidential_boundaries →
   session_status → session_stop`.
   현재 구현된 stdio 0-stderr 조건과 후보 소유 자원 cleanup 조건을 포함한다.
3. **S22U L2 benchmark PASS.** `scripts/benchmark_device.py`의 기존 기준이다. median 기준
   status ≤ 300 ms, text ≤ 2,000 ms, screenshot ≤ 4,000 ms, 작업 오류 0, `quality.status=PASS`.
4. **기기 preflight 차단 항목.** Android/Termux identity, commit·tree·wheel·설치 소스 binding,
   `pip check`, import origin 확인([r4 보강](s22u-r4-test-discovery-followup.ko.md)의 origin JSON).

### 보조 (비차단, 기록만)

- 기기에서의 unit suite 전체 실행. 실패는 L1에서 분류하고 canonical 진행을 막지 않는다.
- 전역 Unix socket 목록(`/proc/net/unix`). Android 권한상 `UNAVAILABLE`이 정상이다.
- RSS, cold start 시간, 외부 사이트 smoke, operator 추가 readback.

보조 항목의 `UNKNOWN`·`UNAVAILABLE`은 PASS로 바꾸지 않지만 alpha 판정도 막지 않는다.

### 동결 규칙

- `scripts/final_verify.py`와 `scripts/benchmark_device.py`의 변경은 **L1에서 재현된 결함의 수정**으로
  제한한다. 새 검사, 새 label, 새 증거 수집은 추가하지 않는다.
- 새 검사 아이디어는 `task_plan.md`의 alpha.2 backlog에 적는다.
- 게이트 정의를 바꾸려면 버전을 올리고(v2) `task_plan.md`의 Decisions Made에 사용자 승인과 함께 기록한다.
- L1용 도구(`scripts/l1_*`)는 게이트가 아니다. 작게 유지하고 필요가 끝나면 지운다.

## 4. 환경이 바뀌면 환경을 먼저 본다

environment epoch는 Termux 리셋, 브라우저 major 버전, Python minor 버전 중 하나가 바뀌면 새로 시작한다.
새 epoch에서는 L2 전에 L1에서 다음을 순서대로 확인한다.

1. 제품 밖 브라우저 단독 시작([Chromium 단독 진단](s22u-l1-chromium-probe.ko.md)).
2. 현재 HEAD의 canonical.
3. 버전 표를 [STATUS.md](../STATUS.md)에 갱신.

코드와 환경이 함께 바뀐 상태에서 실패했다면, 둘 중 하나를 고정한 실행으로 먼저 분리한다.

## 5. 증거 등급

| 등급 | 예 | 전달 | 보관 |
|---|---|---|---|
| 합성 진단 자료 | L1의 stderr, traceback, assertion 값 | 원문 그대로 | 저장소 밖 `Termu-inator-device-artifacts/` |
| 공개 증거 | L2 manifest, 요약, checksum | sanitized | 저장소 밖, 요약만 문서에 인용 |
| 비공개 | 실제 계정·프로필·실사이트 내용, 키·토큰·쿠키 | **전달하지 않음** | 기기에만 |

합성 진단 자료에는 Termux 홈 경로와 PID가 들어갈 수 있다. 저장소에 커밋하지 않는 것으로 충분하다.
전달 전에 실제 URL·token·cookie가 없는지만 확인한다.

## 6. 기록 규칙

| 파일 | 담는 것 | 상한 |
|---|---|---|
| [STATUS.md](../STATUS.md) | 현재 위치, 다음 한 가지, 환경, 열린 질문 | 100줄 |
| [task_plan.md](../task_plan.md) | 범위, 설계, DoD, Phase 체크리스트, 결정 | 이력을 쓰지 않는다 |
| [progress.md](../progress.md) | 기기 회차 원장, 최근 작업 항목 | 400줄. 넘으면 오래된 항목을 history로 |
| [findings.md](../findings.md) | 지금도 유효한 사실 | 날짜별 서술을 쓰지 않는다 |
| `docs/history/` | 2026-11-06까지의 원본 | 수정하지 않는다 |

- 상태가 바뀌면 `STATUS.md`를 먼저 고친다.
- 한 작업 항목은 10줄 이내로 쓴다. 해시와 전체 경로는 저장소 밖 증거 디렉터리의 파일에 두고 이름만 적는다.
- 같은 사실을 두 파일에 쓰지 않는다. 다른 파일에서는 링크한다.
