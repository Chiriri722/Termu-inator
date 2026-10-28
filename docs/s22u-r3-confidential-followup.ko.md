# S22U r3 후속 보강: 민감 페이지 탐색과 고정 실패 진단

2026-10-28 갱신. **로컬 수정 검증 완료 / Chromium 시작 원인 미확정 / S22U 미승인**.
이 문서는 결과 보고서이며 새 기기 실행 승인서가 아니다.

## r3 결과와 전송 무결성을 확인했다

| 항목 | 확인값 |
| --- | --- |
| Commit | `5cc585d6e721b3670f223c1615124908a9692e3d` (`v.0.2.44`) |
| 운영 회차 / run | `OPS-20261023-r3` / `44r30110b1` |
| ZIP | `OPS-20261023-r3-public-evidence-44r30110b1.zip`, 29,523 bytes |
| ZIP SHA-256 | `f78916d3fc3908d978a4dd4facf31a85e064d533e312980ab188f82d69fd2682` |
| Canonical manifest SHA-256 | `847ce068a3c04966d17eacd810dbafad78a7e31d1db10b306a597a240a7be65a` |

CRC, 안전한 regular member 18개, 내부 manifest의 payload 17개 크기·해시,
checksum 목록 5개를 검증했다. Downloads 원본과 이전 봉인 자료를 보존하고,
저장소 밖의 별도 owner-private 분석 디렉터리에 사본과 수신 확인서를 남겼다.
수신 ACK는 전달 확인이지 제품 승인이 아니다.

- Chromium: `session_start / cdp_ready / process_exited / process_returncode=-5`.
  이 기록만으로 구체적인 Chromium 종료 원인을 확정할 수 없다.
- Firefox: `confidential_boundaries / VerificationFailure`. 후속 정적 진단으로
  `REFUSED_CALL_CODE_MISMATCH`, `browser_navigate`, 기대 코드 `session_paused`가
  확인됐다. 실제 반환 code 또는 비-error 응답은 `UNKNOWN_NOT_PRESERVED`다.
- 양 backend post-stop, observer restart, 최종 census와 독립 확인은 PASS다.
  후보 survivor·귀속 불명 프로세스·Singleton entry·filesystem socket은 모두 0이다.
  이는 이번 run에서 관측한 범위이며 전역 프로세스/소켓 증명이 아니다.
- Outer verifier stderr는 0 bytes지만 interactive MCP stderr는 **359 bytes**다.
  Observer stderr는 0이다. 서로 다른 stream을 합치거나 내용을 추정하지 않는다.
- Canonical FAIL / benchmark NOT_RUN / NEEDS_CODE_FIX를 유지한다.

## 탐색 직후 민감 필드를 놓치는 결함을 재현했다

기존 `LegacyPilotBackend.navigate()`는 URL·title만 반환하고
`interactive_elements`를 비웠다. `BrowserService.navigate()`는 그 snapshot에서
비밀번호·OTP 필드를 찾아 takeover를 요구하므로, 실제 adapter 경로에서는 이
감지가 작동하지 않았다. 반면 기존 verifier 테스트의 FakeBackend는 탐색 결과에
필드를 미리 넣어 주어 결함을 놓쳤다. 두 adapter에 공통인 계약 불일치다.

회귀 테스트를 먼저 추가해 다음 실패를 확인했다.

- 탐색 결과의 구조화된 필드가 0개였다.
- 비밀번호·OTP로 이동해도 `session_paused`를 반환하지 않았다.
- DOM 구조 확인이 실패하도록 해도 탐색 성공을 반환했다.

수정은 탐색 완료 후 기존의 값 읽기 없는 DOM 구조 probe를 실행하고 그 결과를
navigation snapshot에 포함한다. 본문·접근성 트리·스크린샷을 추가 요청하지 않는다.
Firefox의 검증된 native URL/title 경로도 유지한다. 구조 probe 실패는 성공으로
처리하지 않고 `operation=goto / stage=navigation_dom`으로 구분한다.
기존 Firefox 구조 probe의 제한된 재시도 수, timeout, 승인 정책은 늘리거나 완화하지 않았다.

새 실제 브라우저 회귀는 Chrome/CDP로 fixture를 읽고 실제 adapter·service·MCP router를
거쳐 canonical confidential helper 전체를 실행한다. 임시 profile과 loopback fixture만
사용하며, 별도의 S22U/Firefox 실행이라고 부르지 않는다.
변경 없는 r3 checkout에서도 이 새 회귀를 실행하여 정확히
`browser_navigate did not return session_paused` 실패를 재현했다. 해당 checkout은
계속 clean이며 수정본에서는 같은 실제 브라우저 경로가 PASS다.
후속 정적 진단이 확인한 기기 assertion도 같은 탐색 거부 경계다. 다만 당시 실제
반환값은 보존되지 않았으므로, 로컬 재현의 성공 응답과 기기의 응답을 동일시하지 않는다.

## confidential 실패의 위치와 실제 오류를 보존한다

검수기에 다음 폐쇄형 label을 추가했다.

- `assertion`: 예상된 거부, 상태 전이, paused metadata, 도구 목록, origin 정책,
  fixture 이동/관찰, prompt 텍스트, takeover 시작/재개/식별자 검증 등 고정 검사명.
- `fixture`: setup / prompt_injection / login / otp.
- `phase`: active / required / takeover / resumed.
- `expected_code`, `observed_result`: 고정된 기대 코드와 success / mcp_error.

이전 `refused()`는 기대와 다른 MCP 오류를 잡은 뒤 코드를 버렸다. 이제 원래
오류와 허용된 backend/operation/stage/code를 보존한다. 성공 응답인데 거부가
필요했던 경우도 별도로 식별한다. 임의 메시지·URL·credential·challenge ID는
공개 context로 복사하지 않으며 JSON과 한국어 요약 모두 같은 allowlist를 적용한다.
검수 성공 조건과 cleanup 판정은 변경하지 않았다.

## 로컬 검증과 증거 경계

TDD의 실패 재현 → 최소 수정 → 관련 검사 → 전체 검사 순서로 진행했다.

- 탐색 회귀: 수정 전 3개 test의 8개 subcase 실패 확인, 수정 후 adapter/handoff
  관련 **32/32 PASS**.
- confidential 진단: 수정 전 검사 위치 누락·오류 코드 소실을 9개 subcase에서
  확인. 수정 후 verifier/census/release-flow 관련 **35/35 PASS**.
- 실제 격리 Mac Chrome fixture: **10/10 PASS**. 같은 회귀를 변경 없는 r3에서
  실행하면 기대한 navigation refusal 실패가 발생한다.
- 첫 보강의 전체 Python **3.14.7**, MCP **1.29.0**, websockets **17.0.1**:
  **648/648 PASS, skip 0**. 기존 opt-in Chrome 검사를 켠 결과이며 새 skip은 없다.
- 기존 startup·Singleton·lifecycle 회귀도 전체 검사에 포함했다. 새 브라우저 flag,
  timeout 증가, Singleton 수동 삭제, S22U 재실행은 하지 않았다.

Mac 테스트 통과는 Android 16 / Chromium 155 시작 성공이나 S22U 승인 증거가 아니다.
새 wheel·authority·기기 실행은 아직 없으며 commit/push도 수행하지 않았다.

## 후속 실패 경로도 확인했다

연속 점검에서 navigation 실패 이후의 원격 읽기와 로컬 재개를 추가로 재현했다.
브라우저는 이미 이동했지만 구조 확인이 실패한 경우, 이전 page context로
스크린샷을 요청할 수 있었다. 또한 takeover 재개가 새 origin에 대한 허가를
확인하지 않아, 로컬 제어 시작을 origin 승인처럼 취급했다.

- backend에 탐색을 전달한 시점부터 결과·최종 origin 검증까지 원격 제어를
  일시 중지한다. 오류·timeout·취소·잘못된 응답이면 중지 상태를 유지한다.
  원래 오류 코드와 취소는 보존한다. 전달 전 입력·context·origin 거부는 기존처럼
  browser를 건드리지 않고 현재 세션을 유지한다.
- `observe`가 실제 URL·title을 다시 읽도록 했다. 실패한 탐색 전의 캐시나
  로컬 조작 전의 origin으로 재개를 판단하지 않는다. metadata 확인 실패도
  `adapter_metadata`로 구분하며 성공으로 바꾸지 않는다.
- 로컬 재개는 현재 HTTP(S) origin의 기존 permission 정책을 검사한다. 새 origin의
  허가가 없으면 local takeover 상태를 유지하고, 별도 승인 뒤 다시 재개할 수 있다.
- 기존 테스트 3건의 암묵적인 fixture-origin 허가를 명시적 로컬 승인으로 바꿨다.
  제품의 permission 기준을 느슨하게 하거나 검사를 제외하지 않았다.

추가 4개 회귀의 실패를 확인한 뒤 수정했다. adapter·navigation·takeover·dialog·
confidential 관련 **52/52 PASS**, 최종 전체 **652/652 PASS, skip 0**다.
이 결과도 실제 격리 Mac Chrome 검사를 포함하지만 S22U 실행은 아니다.
이 단계의 13개 경로는 사용자가 `c0e463f3007fc94d9f9ab99c2a37feafbd7adc1f`
(실제 subject `v.0.2.35`)로 커밋했다. 제목의 버전 숫자 대신 exact SHA로 구분한다.
이 커밋에는 아래의 후속 startup 진단 보강은 아직 포함되지 않는다.

`status`는 계속 메모리 캐시만 읽는다. `observe`에는 URL/title 확인 호출 두 번이
추가됐으므로 S22U의 응답 시간은 아직 검증되지 않았다. 기존 latency 기준은 그대로
유지하고 다음 승인된 candidate에서 측정한다. 새 timeout이나 재시도는 추가하지 않았다.

## 두 정적 진단의 수신을 완료했다

| 파일 | bytes | SHA-256 |
| --- | ---: | --- |
| `r3-static-diagnostic-44r30110b1.sanitized.json` | 3,772 | `bb66eb9b63dc1c2986e2dde1b1a23126f39dd2cd938ee00a2b185646f13cb866` |
| `r3-static-middle-44r30110b1.sanitized.json` | 4,049 | `5dd77002f3ee7012df43007fe3495f65316841b1a3c17ec16cb8efe284964e8d` |

두 파일 모두 같은 commit/run/manifest에 귀속되고 전달된 hash와 일치한다.
Downloads 원본은 보존했다. 새 owner-private 사본도 원본과 byte-for-byte 일치한다.
기기 파일의 권한·소유권은 Hermes의 보존된 관측이며 Mac에서 다시 측정한 값은 아니다.

같은 5,671-byte Chromium 로그의 앞·뒤와 빠진 중간 구간을 합쳐 전체 보존 내용이
검사됐다. 중간의 ERROR 3개는 DBus 연결/메서드 실패 및 고정 category 불명으로
분류됐지만, attempt linkage나 종료 원인은 기록되지 않았다. FATAL/CHECK·명시적
errno도 확인되지 않았다. `cause=UNKNOWN_NOT_RECORDED`를 유지하며 같은 로그를
다시 요청하지 않는다. DBus 패키지 설치나 sandbox/GPU/crashpad flag 변경의 근거가 아니다.

## 실패 당시 값과 정리 후 값을 분리했다

exact r3의 `_finish_failed_chromium_attempt()`는 `stop_owned_process()` **후**의
returncode만 private header에 기록했다. 따라서 multi-process `0`은 정상적인 CDP
시작이나 정리 전 정상 종료를 증명하지 않는다. 마지막 실패의 공개 label만 남아 첫
시도의 readiness 실패 정보도 fallback을 지나면서 사라졌다.

5개 신규 테스트의 18개 실패 assertion을 확인한 뒤 최소 수정했다.

- 기존 최대 3회 시도에 고정 mode/stage/reason/exception type과 허용된 errno를 남긴다.
- `process_returncode`는 실패 시점에 관측된 값만 기록한다. 종료를 관측하지 못했으면
  `exit_state=not_observed`로 표시하고 숫자를 만들지 않는다.
- owned cleanup이 완료된 후의 코드는 별도 `cleanup_returncode`다. timeout을 종료
  코드 `0`이나 강제 종료 코드로 바꿔 해석하지 않는다.
- 최종 오류에 `attempt_1_*`부터 `attempt_3_*`까지 보존한다. 후속 spawn 실패에도
  완료된 앞 시도의 기록을 유지한다. 강제 single-process의 mode 오표기도 바로잡았다.
- adapter → MCP → canonical manifest → 한국어 요약은 같은 고정 allowlist와 숫자
  범위를 적용한다. raw stderr·PID·경로·환경값은 공개하지 않는다.

실제 Python child의 readiness 실패 → SIGTERM 정상 종료 `0`, 뒤 시도의 exit `22/23`,
강제 single-process, 후속 PermissionError와 공개 필드 제한을 검사했다. 이는 실제
프로세스 수명주기 회귀이며 Chromium의 원인 재현이나 Android 실행은 아니다.

관련 startup/Singleton/lifecycle **65/65 PASS**, 실제 격리 Mac Chrome fixture를 포함한
전체 **657/657 PASS, skip 0**다. Python 3.14.7 / MCP 1.29.0 / websockets 17.0.1을 사용했다.
실행 옵션·timeout·fallback 횟수·성공 조건·cleanup 판정은 유지했다. 코드 구조는
`codebase-memory`의 갱신된 graph/coverage와 직접 소스로 대조했으며, 인덱스에서
제외된 `scripts/final_verify.py`는 실제 파일을 읽어 확인했다.

## 다음 후보는 진단 보강 후보이며 아직 기기 승인이 아니다

현재 `c0e463f3…` 대비 후속 변경은 코드·테스트 3개와 기록 4개, **7개 경로**다.
assistant의 commit/push, 새 wheel·authority, 기기 실행은 없었다.

1. 이번 7개 경로가 포함된 새 clean commit SHA를 확인한다.
2. 해당 SHA로 새 wheel을 빌드·source-bind하고 새 authority/runbook/output identity를
   봉인한다. 기존 r3 wheel·남은 예산·소비된 output identity는 재사용하지 않는다.
3. 새 후보에서 전체 preflight와 fresh S22U canonical을 실행한다. 실패하면 앞/뒤 시도의
   고정 진단과 cleanup을 보존한다. 같은 상태 재시도나 근거 없는 환경 변경은 하지 않는다.
4. 모든 canonical 조건이 통과한 경우에만 benchmark로 진행한다. 특히 observe의
   추가 metadata 호출 비용은 기존 기준으로 다시 측정해야 한다.

Chromium의 구체적인 종료 원인은 아직 미확정이다. 보강된 진단을 제품 시작 문제의
해결로 승격하지 않으며, 다음 실행도 실패할 가능성을 전제로 정확한 증거를 수집한다.

사용자가 확정한 S22U 필수 검수 기준을 유지한다. `acceptance/`의 local-only
기준이나 로컬 PASS로 기기 검수·benchmark·production 전환을 대체하지 않는다.
