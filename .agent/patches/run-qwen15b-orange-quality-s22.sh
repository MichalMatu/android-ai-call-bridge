#!/bin/bash
set -euo pipefail

EXPECTED_MAIN="655644bbf83ca46b820bb4b7502438e5f25e1aed"
SERIAL="RFCT70L7E8J"
PKG="pl.michalmatu.aicallbridge"
REMOTE="/data/local/tmp/aicall-phone-llm"
PORT="18115"
MODEL_FILE="qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_SHA="6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e"
MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/${MODEL_FILE}?download=true"
WORK="/tmp/aicall-qwen15b-quality-3690"
MODEL_LOCAL="$WORK/$MODEL_FILE"
MODEL_REMOTE="$REMOTE/model-1.5b.gguf"
export ANDROID_HOME="$HOME/Library/Android/sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export GRADLE_BIN="$HOME/.gradle/local-agent/gradle-9.6.0/bin/gradle"

mkdir -p "$WORK"
test -x "$GRADLE_BIN"
git fetch origin main agent-control
git checkout main
git reset --hard origin/main
git clean -fd
test "$(git rev-parse HEAD)" = "$EXPECTED_MAIN"
test -z "$(git status --porcelain)"

git show origin/agent-control:.agent/patches/qwen15b-quality-patch-20260919.py > "$WORK/patch.py"
python3 "$WORK/patch.py"
git diff --check
"$GRADLE_BIN" :app:testDebugUnitTest --tests 'pl.michalmatu.aicallbridge.textagent.LocalPhoneLlmBackendFactoryTest'
bash scripts/verify_host.sh
echo qwen15b_quality_host_green=true

DEVICES=$(adb devices -l || true)
PRESENT=$(DEVICES="$DEVICES" PYTHONPATH=scripts python3 -c 'import os; from realtime_network_smoke import is_direct_usb_target; print(1 if is_direct_usb_target(os.environ.get("DEVICES", ""), "RFCT70L7E8J") else 0)')
test "$PRESENT" = 1
echo qwen15b_direct_usb=true
CALL_STATE_BEFORE=$(adb -s "$SERIAL" shell dumpsys telephony.registry | sed -n 's/.*mCallState=\([0-9][0-9]*\).*/\1/p' | head -1)
test "$CALL_STATE_BEFORE" = 0
echo qwen15b_call_state_before=$CALL_STATE_BEFORE
adb -s "$SERIAL" shell df -h /data/local/tmp || true

if [ ! -f "$MODEL_LOCAL" ] || [ "$(shasum -a 256 "$MODEL_LOCAL" | awk '{print $1}')" != "$MODEL_SHA" ]; then
  rm -f "$MODEL_LOCAL"
  curl -L --fail --retry 3 --retry-delay 2 -o "$MODEL_LOCAL" "$MODEL_URL"
fi
test "$(shasum -a 256 "$MODEL_LOCAL" | awk '{print $1}')" = "$MODEL_SHA"
echo qwen15b_model_sha_verified=true

adb -s "$SERIAL" shell mkdir -p "$REMOTE"
adb -s "$SERIAL" push "$MODEL_LOCAL" "$MODEL_REMOTE"
REMOTE_SHA=$(adb -s "$SERIAL" shell sha256sum "$MODEL_REMOTE" 2>/dev/null | awk '{print $1}' | tr -d '\r' || true)
if [ -n "$REMOTE_SHA" ]; then
  test "$REMOTE_SHA" = "$MODEL_SHA"
  echo qwen15b_phone_model_sha_verified=true
fi

adb -s "$SERIAL" shell "cd '$REMOTE'; if [ -f server.pid ]; then p=\$(cat server.pid 2>/dev/null || true); if [ -n \"\$p\" ]; then kill \"\$p\" 2>/dev/null || true; fi; fi"
sleep 1
adb -s "$SERIAL" shell "cd '$REMOTE'; export LD_LIBRARY_PATH='$REMOTE'; nohup ./llama-server -m '$MODEL_REMOTE' --host 127.0.0.1 --port $PORT --alias qwen-phone-1.5b -c 1024 -t 4 -np 1 > '$REMOTE/llama-1.5b.log' 2>&1 < /dev/null & echo \$! > '$REMOTE/server.pid'" || true

adb -s "$SERIAL" forward --remove tcp:$PORT >/dev/null 2>&1 || true
adb -s "$SERIAL" forward tcp:$PORT tcp:$PORT >/dev/null
READY=0
for i in $(seq 1 180); do
  if curl -fsS --max-time 3 "http://127.0.0.1:$PORT/health" > "$WORK/health.json" 2>/dev/null; then
    READY=1
    break
  fi
  sleep 1
done
if [ "$READY" != 1 ]; then
  echo '--- qwen15b phone log ---'
  adb -s "$SERIAL" shell tail -120 "$REMOTE/llama-1.5b.log" || true
  exit 1
fi
cat "$WORK/health.json"
echo
echo qwen15b_server_ready=true

python3 - <<'PY'
import json, time, urllib.request
payload = {
    "model": "qwen-phone-1.5b",
    "stream": False,
    "messages": [
        {"role": "system", "content": "Jesteś asystentem rozmowy telefonicznej. Nie zgaduj brakujących faktów. Gdy transkrypt jest bardzo krótki lub niejasny, poproś krótko o doprecyzowanie."},
        {"role": "user", "content": "orange"},
    ],
    "max_tokens": 48,
}
req = urllib.request.Request("http://127.0.0.1:18115/v1/chat/completions", data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
started = time.monotonic()
with urllib.request.urlopen(req, timeout=60) as r:
    data = json.load(r)
elapsed = time.monotonic() - started
text = data["choices"][0]["message"]["content"].strip()
if not text:
    raise SystemExit("blank direct response")
print("qwen15b_direct_response=" + text.replace("\n", " "))
print(f"qwen15b_direct_latency_seconds={elapsed:.3f}")
PY

"$GRADLE_BIN" :app:assembleDebug > "$WORK/build.log" 2>&1 || { cat "$WORK/build.log"; exit 1; }
adb -s "$SERIAL" install -r app/build/outputs/apk/debug/app-debug.apk > "$WORK/install.log" 2>&1 || { cat "$WORK/install.log"; exit 1; }
cat "$WORK/install.log"

adb -s "$SERIAL" shell run-as "$PKG" rm -f files/local-phone-llm-speech-pipeline-report.txt 2>/dev/null || true
adb -s "$SERIAL" shell am force-stop "$PKG"
adb -s "$SERIAL" shell am start -W -n "$PKG/.DiagnosticProbeActivity" --ez run_local_phone_llm_speech_pipeline_probe true > "$WORK/offcall-start.log"
REPORT=''
for i in $(seq 1 300); do
  REPORT=$(adb -s "$SERIAL" shell run-as "$PKG" cat files/local-phone-llm-speech-pipeline-report.txt 2>/dev/null | tr -d '\r' || true)
  if printf '%s\n' "$REPORT" | grep -q '^probe_complete=true$'; then break; fi
  sleep 0.5
done
echo '--- qwen15b offcall report ---'
printf '%s\n' "$REPORT"
echo '--- end qwen15b offcall report ---'
printf '%s\n' "$REPORT" | grep -q '^backend_config_valid=true$'
printf '%s\n' "$REPORT" | grep -q '^stt_transcript_nonblank=true$'
printf '%s\n' "$REPORT" | grep -q '^backend_complete_response=true$'
printf '%s\n' "$REPORT" | grep -q '^approved_output_pcm_nonempty=true$'
printf '%s\n' "$REPORT" | grep -q '^local_phone_llm_speech_pipeline_success=true$'
echo qwen15b_offcall_proven_s22=true

CALL_STATE_PRE_LIVE=$(adb -s "$SERIAL" shell dumpsys telephony.registry | sed -n 's/.*mCallState=\([0-9][0-9]*\).*/\1/p' | head -1)
test "$CALL_STATE_PRE_LIVE" = 0
PYTHONPATH=scripts python3 scripts/local_phone_llm_live_call.py "$SERIAL" | tee "$WORK/orange-live.log"
grep -q '^allowlisted_target=510100100$' "$WORK/orange-live.log"
grep -q '^dial_requested=true$' "$WORK/orange-live.log"
grep -q '^local_phone_llm_orange_live_turn_proven_s22=true$' "$WORK/orange-live.log"
grep -q '^hangup_requested=true$' "$WORK/orange-live.log"
grep -q '^idle_after_hangup=True$' "$WORK/orange-live.log"
CALL_STATE_AFTER=$(adb -s "$SERIAL" shell dumpsys telephony.registry | sed -n 's/.*mCallState=\([0-9][0-9]*\).*/\1/p' | head -1)
test "$CALL_STATE_AFTER" = 0
HELPER=$(adb -s "$SERIAL" shell pidof "$PKG:call_media" 2>/dev/null | tr -d '\r' || true)
test -z "$HELPER"
echo qwen15b_orange_quality_live_proven_s22=true

PID=$(adb -s "$SERIAL" shell cat "$REMOTE/server.pid" 2>/dev/null | tr -d '\r' || true)
if [ -n "$PID" ]; then
  adb -s "$SERIAL" shell "cat /proc/$PID/status 2>/dev/null | grep -E '^(VmRSS|VmHWM|Threads):'" || true
fi

git diff --check
git add \
  app/src/main/kotlin/pl/michalmatu/aicallbridge/textagent/LocalPhoneLlmBackendFactory.kt \
  app/src/main/kotlin/pl/michalmatu/aicallbridge/LocalPhoneLlmLiveCallProbe.kt \
  app/src/test/kotlin/pl/michalmatu/aicallbridge/textagent/LocalPhoneLlmBackendFactoryTest.kt
git commit -m 'feat: improve local phone llm call quality'
NEW=$(git rev-parse HEAD)
git push origin HEAD:main
echo qwen15b_quality_commit=$NEW
test -z "$(git status --porcelain)"
echo qwen15b_quality_upgrade_complete=true
