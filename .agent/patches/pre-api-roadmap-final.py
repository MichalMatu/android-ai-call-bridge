from pathlib import Path

path = Path("docs/ROADMAP.md")
text = path.read_text()
text = text.replace(
    "Status: `HOST_GREEN / WAITING FOR EXTERNAL CREDENTIAL PREREQUISITES`",
    "Status: `HOST_GREEN / WAITING FOR API KEY + DIRECT USB TARGET`",
    1,
)
old = """Status: `BLOCKED ONLY BY HOST ENVIRONMENT`

Required:

```text
OPENAI_API_KEY
AI_CALL_BRIDGE_BROKER_TOKEN
AI_CALL_BRIDGE_BROKER_HTTPS_URL
```
"""
new = """Status: `BLOCKED ONLY BY OPERATOR API KEY + DIRECT USB TARGET`

Preferred developer entrypoint:

```bash
python3 scripts/realtime_offcall_lab.py RFCT70L7E8J
```

The operator supplies only host `OPENAI_API_KEY`. The launcher generates the separate one-shot broker bearer and temporary HTTPS Quick Tunnel. The smoke refuses before secret staging unless serial `RFCT70L7E8J` is the exact S22+ over direct USB ADB.
"""
if old not in text:
    raise RuntimeError("roadmap Gate 3A anchor missing")
path.write_text(text.replace(old, new, 1))
