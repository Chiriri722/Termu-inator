# r4 preflight: tests 패키지 충돌 보강

> **2026-11-10 안내.** 이 수정은 `feb7bd8`에 들어갔다. 아래 "다음 후보의 실행 경로" 절의 봉인 순서는
> 보류됐다. 먼저 L1에서 Chromium 시작 원인을 찾는다. import origin 확인 블록은 그대로 유효하며
> [alpha 게이트 v1](verification-lanes.ko.md)의 preflight 차단 항목으로 쓴다.
> 현재 절차는 [STATUS.md](../STATUS.md)를 따른다.

2026-11-06. **로컬 수정 검증·기기 오류 14건 대조 완료 / 기기 근본 원인 미확정 / S22U 미승인**.

## 수신 결과

대상은 `1b1e4eb9816d081e2241c92fbb57b01517d7b44e` (`v.0.2.35A`),
OPS-20261028-r4다. 공개 ZIP 10849 bytes의 SHA-256은
`caf7e67c5871ed6d792a00e89a18ff3c636d2846b76741a77291fae999cae724`다.
8개 member 안전성, 내부 payload 7개와 각 summary sidecar의 hash를 확인했다.
원본과 owner-private 사본을 보존했다.

기기는 환경·59개 소스 바인딩·Git 검사를 통과했지만 named suite는 1–3개의 import
오류만 수집했고, full discovery는 기대 657개 중 648개와 오류/실패 record 14개를
보고했다. Canonical/benchmark/browser는 시작하지 않았다. 준비 예산 1/3,
canonical 0/2, benchmark 0/2를 보존한다.

최초 공개 자료에는 실제 명령/cwd, missing module 이름, 실패 테스트 이름이 없었다.
이후 정적 추출 JSON을 수신해 아래와 같이 대조했다. 명령/cwd와 실제 import 경로는
기존 기록에 없어 여전히 UNKNOWN이다.
현재 버전은 Python 3.14.6, native cryptography 50.0.2, MCP 1.29.0,
websockets 17.0.1, pydantic-core 2.50.4, Chromium 155.0.8059.79,
Firefox 158.0.1로 보고됐다. 이 버전 목록을 로컬 재현 환경과 혼동하지 않는다.

## 같은 집계를 만드는 결함을 재현했다

Checkout에는 `tests/fixtures/__init__.py`가 있지만 최상위 `tests/__init__.py`가
없었다. 이 구조는 implicit namespace package다. sys.path 뒤쪽의 site-packages에
일반 `tests` 패키지가 존재하면 그 패키지가 선택되어 checkout의 `tests.*`를 가린다.
저장소 경로를 sys.path 맨 앞에 넣는 것만으로는 이 충돌이 해결되지 않는다.

기존 venv를 변경하지 않고 별도 로컬 venv에 합성 `tests` 패키지를 만들었다.
같은 base commit에서 다음 결과를 얻었다.

| 호출 | 수정 전 로컬 결과 |
| --- | --- |
| named verifier | 1개 수집, ModuleNotFoundError |
| full discovery | 648개 수집, failures=5 / errors=9, 총 14 records |

Fixture 모듈의 실제 테스트 10개가 import 오류 placeholder 1개로 바뀌어
`657 - 10 + 1 = 648`이 된다. 다른 tests 모듈을 가져오는 verifier test helper도
실패하며, journal 자식 프로세스는 READY에 도달하지 못한다.
그 결과 AssertionError도 파생된다. S22U의 집계와 일치하지만 기기의 개별
record의 테스트명·subtest·실패 위치도 아래 대조에서 일치했다. 이 일치만으로
기기에서 같은 외부 패키지가 선택됐다고 확정하지는 않는다.

## 기기 정적 추출과 항목별 대조

`r4-preflight-static.sanitized.json` 11,585 bytes의 SHA-256은
`43d48ceeb72c0f8073a36584aac054dc06c67da37edf31d14da2c169fc7cb423`다.
사이드카, r4 commit·wheel·OPS identity, 원래 보고된 stderr 크기와 일치한다.
수신 JSON/사이드카는 별도 디렉터리에 그대로 보존하고 Mac 수신 검증 receipt를
추가했다. 기기의 private 원본 파일 hash를 Mac에서 직접 재검증한 것은 아니다.

14건 모두 **ERROR/FAIL 종류, 테스트 class/method, fixed subtest, source file/function/line**이
로컬 수정 전 재현에 대응한다. 모듈명은 `test_*`와 `tests.test_*` 실행 경로 차이를,
subtest는 문자열 따옴표 차이만 정규화했다. 누락 모듈과 보고된 exception도 대응한다.

| 기기 record | 건수 | 로컬과 일치한 위치·분기 |
| --- | ---: | --- |
| ERROR: `tests.test_benchmark_device` 누락 | 8 | `test_final_verify.py:2141`, `run_candidate`, fault 5개 및 개별 테스트 3개 |
| FAIL 안에 기록된 같은 모듈 누락 | 1 | `test_final_verify.py:2265`, private diagnostic 예외 기대 검사 |
| ERROR: `tests.fixtures` 누락 | 1 | `test_fixture_site.py:20`, fixture 모듈 import |
| FAIL: CLI 요약 AssertionError | 2 | `test_final_verify.py:2373/2374`, status PASS/FAIL |
| FAIL: journal writer AssertionError | 2 | `test_idempotency_journal.py:227`, phase dispatched/terminal |

마지막 네 AssertionError는 **같은 assertion 위치**까지 확인했다. 기기의 expected/actual은
`UNKNOWN_REDACTION_REQUIRED`이므로 값이나 내부 원인까지 일치한다고 주장하지 않는다.
로컬에서는 CLI callback의 cross-test import 실패와 journal 자식의 import 실패가
이 assertion들을 발생시켰고, 패키지 marker를 추가한 뒤 모두 통과했다.
기기에서 실제 선택된 `tests` 경로, 실행 옵션/cwd, 환경변수 값은 기록되지 않았다.
따라서 판정은 **오류 패턴 14/14 일치, 기기의 외부 tests 패키지 가림 원인은 미확정**이다.

Named verifier의 missing module은 `tests.test_final_verify`다. 정적 JSON의
exception_type은 unittest import 실패 wrapper인 `ImportError`로 기록돼 있고,
메시지는 하위 `ModuleNotFoundError`를 설명한다. 원본 분류는 변경하지 않는다.
새 실행으로 과거 명령을 재구성하거나 없는 정보를 추가 요청하지 않는다.

## 최소 수정과 회귀

- `tests/__init__.py`를 추가해 checkout tests를 일반 패키지로 고정했다.
- 새 회귀 2개는 외부 tests 패키지를 둔 별도 Python 프로세스에서 named suite와
  fixture discovery가 실제 checkout의 테스트와 fixture를 수집하는지 확인한다.
- 수정 전에 회귀 2개가 loader error 2개/1개로 실패했고, 수정 후 둘 다 통과했다.
- 런타임 코드·의존성·warning/skip 정책·기존 assertion은 변경하지 않았다.
  기존 657개에 신규 회귀 2개를 더해 기대값이 659개가 됐다.

## 로컬 검증

충돌 패키지를 그대로 둔 환경에서 `-B -W error -m unittest`를 실행했다.

| suite | 결과 |
| --- | --- |
| verifier | 115 PASS |
| native / BiDi / adapter | 90 PASS |
| benchmark / lifecycle / packaging | 107 PASS |
| CDP | 9 PASS |
| startup / Singleton | 30 PASS |
| browser lifecycle | 35 PASS |
| full | 659개 실행, 658 PASS, 기존 opt-in 1개만 skip |
| 실제 Mac Chrome fixture 별도 실행 | 10 PASS, skip 0 |

허용된 opt-in은 `test_live_browser_form_events_count_each_real_submit` 하나다.
위 로컬 환경은 Mac Python 3.14.7 / MCP 1.29.0 / websockets 17.0.1이다.
Mac 결과로 Termux의 native ABI나 S22U 브라우저 시작·작업·성능을 승인하지 않는다.

## 다음 후보의 실행 경로를 고정한다

새 사용자 clean commit과 변경 범위를 확인한 뒤 새 authority를 만든다.
기존 r4 output/예산/결과는 보존하고 재실행 대상으로 사용하지 않는다.
현재 파일은 분석 문서이며 r4 재실행 승인이나 새 실행 authority가 아니다.
정적 대조는 끝났으므로 다음 선행 조건은 이 수정의 **새 clean commit SHA**다.
아직 SHA가 없는 검수 메시지를 Hermes 실행 지시로 보내지 않는다.

다음 검수 문서에는 repo root로 이동하는 명령과 아래 확인을 명시적으로 넣는다.
`TFV_PROJECT`와 `TFV_VENV`는 새 authority에서 이미 검증한 후보 절대경로다.

```bash
cd "$TFV_PROJECT" || exit 1
"$TFV_VENV/bin/python" -B -W error - <<'PY'
from pathlib import Path
import json
import os
import sys
import tests
import tests.fixtures.server as fixture
import scripts.final_verify as verifier
root = Path.cwd().resolve()
origins = {
    "tests": Path(tests.__file__).resolve() == root / "tests" / "__init__.py",
    "fixture": Path(fixture.__file__).resolve() == root / "tests" / "fixtures" / "server.py",
    "verifier": Path(verifier.__file__).resolve() == root / "scripts" / "final_verify.py",
}
print(json.dumps({
    "format": "termuinator-test-import-origin-v1",
    "origins_match_checkout": origins,
    "python_isolated": sys.flags.isolated,
    "python_safe_path": bool(getattr(sys.flags, "safe_path", False)),
    "PYTHONPATH_present": "PYTHONPATH" in os.environ,
    "PYTHONSAFEPATH_present": "PYTHONSAFEPATH" in os.environ,
}, sort_keys=True))
assert all(origins.values()), "TEST_IMPORT_ORIGIN_MISMATCH"
PY
```

Unittest 호출은 위 cwd에서 `"$TFV_VENV/bin/python" -B -W error -m unittest`와
각 suite 인자를 사용한다. 이를 임의로 `-I`나 `-P` 호출로 바꾸지 않는다.
그 옵션들은 현재 디렉터리의 import 처리를 바꾸므로 같은 실행 계약이 아니다.
현재 Python 환경의 안전 경로 설정 때문에 origin 확인이 실패하면 기록하고 중단한다.

새 검수 자료에는 **각 suite 실행 전** 실제 인자 목록과 checkout cwd의 일치 여부를
저장하는 wrapper를 포함한다. Python 절대경로는 공개 자료에서 `<CANDIDATE_PYTHON>`,
cwd는 `<CANDIDATE_CHECKOUT>`으로 치환하고 실제 경로 검증 결과를 boolean으로 남긴다.
기록할 항목은 다음과 같다.

| 시점 | 공개 기록 |
| --- | --- |
| 실행 전 | 후보 SHA, suite ID, 실제 Python 옵션/unittest 인자, cwd·venv 후보 일치 여부 |
| import 확인 | 위 origin JSON, PYTHONPATH/PYTHONSAFEPATH 설정 존재 여부만 기록 |
| 종료 후 | exit code, ran/expected/errors/failures/skips, stdout/stderr 크기·hash |
| 실패 후 | loader error 수, repo test ID, exception class, missing module, 허용된 fixed subtest |

변수 값·전체 환경·임의 traceback/오류 본문은 공개하지 않는다. Import 확인 자체가
실패하더라도 먼저 보존한 실행 인자/cwd 기록은 남겨 다음 진단에 사용한다.
수집 수 차이나 AssertionError를 서로 독립된 runtime 결함으로 단정하지 않는다.

새 S22U gate는 새 clean candidate로 전체 preflight 후 수행하고,
완전 canonical PASS일 때만 benchmark를 연다. 기존 r4는 preflight FAIL /
canonical NOT_RUN / benchmark NOT_RUN으로 보존하며 남은 예산을 새 후보에 이월하지 않는다.
