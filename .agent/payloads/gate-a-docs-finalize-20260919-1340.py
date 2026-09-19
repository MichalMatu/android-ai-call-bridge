from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing marker: {label}")
    return text.replace(old, new, 1)

# README
p = Path("README.md")
s = p.read_text()
s = replace_once(
    s,
    "- product-owned local LLM start/identity-check/stop lifecycle: `DONE / PROVEN_S22`;\n- live end-of-utterance detection: `DONE / PROVEN_S22`;",
    "- product-owned local LLM start/identity-check/stop lifecycle: `DONE / PROVEN_S22`;\n- pre-dial local `READY_TO_DIAL` + prepared local text-call session boundary: `DONE / PROVEN_S22` (off-call readiness);\n- live end-of-utterance detection: `DONE / PROVEN_S22`;",
    "readme proven baseline",
)
s = replace_once(
    s,
    ".agent/results/live-endpointing-orange-s22-20260919-1214.json\n",
    ".agent/results/live-endpointing-orange-s22-20260919-1214.json\n.agent/results/gate-a-offcall-ready-s22-20260919-1335.json\n",
    "readme evidence",
)
s = replace_once(
    s,
    "1. create a hard `READY_TO_DIAL` gate and a clean product-owned local text-call orchestration boundary;",
    "1. **DONE / PROVEN_S22** — hard `READY_TO_DIAL` gate plus a one-shot prepared local text-call session boundary;",
    "readme plan",
)
p.write_text(s)

# ROADMAP
p = Path("docs/ROADMAP.md")
s = p.read_text()
s = replace_once(
    s,
    "## Gate A — clean product orchestration + READY_TO_DIAL\n\nStatus: `NEXT`",
    "## Gate A — clean product orchestration + READY_TO_DIAL\n\nStatus: `DONE / HOST_GREEN / PROVEN_S22` (off-call readiness)",
    "roadmap gate a status",
)
marker = "Exit: selected local backend, STT, TTS and scenario are proven ready before dialing.\n"
insert = """Exit: selected local backend, STT, TTS and scenario are proven ready before dialing.

Implemented boundary:

- `LocalTextCallReadinessCoordinator` validates workflow/target authority, local speech readiness and bounded backend warm-up;
- `AndroidLocalTextCallSpeechPreflight` proves on-device STT plus a non-network TTS voice before dial;
- the existing `IdentityVerifiedLocalPhoneLlmBackend` remains the runtime + exact-identity authority before warm-up inference;
- successful preparation returns one-shot `PreparedLocalTextCall`;
- `LocalTextCallSession` consumes that prepared backend and delegates dialogue turns to the existing `LocalSpeechTextPipeline`;
- telephony media and endpointing remain outside this new layer, so the frozen Samsung path was not changed.

Evidence:

```text
TDD RED:    .agent/results/gate-a-readiness-red-20260919-1325.json
TDD GREEN:  .agent/results/gate-a-readiness-green-20260919-1329.json
HOST_GREEN: .agent/results/gate-a-full-host-20260919-1332.json
PROVEN_S22: .agent/results/gate-a-offcall-ready-s22-20260919-1335.json
```
"""
s = replace_once(s, marker, insert, "roadmap gate a evidence")
s = replace_once(
    s,
    "## Gate B — text-brain benchmark\n\nStatus: `AFTER A`",
    "## Gate B — text-brain benchmark\n\nStatus: `NEXT`",
    "roadmap gate b status",
)
p.write_text(s)

# ARCHITECTURE
p = Path("docs/ARCHITECTURE.md")
s = p.read_text()
s = replace_once(
    s,
    "## Next product ownership boundaries\n\nThe next phase should add responsibilities without turning probes or Activities into product orchestrators.\n",
    """## Product ownership boundaries

Gate A now provides a narrow pre-dial/product session seam without turning probes or Activities into product orchestrators:

```text
CallWorkflow READY_TO_DIAL + explicit target authorization
        |
        v
LocalTextCallReadinessCoordinator
   |       |       |
   |       |       `-> selected backend runtime + exact identity + bounded warm-up
   |       `----------> AndroidLocalTextCallSpeechPreflight (on-device STT + local TTS)
   `------------------> existing task/target/authority state
        |
        v
PreparedLocalTextCall  (one-shot ownership transfer)
        |
        v
LocalTextCallSession
        |
        `-> existing LocalSpeechTextPipeline
```

The new session intentionally does **not** own telephony media or endpointing yet. Those remain outside the Gate A layer so the frozen Samsung path is unchanged; a later call orchestrator composes the prepared session with the already-proven media generation/endpoint lease.

The longer-term conceptual target remains:
""",
    "architecture gate a ownership",
)
p.write_text(s)

# HANDOFF
p = Path("docs/HANDOFF_NEXT_CHAT.md")
s = p.read_text()
s = replace_once(
    s,
    "# Handoff — clean local-first execution baseline",
    "# Handoff — Gate A READY_TO_DIAL proven",
    "handoff title",
)
s = replace_once(
    s,
    "Product-owned local model runtime start/identity verification/stop is physically proven.\n",
    "Product-owned local model runtime start/identity verification/stop is physically proven.\n\nGate A pre-dial `READY_TO_DIAL` + prepared local text-call session boundary is `HOST_GREEN / PROVEN_S22` off-call.\n",
    "handoff solid gate a",
)
s = replace_once(
    s,
    "### A. READY_TO_DIAL + clean product orchestration\n\nFirst active task.",
    "### A. READY_TO_DIAL + clean product orchestration — DONE / PROVEN_S22\n\nCompleted on 2026-09-19 without changing the frozen Samsung media path.",
    "handoff gate a heading",
)
s = replace_once(
    s,
    "Start with a preimplementation architecture audit/TDD plan, then implement the narrowest readiness/session boundary.\n",
    """Implemented with `LocalTextCallReadinessCoordinator`, `AndroidLocalTextCallSpeechPreflight`, one-shot `PreparedLocalTextCall` and `LocalTextCallSession`. The session reuses `LocalSpeechTextPipeline` and does not own telephony media/endpointing.

Evidence:

```text
.agent/results/gate-a-readiness-red-20260919-1325.json
.agent/results/gate-a-readiness-green-20260919-1329.json
.agent/results/gate-a-full-host-20260919-1332.json
.agent/results/gate-a-offcall-ready-s22-20260919-1335.json
```
""",
    "handoff gate a implementation",
)
s = replace_once(
    s,
    "### B. Text-model quality benchmark\n\nAfter readiness:",
    "### B. Text-model quality benchmark — NEXT\n\nGate A is complete. Next:",
    "handoff gate b",
)
start = s.find("## Exact next task for a new chat")
if start < 0:
    raise SystemExit("missing marker: handoff exact next task")
s = s[:start] + """## Exact next task for a new chat

Continue with **Gate B** only:

> Build the deterministic text-model benchmark harness on top of the proven Gate A readiness/session seam. Keep telephony, endpointing, STT/TTS, authority and scenario inputs fixed. Benchmark the current Qwen2.5 1.5B first off-call, then one larger feasible phone-local model, and use GPT-5.6 Sol through this interactive ChatGPT + Local Agent/ADB relay as the strong reference. Measure response quality, invented/unsafe facts, fallback/escalation, inference latency, load/warm-up, RAM and thermal/resource behavior. Do not change the frozen Samsung media path and do not resume paid OpenAI API work.

Do not start Gate C/D/E until Gate B has comparable evidence.
"""
p.write_text(s)
