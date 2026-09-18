#!/usr/bin/env python3
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18114

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self.send_error(400)
            return
        messages = payload.get("messages")
        valid = (
            payload.get("model") == "fixture-model"
            and payload.get("stream") is False
            and isinstance(messages, list)
            and len(messages) >= 1
            and isinstance(messages[-1], dict)
            and messages[-1].get("role") == "user"
            and isinstance(messages[-1].get("content"), str)
            and bool(messages[-1]["content"].strip())
        )
        if not valid:
            self.send_error(422)
            return
        body = json.dumps({
            "id": "chatcmpl-local-fixture",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Lokalny backend Mac działa poprawnie."
                },
                "finish_reason": "stop"
            }]
        }, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass

server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
print(f"fixture_ready_port={PORT}", flush=True)
server.serve_forever()
