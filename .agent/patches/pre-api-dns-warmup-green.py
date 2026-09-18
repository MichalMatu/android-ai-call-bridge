from pathlib import Path

path = Path("scripts/realtime_offcall_lab.py")
text = path.read_text()
text = text.replace(
    'PUBLIC_BROKER_READY_TIMEOUT_SECONDS = 30.0\nQUICK_TUNNEL_ATTEMPTS = 3\n',
    'PUBLIC_BROKER_READY_TIMEOUT_SECONDS = 30.0\nPUBLIC_DNS_WARMUP_SECONDS = 4.0\nQUICK_TUNNEL_ATTEMPTS = 3\n',
    1,
)
old = '''def wait_for_public_broker(
    credential_endpoint: str,
    *,
    timeout_seconds: float = PUBLIC_BROKER_READY_TIMEOUT_SECONDS,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> None:
    request = urllib.request.Request(
        credential_endpoint,
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with opener(request, timeout=3) as response:
                if getattr(response, "status", None) == 401:
                    return
        except urllib.error.HTTPError as error:
            if error.code == 401:
                return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.25)
    raise TimeoutError("public credential broker did not become reachable and protected")
'''
new = '''def wait_for_public_broker(
    credential_endpoint: str,
    *,
    timeout_seconds: float = PUBLIC_BROKER_READY_TIMEOUT_SECONDS,
    opener: Callable[..., object] = urllib.request.urlopen,
    sleeper: Optional[Callable[[float], None]] = None,
    dns_warmup_seconds: float = PUBLIC_DNS_WARMUP_SECONDS,
) -> None:
    if dns_warmup_seconds < 0:
        raise ValueError("dns_warmup_seconds must be >= 0")
    sleep = time.sleep if sleeper is None else sleeper
    if dns_warmup_seconds:
        # TryCloudflare may publish the random hostname shortly before public DNS sees it.
        # Avoid poisoning the host resolver with an immediate NXDOMAIN lookup.
        sleep(dns_warmup_seconds)

    request = urllib.request.Request(
        credential_endpoint,
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with opener(request, timeout=3) as response:
                if getattr(response, "status", None) == 401:
                    return
        except urllib.error.HTTPError as error:
            if error.code == 401:
                return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        sleep(0.25)
    raise TimeoutError("public credential broker did not become reachable and protected")
'''
if old not in text:
    raise SystemExit("GREEN function anchor not found")
path.write_text(text.replace(old, new, 1))
