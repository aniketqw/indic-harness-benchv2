"""Allow-list HTTP proxy: the ONLY route from the OpenClaw container to the host's Ollama.

Allowed: POST /v1/chat/completions (model must be in ALLOWED) and GET /v1/models. Everything else
(e.g. /api/pull, /api/delete, other models) is refused with 403. Runs in its own container that sits on
both the default bridge (to reach host.docker.internal) and the internal agent network.
"""
import http.client
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = ("host.docker.internal", 11434)
ALLOWED = {"gpt-oss:20b-cloud", "gpt-oss:20b", "nemotron-3-super:cloud", "nemotron-3-super",
           "glm-5.3-flash:cloud", "glm-5.3-flash"}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _deny(self, code=403, msg="blocked by rlharness proxy"):
        body = json.dumps({"error": msg}).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def _relay(self, method, body=None):
        conn = http.client.HTTPConnection(*UPSTREAM, timeout=900)
        conn.request(method, self.path, body, {"Content-Type": "application/json"})
        r = conn.getresponse()
        self.send_response(r.status)
        self.send_header("Content-Type", r.getheader("Content-Type", "application/json"))
        self.send_header("Transfer-Encoding", "chunked"); self.end_headers()
        while True:
            chunk = r.read1(65536) if hasattr(r, "read1") else r.read(4096)
            if not chunk:
                break
            self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n"); self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n"); conn.close()

    def do_GET(self):
        if self.path == "/health":
            self._deny(200, "ok")
        elif self.path == "/v1/models":
            self._relay("GET")
        else:
            self._deny()

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return self._deny()
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            model = json.loads(body).get("model", "")
        except Exception:
            return self._deny(400, "bad json")
        if model not in ALLOWED:
            return self._deny(403, "model not allowed")
        self._relay("POST", body)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 11434), H).serve_forever()
