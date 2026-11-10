# STATUS — Termu-inator

갱신: 2026-11-10. **현재 상태의 기준 문서다.** 상태가 바뀌면 이 파일을 먼저 고친다. 100줄을 넘기지 않는다.

## 지금

| 항목 | 값 |
|---|---|
| 단계 | **L1 기기 진단 대기** |
| 다음 한 가지 | S22U에서 `bash scripts/l1_chromium_probe.sh` 실행, `summary.txt` 회수 |
| 막힌 지점 | Termux 리셋 뒤 Chromium 155가 기기에서 시작되지 않는다. 원인 미확인 |
| 코드 기준 commit | `feb7bd8` (`v.0.2.36`). 그 뒤의 변경은 2026-11-10 문서 재구성뿐 |
| L0 로컬 | PASS. unit 659개 OK(opt-in skip 1), 실제 Chrome fixture 10개 PASS (2026-11-10) |
| 마지막 L2 PASS | `22155ee` (`v0.2.20`, 2026-09-22). 리셋 전 환경 |
| 리셋 후 기기 결과 | r2·r3 Chromium 시작 실패, r3 Firefox는 마지막 기능 단계에서 실패(로컬 수정 완료), r4 preflight 실패(수정 commit 완료) |

## 다음 순서

1. **L1: Chromium 단독 진단.** [절차와 해석표](docs/s22u-l1-chromium-probe.ko.md).
   사용자가 Termux에서 직접 실행하거나 Hermes에 전달한다. 봉인과 예산이 필요 없다.
2. **원인 수정.** 결과에 따라 `src/browser.py`의 플래그를 고치거나, 제품 시작 경로를 L1에서 재현하거나,
   패키지 문제라면 Chromium 버전 고정 또는 Firefox 단독 alpha를 결정한다.
3. **L1: 현재 HEAD canonical.** 같은 기기에서 비봉인으로 `scripts/final_verify.py`를 끝까지 실행한다.
   양 backend가 통과할 때까지 L1에서 반복한다. 원문 로그를 본다.
4. **L2: 봉인 인수 1회.** L1에서 통과한 commit으로 canonical → benchmark.
5. **alpha 릴리스 정리.** 문서 최종 검토, 알려진 제한 명시, 버전·changelog, release artifact.

r5를 봉인해서 보내지 않는다. 1번과 3번이 끝나기 전의 봉인은 같은 지점에서 다시 실패할 가능성이 높다.

## 기기 환경

environment epoch `s22u-a16-20261023-3ac540c0` (Termux 리셋 후). Galaxy S22 Ultra, Android 16, Termux 0.118.3.

| | 리셋 전 (v0.2.20 PASS) | 현재 |
|---|---|---|
| Chromium | 149.0.7827.155 | **155.0.8059.79** |
| Firefox | 154.0.1 | **158.0.1** |
| Python | 3.14.6 | 3.14.6 |
| cryptography | 50.0.1 | 50.0.2 |
| MCP / websockets | 1.29.0 / 17.0.1 | 1.29.0 / 17.0.1 |

Mac에서 기기로 가는 직접 경로는 없다. 사용자가 자료를 중계한다.

## Alpha 게이트 v1 (동결)

전체 정의는 [검증 차선과 alpha 게이트](docs/verification-lanes.ko.md)에 있다.

- 필수: L0 PASS, S22U L2 canonical 양 backend PASS, L2 benchmark PASS, 기기 preflight의 binding·import origin.
- 보조(비차단): 기기 unit suite 전체 실행, 전역 Unix socket 목록, RSS, cold start, 외부 사이트 smoke.
- alpha까지 필수 항목을 추가하지 않는다. `scripts/final_verify.py`와 `scripts/benchmark_device.py`는
  L1에서 재현된 결함만 고친다.

| 필수 항목 | 상태 |
|---|---|
| L0 | PASS (2026-11-10) |
| L1 canonical, Chromium | 미실행. 시작 실패 진단 대기 |
| L1 canonical, Firefox | 미실행. r3 수정의 기기 확인 대기 |
| L2 canonical | 미실행 |
| L2 benchmark | 미실행 |

## Alpha 범위

핵심 루프만 alpha에 넣는다. 읽기, 안전한 조작, 민감 입력 감지와 owner 재개, 승인이 필요한 행동이다.
탭·popup·dialog·다운로드의 실제 연결, SSH 원격 round-trip, soak·crash 복구, 구조 정리는 alpha.2다.
항목별 구분은 [task_plan.md](task_plan.md)의 Definition of Done과 Phases에 있다.

## 열린 질문

1. Chromium 155 시작 실패의 원인 (플래그, 패키지·환경, 제품 시작 경로).
2. r3 Firefox 수정이 기기에서 통과하는지.
3. `observe`에 추가된 metadata 호출 두 번의 S22U 지연 시간.
4. r4 import 충돌의 기기 쪽 원인. 다음 실행의 import origin 확인으로 닫는다.

상세는 [findings.md](findings.md)의 "열린 질문"에 있다.

## 코드 기준

runtime(`src/`), 검수기(`scripts/final_verify.py`, `scripts/benchmark_device.py`), `tests/`는 `feb7bd8` 그대로다.
2026-11-10의 변경은 문서, `scripts/l1_chromium_probe.sh`, `acceptance/`의 설명 문구뿐이다.
commit과 push는 사용자가 한다.

## 문서 지도

| 알고 싶은 것 | 문서 |
|---|---|
| 지금 어디이고 다음은 무엇인가 | 이 파일 |
| 어떤 검증을 어떤 엄격함으로 하는가 | [docs/verification-lanes.ko.md](docs/verification-lanes.ko.md) |
| 범위, 설계, 완료 기준, 결정 | [task_plan.md](task_plan.md) |
| 최근 작업과 기기 회차 원장 | [progress.md](progress.md) |
| 지금도 유효한 사실 | [findings.md](findings.md) |
| 왜 이렇게 바꿨는가 | [docs/direction-review-2026-11-10.ko.md](docs/direction-review-2026-11-10.ko.md) |
| 2026-11-06까지의 원본 기록 | `docs/history/` |
| 기기 수신 자료 | 저장소 밖 `../Termu-inator-device-artifacts/` |
