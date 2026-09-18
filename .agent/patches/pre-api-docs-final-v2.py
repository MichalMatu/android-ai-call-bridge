from pathlib import Path
import re
import subprocess


def read(path: str) -> str:
    return Path(path).read_text()


def write(path: str, text: str) -> None:
    Path(path).write_text(text)


def replace_once(text: str, old: str, new: str, path: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing docs anchor in {path}: {old[:120]!r}")
    return text.replace(old, new, 1)


head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
subject = subprocess.check_output(["git", "log", "-1", "--format=%s"], text=True).strip()

# README
path = "README.md"
text = read(path)
text = replace_once(
    text,
    "The genuine off-call smoke additionally requires a separate broker bearer and protected HTTPS URL.\n",
    "For the preferred developer smoke path, `scripts/realtime_offcall_lab.py` generates the one-shot broker bearer and temporary HTTPS Quick Tunnel itself. The operator supplies only the standard `OPENAI_API_KEY` in the host environment; that key remains broker-only.\n",
    path,
)
text = replace_once(
    text,
    "Before any live Realtime cellular call, run the genuine OpenAI **off-call** S22 smoke. Required host environment:\n\n```text\nOPENAI_API_KEY\nAI_CALL_BRIDGE_BROKER_TOKEN\nAI_CALL_BRIDGE_BROKER_HTTPS_URL\n```\n",
    "Before any live Realtime cellular call, run the genuine OpenAI **off-call** S22 smoke. Preferred developer command:\n\n```bash\npython3 scripts/realtime_offcall_lab.py RFCT70L7E8J\n```\n\nOnly `OPENAI_API_KEY` must be supplied by the operator. The launcher generates the distinct broker bearer, starts the loopback broker, creates a temporary Cloudflare Quick Tunnel, waits through its DNS warm-up until the authenticated broker boundary is publicly reachable, runs the smoke, and tears both processes down. The S22 must be present as the exact direct-USB ADB target.\n",
    path,
)
write(path, text)

# AGENTS
path = "AGENTS.md"
text = read(path)
text = replace_once(
    text,
    "The next physical Realtime gate requires the three host variables listed in `docs/HANDOFF_NEXT_CHAT.md`. Do not invent a bypass if they are absent.\n",
    "The preferred off-call gate requires only `OPENAI_API_KEY` from the operator; `scripts/realtime_offcall_lab.py` generates the temporary broker bearer and HTTPS Quick Tunnel. Do not invent a bypass when the standard key or exact direct-USB S22 target is absent.\n",
    path,
)
write(path, text)

# Handoff
path = "docs/HANDOFF_NEXT_CHAT.md"
text = read(path)
pattern = re.compile(
    r"Latest behavior cleanup checkpoint before this documentation refresh:\n\n```text\n[0-9a-f]{40}\n[^\n]+\n```"
)
replacement = (
    "Latest behavior checkpoint before this documentation refresh:\n\n"
    f"```text\n{head}\n{subject}\n```"
)
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise RuntimeError(f"missing behavior checkpoint block in {path}")
text = replace_once(
    text,
    "Host environment must provide:\n\n```text\nOPENAI_API_KEY\nAI_CALL_BRIDGE_BROKER_TOKEN\nAI_CALL_BRIDGE_BROKER_HTTPS_URL\n```\n\nDo not put the standard OpenAI key in APK, source, Intent, app-private config, ADB argv or phone.\n",
    "The only operator-supplied secret prerequisite is `OPENAI_API_KEY` on the host. Do not put it in APK, source, Intent, app-private config, ADB argv or phone.\n\nPreferred gate:\n\n```bash\npython3 scripts/realtime_offcall_lab.py RFCT70L7E8J\n```\n\nThe launcher creates a random one-shot broker bearer, starts the loopback broker, exposes it through a temporary Cloudflare Quick Tunnel, allows for the provider's short DNS warm-up, waits for the public endpoint to reject an unauthenticated request with the broker's `401` boundary, then runs the existing off-call smoke. The standard OpenAI key is present only in the broker child environment; unrelated host secrets are not forwarded. The bearer and tunnel URL exist only for that run and the processes are torn down afterwards.\n\nThe exact S22+ must also be connected over direct USB ADB; do not substitute wireless ADB.\n",
    path,
)
text += "\n## Latest pre-API infrastructure proof\n\nThe real Quick Tunnel / loopback-broker boundary was exercised without calling OpenAI upstream in `.agent/results/pre-api-public-broker-boundary-proof-retry-20260918-3350.json`. The unauthenticated public broker request reached the local broker and was rejected at `401`; the dummy long-lived key was never used upstream. Quick Tunnels remain development-only infrastructure, not the production credential service.\n"
write(path, text)

# Phase 3 status
path = "docs/PHASE3_REALTIME_STATUS_2026-09-18.md"
text = read(path)
pattern = re.compile(
    r"Latest behavior cleanup checkpoint before this documentation refresh:\n\n```text\n[0-9a-f]{40}\n[^\n]+\n```"
)
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise RuntimeError(f"missing behavior checkpoint block in {path}")
text = replace_once(
    text,
    "The real OpenAI network/session smoke has **not** run. Latest prerequisite recheck showed all three host prerequisites absent:\n\n```text\nOPENAI_API_KEY\nAI_CALL_BRIDGE_BROKER_TOKEN\nAI_CALL_BRIDGE_BROKER_HTTPS_URL\n```\n\nThe standard OpenAI key stays only in the host broker environment. The broker bearer is separate. Android receives only broker URL/bearer through the one-shot stdin staging path and then a short-lived Realtime secret.\n",
    "The real OpenAI network/session smoke has **not** run. The only remaining operator-supplied secret prerequisite is `OPENAI_API_KEY` on the host.\n\n`scripts/realtime_offcall_lab.py` now generates a strong one-shot broker bearer, launches the loopback credential broker, creates/retries a temporary Cloudflare Quick Tunnel, waits through the provider's short DNS warm-up until the public endpoint reaches the broker's unauthenticated `401` boundary, then invokes the existing S22 off-call smoke. Child environments are allowlisted so unrelated host secrets are not forwarded.\n\nThe standard OpenAI key stays only in the broker child environment. Android receives only the generated broker URL/bearer through the one-shot stdin staging path and then a short-lived Realtime secret. Exact direct-USB identification of `SM_S906B` happens before device secret staging.\n\nReal no-upstream infrastructure proof: `.agent/results/pre-api-public-broker-boundary-proof-retry-20260918-3350.json`.\n",
    path,
)
write(path, text)

# Security/privacy
path = "docs/SECURITY_PRIVACY.md"
text = read(path)
text = replace_once(
    text,
    "The genuine OpenAI smoke requires a protected/authenticated HTTPS path to that loopback broker. Do not weaken Android network security to plaintext HTTP for convenience.\n",
    "The genuine OpenAI smoke requires a protected/authenticated HTTPS path to that loopback broker. `scripts/realtime_offcall_lab.py` provides the development path: it generates a distinct one-shot bearer, gives the long-lived OpenAI key only to the broker child, gives neither key nor bearer to `cloudflared`, gives only the broker bearer/URL to the smoke child, and tears down the temporary Quick Tunnel afterwards. Child environments use a small allowlist so unrelated host secrets are not inherited. The launcher waits through Quick Tunnel DNS warm-up before its first public broker lookup to avoid a transient NXDOMAIN race. Quick Tunnels are development/test infrastructure with no uptime guarantee; production must use a stable protected backend/tunnel. Do not weaken Android network security to plaintext HTTP for convenience.\n",
    path,
)
text = replace_once(
    text,
    "Before the live Realtime smoke can stage broker configuration it requires:\n",
    "Before either Realtime smoke stages broker configuration, the host verifies the exact S22+ over direct USB ADB. Before the live Realtime smoke can stage broker configuration it additionally requires:\n",
    path,
)
write(path, text)

# Roadmap
path = "docs/ROADMAP.md"
text = read(path)
text = replace_once(
    text,
    "Status: `HOST_GREEN / WAITING FOR EXTERNAL CREDENTIAL PREREQUISITES`",
    "Status: `HOST_GREEN / READY FOR OPENAI_API_KEY + DIRECT-USB S22 GATE`",
    path,
)
text = replace_once(
    text,
    "Status: `BLOCKED ONLY BY HOST ENVIRONMENT`\n\nRequired:\n\n```text\nOPENAI_API_KEY\nAI_CALL_BRIDGE_BROKER_TOKEN\nAI_CALL_BRIDGE_BROKER_HTTPS_URL\n```\n",
    "Status: `READY FOR OPERATOR KEY / DIRECT USB`\n\nPreferred command:\n\n```bash\npython3 scripts/realtime_offcall_lab.py RFCT70L7E8J\n```\n\nThe operator supplies only `OPENAI_API_KEY`. The launcher generates the independent bearer and temporary HTTPS Quick Tunnel, waits for DNS/public `401` readiness, and cleans both processes up. The exact S22+ direct-USB ADB target is mandatory.\n",
    path,
)
write(path, text)
