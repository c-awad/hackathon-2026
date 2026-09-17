"""Serve the dashboard on :3000, and proxy /api/* to the MantisGrid API.

The API has no CORS headers, so a page on :3000 cannot call :8000 directly. This
proxy is the whole reason the price control on the dashboard is a real API call
(GET /v1/efficiency/summary?usd_per_gpu_hour=...) rather than arithmetic in the
browser: when the CFO models a different rate, the response comes back tagged
2026-Q3+custom by the API itself.
"""
import http.server
import json
import os
import socketserver
import urllib.error
import urllib.parse
import urllib.request

PORT = int(os.environ.get("PORT", "3000"))
API = os.environ.get("MGAI_URL", "http://localhost:8000").rstrip("/")
ROOT = os.path.dirname(os.path.abspath(__file__))
ALLOWED = ("/v1/", "/health")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def end_headers(self):
        # The page is rebuilt on every start; a cached copy would show stale numbers.
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):          # one line per request, no noise
        if self.path.startswith("/api/"):
            print(f"proxy {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")

    # --- proxy -------------------------------------------------------------
    def _target(self):
        path = self.path[len("/api"):]
        if not path.startswith(ALLOWED):
            return None
        return f"{API}{path}"

    def _proxy(self, body=None):
        url = self._target()
        if not url:
            self.send_error(404, "only /api/v1/* is proxied")
            return
        req = urllib.request.Request(
            url, data=body, method=self.command,
            headers={"Content-Type": "application/json"} if body else {})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                payload, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            payload, status = e.read(), e.code
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            payload = json.dumps({"error": f"API unreachable: {e}"}).encode()
            status = 502
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._proxy()
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            n = int(self.headers.get("Content-Length") or 0)
            return self._proxy(self.rfile.read(n) if n else b"{}")
        self.send_error(405)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    print(f"dashboard on http://0.0.0.0:{PORT}  (proxying /api/* -> {API})")
    with Server(("0.0.0.0", PORT), Handler) as httpd:
        httpd.serve_forever()
