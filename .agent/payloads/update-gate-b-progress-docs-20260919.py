from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)

roadmap_path = Path("docs/ROADMAP.md")
roadmap = roadmap_path.read_text(encoding="utf-8")
roadmap = replace_once(
    roadmap,
    "## Gate B — text-brain benchmark\n\nStatus: `NEXT`",
    "## Gate B — text-brain benchmark\n\nStatus: `IN PROGRESS / HARNESS_HOST_GREEN / QWEN15B_PROVEN_S22`",
    "roadmap status",
)
marker = (
    "The ChatGPT relay is test infrastructure, not a production autonomous backend. It requires an active interactive chat and must not be described as a background service. "
    "Raw call audio need not leave the phone; the relay can operate on bounded STT text and return bounded response text for local TTS.\n\n"
)
evidence = marker + """Current Gate B evidence (2026-09-19):

- frozen suite `benchmarks/text_model_suite_v1.json` contains 8 identical Polish phone-call transcript scenarios;
- deterministic host harness `scripts/text_model_benchmark.py` fixes generation to `temperature=0`, `seed=42`, `max_tokens=96`, verifies local model identity through `/props`, records complete responses and wall/llama.cpp timings, and applies conservative deterministic safety checks;
- harness TDD + final host verification: `.agent/results/gate-b-benchmark-red-20260919-1405.json`, `.agent/results/gate-b-benchmark-green-20260919-1410.json`, `.agent/results/gate-b-benchmark-final-host-20260919-1440.json`;
- Qwen2.5 1.5B S22 baseline: 24 samples (8 scenarios x 3), only 6/24 deterministic-safe (`25%`), median model-request wall time `1465.535 ms`, p95 `2690.038 ms`, warm-up `3588.515 ms`, and measured server `VmHWM=2087376 kB`; it incorrectly accepted purchase/appointment commitments, so it is not acceptable as an authority/reasoning brain. Evidence: `.agent/results/gate-b-qwen15b-baseline-s22-retry-20260919-1424.json`;
- GPT-5.6 Sol interactive reference: 8/8 deterministic-safe on one reference pass using the same frozen transcripts. This is quality/reference evidence only; interactive ChatGPT serving latency and RAM are deliberately not compared with phone-local inference. Durable result: `benchmarks/results/gpt56_sol_interactive_reference_v1.json`; verification: `.agent/results/gate-b-gpt56-reference-verify-20260919-1443.json`;
- larger-model candidate Qwen3-4B-Instruct-2507 Q4_K_M was copied to the S22 with exact SHA and reached `/health`, but the first completion disconnected after about 76 seconds. Root cause is not yet proven; the next crash-diagnostic attempt was blocked because the S22 disappeared from USB ADB. Do not label the 4B model as OOM until server/LMKD evidence proves it. Evidence: `.agent/results/gate-b-qwen3-4b-install-benchmark-s22-20260919-1432.json`, `.agent/results/gate-b-qwen3-4b-latency-diagnostic-s22-20260919-1440.json`, `.agent/results/gate-b-qwen3-4b-crash-diagnostic-s22-retry-20260919-1436.json`.

Next Gate B step: when direct USB ADB to `RFCT70L7E8J` is available again, diagnose the already-present 4B model without re-downloading it. Capture server log, process lifetime/RSS and LMKD/OOM evidence around the first completion. If that quant/model is not viable, select a lower-memory but still meaningfully larger phone-local candidate and run the exact same frozen suite before any live call comparison.\n\n"""
roadmap = replace_once(roadmap, marker, evidence, "roadmap evidence insertion")
roadmap_path.write_text(roadmap, encoding="utf-8")

handoff_path = Path("docs/HANDOFF_NEXT_CHAT.md")
handoff = handoff_path.read_text(encoding="utf-8")
handoff = replace_once(
    handoff,
    "# Handoff — Gate A READY_TO_DIAL proven",
    "# Handoff — Gate B text benchmark in progress",
    "handoff title",
)
old_b = """### B. Text-model quality benchmark — NEXT

Gate A is complete. Next:

- current Qwen2.5 1.5B;
- one larger feasible local phone model;
- GPT-5.6 Sol through this interactive ChatGPT conversation using Local Agent/ADB as a developer relay.

Use the same scenarios, STT/TTS, endpointing and telephony path. Measure quality, hallucinations, latency, load/warm-up, RAM and resources.

The ChatGPT relay is a controlled interactive benchmark, not a production/background backend.
"""
new_b = """### B. Text-model quality benchmark — IN PROGRESS

The deterministic text-only comparison seam is now on `main`:

```text
benchmarks/text_model_suite_v1.json
scripts/text_model_benchmark.py
scripts/test_text_model_benchmark.py
```

The harness intentionally isolates model quality from STT/TTS variability. It fixes `temperature=0`, `seed=42`, `max_tokens=96`, verifies local `/props` identity and records responses/timings/findings. Full speech/live comparisons come only after a useful text-model candidate survives this gate.

Current evidence:

```text
Harness RED:        .agent/results/gate-b-benchmark-red-20260919-1405.json
Harness GREEN:      .agent/results/gate-b-benchmark-green-20260919-1410.json
Final HOST_GREEN:   .agent/results/gate-b-benchmark-final-host-20260919-1440.json
Qwen2.5 1.5B S22:  .agent/results/gate-b-qwen15b-baseline-s22-retry-20260919-1424.json
GPT-5.6 reference:  .agent/results/gate-b-gpt56-reference-verify-20260919-1443.json
```

Measured so far:

- Qwen2.5-1.5B Q4_K_M: `6/24` deterministic-safe (`25%`) across three repeats; median request `1465.535 ms`, p95 `2690.038 ms`, warm-up `3588.515 ms`; it incorrectly accepted purchase/appointment commitments;
- GPT-5.6 Sol interactive reference: `8/8` deterministic-safe on one reference pass. Result is in `benchmarks/results/gpt56_sol_interactive_reference_v1.json`. It is not a production backend and its ChatGPT serving latency/RAM are not comparable to phone-local llama.cpp;
- Qwen3-4B-Instruct-2507 Q4_K_M is already present on the S22 with verified SHA and can reach `/health`, but its first completion disconnected after about 76 seconds. The root cause is still unproven because the next diagnostic could not start after the S22 disappeared from direct USB ADB.

Do not infer OOM from the disconnect alone. Resume by capturing the 4B server log, process/RSS and LMKD/OOM evidence around its first completion. If this 4B quant is not viable, choose a lower-memory but meaningfully larger local candidate and run the identical frozen suite.

The ChatGPT relay remains controlled interactive benchmark infrastructure, never a production/background backend.
"""
handoff = replace_once(handoff, old_b, new_b, "handoff Gate B section")
old_next = """## Exact next task for a new chat

Continue with **Gate B** only:

> Build the deterministic text-model benchmark harness on top of the proven Gate A readiness/session seam. Keep telephony, endpointing, STT/TTS, authority and scenario inputs fixed. Benchmark the current Qwen2.5 1.5B first off-call, then one larger feasible phone-local model, and use GPT-5.6 Sol through this interactive ChatGPT + Local Agent/ADB relay as the strong reference. Measure response quality, invented/unsafe facts, fallback/escalation, inference latency, load/warm-up, RAM and thermal/resource behavior. Do not change the frozen Samsung media path and do not resume paid OpenAI API work.

Do not start Gate C/D/E until Gate B has comparable evidence.
"""
new_next = """## Exact next task for a new chat

Continue with **Gate B** only:

> Fetch fresh `main` and `agent-control:.agent/status/daemon.json`. Do not rebuild the benchmark harness or rerun the proven 1.5B baseline. First check that S22 `RFCT70L7E8J` is again available over direct USB ADB. The Qwen3-4B-Instruct-2507 Q4_K_M candidate is already on the phone; reproduce its first-completion disconnect while capturing the llama-server log, process/RSS lifetime and LMKD/OOM evidence. Do not assume OOM before measuring it. If this candidate is not viable, choose a lower-memory but still meaningfully larger phone-local model and run the exact frozen `phone-call-text-v1` suite. Compare it against the existing Qwen2.5 1.5B and GPT-5.6 Sol evidence, then decide Gate B. Do not change frozen Samsung media and do not resume paid OpenAI API work.

Do not start Gate C/D/E until Gate B has comparable larger-local-model evidence.
"""
handoff = replace_once(handoff, old_next, new_next, "handoff next task")
handoff_path.write_text(handoff, encoding="utf-8")
