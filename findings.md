# Findings: Termu-inator

**지금도 유효한 사실만** 적는다. 경과는 [progress.md](progress.md), 현재 상태는 [STATUS.md](STATUS.md)에 있다.
2026-11-06까지의 조사 기록 전체는
[docs/history/findings-through-2026-11-06.md](docs/history/findings-through-2026-11-06.md)에 원문 그대로 있다.
아래의 `(L123)`은 그 파일의 줄 번호다.

작성 규칙

- 한 사실은 두세 줄 이내로 쓴다. 더 이상 맞지 않으면 고치거나 지운다.
- 답이 나온 열린 질문은 해당 절의 사실로 옮긴다.

## 열린 질문

1. **Chromium 155가 S22U에서 시작되지 않는 원인.** r2는 `session_start`, r3는 `cdp_ready` 전 종료(코드 -5).
   플래그, 패키지·환경, 제품 시작 경로 중 어느 것인지 모른다.
   [L1 단독 진단](docs/s22u-l1-chromium-probe.ko.md)으로 가른다.
2. **r3 Firefox 수정의 기기 확인.** 탐색 직후 민감 필드 감지 누락은 로컬에서 수정했다. 기기에서는 미확인이다.
3. **`observe`의 지연 시간.** r3 뒤 URL·title 확인 호출 두 번이 추가됐다. S22U에서 다시 재야 한다.
4. **r4 import 충돌의 기기 원인.** 로컬 재현과 오류 14건의 위치가 모두 일치하지만, 기기에서 실제로 선택된
   `tests` 경로는 기록되지 않았다. 다음 기기 실행의 import origin 확인으로 닫는다.
5. **v0.2.20의 추가 readback이 exit 1로 끝난 이유.** stderr를 읽지 않아 모른다. 보조 항목이므로 alpha를 막지 않는다.

## 기기와 환경

- 대상은 Galaxy S22 Ultra, Android 16, aarch64, Termux 0.118.3이다.
- 버전은 Termux 리셋(2026-10-23 이전)을 경계로 달라졌다.

  | | 리셋 전 (v0.2.20 PASS) | 리셋 후 (r2–r4) |
  |---|---|---|
  | Chromium | 149.0.7827.155 | 155.0.8059.79 |
  | Firefox | 154.0.1 | 158.0.1 |
  | Python | 3.14.6 | 3.14.6 |
  | cryptography (Termux native) | 50.0.1 | 50.0.2 |

- **Mac에서 기기로 가는 직접 경로가 없다.** Tailscale ping은 되지만 TCP 22와 8022는 거부된다.
  기기 실행은 사용자가 직접 하거나 기기 안의 Hermes가 한다. 자료는 사용자가 중계한다. (L572, L1136)
- `/tmp`에 쓸 수 없다. `TMPDIR`(`$PREFIX/tmp`)을 쓴다. 테스트와 스크립트에 `/tmp`를 고정하지 않는다. (L1244)
- Chromium은 `TMPDIR`이 없으면 ProcessSingleton socket 디렉터리를 만들지 못해 exit 21로 끝난다.
  제품은 Chromium child 환경에만 `TMPDIR`을 설정한다. (L1158, L1184)
- Unix socket 경로 한도는 제품 기준 100 bytes다. 깊은 출력 경로에서는 control socket이 넘칠 수 있다. (L1222)
- 전역 Unix socket 목록(`/proc/net/unix`)은 권한 오류(EACCES)로 읽을 수 없다. 전역 census 대신
  후보가 소유한 자원의 종료 증거로 판정한다. (L444)
- native `cryptography`는 Termux 패키지를 `--system-site-packages` venv로 사용한다. pip wheel이나 소스
  빌드로 대체하지 않는다. `pkg` 갱신에 따라 버전이 바뀐다. (L1423)
- 리셋 후 준비에서 `pydantic-core` 2.50.x가 소스 빌드 경로로 들어가 `rust`와
  `rust-std-aarch64-linux-android`가 필요했다(r2 준비 1회차). 설치 문서에는 아직 없다.
- Termux 앱 데이터를 리셋하면 `~/.local/state`를 포함해 전부 사라진다. Mac에 받아 둔 자료가 유일한 외부 기록이다.
- 의존성 고정은 `mcp==1.29.0`(protocol `2025-11-25`), `websockets==17.0.1`이다
  (`requirements-termux.txt`). 제약 없이 설치하면 websockets 17.1이 선택된다. (L597)

## Backend

- **Chromium**이 기본 backend다. Xvfb 위에서 CDP로 제어한다. 시작은 다중 프로세스, `--single-process`,
  (VirGL일 때) SwiftShader 순으로 최대 3회 시도하고, 준비 여부는 `/json/version` polling으로 확인한다.
- Chromium의 `Pilot.a11y_tree()`는 legacy 요약 문자열이다. 구조화 노드는 별도 `a11y_nodes()` 경로로 받는다. (L1169)
- **Firefox**는 탐색과 JavaScript 기반 관찰에 loopback WebDriver BiDi를, 입력과 창 캡처에 X11을 쓴다.
  Remote Agent에 붙지 못했을 때만 console·clipboard 경로로 내려간다. (L1373, L1395)
- BiDi를 쓰면 `navigator.webdriver=true`가 된다. 신뢰성을 택한 tradeoff이며 anti-bot 결과는 게이트가 아니다. (L1373)
- `xclip`은 `-quiet`로 띄워야 foreground selection owner가 되어 PID로 정확히 정리할 수 있다. (L1315)
- legacy 탭·dialog·다운로드 명령은 브라우저 이벤트가 아니라 daemon 전역의 주입 JavaScript 로그다.
  그래서 typed service에 연결하지 않았고 alpha.2로 미뤘다. (L787, L1090)
- MCP 서버는 SIGTERM에서도 control socket을 정리해야 같은 data root에서 다시 시작할 수 있다. (L1190)

## 제품 경계

- compact MCP의 interactive profile은 14개 도구, observer profile은 `browser_act`와 `browser_tabs`를 뺀
  12개 도구다. (L1102)
- 권한·승인·takeover를 바꾸는 조작은 CLI와 host 전용이다. MCP에는 읽기 전용 상태만 노출한다. (L914)
- takeover가 필요하거나 진행 중이면 agent의 탐색·관찰·행동·screenshot·artifact·trace·Developer 읽기를
  모두 막는다. takeover를 처음 감지한 응답도 내보내지 않는다. (L265, L932)
- 탐색 직후의 민감 필드 감지는 adapter `navigate()`가 DOM 구조 probe를 함께 반환해야 작동한다. (L53)
- redirect를 따라가기 전의 차단과 DNS/peer enforcement는 없다. origin 권한과 사후 quarantine만 있다.
  그래서 alpha는 통제된 환경으로 제한한다. (L1117)
- 배포 이름은 `termux-browser-pilot` `0.1.0a1`이고 entrypoint는 `tbp`, `tbp-control`,
  `tbp-mcp`(legacy), `tbp-mcp-v1`(compact) 네 개다. commit 제목의 `v.0.2.x`는 배포 버전이 아니며
  순서도 보장되지 않는다. commit은 SHA로 구분한다.

## 검증에서 배운 것

- **Fake backend가 실제 adapter의 계약 불일치를 두 번 가렸다.** 8월의 accessibility 반환 형식과
  r3의 탐색 snapshot이다. service 동작은 실제 adapter 경로의 회귀로 고정한다. (L53, L1169)
- **제품 밖 단독 실행이 가장 빨리 원인을 좁힌다.** 8월 `0007a1e`에서 같은 Chromium 바이너리의 최소
  실행이 성공해 원인을 시작 경로로 좁혔다. (L1147)
- **시간 값 조정으로 추측하지 않는다.** Firefox `address_bar_copy`는 대기 시간 조정 뒤에도 같은 지점에서
  실패했고, 단계별 진단과 구조 변경(BiDi)으로 해결됐다. (L1351, L1373)
- 검수기의 MCP 요청은 고정된 MCP SDK의 실제 입력 검증을 통과해야 한다. nullable 필드도 명시한다. (L150)
- fixture의 `<button>`에는 type을 명시한다. 기본값 `submit`은 승인이 필요한 행동으로 분류된다. (L111)
- `tests/`는 `__init__.py`가 있는 일반 패키지여야 한다. 없으면 site-packages의 다른 `tests`가 가린다. (L3)
- wheel은 추적 파일만 복사한 빈 staging tree에서 빌드한다. 무시된 `build/`가 재사용된 wheel은 무효다.
- 설치 provenance는 pip로 설치해 확인한다. uv는 PEP 610의 `archive_info.hashes`를 남기지 않는다.
- checkout 안에서 배포 metadata를 조회하면 `.egg-info`가 설치본보다 먼저 잡힌다. 다른 cwd에서 조회한다.

## 작업 환경 (Mac)

- 관리형 sandbox 안에서는 loopback TCP와 Unix socket bind가 거부되어 socket 테스트 15개 안팎이 실패한다.
  제품 문제가 아니다. 로컬 socket 권한이 있는 환경에서 같은 명령을 다시 실행한다.
- macOS 기본 `python3`는 3.9라 문법 오류가 난다. `.venv_verify/bin/python`처럼 3.10 이상을 명시한다.
- `.venv_verify`는 Python 3.14.10, MCP 1.29.0, websockets 17.1이다. websockets가 고정 버전과 다르다.
- macOS의 임시 경로는 길어서 Unix socket 경로 한도를 넘기기 쉽다.
- sandbox에서 DNS가 막히면 pip 설치가 실패한다. 네트워크가 허용된 환경에서 다시 실행한다.
- code graph는 `scripts/`와 `docs/`를 색인하지 않는다. 이 두 곳은 파일을 직접 읽는다.
