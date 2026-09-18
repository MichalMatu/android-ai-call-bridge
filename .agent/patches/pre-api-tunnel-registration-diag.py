#!/usr/bin/env python3
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path.cwd()
BROKER = ROOT / "scripts" / "realtime_credential_broker.py"
URL_RE = re.compile(r"https://[a-z0-9-]+[.]trycloudflare[.]com", re.I)

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

token = secrets.token_urlsafe(48)
env = dict(os.environ)
env["OPENAI_API_KEY"] = "dummy-never-used"
env["AI_CALL_BRIDGE_BROKER_TOKEN"] = token

tmp = Path(tempfile.mkdtemp(prefix="aicall-tunnel-diag-"))
broker_log = tmp / "broker.err"
tunnel_log = tmp / "tunnel.err"

broker = None
tunnel = None
try:
    with broker_log.open("w") as berr:
        broker = subprocess.Popen(
            [sys.executable, str(BROKER), "--port", str(port)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=berr,
            text=True,
        )
    local_ready = False
    for _ in range(60):
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "1", f"http://127.0.0.1:{port}/"],
            capture_output=True,
            text=True,
        )
        if result.stdout.strip() == "405":
            local_ready = True
            break
        time.sleep(0.1)
    print(f"local_ready={str(local_ready).lower()}")
    if not local_ready:
        raise SystemExit(2)

    with tunnel_log.open("w") as terr:
        tunnel_env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL"}}
        tunnel = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
            env=tunnel_env,
            stdout=subprocess.DEVNULL,
            stderr=terr,
            text=True,
        )

    url = None
    published_at = None
    registered_at = None
    start = time.monotonic()
    for _ in range(240):
        text = tunnel_log.read_text(errors="replace") if tunnel_log.exists() else ""
        if url is None:
            match = URL_RE.search(text)
            if match:
                url = match.group(0).lower()
                published_at = time.monotonic() - start
        if registered_at is None and "Registered tunnel connection" in text:
            registered_at = time.monotonic() - start
        if url and registered_at is not None:
            break
        if tunnel.poll() is not None:
            break
        time.sleep(0.25)

    print(f"url_published={str(url is not None).lower()}")
    if published_at is not None:
        print(f"url_published_seconds={published_at:.2f}")
    print(f"edge_registered={str(registered_at is not None).lower()}")
    if registered_at is not None:
        print(f"edge_registered_seconds={registered_at:.2f}")
    print(f"cloudflared_running={str(tunnel.poll() is None).lower()}")

    if url:
        host = url.split("//", 1)[1]
        try:
            addrs = sorted({entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
            print(f"dns_resolved=true")
            print(f"dns_address_count={len(addrs)}")
        except OSError as error:
            print("dns_resolved=false")
            print(f"dns_error={type(error).__name__}")

        curl = subprocess.run(
            ["curl", "-sS", "-o", str(tmp / "body"), "-w", "%{http_code}", "--connect-timeout", "5", "--max-time", "10", url + "/"],
            capture_output=True,
            text=True,
        )
        print(f"public_get_code={curl.stdout.strip() or 'none'}")
        print(f"public_get_rc={curl.returncode}")
        if curl.stderr.strip():
            print("public_get_error=" + curl.stderr.strip().splitlines()[-1][:180])

    text = tunnel_log.read_text(errors="replace") if tunnel_log.exists() else ""
    interesting = [
        line for line in text.splitlines()
        if any(term in line for term in ("Registered tunnel connection", "ERR", "error=", "protocol=", "connection"))
    ]
    for line in interesting[-12:]:
        sanitized = re.sub(r"https://[a-z0-9-]+[.]trycloudflare[.]com", "https://HOST.trycloudflare.com", line, flags=re.I)
        print("cloudflared=" + sanitized[:400])
finally:
    for proc in (tunnel, broker):
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
    for child in tmp.iterdir() if tmp.exists() else []:
        child.unlink(missing_ok=True)
    tmp.rmdir() if tmp.exists() else None
