#!/usr/bin/env python3
from pathlib import Path
import json

root = Path('.')
orange_log = Path('/tmp/qwen15b-3710-orange.log').read_text(errors='replace')
props = json.loads(Path('/tmp/qwen15b-3710-props.json').read_text())

def kv(text: str, key: str, default: str = 'not-recorded') -> str:
    prefix = key + '='
    values = [line[len(prefix):].strip() for line in text.splitlines() if line.startswith(prefix)]
    return values[-1] if values else default

stt = kv(orange_log, 'stt_text')
approved = kv(orange_log, 'approved_text')
stt_ms = kv(orange_log, 'stt_elapsed_ms')
llm_ms = kv(orange_log, 'llm_approved_elapsed_ms')
turn_ms = kv(orange_log, 'turn_complete_elapsed_ms')
tx_bytes = kv(orange_log, 'telephony_tx_pcm_bytes')
assert props.get('model_alias') == 'qwen-phone-1.5b'
assert props.get('model_path', '').endswith('/model-1.5b.gguf')
assert kv(orange_log, 'local_phone_llm_live_call_success') == 'true'

status = f'''# Local text-agent status — 2026-09-19

## Verdict

The local speech/text telephone-agent path is physically proven on the target Samsung S22+.

Proven live cellular path:

```text
allowlisted cellular dial
  -> telephony RX PCM16/16k
  -> on-device pl-PL STT
  -> text LLM provider
  -> application-owned output approval
  -> local pl-PL TTS
  -> telephony TX
  -> bounded hangup / cleanup
```

The frozen Samsung Phase 2D media invariants were reused; this work did not introduce a second telephony media implementation.

## Durable checkpoints

```text
a8c363ae7b05e9da6836156829c2d1fc1d560869
feat: add local phone llm runtime provider

655644bbf83ca46b820bb4b7502438e5f25e1aed
feat: add allowlisted local phone live turn

7ae1c7cd4892b780caa7be28974aa04a69e97696
feat: improve local phone llm call quality
```

## Qwen2.5 0.5B evidence

`Qwen2.5-0.5B-Instruct Q4_K_M` was the first on-device proof model. It proved the complete architecture and an automated live Orange call, but response quality was inadequate for normal use.

First live Orange proof included:

```text
stt_text=orange
backend_complete_response=true
telephony_tx_pcm_bytes=142946
local_phone_llm_live_call_success=true
```

This is retained as a small/offline smoke model, not the preferred quality model.

## Qwen2.5 1.5B corrected evidence

Model artifact:

```text
Qwen2.5-1.5B-Instruct Q4_K_M
SHA256=6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e
```

Corrected model-identity gate required `/props` to report both:

```text
model_alias={props['model_alias']}
model_path={props['model_path']}
```

This requirement exists because an earlier quality run downloaded and verified the 1.5B GGUF but accidentally continued talking to the stale 0.5B server on port 18115. The follow-up audit caught that mismatch. Do not treat the earlier run as 1.5B evidence.

Corrected verified live Orange turn:

```text
stt_text={stt}
approved_text={approved}
stt_elapsed_ms={stt_ms}
llm_approved_elapsed_ms={llm_ms}
telephony_tx_pcm_bytes={tx_bytes}
turn_complete_elapsed_ms={turn_ms}
local_phone_llm_live_call_success=true
```

The runner establishes only the operator-defined allowlisted test destination, restores temporary Bluetooth/mute state, hangs up the call it created and requires clean final call/helper state.

## Product modes

### LOCAL_PHONE_LLM

Purpose: private/offline/local fallback and experimentation.

```text
telephony RX -> local STT -> llama.cpp/Qwen on S22 -> approval -> local TTS -> telephony TX
```

Benefits:

- no cloud model dependency;
- transcript/model text can remain on-device;
- works without Mac;
- same deterministic workflow/commitment/output gates as every other provider.

Tradeoffs:

- model quality is constrained by phone memory/compute/thermals;
- inference-server lifecycle is not yet app-owned production lifecycle;
- current whole-turn speech path is optimized for proof/safety rather than conversational latency.

### OPENAI_TEXT hybrid

Recommended next quality path:

```text
telephony RX
  -> on-device STT
  -> transcript only to narrow authenticated backend
  -> OpenAI text model
  -> application-owned approval
  -> on-device TTS
  -> telephony TX
```

Raw call audio does not need to leave the S22 in this mode. A standard OpenAI API key stays on the backend and never ships in the APK/ADB/Android storage.

This is not the same persistent ChatGPT UI conversation. It is an API-backed text agent supplied with the call task, constraints, authorized facts, system prompt and bounded conversation history.

## Latency plan

The current live probe uses a fixed speech capture window, which dominates turn latency. The priority optimization is end-of-speech detection/VAD, not prematurely streaming unapproved model audio.

Target sequence:

```text
speech end detected
 -> finalize local STT immediately
 -> one short text-model request
 -> complete candidate approval
 -> short local TTS response
 -> TX
```

Near-term target: begin speaking roughly 2–4 seconds after the counterparty stops under good network/device conditions. This is a target to measure, not a guaranteed SLA.

Keep whole-response approval initially. Later sentence/chunk optimization is allowed only if it preserves equivalent application-owned approval and commitment semantics.

## Phone memory planning

16 GB system RAM is useful but not a requirement for local LLM mode.

Rough planning guidance for Q4-class models (actual runtime use varies with architecture, context/KV cache and backend):

- ~1.5B: comfortable proof class on an 8 GB phone;
- ~3B: realistic next quality tier on 8 GB with bounded context and careful background memory;
- ~7B: often possible only with much tighter headroom and materially worse thermal/latency risk on an 8 GB Android phone;
- 12–16 GB: much better headroom for 7B-class models and larger context; larger models can still be limited by memory bandwidth, CPU/GPU/NPU support and heat.

Do not select models from weight-file size alone. Measure RSS/HWM, tokens/s, first-response latency and sustained temperature on the target phone.

## Next engineering gates

1. Add speech end detection/VAD instead of a fixed 8-second capture window.
2. Implement `OPENAI_TEXT` as a production text backend through a narrow credential/backend boundary.
3. Keep model response to one short phone-friendly utterance and measure time-to-first-TX audio.
4. Make local `llama-server` readiness/lifecycle app-owned before calling local mode product-ready.
5. Compare verified 1.5B/3B local models against the hybrid OpenAI text path using the same transcripts and approval policy.
'''
(root / 'docs/LOCAL_TEXT_AGENT_STATUS_2026-09-19.md').write_text(status)

arch = (root / 'docs/ARCHITECTURE.md').read_text()
arch = arch.replace(
'''          text LLM provider
          /              \\
 OPENAI_TEXT       LOCAL_MAC_LLM
''',
'''                 text LLM provider
          /              |              \\
 OPENAI_TEXT       LOCAL_PHONE_LLM       LOCAL_MAC_LLM
''')
arch = arch.replace(
'- text LLM provider for `LOCAL_STT_TTS`: `OPENAI_TEXT`, `LOCAL_MAC_LLM`;',
'- text LLM provider for `LOCAL_STT_TTS`: `OPENAI_TEXT`, `LOCAL_PHONE_LLM`, `LOCAL_MAC_LLM`;')
arch = arch.replace(
'''Planned implementations:

- `OPENAI_TEXT` — remote text provider through a safe backend credential boundary;
- `LOCAL_MAC_LLM` — local/LAN model server on the user's Mac.
''',
'''Provider implementations/directions:

- `OPENAI_TEXT` — recommended hybrid quality path: local S22 STT/TTS with transcript-only remote text inference through a safe backend credential boundary;
- `LOCAL_PHONE_LLM` — proven S22 phone-loopback `llama.cpp` provider for private/offline operation and fallback;
- `LOCAL_MAC_LLM` — proven local/LAN OpenAI-compatible model server path on the user's Mac.

`LOCAL_PHONE_LLM` and `OPENAI_TEXT` share the same `TextCallAgentBackend`, `TextCallTurnController`, approval and commitment boundaries. Provider choice must not change authority semantics.
''')
(root / 'docs/ARCHITECTURE.md').write_text(arch)

road = (root / 'docs/ROADMAP.md').read_text()
road = road.replace(
'Status: `LOCAL SPEECH + LOCAL PHONE LLM OFF-CALL PROVEN_S22 / LIVE CELLULAR INTEGRATION NEXT / OPENAI REALTIME AUDIO FROZEN`',
'Status: `LOCAL SPEECH + LOCAL PHONE LLM LIVE CELLULAR PROVEN_S22 / OPENAI_TEXT HYBRID NEXT / OPENAI REALTIME AUDIO FROZEN`')
road = road.replace(
'Status: `LOCAL_MAC_LLM PROVEN_S22 / LOCAL_PHONE_LLM OFF-CALL PROVEN_S22 / PRODUCT RUNTIME WIRING NEXT`',
'Status: `LOCAL_MAC_LLM PROVEN_S22 / LOCAL_PHONE_LLM 1.5B LIVE PROVEN_S22`')
road = road.replace(
'Next: promote `LOCAL_PHONE_LLM` from diagnostic configuration into normal runtime provider selection with readiness/lifecycle/failure handling and rerun the focused S22 regression gate.',
'`LOCAL_PHONE_LLM` is now a normal runtime provider. Qwen2.5 0.5B proved the initial architecture; the corrected 1.5B gate additionally requires model identity from `/props` before physical evidence is accepted. App-owned inference-server lifecycle/readiness remains a productization task.')
road = road.replace('### Gate 3L-D — controlled automated local-speech cellular call\n\nStatus: `NEXT`', '### Gate 3L-D — controlled automated local-speech cellular call\n\nStatus: `DONE / PROVEN_S22`')
marker = '### OpenAI Realtime Audio branch\n'
insert = '''Live automated Orange validation is now physically proven with local STT, local phone LLM, application approval, local TTS, telephony TX, bounded hangup and clean helper/call state. See `docs/LOCAL_TEXT_AGENT_STATUS_2026-09-19.md` for the corrected 1.5B identity gate and latency measurements.\n\n### Gate 3L-E — hybrid OpenAI text brain\n\nStatus: `NEXT`\n\nKeep STT/TTS and telephony media on the S22 while sending only finalized transcript/context through a narrow authenticated backend to an OpenAI text model. Preserve complete-response application approval initially. Primary latency work is VAD/end-of-speech finalization plus short responses, not bypassing approval.\n\n'''
if insert not in road:
    road = road.replace(marker, insert + marker)
road = road.replace(
'Finish `LOCAL_PHONE_LLM` as a normal runtime provider, then run the first controlled automated cellular validation against an explicitly allowlisted Orange customer-service destination on the dedicated test SIM. Preserve frozen Samsung media behavior and the OpenAI Realtime alternative.',
'Optimize live-turn latency with end-of-speech/VAD, then implement the hybrid `OPENAI_TEXT` backend while retaining verified `LOCAL_PHONE_LLM` as private/offline fallback. Preserve frozen Samsung media behavior and the OpenAI Realtime alternative.')
(root / 'docs/ROADMAP.md').write_text(road)

sec = (root / 'docs/SECURITY_PRIVACY.md').read_text()
sec = sec.replace('''OPENAI_TEXT
LOCAL_MAC_LLM
''', '''OPENAI_TEXT
LOCAL_PHONE_LLM
LOCAL_MAC_LLM
''')
sec = sec.replace(
'No validation runner may dial or hang up the cellular call unless a future explicit test requirement says so and is separately authorized.',
'Controlled validation runners may dial and hang up only operator-defined allowlisted test destinations under the project guardrails. Model/tool output cannot create or widen the allowlist, and emergency/premium/bulk/arbitrary-short-code dialing remains prohibited.')
sec = sec.replace(
'- production local speech adapters in a real cellular call;\n- `OPENAI_TEXT` telephone-agent path;',
'- `OPENAI_TEXT` telephone-agent path;')
if '- local phone LLM automated live cellular turn;' not in sec:
    sec = sec.replace('- local TTS -> PCM16LE mono 16 kHz -> PFD pipe -> on-device STT round-trip on S22;\n', '- local TTS -> PCM16LE mono 16 kHz -> PFD pipe -> on-device STT round-trip on S22;\n- local phone LLM automated live cellular turn with application approval and clean hangup/cleanup;\n')
(root / 'docs/SECURITY_PRIVACY.md').write_text(sec)

handoff = (root / 'docs/HANDOFF_NEXT_CHAT.md').read_text()
append = '''\n## 2026-09-19 closure update\n\nThe previous immediate-next sections above are historical context. Current authoritative local text-agent state is `docs/LOCAL_TEXT_AGENT_STATUS_2026-09-19.md`.\n\nCurrent priority:\n\n1. retain verified `LOCAL_PHONE_LLM` as private/offline fallback;\n2. add VAD/end-of-speech turn finalization to remove the fixed capture-window latency;\n3. implement `OPENAI_TEXT` as the preferred quality path using local S22 STT/TTS and transcript-only remote inference through a narrow backend credential boundary;\n4. keep whole-response application approval until any lower-latency sentence/chunk scheme proves equivalent safety;\n5. keep OpenAI Realtime audio preserved/frozen unless explicitly resumed.\n\nCorrected 1.5B evidence must include `/props` identity for `qwen-phone-1.5b`; an earlier run that merely downloaded the 1.5B file was invalid because the stale 0.5B process still owned port 18115.\n'''
if '## 2026-09-19 closure update' not in handoff:
    handoff += append
(root / 'docs/HANDOFF_NEXT_CHAT.md').write_text(handoff)

print('local_text_agent_docs_finalized=true')
