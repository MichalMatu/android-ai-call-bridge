#!/bin/bash
set -euo pipefail

EXPECTED=d9e705a2e38f73cc6653b43a6e990e590577e909
SERIAL=RFCT70L7E8J
PKG=pl.michalmatu.aicallbridge
PORT=18115
ALIAS=qwen-phone-0.5b
REMOTE=/data/local/tmp/aicall-phone-llm
WORK=/tmp/aicall-phone-llm-3610
LLAMA_TAG=b10976
LLAMA_ASSET=llama-b10976-bin-android-arm64.tar.gz
LLAMA_SHA=cdcf4fab76fd24c1eae41acdbab0e4c08937d924a867fb4f9025ae556da493e0
MODEL_FILE=qwen2.5-0.5b-instruct-q4_k_m.gguf
MODEL_SHA=74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db

export ANDROID_HOME="$HOME/Library/Android/sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export GRADLE_BIN="$HOME/.gradle/local-agent/gradle-9.6.0/bin/gradle"
test -x "$GRADLE_BIN"

git fetch origin main
git checkout main
git reset --hard origin/main
git clean -fd
test "$(git rev-parse HEAD)" = "$EXPECTED"

DEVICES="$(adb devices -l || true)"
PRESENT="$(DEVICES="$DEVICES" PYTHONPATH=scripts python3 -c 'import os; from realtime_network_smoke import is_direct_usb_target; print(1 if is_direct_usb_target(os.environ.get("DEVICES", ""), "RFCT70L7E8J") else 0)')"
test "$PRESENT" = 1
echo local_phone_llm_direct_usb=true

CALL_STATE="$(adb -s "$SERIAL" shell dumpsys telephony.registry | sed -n 's/.*mCallState=\([0-9][0-9]*\).*/\1/p' | head -1)"
echo local_phone_llm_call_state_before="$CALL_STATE"
test "$CALL_STATE" = 0

echo '--- device disk ---'
adb -s "$SERIAL" shell df -h /data/local/tmp
echo '--- end device disk ---'

rm -rf "$WORK"
mkdir -p "$WORK/llama"

LLAMA_URL="https://github.com/ggml-org/llama.cpp/releases/download/$LLAMA_TAG/$LLAMA_ASSET"
curl -fL --retry 3 --connect-timeout 20 "$LLAMA_URL" -o "$WORK/$LLAMA_ASSET"
printf '%s  %s\n' "$LLAMA_SHA" "$WORK/$LLAMA_ASSET" | shasum -a 256 -c -
tar -xzf "$WORK/$LLAMA_ASSET" -C "$WORK/llama"
SERVER="$(find "$WORK/llama" -type f -name llama-server | head -1)"
test -n "$SERVER"
echo local_phone_llm_llama_server_found=true

MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/$MODEL_FILE?download=true"
curl -fL --retry 3 --connect-timeout 20 "$MODEL_URL" -o "$WORK/$MODEL_FILE"
printf '%s  %s\n' "$MODEL_SHA" "$WORK/$MODEL_FILE" | shasum -a 256 -c -
echo local_phone_llm_model_download_verified=true

adb -s "$SERIAL" shell "mkdir -p $REMOTE"
OLD_PID="$(adb -s "$SERIAL" shell cat "$REMOTE/server.pid" 2>/dev/null | tr -d '\r' || true)"
if [ -n "$OLD_PID" ]; then
  adb -s "$SERIAL" shell kill "$OLD_PID" 2>/dev/null || true
fi
adb -s "$SERIAL" shell "rm -f $REMOTE/server.pid $REMOTE/server.log"

adb -s "$SERIAL" push "$SERVER" "$REMOTE/llama-server" >/tmp/phone-llm-push-server.log
cat /tmp/phone-llm-push-server.log
find "$WORK/llama" -type f -name '*.so' | sort | while IFS= read -r LIB; do
  adb -s "$SERIAL" push "$LIB" "$REMOTE/$(basename "$LIB")" >/dev/null
done
adb -s "$SERIAL" push "$WORK/$MODEL_FILE" "$REMOTE/model.gguf" >/tmp/phone-llm-push-model.log
cat /tmp/phone-llm-push-model.log
adb -s "$SERIAL" shell "chmod 755 $REMOTE/llama-server; chmod 644 $REMOTE/model.gguf $REMOTE/*.so 2>/dev/null || true"

echo local_phone_llm_artifacts_pushed=true

KEEP_SERVER=0
cleanup_phone_llm() {
  if [ "$KEEP_SERVER" != 1 ]; then
    PID="$(adb -s "$SERIAL" shell cat "$REMOTE/server.pid" 2>/dev/null | tr -d '\r' || true)"
    if [ -n "$PID" ]; then
      adb -s "$SERIAL" shell kill "$PID" 2>/dev/null || true
    fi
  fi
}
trap cleanup_phone_llm EXIT

REMOTE_CMD="cd $REMOTE; export LD_LIBRARY_PATH=$REMOTE; nohup ./llama-server -m ./model.gguf --host 127.0.0.1 --port $PORT --alias $ALIAS -c 1024 -t 4 -np 1 >server.log 2>&1 </dev/null & echo \$! >server.pid"
adb -s "$SERIAL" shell "$REMOTE_CMD"

adb -s "$SERIAL" forward --remove tcp:$PORT >/dev/null 2>&1 || true
adb -s "$SERIAL" forward tcp:$PORT tcp:$PORT >/dev/null
READY=0
for i in $(seq 1 120); do
  if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/health" >/tmp/phone-llm-health.json 2>/dev/null; then
    READY=1
    break
  fi
  sleep 1
done
if [ "$READY" != 1 ]; then
  echo '--- llama server log ---'
  adb -s "$SERIAL" shell tail -120 "$REMOTE/server.log" || true
  echo '--- end llama server log ---'
  exit 1
fi

echo local_phone_llm_server_ready=true
cat /tmp/phone-llm-health.json

START="$(python3 -c 'import time; print(time.time())')"
curl -fsS --max-time 120 \
  -H 'Content-Type: application/json' \
  -X POST "http://127.0.0.1:$PORT/v1/chat/completions" \
  --data '{"model":"qwen-phone-0.5b","messages":[{"role":"user","content":"Odpowiedz po polsku jednym krótkim zdaniem, że lokalny model na telefonie działa."}],"stream":false,"max_tokens":48}' \
  >/tmp/phone-llm-chat.json
END="$(python3 -c 'import time; print(time.time())')"
cat /tmp/phone-llm-chat.json

python3 -c 'import json; d=json.load(open("/tmp/phone-llm-chat.json")); t=d["choices"][0]["message"]["content"].strip(); assert t; print("local_phone_llm_direct_response_nonblank=true"); print("local_phone_llm_direct_response="+t.replace("\n"," ")[:240])'
python3 -c 'import sys; print(f"local_phone_llm_direct_latency_seconds={float(sys.argv[2])-float(sys.argv[1]):.3f}")' "$START" "$END"

"$GRADLE_BIN" :app:assembleDebug >/tmp/phone-llm-app-build.log 2>&1
tail -20 /tmp/phone-llm-app-build.log
adb -s "$SERIAL" install -r app/build/outputs/apk/debug/app-debug.apk >/tmp/phone-llm-install.log
cat /tmp/phone-llm-install.log

adb -s "$SERIAL" shell run-as "$PKG" rm -f files/local-mac-text-backend-report.txt 2>/dev/null || true
adb -s "$SERIAL" shell am force-stop "$PKG"
adb -s "$SERIAL" shell am start -W -n "$PKG/.DiagnosticProbeActivity" \
  --ez run_local_mac_text_backend_probe true \
  --es local_text_base_url "http://127.0.0.1:$PORT/v1/" \
  --es local_text_model "$ALIAS"

REPORT=''
for i in $(seq 1 240); do
  REPORT="$(adb -s "$SERIAL" shell run-as "$PKG" cat files/local-mac-text-backend-report.txt 2>/dev/null | tr -d '\r' || true)"
  if printf '%s\n' "$REPORT" | grep -q '^probe_complete=true$'; then
    break
  fi
  sleep 0.5
done

echo '--- local phone llm app report ---'
printf '%s\n' "$REPORT"
echo '--- end local phone llm app report ---'
printf '%s\n' "$REPORT" | grep -q '^probe_complete=true$'
printf '%s\n' "$REPORT" | grep -q '^backend_config_valid=true$'
printf '%s\n' "$REPORT" | grep -q '^backend_complete_response=true$'
printf '%s\n' "$REPORT" | grep -q '^approved_output_pcm_nonempty=true$'
printf '%s\n' "$REPORT" | grep -q '^local_mac_backend_success=true$'

CALL_STATE_AFTER="$(adb -s "$SERIAL" shell dumpsys telephony.registry | sed -n 's/.*mCallState=\([0-9][0-9]*\).*/\1/p' | head -1)"
echo local_phone_llm_call_state_after="$CALL_STATE_AFTER"
test "$CALL_STATE_AFTER" = 0

PID="$(adb -s "$SERIAL" shell cat "$REMOTE/server.pid" | tr -d '\r')"
echo local_phone_llm_server_pid="$PID"
echo '--- phone llama process status ---'
adb -s "$SERIAL" shell "grep -E '^(VmRSS|VmHWM|Threads):' /proc/$PID/status 2>/dev/null || true"
echo '--- phone llama log tail ---'
adb -s "$SERIAL" shell tail -60 "$REMOTE/server.log" || true
echo '--- end phone llama log tail ---'

echo local_phone_llm_qwen05b_flow_proven_s22=true
KEEP_SERVER=1
trap - EXIT

test "$(git rev-parse HEAD)" = "$EXPECTED"
test -z "$(git status --porcelain)"
