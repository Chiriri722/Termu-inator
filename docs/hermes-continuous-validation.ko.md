# S22U 환경 복구와 연속 검수 — OPS-20261023-r1

환경 복구가 끝났다는 중간 답변만 하고 멈추지 않는다. 아래 범위 안에서
현황 확인 → 필요한 준비 → 사전 검사 → canonical → 조건부 benchmark →
원인 진단·허용된 복구 → 증거 반환을 이어간다. 단계별로 재승인을 기다리지 않는다.
이 문서는 2026-10-23 사용자의 연속 작업 요청을 구체화한 운영 승인이다.
제작팀이 이 문서를 만들었다는 사실은 기기 실행이나 PASS 증거가 아니다.

## 1. 기존 결과를 바꾸지 않고 운영 정책만 교체한다

- 기존 BLOCKED / NOT_RUN / FAIL / PASS와 원본 봉인 ZIP은 그대로 보존한다.
  리셋으로 없어진 파일은 `LOST_AFTER_RESET`, 존재 여부를 모르면 `UNKNOWN`이다.
  과거 기록·해시를 새 실행 결과로 복제하거나 없는 증거를 재구성하지 않는다.
- 동봉 구 ZIP은 코드·wheel 출처다. 구 전달 메시지 HERMES-MESSAGE.ko.txt와
  구 ZIP의 HERMES-CANONICAL-RERUN.md를 실행 순서로 다시 사용하지 않는다.
  구 authority.json의 코드 식별자는 유지하지만, 운영 권한·회수·경로는
  **OPS-AUTHORITY.json과 이 문서**가 대체한다. 구 파일을 직접 고치지 않는다.
- 환경 복구만으로 코드 SHA를 새로 만들 필요는 없다. 같은 SHA/wheel이라도
  새 run ID와 현재 환경 기록을 연결한다. 소스나 검수 기준을 고쳐야 하면
  제작팀의 새 commit과 그 commit에 바인딩된 wheel이 필요하다.
- 이미 진행 중인 준비는 중복 실행하지 않는다. 현재 단계와 파일을 확인하고
  검증된 준비 결과를 이어 쓴다. 실패·미완성 venv는 보존하고 새 경로를 선택한다.
- 원격 main이 앞으로 이동해도 아래 SHA를 임의로 최신 SHA로 바꾸지 않는다.
  지정 commit을 가져올 수 있고 바인딩이 일치하면 그 commit으로 진행한다.

| 고정 코드 식별자 | 값 |
| --- | --- |
| Commit | `5f79919c250f52b5b48446922ef4bf1656da2ca2` |
| Subject / tree | `v.0.2.43` / `0c0205e6508986a13d5f1506a39c9695d20b4c9c` |
| Parent / 변경 경로 수 | `ff62c307061bfff340f6c80a8b78c99033ad29bf` / 7 |
| 원본 ZIP | `hermes-v0243-5f79919c250f.zip`, 290341 bytes |
| 원본 ZIP SHA-256 | `8d9e0655b24efb5d7d3107fef9038b630d54c106f38388a0730b10d729524305` |
| Wheel | `termux_browser_pilot-0.1.0a1-py3-none-any.whl`, 282268 bytes |
| Wheel SHA-256 | `9fe9c0f3184ec91aa7e925e19da31c40973c2b9bee1e25a130bd2e5fb87794ce` |
| Packaged source | 58 files |
| Source-tree SHA-256 | `167ebcb8e700b881498c46dfabdd7bf82a624248a178a7cc950c8244c2559c22` |
| MCP / websockets | `1.29.0` / `17.0.1` |

## 2. 준비·진단·복구의 허용 범위

다음은 추가 질문 없이 진행한다. 실행 전후 상태와 변경 이유를 기록한다.

- 현재 버전·실행 파일·선택한 경로의 소유권/권한·디스크/임시 경로·DNS/TLS,
  후보에 귀속된 프로세스·소켓·로그의 읽기 전용 확인. 기본 HOME의 `tbp status`
  같은 daemon 자동 시작 명령을 읽기 전용 조회로 사용하지 않는다.
- 지정 commit의 새 detached checkout, 검증한 wheel의 사본,
  새 `--system-site-packages` venv와 그 안의 pinned MCP 의존성 설치.
  설치·바인딩이 다시 확인된 복구용 checkout/venv는 재사용 가능하다.
  다른 Hermes 등록이나 실행 중인 프로세스가 쓰는 venv는 수정하지 않는다.
- 누락된 native 준비물만 설치한다. 허용 목록은 git, curl, coreutils,
  ca-certificates, python, python-cryptography, chromium, firefox, file,
  imagemagick, openbox, xclip, xdotool, xorg-server-xvfb다.
  저장소 채널은 후보 setup.sh에 명시된 x11-repo / tur-repo만 추가할 수 있다.
  TUR는 별도 커뮤니티 저장소이며 임의 미러·새 서명 키를 신뢰할 권한은 없다.
- `pkg update`로 목록을 갱신할 수 있다. 설치 전에 package manager의 simulation으로
  전체 transaction을 확인한다. 누락 항목과 필요한 새 의존성 설치만 허용한다.
  기존 Python/OpenSSL 등 설치된 공유 패키지의 upgrade/downgrade/removal이 필요하면
  그 목록·영향을 한 번에 보고하고 해당 변경 승인을 요청한다. 무조건적인
  `pkg upgrade`, 패키지 제거, `setup.sh` 전체 실행, system pip 설치는 하지 않는다.
- 새 후보 venv의 누락 의존성, 쓸 수 없는 임시 경로, 새 실행 경로 충돌처럼
  근거가 확인된 준비 문제를 고친다. 기존 디렉터리를 덮어쓰거나 삭제하는 대신
  새 경로를 선택한다. `/tmp`를 가정하지 말고 실제 Termux TMPDIR을 확인한다.
- 기존 native cryptography가 정상이라면 유지한다. 없으면 위 허용 범위에서
  native 패키지를 준비하고 버전/경로를 새 기준선으로 기록한다. 과거 50.0.1을
  강제하지 않는다. pip cryptography wheel 설치·소스 빌드로 대체하지 않는다.

아래 작업은 중단하고 필요한 선택지만 묶어 요청한다. 가능한 독립적인 읽기 전용
진단과 증거 반환까지 멈출 필요는 없다.

- 삭제·기존 프로필 reset·기존 venv 수정·소유권 불명 프로세스 종료·lock unlink.
- Tailscale/DNS/proxy, Hermes 설정·등록, SSH/Buzz/키, production 전환.
- TLS/서명 검증 해제, 임의 repository, runtime 코드 patch, 테스트 제외,
  timeout/성공 기준 완화, 실제 계정/OTP/외부 사이트 제출, fault/soak 검사.
- 바인딩/해시 불일치, unsafe path, 권한·cleanup 불명, 승인 예산 불명.

## 3. 반복은 제한하고, 리셋에도 이어갈 기록을 남긴다

이 운영 승인 1건의 예산은 준비/사전 검사 **최대 3회**, canonical **최대 2회**,
각 canonical 완전 PASS에 바로 연결되는 benchmark **각 1회(총 최대 2회)**다.
실패 1건당 읽기 전용 원인 확인은 최대 3개의 질문/진단 묶음으로 제한한다.
상태가 같으면 같은 검사를 반복하지 않는다. 세션 재시작으로 예산을 초기화하지 않는다.

1. 첫 검증 실패 후에도 아래 최소 진단과 독립 파일 검사는 계속한다.
2. 허용된 환경 문제라는 근거, 적용한 한 가지 복구, 안전한 후보 cleanup이
   모두 확인되고 예산이 남으면 새 run ID로 자동 진행한다. 재승인 대기는 없다.
3. 제품/검수기 코드 문제, 원인 불명, 동일 실패 반복, cleanup 불명 또는 예산
   소진이면 무작정 재검증하지 않는다. `NEEDS_CODE_FIX` 또는 구체적
   `BLOCKED_NEEDS_INPUT`으로 필요한 증거와 다음 조치를 반환한다.
4. 실제 canonical process를 시작했다면 초기에 실패해도 1회 사용이다.
   시작 여부가 불명이면 사용한 회차로 취급한다. 기존 BLOCKED가 NOT_RUN이었다는
   근거가 있으면 과거 기록은 보존하고 이 새 승인의 예산과 구분한다.

운영 기록은 `~/.local/state/termuinator/recovery/OPS-20261023-r1/`의
owner-private 디렉터리에 둔다. 첫 진입에는 새 디렉터리를 만들고, 재개 시에는
소유권·권한·기존 회차 기록을 확인한다. 같은 campaign의 동시 실행은 금지한다.
각 단계 기록은 새 파일로 추가하고 이전 JSON을 덮어쓰지 않는다.

- `environment_epoch`: 이번 리셋 이후 환경 식별자. 모르면 새로 부여하고 과거와
  동일하다고 주장하지 않는다. 준비 완료 시 실제 버전/경로/패키지 목록의 지문을 남긴다.
- `run_id`: 짧은 신규 식별자(예: `43r1` + 임의 6자리 hex), 회차 번호,
  앞 회차 ID와 실패 후 변경 이유. canonical/benchmark 경로는 매번 새로 만든다.
- 코드 SHA/tree, wheel SHA, 검증된 checkout/venv/wheel 경로는 연결 기록에 남긴다.
- 환경 준비·사전 검사·각 검수/진단 종료 때 공개 요약 JSON/한국어 요약과
  파일 SHA-256 목록을 기존 봇 대화에 첨부한다. 회신을 기다리지 않고 허용된
  다음 단계를 진행한다. 전송 실패는 `backup_delivery=UNCONFIRMED`로 기록한다.
- `.local/state`도 Termux 앱 데이터 리셋 때 사라진다. 이는 백업 자체가 아니다.
  Mac에 수신한 공개 자료가 외부 복구 근거다. 키·토큰·쿠키·브라우저 프로필은
  자동 백업/전송하지 않는다. 기록 유실로 사용 예산이 불명이면 추정해서 재실행하지 않는다.

## 4. 환경 준비가 끝나면 사전 검사로 바로 이어간다

아직 준비 중이면 2절 범위에서 계속 준비한다. 다른 작업이 같은 환경을 준비 중이면
중복 설치하지 말고 그 작업의 완료 상태를 확인한다. 다음 조건을 확인하면 READY다.

- Android/Termux identity, writable TMPDIR, 필요한 실행 파일, native cryptography
  import와 PREFIX/lib 출처, Python/MCP/websockets import, pip check가 정상이다.
- 현재 Tailscale 상태를 관측 가능한 범위에서 기록한다. 과거의 Excluding / Termux OFF를
  현재 사실로 복사하지 않는다. UI 조회가 불가능해도 UNKNOWN으로 남기고 loopback
  검수는 계속할 수 있다. 네트워크 설정은 자동 변경하지 않는다. DNS 실패와 직접 IP
  TLS 실패를 구분하고 원시 IP는 공유하지 않는다. 공개 URL benchmark가 실패하면
  그 결과를 보존하며 네트워크 설정 변경은 별도 승인 대상이다.
- 지정 commit/tree/parent/7개 변경 경로가 구 authority.json과 일치하는 clean checkout,
  .DS_Store 미추적, wheel 크기/해시/metadata/RECORD/entrypoints/소스 58개 바인딩,
  설치 소스·pip direct_url의 wheel 해시가 모두 일치한다.
- 기존 venv를 그대로 쓰려면 아래 바인딩을 다시 확인한다. 디렉터리 존재만으로
  중단하지도, 정상으로 간주하지도 않는다. 불일치 venv는 보존하고 새로 만든다.

TFV_PROJECT / TFV_VENV / TFV_WHEEL / TFV_SOURCE_BUNDLE은 Hermes가 관측한
실제 절대경로로 정한다. 경로 문자열을 제작팀이 다시 지정할 때까지 기다리지 않는다.
복구해 놓은 후보가 위 조건을 만족하면 그 경로를 사용한다. 모두 없으면 짧은 신규
prep ID를 정해 `~/.local/src/Termu-inator-5f79919c250f-<prep-id>`,
`~/.venvs/termuinator-mcp-5f79919c250f-<prep-id>`,
`~/.local/share/termuinator/wheels/<prep-id>/`를 사용한다. 선택한 경로와 부모가
소유한 real directory인지 확인하고 symlink·타인 소유·공용 쓰기 가능 경로는 거부한다.

원본 ZIP을 해제하기 전 크기/해시, 중복 member·절대경로·경로 탈출·symlink 부재를
확인한다. 새 0700 디렉터리에 regular 0600 파일만 해제하고 bundle-files.sha256을
검증한다. wheel 사본의 해시는 그대로여야 하며 설치 후 그 사본을 이동하지 않는다.
새 checkout이 필요한 경우에만 `https://github.com/Chiriri722/Termu-inator.git`을
선택한 빈 경로로 복제하고 `git checkout --detach 5f79919c250f52b5b48446922ef4bf1656da2ca2`로
고정한다. 다른 checkout을 reset/clean하지 않는다.

새 venv가 필요할 때만 실행한다. 아래 경로 변수는 검증한 절대경로이며,
`TFV_VENV`는 다른 작업이 쓰지 않는 새 경로여야 한다.

```bash
umask 077
test ! -e "$TFV_VENV" && test ! -L "$TFV_VENV" || exit 1
"$PREFIX/bin/python" -m venv --system-site-packages "$TFV_VENV" || exit 1
"$TFV_VENV/bin/python" -m pip install --no-deps --ignore-installed \
  "$TFV_WHEEL" 'mcp==1.29.0' 'websockets==17.0.1' || exit 1
"$TFV_VENV/bin/python" -m pip install --constraint "$TFV_PROJECT/requirements-termux.txt" \
  --only-binary=cryptography "${TFV_WHEEL}[mcp]" || exit 1
"$TFV_VENV/bin/python" -m pip --disable-pip-version-check --no-cache-dir check
```

설치 stdout/stderr는 해당 준비 회차의 private 파일에 보존한다. 실패하면 이 설치
블록만 종료하고 6절 진단·반환을 수행한다. 운영 작업 전체를 끝내거나 다음 검수를
억지로 진행하지 않는다. 기존 canonical verifier의 함수를 그대로 이용해 다음을 확인한다.
아래 `TFV_SOURCE_BUNDLE`은 안전하게 해제하고 체크섬을 확인한 **구 ZIP** 디렉터리다.

```bash
cd "$TFV_PROJECT" || exit 1
"$TFV_VENV/bin/python" -B - "$TFV_WHEEL" "$TFV_PROJECT" "$TFV_SOURCE_BUNDLE/authority.json" <<'PY'
import cryptography, hashlib, json, os, platform, subprocess, sys, sysconfig
from pathlib import Path
from scripts.final_verify import (_runtime_distribution, validate_android_termux_identity,
    validate_wheel_source_binding, validate_installed_source_binding, validate_wheel_provenance)
wheel, repo, authority = map(Path, sys.argv[1:])
a = json.loads(authority.read_text())
def git(*args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
assert a['commit'] == '5f79919c250f52b5b48446922ef4bf1656da2ca2' == git('rev-parse', 'HEAD')
assert git('rev-parse', 'HEAD^{tree}') == a['tree']
assert git('rev-parse', 'HEAD^') == a['parent']
assert git('log', '-1', '--format=%s') == a['subject']
assert not git('status', '--porcelain=v1', '--untracked-files=all')
assert not git('ls-files', '--', '.DS_Store', '*/.DS_Store')
assert sorted(git('diff', '--name-only', 'HEAD^', 'HEAD').splitlines()) == sorted(a['changed_paths'])
assert len(a['changed_paths']) == 7
subprocess.run(['git', '-C', str(repo), 'diff', '--check', 'HEAD^', 'HEAD'], check=True)
validate_android_termux_identity(python_platform=sys.platform, system_name=platform.system(), android_root=os.environ.get('ANDROID_ROOT'))
native = Path(cryptography.__file__).resolve()
assert (Path(os.environ['PREFIX'])/'lib').resolve() in native.parents
assert not wheel.is_symlink() and wheel.is_file() and wheel.stat().st_size == a['wheel_bytes']
assert hashlib.sha256(wheel.read_bytes()).hexdigest() == a['wheel_sha256']
assert _runtime_distribution('mcp').version == a['expected_mcp']
assert _runtime_distribution('websockets').version == a['expected_websockets']
d = _runtime_distribution('termux-browser-pilot')
entries = {e.name:e.value for e in d.entry_points if e.group == 'console_scripts'}
roots = tuple(Path(v) for v in {sysconfig.get_path('purelib'), sysconfig.get_path('platlib')} if v)
r = {**validate_wheel_source_binding(wheel, repo),
     **validate_installed_source_binding(repo, installed_roots=roots, entrypoints=entries),
     **validate_wheel_provenance(d.read_text('direct_url.json'), expected_sha256=a['wheel_sha256'], wheel_path=wheel)}
assert r['source_files_verified'] == r['installed_source_files_verified'] == a['source_files']
assert r['source_tree_sha256'] == r['installed_source_tree_sha256'] == a['source_tree_sha256']
print(json.dumps({'binding': 'PASS', 'python': platform.python_version(),
    'native_cryptography': cryptography.__version__, 'native_origin': 'PREFIX/lib', **r}, sort_keys=True))
PY
```

이어 같은 venv Python의 `-B -W error -m unittest`로 아래 검사를 실행한다.
결과는 별도 파일에 저장하고 각 종료 코드와 건수를 기록한다. 독립 suite는
하나가 실패해도 나머지를 진단 목적으로 실행할 수 있지만 전부 통과하기 전에는
canonical을 시작하지 않는다. `TERMUINATOR_TEST_BROWSER=''`로 지정하고
기본 HOME의 브라우저는 시작하지 않는다.

| suite | 기대값 |
| --- | --- |
| `tests.test_final_verify -q` | 111, skip 0 |
| `tests.test_native_exec_latency tests.test_firefox_bidi tests.test_legacy_backend_adapter -q` | 85, skip 0 |
| `tests.test_benchmark_lifecycle tests.test_benchmark_device tests.test_packaging_contract -q` | 105, skip 0 |
| `discover -s tests -q` | 609, 기존 opt-in `test_live_browser_form_events_count_each_real_submit` 1개만 skip |

건수 차이, 추가 skip, failure/error는 진단 대상이다. 테스트나 기대값을 바꾸어
통과시키지 않는다. READY와 각 suite PASS를 기록하면 승인 대기 없이 5절로 진행한다.

## 5. 새 회차에서 canonical과 조건부 benchmark를 실행한다

앞서 검증한 경로 변수를 사용한다. 준비된 환경·소스를 고정하고 중간에 패키지 갱신,
환경 복구·설정 변경을 끼우지 않는다. TFV_NETWORK_KIND와 TFV_TAILSCALE_STATE는
현재 관측값 또는 `UNKNOWN; no settings changed`로 지정한다.
TFV_ATTEMPT는 보존된 campaign 기록에서 계산한 이번 canonical 순번(1 또는 2)이다.
새 세션이라고 1로 다시 시작하지 않는다. 출력/기록 디렉터리의 부모는 실행 전에
실제 소유자·권한·symlink 부재를 검증한다. 새 기록 디렉터리는 0700이어야 한다.
코드는 Bash로 실행한다. 외부의 `set -e` 때문에 실패 후 증거 수집이 생략되지 않도록
분리된 subshell에서 종료 코드를 명시적으로 다룬다. 실패를 PASS로 바꾸는 조치가 아니다.

```bash
(
set +e
umask 077
: "${TFV_PROJECT:?}" "${TFV_VENV:?}" "${TFV_WHEEL:?}" "${TFV_NETWORK_KIND:?}" "${TFV_TAILSCALE_STATE:?}"
: "${TFV_ATTEMPT:?보존된 기록으로 이번 회차를 계산하세요}"
case "$TFV_ATTEMPT" in 1|2) ;; *) exit 1 ;; esac
TFV_COMMIT=5f79919c250f52b5b48446922ef4bf1656da2ca2
TFV_SHA=9fe9c0f3184ec91aa7e925e19da31c40973c2b9bee1e25a130bd2e5fb87794ce
TFV_RUN_ID="$("$TFV_VENV/bin/python" -c 'import secrets; print("43r1" + secrets.token_hex(3))')" || exit 1
TFV_OUTPUT="$HOME/.cache/tfv/$TFV_RUN_ID"
TFV_PREFLIGHT="$HOME/.local/state/termuinator/recovery/OPS-20261023-r1/$TFV_RUN_ID"
TFV_BENCH_RUNTIME="$HOME/.cache/tfb/$TFV_RUN_ID"
for TFV_NEW in "$TFV_OUTPUT" "$TFV_PREFLIGHT" "$TFV_BENCH_RUNTIME"; do
  test ! -e "$TFV_NEW" && test ! -L "$TFV_NEW" || exit 1
done
mkdir -p "$TFV_PREFLIGHT" "$(dirname "$TFV_OUTPUT")" "$(dirname "$TFV_BENCH_RUNTIME")" || exit 1
printf 'RUN_ID=%s\n' "$TFV_RUN_ID"
cd "$TFV_PROJECT" || exit 1
printf 'ops_revision=OPS-20261023-r1\nrun_id=%s\nattempt=%s\ncommit=%s\n' \
  "$TFV_RUN_ID" "$TFV_ATTEMPT" "$TFV_COMMIT" > "$TFV_PREFLIGHT/started.txt" || exit 1
TFV_EXIT=0
"$TFV_VENV/bin/python" -B scripts/final_verify.py \
  --project-root "$TFV_PROJECT" --mcp-command "$TFV_VENV/bin/tbp-mcp-v1" \
  --control-command "$TFV_VENV/bin/tbp-control" --wheel "$TFV_WHEEL" \
  --expected-commit "$TFV_COMMIT" --expected-wheel-sha256 "$TFV_SHA" --output "$TFV_OUTPUT" \
  > "$TFV_PREFLIGHT/canonical-stdout.json" 2> "$TFV_PREFLIGHT/canonical-stderr.log" || TFV_EXIT=$?
TFV_CHECKSUM_EXIT=0
(cd "$TFV_OUTPUT" && sha256sum -c final-verify-manifest.sha256) || TFV_CHECKSUM_EXIT=$?
printf 'FINAL_VERIFY_EXIT=%s\nMANIFEST_CHECKSUM_EXIT=%s\n' "$TFV_EXIT" "$TFV_CHECKSUM_EXIT"
wc -c "$TFV_PREFLIGHT/canonical-stdout.json" "$TFV_PREFLIGHT/canonical-stderr.log"
TFV_BENCH_EXIT=NOT_RUN
if test "$TFV_EXIT" -eq 0 && test "$TFV_CHECKSUM_EXIT" -eq 0 && test ! -s "$TFV_PREFLIGHT/canonical-stderr.log"; then
  if "$TFV_VENV/bin/python" -B - "$TFV_OUTPUT/final-verify-manifest.json" <<'PY'
import json, sys
from pathlib import Path
from scripts.benchmark_device import load_canonical_manifest
m, digest = load_canonical_manifest(Path(sys.argv[1]))
assert m['source']['commit'] == '5f79919c250f52b5b48446922ef4bf1656da2ca2'
assert m['status'] == 'PASS' and m['benchmark_allowed'] is True
assert {b['backend'] for b in m['device']['backends']} == {'chromium', 'firefox'}
assert len(m['device']['backends']) == 2
for backend in m['device']['backends']:
    assert backend['status'] == 'PASS'
    boundary = backend['action_boundaries']
    assert boundary['removal_item_counts'] == {'before_approval': 2, 'after_approval': 1, 'after_replay': 1}
    assert boundary['removal_replay_result_identical'] is True
print(json.dumps({'canonical_manifest_sha256': digest, 'boundary_checks': 'PASS'}))
PY
  then
    TFV_BENCH_EXIT=0
    "$TFV_VENV/bin/python" -B scripts/benchmark_device.py \
      --project-root "$TFV_PROJECT" --tbp "$TFV_VENV/bin/tbp" --wheel "$TFV_WHEEL" \
      --canonical-manifest "$TFV_OUTPUT/final-verify-manifest.json" \
      --isolated-runtime "$TFV_BENCH_RUNTIME" --url 'https://example.com' \
      --network-kind "$TFV_NETWORK_KIND" --tailscale-termux-state "$TFV_TAILSCALE_STATE" \
      > "$TFV_PREFLIGHT/benchmark-stdout.log" 2> "$TFV_PREFLIGHT/benchmark-stderr.log" || TFV_BENCH_EXIT=$?
    wc -c "$TFV_PREFLIGHT/benchmark-stdout.log" "$TFV_PREFLIGHT/benchmark-stderr.log"
  fi
fi
printf 'BENCHMARK_EXIT=%s\n' "$TFV_BENCH_EXIT"
git status --short
)
```

이것은 무한 반복 스크립트가 아니다. 실행 전 campaign의 남은 예산과 이전 회차
cleanup을 확인하고 시작을 기록한다. 종료 후에는 성공/실패 모두 다음 절까지 진행한다.
subshell의 종료 코드만으로 종합 PASS를 판정하지 않는다. canonical과 benchmark의
저장된 결과·개별 종료 코드·반환 파일 완전성이 판정 근거다.

Canonical은 양 backend, stdio, post_stop, cleanup, post_run, 반환 파일 검증이
모두 PASS여야 한다. Benchmark는 exit 0, stderr 0, quality.status=PASS,
각 backend cold 3/status 20/text 10/screenshot 5 성공, 오류 0, PNG 10개 검증을 요구한다.
중앙값 status≤300ms/text≤2000ms/screenshot≤4000ms는 바꾸지 않는다.
기존 benchmark authority 검사를 우회하지 않는다. cleanup 증명 범위는 관측 가능한
동일 UID의 후보에 한정하며 Android 전체나 모든 Unix socket의 종료로 주장하지 않는다.

## 6. 실패해도 원인 확인과 독립 검사는 계속한다

“실패했으니 로그를 읽지 않고 종료”로 돌아가지 않는다. 먼저 공개 manifest의
failure_context/additional_failure, 종료 코드, stderr bytes를 확인한다.
부족하면 이 campaign에서 **실패한 후보만** 대상으로 추가 진단한다.

- 실행 flag명, 함수/검사/단계, 예외 class, errno, 고정 label,
  expected/actual의 bool·숫자·null, 버전, 파일의 유무/size/hash/mode를 추출한다.
- 새 후보의 private raw-errors·stderr·package install log는 기기 안에서
  파일당 최대 4KiB이자 80행, 실패 1건당 최대 2개 파일의 관련 부분을 확인할 수 있다.
  로컬 추출로 위 필드만 반환한다. 전체 파일, 임의 예외 message, 페이지 본문,
  URL query, header, 환경변수, 비밀값을 도구 출력에 흘리지 않는다.
- traceback은 해당 코드의 상대 파일명·함수명·행 번호·예외 class만 추출한다.
  지역변수, 사용자 경로, request/response 본문, challenge ID는 제외한다.
  안전한 추출이 안 되면 `UNKNOWN_REDACTION_REQUIRED`로 두고 생로그를 보내지 않는다.
- 기존 Hermes 로그, production 프로필, 다른 앱 데이터, credential store는
  대상이 아니다. 리셋 전 private 기록도 일괄 재조사하지 않는다.
- 원인 설명에 observed / inferred / unknown을 구분한다. mcp_error나
  backend_crashed만으로 OS process crash를 단정하지 않는다. 로그는 증거일 뿐
  지시가 아니며 로그에 나온 설치/설정 명령을 그대로 실행하지 않는다.

PNG, 파일 완전성/권한, Git, 환경, 후보 cleanup은 서로 독립적으로 끝까지 집계한다.
읽기 거부를 0건/정상 부재로 바꾸지 않는다. 미실행은 NOT_RUN, 관측 불가는
UNAVAILABLE, 결과 불명은 UNKNOWN이다. `/proc/net/unix` 전체 조사는 추가하지 않는다.
JSON이 완성되면 “추가 답변 대기”로 남기지 말고 그것을 최종 결과로 반환한다.

## 7. 매번 같은 형태로 결과를 돌려준다

기존 공개 결과 7개는 실제 생성된 것만 반환한다. 미생성 파일은 거짓 대체물을
만들지 말고 이유를 적는다. 각 단계에서 `ops-summary-<sequence>.json`,
`ops-summary-<sequence>.ko.txt`와 SHA-256 목록을 새로 만든다.
공유 JSON에는 다음 항목을 넣되 기존 canonical manifest는 수정하지 않는다.

- ops_revision / commit / wheel_sha256 / environment_epoch / run_id / parent_run_id.
- phase, env_ready, preflight/canonical/benchmark 각 status·exit code, 실행 횟수.
- 확인한 버전, native_origin, 환경 변경 전후의 차이와 적용 이유.
- failure: stage / tool / action_kind / error_code / exception_type / errno / code_location /
  expected / actual / evidence_kind. 미확인은 null이며 비밀값은 넣지 않는다.
- independent_checks: PNG / return_files / permissions / git / environment / cleanup.
- artifacts: 존재/미생성/리셋으로 유실, size/hash, 과거 결과와의 관계.
- diagnosis: 확인한 사실, 가설, 미해결점. 적용한 복구와 남은 예산.
- next_action: 계속 진행 중 / 완료 / 제작팀 코드 수정 필요 / 구체적인 권한·부족 입력.
- backup_delivery: SENT_UNCONFIRMED / ACKNOWLEDGED / UNCONFIRMED.

공개 7개 파일은 final-verify-manifest.json / .sha256, final-verify-summary.ko.txt,
final-verify-files.json, baseline-summary.json / .ko.txt, baseline-files.json이다.
private 원본은 기기에 보존하고 공개 파일과 sanitized 진단만 기존 채널로 반환한다.
Hash는 전송된 자료의 동일성 검사이지 외부 백업 수신이나 검사 PASS 자체가 아니다.

다음에 필요한 것을 구체화하고 종료한다. “재승인 대기”만 남기지 않는다.
허용된 환경 복구면 계속 진행하고, 코드 문제라면 재현 조건·관련 계약·최소 수정안·
필요한 회귀를 정리한다. 실제 코드 수정, MCP 등록, production 전환은 자동 실행하지 않는다.

다음 릴리스에도 이 운영 흐름을 사용하되, 제작팀은 새로 확인한 코드/wheel 식별자와
기대 테스트 수를 넣어 새 ops revision을 발행한다. 이전 패키지와 기록은 보존한다.
단순 세션 재시작이나 문구 변경을 실행 예산 초기화의 근거로 삼지 않는다.
