from pathlib import Path

path = Path("scripts/test_realtime_offcall_lab.py")
text = path.read_text()
anchor = '''        self.assertEqual(2, len(calls))
        self.assertEqual(endpoint, calls[0][0])

    def test_quick_tunnel_retries_fresh_process_after_transient_failure(self):
'''
insert = '''        self.assertEqual(2, len(calls))
        self.assertEqual(endpoint, calls[0][0])

    def test_public_readiness_waits_for_dns_warmup_before_first_lookup(self):
        from realtime_offcall_lab import PUBLIC_DNS_WARMUP_SECONDS, wait_for_public_broker

        endpoint = "https://quiet-moon.trycloudflare.com/v1/realtime/client-secret"
        events = []

        class Response:
            status = 401

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def opener(request, timeout):
            events.append("open")
            return Response()

        def sleeper(seconds):
            events.append(("sleep", seconds))

        wait_for_public_broker(
            endpoint,
            timeout_seconds=1,
            opener=opener,
            sleeper=sleeper,
        )

        self.assertEqual(
            [("sleep", PUBLIC_DNS_WARMUP_SECONDS), "open"],
            events,
        )
        self.assertGreaterEqual(PUBLIC_DNS_WARMUP_SECONDS, 3.0)

    def test_quick_tunnel_retries_fresh_process_after_transient_failure(self):
'''
if anchor not in text:
    raise SystemExit("RED anchor not found")
path.write_text(text.replace(anchor, insert, 1))
