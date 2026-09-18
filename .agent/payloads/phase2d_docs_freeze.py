from pathlib import Path
import re


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"missing literal in {path}: {old!r}")
    p.write_text(text.replace(old, new, 1))


def replace_section(path: str, start_heading: str, next_heading: str, body: str) -> None:
    p = Path(path)
    text = p.read_text()
    pattern = re.escape(start_heading) + r"\n.*?(?=" + re.escape(next_heading) + r")"
    updated, count = re.subn(pattern, body.rstrip() + "\n\n", text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"section not found in {path}: {start_heading!r} -> {next_heading!r}")
    p.write_text(updated)


Path("docs/PHASE2D_FREEZE_2026-09-18.md").write_text("""# Phase 2 Milestone D freeze — 2026-09-18

## Verdict

Milestone D is `DONE / PROVEN_S22` on the target Samsung Galaxy S22+ `SM-S906B` running Android 16 / API 36 / One UI 8 with Orange PL, Google Phone and Shizuku shell UID 2000.

This freeze preserves the proven Samsung media path. It does not refactor the low-level RX/TX primitives.

## Physical fail-safe evidence

GREEN on the target device:

- normal app death while media is active:
  - task `phase2-milestone-d-app-death-physical-v5-20260917-2301`;
  - app disappeared about 180 ms after force-stop;
  - helper disappeared about 340 ms;
  - media stopped about 530 ms;
  - cellular call and Shizuku server remained alive;
- transferred endpoint close:
  - task `phase2-milestone-d-endpoint-close-physical-v2-20260917-2330`;
  - RX PFD close -> whole generation inactive about 39 ms;
  - TX PFD close -> whole generation inactive about 13 ms;
- repeated lifecycle: 20/20 start/abort cycles with stable UserService PID and clean final prepared/active/heartbeat state;
- natural cellular call end:
  - the first gate exposed a real product defect: heartbeats could keep media active after the call ended;
  - fixed by helper-side `CallModeWatchdog`, watching loss of `AudioManager.MODE_IN_CALL`;
  - physical validation task `phase2-natural-call-end-watchdog-physical-20260918-0108` is GREEN;
- bidirectional endurance:
  - task `phase2-milestone-d-10min-segmented-live-soak-v2-20260918-0125`;
  - 10 independent 60-second live sessions;
  - 600 seconds total real bidirectional RX+TX;
  - all heartbeats/session-state checks GREEN and every segment cleaned up;
- resource trend:
  - one separate short live run preserved 24 external samples over 50.1 seconds while the call remained active;
  - app PID stable: RSS 123128 -> 124196 KiB, FD 41 -> 41, threads 27 -> 25;
  - helper PID stable: RSS 152932 -> 153948 KiB, FD 41 -> 41, threads 19 -> 19;
  - no resource-growth signal was observed.

The resource run complements the 600-second media soak. It is not a claim that RSS/FD/thread telemetry was preserved for the full 600 seconds.

## Final host regression

At the pre-freeze product HEAD:

- Python: 48/48 tests PASS;
- Gradle unit tests for `privileged-helper`, `app`, `audio-bridge` and `realtime-client`: GREEN;
- `:app:assembleDebug`: GREEN;
- Gradle result: `BUILD SUCCESSFUL`;
- `git diff --check`: GREEN;
- clean product tree: GREEN.

Security-shape checks:

- `.agent` absent from the product branch;
- `DiagnosticProbeActivity` protected by `android.permission.DUMP`;
- exported `MainActivity` does not expose privileged live-probe automation extras;
- no long-lived OpenAI API key pattern found in product modules;
- realtime contract uses a short-lived credential;
- no per-frame Binder PCM transport;
- local `abortNow()` / TAKE OVER and helper fail-safe remain independent of model/network availability;
- call recording remains off by default.

## Frozen invariants

Do not casually change:

- direct-shell RX prepare-before-explicit-context ordering;
- Shizuku attributed-context ordering;
- RX system attribution;
- TX `com.android.shell` attribution;
- `USAGE_CALL_ASSISTANT / AUDIO_STREAM_CALL_ASSISTANT`;
- `AUDIO_DEVICE_OUT_TELEPHONY_TX`;
- internal mono PCM16LE;
- stereo duplication only at the Samsung TX boundary;
- PFD AutoClose ownership;
- one shared RX+TX fail-safe generation;
- endpoint loss -> whole-generation cleanup;
- no per-frame Binder transport;
- local immediate TAKE OVER;
- `CallModeWatchdog` unless concrete regression evidence requires a change.

## Next phase

Do not start another Phase 2 robustness expansion. The next product work is Telephone Agent v1, beginning with a production app-side `CallMediaSessionCoordinator`, then the user-level call task/workflow model, and only then OpenAI Realtime transport integration.
""")

replace_once(
    "docs/ROADMAP.md",
    "Status: `MILESTONES B+C PROVEN / MILESTONE D ACTIVE`",
    "Status: `MILESTONES B+C+D PROVEN / MILESTONE D FROZEN`",
)
replace_section(
    "docs/ROADMAP.md",
    "### Milestone D — robustness and endurance",
    "## Phase 3 — Realtime AI integration",
    """### Milestone D — robustness and endurance

Status: `DONE / PROVEN_S22 / FROZEN`

Milestone D is physically closed on the target S22+.

Proven:
- normal-app death while media is active -> local helper/media cleanup while the cellular call and Shizuku survive;
- transferred RX or TX PFD close -> whole-generation cleanup;
- 20/20 repeated start/abort cycles with clean final state;
- natural cellular call end -> full cleanup after the `CallModeWatchdog` fix;
- 600 seconds total real bidirectional media as 10 x 60-second live sessions;
- separate external resource trend during 50.1 seconds of active media: app FD 41 -> 41, helper FD 41 -> 41, no thread growth, roughly 1 MiB RSS increase per process;
- final 48 Python tests PASS;
- full Gradle unit tests + `:app:assembleDebug` GREEN;
- final security-shape and clean-tree checks GREEN.

The full 600-second soak did not preserve its external RSS/FD/thread summary because the background telemetry child was cleaned up by Local Agent. The separate foreground resource run closes the resource-trend evidence gap without pretending those metrics cover all 600 seconds.

Freeze evidence: `docs/PHASE2D_FREEZE_2026-09-18.md`.""",
)
replace_once("docs/ROADMAP.md", "Status: `NOT STARTED BY DESIGN`", "Status: `READY — MILESTONE D FROZEN`")

replace_once(
    "docs/ARCHITECTURE.md",
    "normal-app-death cleanup timing                      OPEN MILESTONE D GATE",
    "normal-app-death cleanup                            PROVEN_S22",
)
replace_once(
    "docs/ARCHITECTURE.md",
    "Normal-app death is covered architecturally by heartbeat loss, but its end-to-end cleanup latency still requires a clean physical Milestone D measurement.",
    "Normal-app death is physically proven: app/helper/media cleanup occurs locally while the cellular call and Shizuku server remain alive.",
)
replace_section(
    "docs/ARCHITECTURE.md",
    "## Current Milestone D gates",
    "## Hard architectural rules",
    """## Milestone D freeze state

Milestone D is `DONE / PROVEN_S22`.

Physical evidence now covers normal-app death, helper/UserService death, transferred RX and TX endpoint close, natural cellular call end, 20 repeated start/abort cycles, 600 seconds total real bidirectional media, and separate external RSS/FD/thread trend evidence during a 50.1-second active session.

Natural call-end testing found and fixed one real lifecycle defect. `CallModeWatchdog` observes the same public `AudioManager.MODE_IN_CALL` condition required by RX startup. When call mode leaves `MODE_IN_CALL`, the downlink terminates and the existing shared controller aborts the sibling TX. This keeps the correction inside the helper fail-safe boundary and does not change the proven Samsung PCM primitives.

Resource evidence intentionally remains external to Binder. The preserved short live run showed stable PIDs, no FD growth, no thread growth, and only about 1 MiB RSS increase in both the app and helper.

Detailed freeze evidence: `docs/PHASE2D_FREEZE_2026-09-18.md`.

The next architecture work is a production app-side `CallMediaSessionCoordinator`; diagnostic probes remain regression tools and must not become the production lifecycle owner.""",
)

security = Path("docs/SECURITY_PRIVACY.md")
security_text = security.read_text()
if "## Milestone D verified fail-safe evidence" not in security_text:
    security.write_text(
        security_text.rstrip()
        + """

## Milestone D verified fail-safe evidence

As of 2026-09-18 on the target S22+, destructive physical tests verify that active AI media fails closed for normal-app death, helper/UserService death, transferred RX/TX endpoint loss, explicit TAKE OVER/abort, and natural cellular call end. The natural-call-end gate exposed a real heartbeat-lifetime defect and the helper-side `CallModeWatchdog` fix was physically revalidated.

The final product-branch security-shape audit also verified:
- privileged diagnostic automation remains behind `android.permission.DUMP`;
- the exported launcher does not accept privileged live-probe automation extras;
- no long-lived OpenAI key pattern is embedded in product modules;
- PCM remains PFD-based rather than per-frame Binder;
- recording is still disabled by default.

See `docs/PHASE2D_FREEZE_2026-09-18.md`.
"""
    )

replace_once("README.md", "## Current status — 2026-09-17", "## Current status — 2026-09-18")
replace_section(
    "README.md",
    "### Current gate — Milestone D robustness",
    "## Architecture",
    """### Phase 2D — robustness and endurance

`DONE / PROVEN_S22 / FROZEN`

Physically GREEN on the target S22+: normal-app death, helper/UserService death, transferred RX/TX PFD close with whole-generation cleanup, 20/20 start/abort cycles, natural cellular call-end cleanup after the helper-side `CallModeWatchdog` fix, and 600 seconds total real bidirectional media as 10 x 60-second live sessions.

A separate preserved 50.1-second active resource run showed stable app/helper PIDs, FD counts of `41 -> 41` for both processes, no thread growth, and roughly 1 MiB RSS increase in each process. This complements the 600-second media soak; it is not presented as 600 seconds of resource telemetry.

Final regression: 48 Python tests PASS, full Gradle unit tests + `:app:assembleDebug` GREEN, security-shape audit GREEN, clean tree.

Detailed evidence: `docs/PHASE2D_FREEZE_2026-09-18.md`.

The next product work is Telephone Agent v1: a production `CallMediaSessionCoordinator`, task/workflow orchestration, and then Realtime AI as the conversational engine.""",
)

Path("docs/HANDOFF_NEXT_CHAT.md").write_text("""# Handoff — Milestone D frozen / Telephone Agent v1 next

Date: 2026-09-18

Repository: `MichalMatu/android-ai-call-bridge`

Work branch: `work/phase1-live-call-probes`

Local Agent binding:

```text
agent_binding: c25f88c0-4682-414c-8062-c47fa4034cb0
repository_id: android-ai-call-bridge
control_branch: agent-control
```

## Start rule

Milestone D is closed. Do not rerun Phase 2 physical gates or expand the diagnostic harness unless a concrete regression requires it.

Read `AGENTS.md`, this handoff, `docs/PHASE2D_FREEZE_2026-09-18.md`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY_PRIVACY.md`, and `docs/PHASE2_DEEP_AUDIT_2026-09-16.md`.

## Frozen earlier checkpoints

```text
Phase 2B:
milestone/phase2b-proven-s22-20260916
c10f8dde29f245f8f98fb008a3572c21fe73fe35

Phase 2C:
milestone/phase2c-shizuku-live-proven-20260916
9c136fc05c5b33f383d72b0b7080ad5b9a754bb4
```

## Milestone D final evidence

Physical GREEN on the target S22+: normal app death during active media, helper/UserService death, transferred RX and TX PFD close, 20/20 start/abort cycles, natural call end after the `CallModeWatchdog` fix, and 600 seconds total live bidirectional media as 10 x 60 seconds.

Resource trend was closed with one additional short live run, not another ten calls:
- 24 external samples / 50.1 seconds, call active throughout;
- app: RSS 123128 -> 124196 KiB, FD 41 -> 41, threads 27 -> 25;
- helper: RSS 152932 -> 153948 KiB, FD 41 -> 41, threads 19 -> 19;
- stable app/helper PIDs;
- cleanup left call idle, helper absent and Bluetooth restored.

Final regression:
- 48/48 Python tests PASS;
- full Gradle unit tests + `:app:assembleDebug` GREEN;
- security-shape GREEN;
- `git diff --check` GREEN;
- clean product tree.

Do not claim the 50.1-second resource trend is 600 seconds of resource telemetry. The 600-second proof is media-plane endurance.

## Preserve these invariants

Preserve direct-shell RX ordering, Shizuku attribution ordering, RX system attribution, TX `com.android.shell` attribution, CALL_ASSISTANT / TELEPHONY_TX, internal mono PCM16LE, stereo duplication only at the Samsung TX boundary, PFD AutoClose ownership, one shared RX+TX fail-safe generation, endpoint loss -> whole-generation cleanup, no per-frame Binder, local TAKE OVER, helper heartbeat, and `CallModeWatchdog` unless concrete regression evidence requires change.

## Next product work — Telephone Agent v1

Do not make `MainActivity` or diagnostic probes the production lifecycle owner.

First introduce production app-side call-media orchestration:
- `CallMediaSessionCoordinator`;
- `IDLE / BINDING / PREPARING / ACTIVE / STOPPING / FAILED`;
- generation/session id and failure reason;
- direct Binder death handling;
- structured telemetry;
- owned heartbeat and PFD lifetime;
- local immediate TAKE OVER.

Then add the user-level task/workflow model with target/action/service, date/time/price/insurance/NFZ/private constraints, authorized user facts, business resolution, `RESEARCHING -> READY_TO_DIAL -> DIALING -> ACTIVE_NEGOTIATION -> NEEDS_USER_DECISION? -> COMPLETED/FAILED`, and structured outcome.

Realtime AI is a conversation engine inside that orchestrator. Before implementing it, verify current official OpenAI Realtime documentation. Never put a long-lived OpenAI API key in the APK; use short-lived/server-mediated credentials. No call recording by default.

Safe test number `510100100` remains authorized only if a future physical regression genuinely requires it. Keep the phone silent, Bluetooth off during the call, mute before dial and after ACTIVE, speakerphone off, and restore Bluetooth afterward.
""")
