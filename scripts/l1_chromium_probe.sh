#!/usr/bin/env bash
# L1 진단: 제품 밖에서 Chromium 단독 시작을 확인한다. 인수 증거가 아니다.
#
# - 임시 프로필과 about:blank만 사용한다. 기존 프로필, venv, 설정을 건드리지 않는다.
# - 이 스크립트가 직접 띄운 Xvfb와 Chromium만 종료한다.
# - 결과는 새 임시 디렉터리의 summary.txt에 남는다. 이 파일을 그대로 전달한다.
#
# 사용:  bash scripts/l1_chromium_probe.sh
# 안내:  docs/s22u-l1-chromium-probe.ko.md
set -u

BIN="${TBP_PROBE_BIN:-$(command -v chromium-browser || command -v chromium || true)}"
DISPLAY_NAME="${TBP_PROBE_DISPLAY:-:97}"
PORT_BASE="${TBP_PROBE_PORT_BASE:-9340}"
WAIT_S="${TBP_PROBE_WAIT:-20}"

if [ -z "$BIN" ]; then
  echo "chromium 실행 파일을 찾지 못했다. TBP_PROBE_BIN으로 지정한다." >&2
  exit 2
fi

OUT="$(mktemp -d "${TMPDIR:-/tmp}/chr-probe.XXXXXX")" || exit 2
chmod 700 "$OUT"
SUMMARY="$OUT/summary.txt"
XVFB_PID=""
COUNT=0
LAST_OK=no

say() { printf '%s\n' "$*" | tee -a "$SUMMARY"; }

cleanup() {
  if [ -n "$XVFB_PID" ]; then
    kill "$XVFB_PID" 2>/dev/null
    wait "$XVFB_PID" 2>/dev/null
  fi
}
trap cleanup EXIT

# probe <label> <flag>...  : 띄우고, CDP 준비를 기다리고, 종료 상태를 한 줄로 남긴다.
probe() {
  local label="$1"; shift
  COUNT=$((COUNT + 1))
  local port=$((PORT_BASE + COUNT))
  local err="$OUT/$label.err"
  env "${PROBE_ENV[@]}" "$BIN" --remote-debugging-port="$port" \
    --user-data-dir="$OUT/$label.profile" "$@" about:blank >/dev/null 2>"$err" &
  local pid=$!
  local cdp=no state code waited=0
  while [ "$waited" -lt "$WAIT_S" ]; do
    sleep 1
    waited=$((waited + 1))
    kill -0 "$pid" 2>/dev/null || break
    if curl -fsS -m 2 "http://127.0.0.1:$port/json/version" >/dev/null 2>&1; then
      cdp=yes
      break
    fi
  done
  if kill -0 "$pid" 2>/dev/null; then
    state=alive
    code=-
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
  else
    wait "$pid" 2>/dev/null
    code=$?
    state=exited
  fi
  LAST_OK="$cdp"
  say "$(printf '%-18s state=%-6s cdp_ready=%-3s exit=%-3s waited=%ss stderr_bytes=%s' \
    "$label" "$state" "$cdp" "$code" "$waited" "$(wc -c < "$err" | tr -d ' ')")"
  if [ "$cdp" != yes ]; then
    say "  --- $label stderr 마지막 15줄 ---"
    tail -n 15 "$err" | sed 's/^/  | /' | tee -a "$SUMMARY"
  fi
  sleep 1
}

say "format=termuinator-l1-chromium-probe-v1"
say "date_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [ "${TBP_PROBE_NO_XVFB:-0}" != 1 ]; then
  Xvfb "$DISPLAY_NAME" -screen 0 1920x1080x24 >/dev/null 2>&1 &
  XVFB_PID=$!
  sleep 2
  if ! kill -0 "$XVFB_PID" 2>/dev/null; then
    say "Xvfb를 $DISPLAY_NAME 에서 시작하지 못했다. TBP_PROBE_DISPLAY로 다른 번호를 지정한다."
    XVFB_PID=""
    exit 2
  fi
  export DISPLAY="$DISPLAY_NAME"
fi
# 제품의 SwiftShader 경로와 같은 환경. probe마다 env로 넘긴다.
PROBE_ENV=(LIBGL_ALWAYS_SOFTWARE=1)

say "version=$("$BIN" --version 2>/dev/null | head -n 1)"
say "wait_seconds=$WAIT_S"
say ""

# 제품이 쓰는 플래그 (src/browser.py: CHROMIUM_BASE_FLAGS + SwiftShader GL).
GL_FLAGS=(--enable-webgl --use-gl=angle --use-angle=swiftshader-webgl)
PRODUCT_FLAGS=(
  --remote-debugging-address=127.0.0.1 --window-size=1920,1080
  --no-sandbox --no-zygote --disable-setuid-sandbox --disable-dev-shm-usage
  --test-type --disable-blink-features=AutomationControlled --start-maximized
  --lang=en-US,en --js-flags=--max-old-space-size=1024
  --disable-breakpad --disable-component-update
  "${GL_FLAGS[@]}"
)

probe A-minimal --no-sandbox
A_OK="$LAST_OK"
probe B-product "${PRODUCT_FLAGS[@]}"
B_OK="$LAST_OK"
probe C-product-single "${PRODUCT_FLAGS[@]}" --single-process
C_OK="$LAST_OK"
probe D-headless --no-sandbox --headless=new
D_OK="$LAST_OK"

# 검수기처럼 HOME과 TMPDIR을 전용 경로로 격리한 환경에서 제품 플래그로 띄운다.
mkdir -m 700 "$OUT/iso-home" "$OUT/iso-tmp"
PROBE_ENV=(LIBGL_ALWAYS_SOFTWARE=1 "HOME=$OUT/iso-home" "TMPDIR=$OUT/iso-tmp")
probe E-product-isolated "${PRODUCT_FLAGS[@]}"
E_OK="$LAST_OK"
PROBE_ENV=(LIBGL_ALWAYS_SOFTWARE=1)

# 최소 구성은 뜨는데 제품 구성이 안 뜨면, 플래그를 하나씩 얹어 원인을 찾는다.
if [ "$A_OK" = yes ] && [ "$B_OK" != yes ]; then
  say ""
  say "flag bisect: --no-sandbox 에 아래 플래그를 하나씩 더했다."
  SINGLE_FLAGS=(
    --no-zygote --disable-setuid-sandbox --disable-dev-shm-usage --test-type
    --disable-blink-features=AutomationControlled --start-maximized
    --lang=en-US,en --js-flags=--max-old-space-size=1024
    --disable-breakpad --disable-component-update
    --remote-debugging-address=127.0.0.1 --window-size=1920,1080
  )
  index=0
  for flag in "${SINGLE_FLAGS[@]}"; do
    index=$((index + 1))
    say "F$(printf '%02d' "$index") = $flag"
    probe "F$(printf '%02d' "$index")" --no-sandbox "$flag"
  done
  say "FGL = ${GL_FLAGS[*]}"
  probe FGL --no-sandbox "${GL_FLAGS[@]}"
fi

say ""
say "result A=$A_OK B=$B_OK C=$C_OK D=$D_OK E=$E_OK"
say "exit 133 = SIGTRAP(128+5), 134 = SIGABRT, 139 = SIGSEGV"
say "output_dir=$OUT"
