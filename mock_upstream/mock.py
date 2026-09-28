"""A minimal OpenAI-compatible chat completions server that answers instantly.

The benchmark routes send to this instead of a real model, so the latency measured through the gateway
is the gateway plus the guardrail, not the model. It echoes the last user message.

  python mock_upstream/mock.py            # listens on 0.0.0.0:8000 (or $PORT)
"""
import json, os, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._json(200, {"status": "ok"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json(400, {"error": {"message": "invalid JSON"}})
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._json(404, {"error": {"message": "not found"}})
        last = next((m.get("content") for m in reversed(req.get("messages") or []) if m.get("role") == "user"), "")
        text = last if isinstance(last, str) else json.dumps(last)
        self._json(200, {
            "id": "chatcmpl-mock", "object": "chat.completion", "created": int(time.time()),
            "model": req.get("model", "mock"),
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "Echo: " + text[:200]}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8000"))), Handler).serve_forever()
