from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    if old not in text:
        raise RuntimeError(f"missing checkpoint anchor in {path}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1))


checkpoint_old = """Latest behavior cleanup checkpoint before this documentation refresh:

```text
d191b6cc8afcee636a3ad3c8b7b4dc7fee6e8417
refactor: use strict Gson reader API
```
"""
checkpoint_new = """Latest behavior checkpoint before this documentation refresh:

```text
b6774dd00efaab5c5272e3be196d42c3def64da5
fix: harden pre-api credential boundary
```

This includes the one-command off-call launcher, Quick Tunnel readiness/retry handling, allowlisted child environments, strict Quick Tunnel host parsing, and exact direct-USB S22 validation before off-call secret staging.
"""
replace_once("docs/HANDOFF_NEXT_CHAT.md", checkpoint_old, checkpoint_new)
replace_once("docs/PHASE3_REALTIME_STATUS_2026-09-18.md", checkpoint_old, checkpoint_new)

replace_once(
    "docs/PHASE3_REALTIME_STATUS_2026-09-18.md",
    "The final main audit before the last strictness cleanup reported 257 JVM tests with zero failures/errors/skips plus 65 Python tests. `audio-bridge` currently has no direct JVM tests because it is a small contract/model module; its behavior is exercised through higher-level app/session tests. Add direct tests there only when executable logic is added.\n",
    "The current pre-API host gate covers 257 JVM tests with zero failures/errors/skips plus 76 Python tests (333 automated cases total), together with lint/build/security checks. `audio-bridge` currently has no direct JVM tests because it is a small contract/model module; its behavior is exercised through higher-level app/session tests. Add direct tests there only when executable logic is added.\n",
)

needle = "Physical S22 evidence already covers live-probe off-call refusal, preflight observability and idempotent/reversible voice-call mute. It does **not** cover an actual OpenAI Realtime session or cellular Realtime audio.\n"
replacement = needle + "\nAt the final pre-key readiness check the S22 was not attached over ADB, so the next run must first reconnect serial `RFCT70L7E8J` by direct USB. The smoke will fail closed rather than substitute wireless ADB or another device.\n"
replace_once("docs/HANDOFF_NEXT_CHAT.md", needle, replacement)

needle2 = "The controlled live Realtime call has not yet been executed; do not phrase it as proven.\n"
replacement2 = needle2 + "\nFinal host-side preparation is complete; the remaining external prerequisites are direct-USB presence of the target S22 and the operator-supplied `OPENAI_API_KEY`.\n"
replace_once("docs/PHASE3_REALTIME_STATUS_2026-09-18.md", needle2, replacement2)
