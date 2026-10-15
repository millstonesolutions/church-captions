#!/usr/bin/env python3
"""Public caption relay: puts the hub's captions on a web server so phones can follow along off the
church network.

The hub (hub/public.py) POSTs each caption line here over HTTPS with a shared key - an outbound
connection, so nothing is opened on the church's router. Viewers load the reader page and get
lines over Server-Sent Events, which every phone browser supports and reconnects on its own.

Standard library only: no venv or pip on the server. Meant to sit behind a TLS proxy (Caddy):

  RELAY_KEY=<secret> python3 relay.py        # listens on 127.0.0.1:8788

  GET  /            reader page            GET /events   live caption stream (SSE)
  GET  /static/*    page assets            GET /healthz  {"viewers", "public", "hub_seen_s"}
  POST /publish     hub -> relay, needs "Authorization: Bearer <RELAY_KEY>"
"""
import hmac
import json
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Installed: relay/static next to this file. Run from a checkout: the hub's own pages.
STATIC = Path(os.environ.get("RELAY_STATIC") or (HERE / "static" if (HERE / "static").is_dir()
                                                 else HERE.parent / "hub" / "static")).resolve()
KEY = os.environ.get("RELAY_KEY", "")
BIND = os.environ.get("RELAY_BIND", "127.0.0.1")
PORT = int(os.environ.get("RELAY_PORT", "8788"))
HUB_TIMEOUT_S = 75          # no publish or heartbeat for this long = hub gone, take captions down
MAX_VIEWERS = 500
TYPES = {"html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8",
         "css": "text/css; charset=utf-8", "ttf": "font/ttf", "png": "image/png", "svg": "image/svg+xml"}


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.viewers: set[queue.Queue] = set()
        self.history: list[str] = []
        self.history_lines = 0      # set by the hub; 0 = no backlog for late joiners
        self.live = False           # the hub has public captions switched on
        self.last_hub = 0.0

    def snapshot(self) -> dict:
        with self.lock:
            return {"type": "snapshot", "running": self.live, "history": list(self.history), "partial": ""}

    def broadcast(self, msg: dict):
        data = json.dumps(msg)
        with self.lock:
            for q in list(self.viewers):
                try:
                    q.put_nowait(data)
                except queue.Full:           # a phone that stopped reading; drop it, it will reconnect
                    self.viewers.discard(q)
                    try:
                        while True:
                            q.get_nowait()
                    except queue.Empty:
                        pass
                    q.put_nowait(None)       # tells its thread to hang up

    def go_dark(self):
        with self.lock:
            self.history.clear()
            was = self.live
            self.live = False
        if was:
            self.broadcast({"type": "clear"})
            self.broadcast({"type": "status", "running": False})

    def publish(self, m: dict):
        kind = m.get("type")
        self.last_hub = time.time()
        if "history_lines" in m:
            self.history_lines = max(0, min(200, int(m["history_lines"])))
        if kind in ("status", "heartbeat"):
            if m.get("running"):
                with self.lock:
                    was, self.live = self.live, True
                if not was or kind == "status":
                    self.broadcast({"type": "status", "running": True})
            else:
                self.go_dark()
            return
        if not self.live:
            return
        text = str(m.get("text", ""))[:2000]
        if kind == "final":
            with self.lock:
                self.history.append(text)
                del self.history[:-self.history_lines or len(self.history)]
            self.broadcast({"type": "final", "text": text})
        elif kind == "partial":
            self.broadcast({"type": "partial", "text": text})
        elif kind == "clear":
            with self.lock:
                self.history.clear()
            self.broadcast({"type": "clear"})


S = State()


def watchdog():
    while True:
        time.sleep(5)
        if S.live and time.time() - S.last_hub > HUB_TIMEOUT_S:
            print("hub went quiet; taking public captions down", flush=True)
            S.go_dark()


class Handler(BaseHTTPRequestHandler):
    server_version = "captions-relay"
    sys_version = ""

    def log_message(self, fmt, *args):
        pass                                   # Caddy's access log already has every request

    def _send(self, code: int, body: bytes, ctype="application/json", cache="no-cache"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj).encode())

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            page = (STATIC / "reader.html").read_text()
            # Same reader page as on the church network, told to use SSE instead of the hub's WebSocket.
            page = page.replace('<script src="static/caption-client.js">',
                                '<script>window.CAPTIONS_SSE = "events";</script>\n<script src="static/caption-client.js">')
            return self._send(200, page.encode(), TYPES["html"])
        if path == "/events":
            return self._events()
        if path == "/healthz":
            return self._json(200, {"viewers": len(S.viewers), "public": S.live,
                                    "hub_seen_s": round(time.time() - S.last_hub) if S.last_hub else None})
        if path.startswith("/static/"):
            f = (STATIC / path[len("/static/"):]).resolve()
            if f.is_file() and STATIC in f.parents:
                # Fonts can be cached; the page script must not be, or phones run a stale reader.
                return self._send(200, f.read_bytes(), TYPES.get(f.suffix[1:], "application/octet-stream"),
                                  "public, max-age=86400" if f.suffix == ".ttf" else "no-cache")
        self._send(404, b"not found", "text/plain")

    def do_HEAD(self):
        # Link previews and uptime checks use HEAD; answer like GET without a body (or a stream).
        if self.path.split("?", 1)[0] == "/events":
            return self._send(200, b"", "text/event-stream")
        self.do_GET()

    def _events(self):
        if len(S.viewers) >= MAX_VIEWERS:
            return self._send(503, b"too many viewers", "text/plain")
        q: queue.Queue = queue.Queue(maxsize=200)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        with S.lock:
            S.viewers.add(q)
        try:
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.write(f"data: {json.dumps(S.snapshot())}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    data = q.get(timeout=15)
                except queue.Empty:
                    data = ""
                if data is None:
                    break
                self.wfile.write(f"data: {data}\n\n".encode() if data else b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass
        finally:
            with S.lock:
                S.viewers.discard(q)

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/publish":
            return self._send(404, b"not found", "text/plain")
        auth = self.headers.get("Authorization", "")
        if not KEY or not hmac.compare_digest(auth.encode(), f"Bearer {KEY}".encode()):
            return self._json(401, {"error": "bad key"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > 65536:
            return self._json(413, {"error": "too large"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            for m in body if isinstance(body, list) else [body]:
                S.publish(m)
        except (ValueError, TypeError) as e:
            return self._json(400, {"error": str(e)})
        self._json(200, {"viewers": len(S.viewers), "public": S.live})


def main():
    if not KEY:
        raise SystemExit("RELAY_KEY is not set")
    threading.Thread(target=watchdog, daemon=True).start()
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    srv.daemon_threads = True
    print(f"captions relay on {BIND}:{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
