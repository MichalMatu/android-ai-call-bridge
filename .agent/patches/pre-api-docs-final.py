from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    if old not in text:
        raise RuntimeError(f"missing docs patch anchor in {path}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1))


replace_once(
    "README.md",
    "The genuine off-call smoke additionally requires a separate broker bearer and protected HTTPS URL.\n",
    "For the preferred developer smoke path, `scripts/realtime_offcall_lab.py` generates the one-shot broker bearer and temporary HTTPS Quick Tunnel itself. The operator supplies only the standard `OPENAI_API_KEY` in the host environment; that key remains broker-only.\n",
)
replace_once(
    "README.md",
    "Before any live Realtime cellular call, run the genuine OpenAI **off-call** S22 smoke. Required host environment:\n\n```text\nOPENAI_API_KEY\nAI_CALL_BRIDGE_BROKER_TOKEN\nAI_CALL_BRIDGE_BROKER_HTTPS_URL\n```\n",
    "Before any live Realtime cellular call, run the genuine OpenAI **off-call** S22 smoke. Preferred developer command:\n\n```bash\npython3 scripts/realtime_offcall_lab.py RFCT70L7E8J\n```\n\nOnly `OPENAI_API_KEY` must be supplied by the operator. The launcher generates the distinct broker bearer, starts the loopback broker, creates a temporary Cloudflare Quick Tunnel, waits for its authenticated boundary to become reachable, runs the smoke, and tears both processes down.\n",
)

replace_once(
    "AGENTS.md",
    "The next physical Realtime gate requires the three host variables listed in `docs/HANDOFF_NEXT_CHAT.md`. Do not invent a bypass if they are absent.\n",
    "The preferred off-call gate requires only `OPENAI_API_KEY` from the operator; `scripts/realtime_offcall_lab.py` generates the temporary broker bearer and HTTPS Quick Tunnel. Do not invent a bypass when the standard key is absent.\n",
)

replace_once(
    "docs/HANDOFF_NEXT_CHAT.md",
    "Host environment must provide:\n\n```text\nOPENAI_API_KEY\nAI_CALL_BRIDGE_BROKER_TOKEN\nAI_CALL_BRIDGE_BROKER_HTTPS_URL\n```\n\nDo not put the standard OpenAI key in APK, source, Intent, app-private config, ADB argv or phone.\n",
    "The only operator-supplied prerequisite is `OPENAI_API_KEY` on the host. Do not put it in APK, source, Intent, app-private config, ADB argv or phone.\n\nPreferred gate:\n\n```bash\npython3 scripts/realtime_offcall_lab.py RFCT70L7E8J\n```\n\nThe launcher creates a random one-shot broker bearer, starts the loopback broker, exposes it through a temporary Cloudflare Quick Tunnel, waits for the public endpoint to be reachable and protected, then runs the existing off-call smoke. The bearer and tunnel URL are generated at runtime and both broker/tunnel processes are torn down afterwards.\n",
)

replace_once(
    "docs/PHASE3_REALTIME_STATUS_2026-09-18.md",
    "The real OpenAI network/session smoke has **not** run. Latest prerequisite recheck showed all three host prerequisites absent:\n\n```text\nOPENAI_API_KEY\nAI_CALL_BRIDGE_BROKER_TOKEN\nAI_CALL_BRIDGE_BROKER_HTTPS_URL\n```\n\nThe standard OpenAI key stays only in the host broker environment. The broker bearer is separate. Android receives only broker URL/bearer through the one-shot stdin staging path and then a short-lived Realtime secret.\n",
    "The real OpenAI network/session smoke has **not** run. The only remaining operator-supplied prerequisite is `OPENAI_API_KEY` on the host.\n\n`scripts/realtime_offcall_lab.py` now generates a strong one-shot broker bearer, launches the loopback credential broker, creates/retries a temporary Cloudflare Quick Tunnel, waits until its unauthenticated request is rejected with the broker's 401 boundary, then invokes the existing S22 off-call smoke. Child environments are allowlisted so unrelated host secrets are not forwarded.\n\nThe standard OpenAI key stays only in the broker child environment. Android receives only the generated broker URL/bearer through the one-shot stdin staging path and then a short-lived Realtime secret.\n",
)

replace_once(
    "docs/SECURITY_PRIVACY.md",
    "The genuine OpenAI smoke requires a protected/authenticated HTTPS path to that loopback broker. Do not weaken Android network security to plaintext HTTP for convenience.\n",
    "The genuine OpenAI smoke requires a protected/authenticated HTTPS path to that loopback broker. `scripts/realtime_offcall_lab.py` provides the development path: it generates a distinct one-shot bearer, gives the long-lived OpenAI key only to the broker child, gives neither key nor bearer to `cloudflared`, gives only the broker bearer/URL to the smoke child, and tears down the temporary Quick Tunnel afterwards. Child environments use a small allowlist so unrelated host secrets are not inherited. Do not weaken Android network security to plaintext HTTP for convenience.\n",
)

replace_once(
    "docs/SECURITY_PRIVACY.md",
    "Before the live Realtime smoke can stage broker configuration it requires:\n",
    "Before either Realtime smoke stages broker configuration, the host verifies the exact S22+ over direct USB ADB. Before the live Realtime smoke can stage broker configuration it additionally requires:\n",
)
