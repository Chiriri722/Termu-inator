# S22U r2 시작 실패 보강 — 로컬 수정 결과와 다음 검수 조건

2026-10-23. 상태: **LOCAL_FIXED / S22U 미검증 / 새 SHA 대기**.
이 문서는 결과 설명이며 실행 승인서가 아니다. 새 commit·wheel·authority가
봉인되기 전에는 기존 후보를 다시 실행하거나 이 문서를 설치 지시로 사용하지 않는다.

## 수신 증거와 확정 범위

| 항목 | 확인값 |
| --- | --- |
| 기존 commit | `d3486161af763455e0ad6cdc45e9f0790b8e15cf` (`v.0.2.43A`) |
| 운영 회차 / run ID | `OPS-20261023-r2` / `43a254707d` |
| ZIP | `OPS-20261023-r2-public-evidence-43a254707d.zip`, 36,805 bytes |
| ZIP SHA-256 | `b5b13f22d47a7baccdc1ee802521ed5539480b4507b932eb784b40b51e2c8406` |
| Manifest SHA-256 | `075f5c567494ad569266b1b77bcad42b558e842f0ce383de2f42a3e992c36be6` |

ZIP의 CRC, 안전한 regular member 20개, 내부 manifest가 지정한 payload 19개의
크기·SHA-256, 내부 checksum 목록 6개를 확인했다. Downloads 원본과 과거 봉인
자료는 그대로 두고 별도의 owner-private 분석 디렉터리에 검증 사본을 보존했다.

Chromium은 `browser_session_start` / `backend_crashed`에서 실패했다.
실제 OS crash, errno, Xvfb 문제, permission, CDP 준비 timeout 중 어느 것인지는
기존 공개 증거로 확정할 수 없다. 중간 census의 신규 2개 프로세스는 귀속 불명이며,
이를 임의로 Chromium 잔존 또는 무관한 프로세스로 분류하지 않는다. Firefox SKIPPED,
PNG 없음, benchmark NOT_RUN과 기존 NEEDS_CODE_FIX 판정을 유지한다.

중요한 구분: **outer verifier stderr는 0 bytes지만, manifest의
`device.stdio.interactive.stderr_bytes`는 352**다. 두 stream을 혼동하지 않는다.
352 bytes의 내용은 전달받지 않았고 열람·추정하지 않았다.

## 구현한 변경

### 시작 오류를 고정된 공개 사실로 전달

`BrowserStartupError`에 binary resolution, display allocation, Xvfb spawn/ready,
window manager, GPU, profile, Chromium spawn, CDP ready, session initialization,
singleton cleanup 단계를 구분했다. adapter → MCP → canonical manifest/한국어
요약까지 allowlist를 통과하는 label만 전달한다.

- 공개 필드: backend, operation, stage, reason, 제한된 exception_type.
- errno는 정수 1–4095, process_returncode는 정수 -255–255만 허용한다.
  bool·문자열·범위 밖 숫자는 거부한다. 경로·PID·stderr·임의 예외 문구는 공개하지 않는다.
- 준비 timeout은 `timeout`; 실제 종료 여부는 별도 `process_exited`와 관측된 코드다.
- 종료 코드는 정리 전에 확보한다. 정리 과정의 SIGTERM/SIGKILL을 원래 crash로 기록하지 않는다.
- 기존의 제한된 CDP 호환 모드 fallback 수는 늘리지 않는다. 소유권 실패에는 fallback하지 않는다.
- 원래 Python 예외의 cause와 취소 전파, 실패 시 소유 핸들 보존 계약을 유지한다.

### Singleton 정리는 새 실행의 소유권을 입증한 경우만

기존 `_clear_profile_locks()`의 무조건적인 세 파일 삭제를 제거했다.
시작 전에 profile의 기존 singleton을 인수하지 않고, private directory identity,
직접 실행한 child PID, hostname-PID lock, 양쪽 cookie, socket type/identity를 묶어 확인한다.
자식이 reap됐고 PID가 현재 비활성이며, 직접 socket probe가 `ECONNREFUSED`인
경우에만 캡처한 항목을 directory-relative unlink로 정리한다. private remote
directory도 예상한 항목만 있고 비었을 때만 제거하며 persistent profile은 보존한다.

살아 있는 socket, liveness UNKNOWN, PID 재사용, cookie/PID 불일치, symlink parent,
directory/entry 교체, 추가 파일, 기존 profile singleton은 삭제하지 않는다.
이 경우 정상 cleanup이나 다음 compatibility launch로 승격하지 않는다.
현재 구현의 정리 범위는 **실행 시 지정한 TMPDIR 아래 직접 자식 directory**다.
그 밖의 socket은 추측해 인수하지 않는다. 부분 생성되어 binding이 불완전한 항목도 보존한다.

이 binding은 Chromium의 [POSIX singleton 구현](https://chromium.googlesource.com/chromium/src/+/main/chrome/browser/process_singleton_posix.cc)
에서 확인한 PID lock·profile/remote cookie·temporary socket 구성을 따른다.
기기에서 사용한 Chromium 빌드가 동일하게 동작했다는 증거로 쓰지는 않는다.

### MCP 호출 중에도 소유 관계 관측

긴 MCP RPC의 전후에만 관측하던 방식에, pending 중 100 ms 간격의 관측을 추가했다.
부모가 종료되고 자식이 reparent되기 전에 보인 PID/start_ticks 관계를 보존한다.
요청 취소 시 관측과 요청 task도 정리한다. RPC timeout이나 canonical 재시도 수는 늘리지 않는다.

**이는 sampled ancestry다.** 모든 후손을 포착하는 OS containment가 아니며,
보이지 않은 프로세스는 계속 UNKNOWN이다. 과거 귀속 불명 2개를 소급해서 분류하거나
프로세스 이름·새 PID 목록만으로 kill 권한을 부여하지 않는다.

## 로컬 검증

TDD 순서로 실패를 먼저 확인하고 수정했다. 시작/관측 첫 7개 검사는 5개 의도된
실패와 2개 보존 검사 통과였고, singleton 첫 4개도 모두 의도대로 실패했다.
이후 디렉터리 교체, PID 재사용, 권한 오류의 errno 보존, 취소가 오래된 오류
metadata로 덮이는 경우와 불필요한 호환 재시도를 추가로 재현해 보강했다.

- 최종 focused 시작·singleton·lifecycle·adapter·verifier: **194/194 PASS**.
- 전체 Python 3.14.7 + pinned MCP 환경: **638/638 PASS, skip 0**.
  기존 opt-in 실제 Chrome fixture도 활성화한 실행이다. 이번에 추가한 회귀는 22개다.
- 보조 Python 3.11.15: **638개 실행, 617 PASS / 21 skip**.
  선택 의존성/실제 브라우저 opt-in이 없는 보조 환경이며 S22U skip 허용 확대가 아니다.
- 실제 격리 Mac Chrome 폼 fixture: **10/10 PASS**.
- 실제 Mac Chrome 시작/정리 probe: CDP ready, singleton capture, child reap,
  profile singleton 부재, 캡처한 remote directory 부재, owner claim 해제 모두 PASS.
- 첫 Mac probe는 요청한 custom TMPDIR 밖에 socket을 생성해 소유권 검증에서 거부됐다.
  해당 자료를 보존했고, 실제 Mac temporary root를 사용한 별도 로컬 회차에서 확인했다.
  이것을 S22U 재실행이나 S22U PASS로 계산하지 않는다.

로컬 결과와 원시 테스트 로그는 저장소 밖
`../Termu-inator-device-artifacts/s22u-r2-43a254707d-analysis-TnHrJf/`에 보존한다.
공유용 자료에는 private process snapshot·browser profile·stderr를 넣지 않는다.

`git diff --check`도 통과했다. 새 wheel을 만들거나 설치 검증을 완료했다고 주장하지
않는다. 이번 검사는 checkout 소스와 기존 pinned-MCP 로컬 테스트 환경에서 수행했다.

## 이번 변경 경로 — 13개

```text
docs/s22u-r2-startup-followup.ko.md
findings.md
progress.md
scripts/final_verify.py
src/browser.py
src/chromium_singleton.py
src/pilot.py
src/termuinator/backends/legacy.py
task_plan.md
tests/test_browser_lifecycle.py
tests/test_browser_startup_evidence.py
tests/test_chromium_singleton_cleanup.py
tests/test_final_verify.py
```

commit/push는 실행하지 않았다. 과거 acceptance 문서 자체는 수정하지 않았으며,
현재 사용자의 S22U 필수 기준이 우선한다는 설명을 progress/task plan 앞에 추가했다.

## 다음 Hermes 검수 자료 봉인 조건

1. 사용자가 이 변경의 새 clean commit SHA를 제공한다. 기존 d348...은 재사용하지 않는다.
2. exact commit의 전체 변경 경로와 tree, remote 일치 여부를 확인한다.
3. 새 소스 파일 `src/chromium_singleton.py`를 포함한 wheel을 재빌드한다.
   과거 58-source wheel을 재사용하지 않는다. 새 commit 기준 source/member/RECORD/
   metadata/entrypoint/install binding과 wheel SHA·크기를 새 authority에 기록한다.
4. 새로운 OPS authority/runbook과 output identity를 발행한다. 기존 r2 결과·예산
   기록은 연결해서 보존하며, 남은 1회를 동일 상태 재시도 권한으로 사용하지 않는다.
5. 준비는 이미 검증한 native cryptography 50.0.2·Rust 환경을 우선 재확인한다.
   이를 강제 downgrade하거나 무조건 재설치하지 않는다. 환경 drift는 새 회차에 기록한다.
6. 전체 preflight에 신규 시작/singleton 테스트를 포함하고 fresh S22U canonical을
   수행한다. 같은 실행 환경의 완전 PASS에만 benchmark를 연결한다.
7. 실패하면 새 fixed label과 census/cleanup을 보존하고, 허용된 독립 파일 검사와
   한국어 요약·sanitized ZIP 반환까지 이어간다. 동일 상태 재시도, 기기 source patch,
   timeout/성공 기준 완화, MCP 등록·production 전환은 하지 않는다.

실제 S22U 검수는 계속 필수다. `acceptance/`의 별도 local-only 기준이나 로컬
회귀 PASS로 대체하지 않는다. 기존 11-path commit과 수신 증거는 보존한다.
