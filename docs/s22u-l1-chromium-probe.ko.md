# S22U L1 진단 — Chromium 단독 시작 확인

2026-11-10. **L1 진단이며 인수 증거가 아니다.** 차선 규칙은 [검증 차선](verification-lanes.ko.md)을 따른다.
봉인, authority, 실행 예산이 필요 없고 여러 번 실행해도 된다.

## 확인하려는 것

Termux 리셋 뒤 Chromium이 149에서 155로 바뀌었고, 그 뒤 r2와 r3에서 Chromium이 시작되지 않았다
(`cdp_ready` 전 종료, 코드 -5). 원인 후보는 셋이다.

| 가설 | 뜻 |
|---|---|
| H1 플래그 | Chromium 155가 `src/browser.py`의 시작 플래그 중 일부에서 스스로 중단한다 |
| H2 패키지·환경 | Chromium 155 패키지가 이 기기에서 어떤 구성으로도 뜨지 않는다 |
| H3 제품 시작 경로 | 단독 실행은 정상이고, 제품의 시작·준비 확인 순서에 문제가 있다 |

이 진단은 제품 코드를 거치지 않고 Chromium만 띄워 세 가설을 한 번에 가른다.
새로운 방법이 아니다. 2026-08-25의 `0007a1e` 회차에서도 같은 바이너리의 단독 실행이 성공한 것을
근거로 원인을 제품의 시작 경로로 좁혔고, 이어 `TMPDIR` 누락 시 ProcessSingleton 실패(exit 21)를 찾아냈다.

## 실행

`scripts/l1_chromium_probe.sh` 파일 하나만 있으면 된다. 저장소 checkout, venv, wheel이 필요 없다.

```bash
bash scripts/l1_chromium_probe.sh
```

- 소요 시간은 보통 1~3분이다. 플래그를 하나씩 확인하는 경우 최대 7분 정도 걸린다.
- 스크립트는 새 임시 디렉터리(`$TMPDIR/chr-probe.XXXXXX`)에만 쓴다.
- Xvfb를 `:97`에 직접 띄우고 끝나면 자기가 띄운 것만 종료한다.
  `:97`이 사용 중이면 `TBP_PROBE_DISPLAY=:96`처럼 바꾼다.
- 기존 프로필, venv, Hermes 등록, 네트워크 설정을 건드리지 않는다. 외부 사이트에 접속하지 않는다.

스크립트가 하는 일은 다음과 같다.

| 실행 | 구성 |
|---|---|
| A-minimal | `--no-sandbox`만 |
| B-product | 제품의 다중 프로세스 시작 플래그 전체 |
| C-product-single | B에 `--single-process` 추가 (제품의 fallback) |
| D-headless | `--no-sandbox --headless=new` (참고용) |
| E-product-isolated | B와 같은 플래그. `HOME`과 `TMPDIR`을 검수기처럼 전용 경로로 격리 |
| F01… , FGL | A는 뜨고 B가 안 뜰 때만. `--no-sandbox`에 제품 플래그를 하나씩 얹는다 |

각 실행은 `about:blank`를 열고 `/json/version` 응답을 최대 20초 기다린 뒤 한 줄로 기록한다.

```text
B-product          state=exited cdp_ready=no  exit=133 waited=2s stderr_bytes=812
```

`cdp_ready=yes`면 정상 시작이다. `exit=133`은 SIGTRAP(128+5)이고 r3의 -5와 같은 신호다.
시작하지 못한 실행은 stderr 마지막 15줄이 함께 기록된다.

## 돌려받을 것

출력 마지막 줄 `output_dir=`에 있는 **`summary.txt` 한 파일**을 그대로 전달한다.
합성 실행의 원문 stderr가 들어 있으며, 이번부터 전달을 허용한다. sanitize하지 않는다.
더 필요하면 같은 디렉터리의 `*.err` 원본을 추가로 요청한다.

## 결과 해석

| A | B | C | E | 결론 | 다음 작업 |
|---|---|---|---|---|---|
| yes | yes | 무관 | yes | H3. 단독 실행은 정상 | 현재 HEAD로 제품 Chromium 세션 시작을 L1에서 실행하고 원문 로그를 본다 |
| yes | yes | 무관 | no | H3. 격리된 `HOME`·`TMPDIR`에서만 실패 | E의 stderr를 읽는다. 검수기가 넘기는 `TMPDIR` 경로와 singleton socket 위치를 확인 |
| yes | no | yes | 무관 | H1. 다중 프로세스 구성만 실패 | F 결과의 원인 플래그를 `src/browser.py`에서 수정. fallback이 왜 못 살렸는지도 확인 |
| yes | no | no | 무관 | H1. 공통 플래그 문제 | F 결과에서 `cdp_ready=no`인 플래그를 제거하거나 대체 |
| no | no | no | no | H2. 패키지·환경 문제 | A의 stderr를 읽는다. Chromium 버전 고정, 패키지 재설치, Firefox 단독 alpha 중 결정 |

F 실행이 모두 `yes`인데 B만 `no`라면 플래그 조합의 문제다. 그때는 B에서 플래그를 반씩 빼는
실행을 한 번 더 한다.

원인을 고친 뒤에도 L1에 머문다. 같은 기기에서 현재 HEAD의 canonical을 비봉인으로 끝까지 실행해
양 backend가 통과하는지 확인하고, 그 다음에 L2를 봉인한다.

## Hermes에 전달할 문장

사용자가 Termux에서 직접 실행해도 되고, 아래 문장과 스크립트 파일을 Hermes에 전달해도 된다.

```text
[L1 진단 요청 — 인수 회차 아님, 예산 차감 없음]
첨부한 l1_chromium_probe.sh를 새 임시 경로에 저장하고 `bash l1_chromium_probe.sh`를 1회 실행해 주세요.
- 목적: 제품 코드 없이 Chromium 155 단독 시작 여부와 원인 플래그 확인.
- 범위: 임시 프로필과 about:blank만 사용. 스크립트가 띄운 Xvfb/Chromium만 종료.
- 금지: 기존 checkout·venv·프로필·Hermes 설정·네트워크 변경, 패키지 설치/업그레이드, 다른 프로세스 종료.
- 반환: 출력의 output_dir 안 summary.txt 원문 그대로(이번 합성 실행은 stderr 원문 전달 허용).
- :97 display가 사용 중이면 TBP_PROBE_DISPLAY=:96 으로 다시 실행.
- canonical·benchmark·OPS 예산과 무관합니다. 실패해도 재시도·수정하지 말고 summary.txt만 반환해 주세요.
```

## 확인 범위

스크립트의 판정 로직은 Mac에서 가짜 실행 파일로 네 경우(전부 정상, 특정 플래그에서 SIGTRAP,
항상 SIGTRAP, 살아 있지만 CDP 미준비)를 확인했다. **Termux의 실제 Chromium과 Xvfb로는 실행해 보지
않았다.** 첫 실행에서 스크립트 자체가 실패하면 그 출력을 그대로 돌려받아 고친다.
