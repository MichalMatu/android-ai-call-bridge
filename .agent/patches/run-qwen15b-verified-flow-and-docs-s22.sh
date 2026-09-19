#!/bin/bash
set -euo pipefail

EXPECTED_MAIN="7ae1c7cd4892b780caa7be28974aa04a69e97696"
SERIAL="RFCT70L7E8J"
PKG="pl.michalmatu.aicallbridge"
REMOTE="/data/local/tmp/aicall-phone-llm"
PORT="18115"
MODEL_LOCAL="/tmp/aicall-qwen15b-quality-3690/qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_REMOTE="$REMOTE/model-1.5b.gguf"
MODEL_SHA="6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e"
export ANDROID_HOME="$HOME/Library/Android/sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export GRADLE_BIN="$HOME/.gradle/local-agent/gradle-9.6.0/bin/gradle"

git fetch origin main agent-control
git checkout main
git reset --hard origin/main
git clean -fd
test "$(git rev-parse HEAD)" = "$EXPECTED_MAIN"
test -z "$(git status --porcelain)"

CALL_STATE=$(adb -s "$SERIAL" shell dumpsys telephony.registry | sed -n 's/.*mCallState=\([0-9][0-9]*\).*/\1/p' | head -1)
test "$CALL_STATE" = 0
echo qwen15b_verified_call_state_before=$CALL_STATE

test -f "$MODEL_LOCAL"
test "$(shasum -a 256 "$MODEL_LOCAL" | awk '{print $1}')" = "$MODEL_SHA"
REMOTE_SHA=$(adb -s "$SERIAL" shell sha256sum "$MODEL_REMOTE" | awk '{print $1}' | tr -d '\r')
test "$REMOTE_SHA" = "$MODEL_SHA"
echo qwen15b_verified_model_sha=true

PIDS=$(adb -s "$SERIAL" shell pidof llama-server 2>/dev/null | tr -d '\r' || true)
for p in $PIDS; do
  adb -s "$SERIAL" shell kill "$p" 2>/dev/null || true
done
for i in $(seq 1 40); do
  NOW=$(adb -s "$SERIAL" shell pidof llama-server 2>/dev/null | tr -d '\r' || true)
  [ -z "$NOW" ] && break
  sleep 0.25
done
test -z "$(adb -s "$SERIAL" shell pidof llama-server 2>/dev/null | tr -d '\r' || true)"
echo qwen15b_old_servers_stopped=true

adb -s "$SERIAL" shell "rm -f '$REMOTE/server.pid' '$REMOTE/llama-1.5b.log'; cd '$REMOTE'; export LD_LIBRARY_PATH='$REMOTE'; nohup ./llama-server -m '$MODEL_REMOTE' --host 127.0.0.1 --port $PORT --alias qwen-phone-1.5b -c 1024 -t 4 -np 1 > '$REMOTE/llama-1.5b.log' 2>&1 < /dev/null &" || true
adb -s "$SERIAL" forward --remove tcp:$PORT >/dev/null 2>&1 || true
adb -s "$SERIAL" forward tcp:$PORT tcp:$PORT >/dev/null
READY=0
for i in $(seq 1 180); do
  if curl -fsS --max-time 3 "http://127.0.0.1:$PORT/health" >/tmp/qwen15b-3710-health.json 2>/dev/null; then
    READY=1
    break
  fi
  sleep 1
done
if [ "$READY" != 1 ]; then
  echo '--- qwen15b server log ---'
  adb -s "$SERIAL" shell tail -160 "$REMOTE/llama-1.5b.log" || true
  exit 1
fi

curl -fsS --max-time 5 "http://127.0.0.1:$PORT/props" > /tmp/qwen15b-3710-props.json
python3 - <<'PY'
import json
p=json.load(open('/tmp/qwen15b-3710-props.json'))
assert p.get('model_alias')=='qwen-phone-1.5b', p.get('model_alias')
assert p.get('model_path','').endswith('/model-1.5b.gguf'), p.get('model_path')
assert p.get('chat_template')
print('qwen15b_props_alias_verified=true')
print('qwen15b_props_model_path_verified=true')
print('qwen15b_chat_template_present=true')
PY
PID=$(adb -s "$SERIAL" shell pidof llama-server 2>/dev/null | tr -d '\r' | awk '{print $1}')
test -n "$PID"
adb -s "$SERIAL" shell "echo '$PID' > '$REMOTE/server.pid'"
adb -s "$SERIAL" shell "tr '\0' ' ' < /proc/$PID/cmdline 2>/dev/null; echo" || true
echo qwen15b_verified_server_ready=true

python3 - <<'PY'
import json, urllib.request, time

def ask(messages):
    p={'model':'qwen-phone-1.5b','stream':False,'temperature':0.0,'max_tokens':64,'messages':messages}
    r=urllib.request.Request('http://127.0.0.1:18115/v1/chat/completions',data=json.dumps(p).encode(),headers={'Content-Type':'application/json'})
    started=time.monotonic()
    with urllib.request.urlopen(r,timeout=60) as f:
        text=json.load(f)['choices'][0]['message']['content'].strip()
    return text,time.monotonic()-started

math,math_s=ask([{'role':'user','content':'Odpowiedz tylko liczbą: ile to 2+2?'}])
print('qwen15b_verified_math=' + math.replace('\n',' '))
print(f'qwen15b_verified_math_latency_seconds={math_s:.3f}')
assert math.strip()=='4', math
prompt='Jesteś lokalnym asystentem reprezentującym użytkownika w rozmowie telefonicznej po polsku. Wejście użytkownika jest automatycznym transkryptem wypowiedzi drugiej strony i może być niepełne lub niedokładne. Odpowiadaj krótko i naturalnie, najwyżej jednym zdaniem. Nie wymyślaj faktów, nazw, ofert ani intencji. Jeśli transkrypt jest zbyt krótki, niejasny albo wygląda jak fragment powitania lub komunikatu IVR, poproś krótko o kontynuowanie lub doprecyzowanie. Nie składaj zamówień, nie akceptuj umów, nie ujawniaj danych wrażliwych i nie podejmuj zobowiązań bez jawnej autoryzacji aplikacji.'
text,text_s=ask([{'role':'system','content':prompt},{'role':'user','content':'orange'}])
print('qwen15b_verified_ambiguous_response=' + text.replace('\n',' '))
print(f'qwen15b_verified_ambiguous_latency_seconds={text_s:.3f}')
assert text and len(text)<300
PY
echo qwen15b_direct_quality_smoke=true

"$GRADLE_BIN" :app:assembleDebug >/tmp/qwen15b-3710-build.log 2>&1 || { cat /tmp/qwen15b-3710-build.log; exit 1; }
adb -s "$SERIAL" install -r app/build/outputs/apk/debug/app-debug.apk >/tmp/qwen15b-3710-install.log 2>&1 || { cat /tmp/qwen15b-3710-install.log; exit 1; }
adb -s "$SERIAL" shell run-as "$PKG" rm -f files/local-phone-llm-speech-pipeline-report.txt 2>/dev/null || true
adb -s "$SERIAL" shell am force-stop "$PKG"
adb -s "$SERIAL" shell am start -W -n "$PKG/.DiagnosticProbeActivity" --ez run_local_phone_llm_speech_pipeline_probe true >/tmp/qwen15b-3710-offcall-start.log
REPORT=''
for i in $(seq 1 300); do
  REPORT=$(adb -s "$SERIAL" shell run-as "$PKG" cat files/local-phone-llm-speech-pipeline-report.txt 2>/dev/null | tr -d '\r' || true)
  printf '%s\n' "$REPORT" | grep -q '^probe_complete=true$' && break
  sleep 0.5
done
printf '%s\n' "$REPORT" > /tmp/qwen15b-3710-offcall-report.txt
echo '--- verified 1.5b offcall report ---'
cat /tmp/qwen15b-3710-offcall-report.txt
echo '--- end verified 1.5b offcall report ---'
printf '%s\n' "$REPORT" | grep -q '^backend_config_valid=true$'
printf '%s\n' "$REPORT" | grep -q '^stt_transcript_nonblank=true$'
printf '%s\n' "$REPORT" | grep -q '^backend_complete_response=true$'
printf '%s\n' "$REPORT" | grep -q '^approved_output_pcm_nonempty=true$'
printf '%s\n' "$REPORT" | grep -q '^local_phone_llm_speech_pipeline_success=true$'
echo qwen15b_verified_offcall_proven_s22=true

CALL_STATE=$(adb -s "$SERIAL" shell dumpsys telephony.registry | sed -n 's/.*mCallState=\([0-9][0-9]*\).*/\1/p' | head -1)
test "$CALL_STATE" = 0
PYTHONPATH=scripts python3 scripts/local_phone_llm_live_call.py "$SERIAL" | tee /tmp/qwen15b-3710-orange.log
grep -q '^allowlisted_target=510100100$' /tmp/qwen15b-3710-orange.log
grep -q '^local_phone_llm_orange_live_turn_proven_s22=true$' /tmp/qwen15b-3710-orange.log
grep -q '^hangup_requested=true$' /tmp/qwen15b-3710-orange.log
grep -q '^idle_after_hangup=True$' /tmp/qwen15b-3710-orange.log
CALL_STATE_AFTER=$(adb -s "$SERIAL" shell dumpsys telephony.registry | sed -n 's/.*mCallState=\([0-9][0-9]*\).*/\1/p' | head -1)
test "$CALL_STATE_AFTER" = 0
HELPER=$(adb -s "$SERIAL" shell pidof "$PKG:call_media" 2>/dev/null | tr -d '\r' || true)
test -z "$HELPER"
echo qwen15b_verified_orange_live_proven_s22=true
adb -s "$SERIAL" shell "cat /proc/$PID/status 2>/dev/null | grep -E '^(VmRSS|VmHWM|Threads):'" || true

git show origin/agent-control:.agent/patches/finalize-local-text-agent-docs-20260919.py > /tmp/finalize-local-text-agent-docs.py
python3 /tmp/finalize-local-text-agent-docs.py
git diff --check
git add docs/ARCHITECTURE.md docs/ROADMAP.md docs/SECURITY_PRIVACY.md docs/HANDOFF_NEXT_CHAT.md docs/LOCAL_TEXT_AGENT_STATUS_2026-09-19.md
git commit -m 'docs: close local text agent live flow'
DOCS_COMMIT=$(git rev-parse HEAD)
git push origin HEAD:main
echo local_text_agent_docs_commit=$DOCS_COMMIT
test -z "$(git status --porcelain)"
echo qwen15b_verified_flow_and_docs_complete=true
