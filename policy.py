"""grok-build-bridge — minimal REST bridge with hard government-domain policy.

Run with: python -m grok_build_bridge.bridge
"""

from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import sys
import os

# Add parent directory to path so we can import policy.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from policy import is_government_domain, blocked_error


class BridgeHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, data: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/chat":
            self._send_json(404, {"error": "not_found"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid_json"})
            return

        prompt = data.get("prompt") or data.get("message") or ""

        # === HARD POLICY CHECK ===
        if is_government_domain(prompt):
            self._send_json(403, blocked_error())
            return
        # === END POLICY CHECK ===

        # TODO: Replace this placeholder with your real Grok call
        # (Safari injection, Grok API, browser automation, etc.)
        result = {
            "response": f"[BRIDGE PLACEHOLDER] You asked: {prompt[:100]}...",
            "note": "Replace the placeholder above with your actual Grok logic.",
            "policy": "government domains are blocked on this instance"
        }

        self._send_json(200, result)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {
                "status": "ok",
                "policy": "government domains blocked",
                "version": "0.1.0"
            })
        else:
            self._send_json(404, {"error": "not_found"})

    def log_message(self, format, *args):
        # Quiet logs — only show important events
        if "chat" in args[0] or "403" in str(args):
            super().log_message(format, *args)


def run(port: int = 19998) -> None:
    server = HTTPServer(("", port), BridgeHandler)
    print(f"🚀 grok-build-bridge running on http://localhost:{port}")
    print("   POST /chat   → send your prompt")
    print("   GET  /health → check status + policy")
    print("   Policy: .gov / .mil domains are HARD BLOCKED")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Bridge stopped.")


if __name__ == "__main__":
    run()
