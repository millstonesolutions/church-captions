"""Caption hub: takes transcript segments from the STT worker and fans them out.

Outputs
  ws://host:8787/ws           JSON caption stream (overlay, reader, anything else)
  http://host:8787/overlay    transparent lower-third page for an OBS Browser Source
  http://host:8787/reader     large-type page for tablets handed to the congregation
  http://host:8787/settings   every setting in config.yaml, applied live
  http://host:8787/api/*      control endpoints (Companion-friendly, plain HTTP)
"""
import asyncio
import base64
import json
import secrets
import subprocess
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from ruamel.yaml import YAML

from propresenter import ProPresenterPusher
from public import PublicRelay
from stt import Transcriber
from vocab import Vocab

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT.parent / "config.yaml"           # this Mac's settings; not committed
EXAMPLE_PATH = ROOT.parent / "config.example.yaml"
LEXICON_PATH = ROOT.parent / "data" / "lexicon.json"
_yaml = YAML()                       # round-trip mode: keeps the comments in config.yaml
_yaml.preserve_quotes = True
if not CONFIG_PATH.exists():
    CONFIG_PATH.write_text(EXAMPLE_PATH.read_text())
CONFIG = _yaml.load(CONFIG_PATH.read_text())
for section in ("hub", "audio", "stt", "vocab", "overlay", "propresenter", "public"):
    CONFIG.setdefault(section, {})

# Every knob the settings page shows. The page is generated from this list, and POST /api/config
# only accepts keys listed here, coerced and clamped to these types and ranges.
#   restart="stt"  -> restart the audio/model pipeline     restart="hub" -> needs a process restart
SCHEMA = [
    {"section": "Audio input", "items": [
        {"key": "audio.device", "type": "device", "label": "Input device", "restart": "stt",
         "help": "The X32 over USB shows as X-USB. Blank = system default input."},
        {"key": "audio.channel", "type": "int", "ui": "channel", "min": 0, "max": 63, "label": "Input channel", "restart": "stt",
         "help": "The X-USB channel carrying the speech-only bus. The list matches the selected device."},
        {"key": "audio.gain_db", "type": "float", "min": -20, "max": 30, "step": 1, "label": "Software gain (dB)",
         "help": "Aim for speech peaking around -20 to -10 dB on the meter."},
    ]},
    {"section": "Recognition", "items": [
        {"key": "stt.model", "type": "select", "label": "Model", "restart": "stt",
         "options": ["mlx-community/whisper-small.en-mlx", "mlx-community/whisper-medium.en-mlx",
                     "mlx-community/whisper-large-v3-turbo"],
         "help": "Small is right for an 8 GB Mac running OBS. A new model downloads on first use."},
        {"key": "stt.vad_aggressiveness", "type": "int", "ui": "segmented", "min": 0, "max": 3, "label": "Speech detector strictness",
         "labels": ["Loosest", "Loose", "Normal", "Strict"],
         "help": "Normal is the default. Use Strict if music or room noise produces junk lines."},
        {"key": "stt.end_silence_ms", "type": "int", "min": 200, "max": 2000, "step": 50, "label": "Pause that ends a line (ms)",
         "help": "Lower = snappier lines; higher if the pastor pauses mid-sentence."},
        {"key": "stt.min_speech_ms", "type": "int", "min": 100, "max": 2000, "step": 50, "label": "Ignore sounds shorter than (ms)"},
        {"key": "stt.max_utterance_s", "type": "float", "min": 3, "max": 30, "step": 1, "label": "Longest line before a forced break (s)"},
        {"key": "stt.min_logprob", "type": "float", "min": -3, "max": 0, "step": 0.1, "label": "Junk filter: minimum confidence",
         "help": "Lines Whisper is less sure of than this are dropped. Raise toward -0.6 if junk appears in quiet moments."},
        {"key": "stt.max_no_speech", "type": "float", "min": 0.1, "max": 1, "step": 0.05, "label": "Junk filter: no-speech cutoff",
         "help": "Lower = more eager to drop lines from noise, music or applause."},
        {"key": "stt.max_compression", "type": "float", "min": 1.5, "max": 4, "step": 0.1, "label": "Junk filter: repetition cutoff",
         "help": "Drops looping output like \"the Holy Spirit, the Holy Spirit, the Holy Spirit\"."},
        {"key": "stt.partial_interval_s", "type": "float", "min": 0.3, "max": 5, "step": 0.1, "label": "In-progress line refresh (s)",
         "help": "Lower feels livelier but costs more GPU."},
    ]},
    {"section": "Bible vocabulary", "items": [
        {"key": "vocab.focus_book", "type": "book", "label": "Book being preached",
         "help": "Puts that book's names first in the prompt. Also settable from Companion: /api/focus?book=PHI"},
        {"key": "vocab.auto_detect_book", "type": "bool", "label": "Follow books cited in the sermon",
         "help": "\"Turn to Romans 8\" or \"the book of Ruth\" adds that book for a while."},
        {"key": "vocab.focus_minutes", "type": "int", "min": 5, "max": 180, "label": "Detected book stays for (min)"},
        {"key": "vocab.use_lexicon", "type": "bool", "label": "Use the World English Bible word list"},
        {"key": "vocab.custom", "type": "list", "label": "Always-boost words (one per line)",
         "help": "Church name, staff, members, local places. These go in ahead of Bible words."},
        {"key": "vocab.prompt_tokens", "type": "int", "min": 0, "max": 220, "step": 10, "label": "Prompt size (tokens)",
         "help": "Whisper ignores anything past ~223. A Bible name costs about 5."},
        {"key": "vocab.autocorrect", "type": "bool", "label": "Fix near-miss Bible names",
         "help": "\"Habakuk\" -> \"Habakkuk\", checked against all 3,000+ words in the lexicon."},
        {"key": "vocab.autocorrect_strictness", "type": "float", "min": 0.7, "max": 0.98, "step": 0.01, "label": "Fix strictness",
         "help": "Higher = only fix very close misspellings."},
        {"key": "vocab.corrections", "type": "map", "label": "Exact replacements (wrong = right, one per line)",
         "help": "Applied to every line, e.g. \"Pastor Jim's\" = \"Pastor Jem's\"."},
    ]},
    {"section": "OBS overlay", "items": [
        {"key": "overlay.lines", "type": "int", "ui": "segmented", "min": 1, "max": 4, "label": "Lines shown"},
        {"key": "overlay.size", "type": "int", "min": 20, "max": 96, "label": "Text size (px at 1080p)"},
        {"key": "overlay.bottom", "type": "int", "min": 0, "max": 600, "step": 5, "label": "Distance from bottom (px)"},
        {"key": "overlay.fade_s", "type": "float", "min": 2, "max": 60, "step": 1, "label": "Clear after silence (s)"},
        {"key": "overlay.box_opacity", "type": "float", "min": 0, "max": 1, "step": 0.05, "label": "Background box opacity"},
    ]},
    {"section": "ProPresenter", "items": [
        {"key": "propresenter.enabled", "type": "bool", "label": "Send captions to a ProPresenter Message"},
        {"key": "propresenter.host", "type": "str", "label": "ProPresenter host"},
        {"key": "propresenter.port", "type": "int", "ui": "number", "min": 1, "max": 65535, "label": "Network port"},
        {"key": "propresenter.message_id", "type": "str", "label": "Message name"},
        {"key": "propresenter.token", "type": "str", "label": "Text token name"},
        {"key": "propresenter.lines", "type": "int", "ui": "segmented", "min": 1, "max": 4, "label": "Lines sent"},
        {"key": "propresenter.min_interval_s", "type": "float", "min": 0.1, "max": 5, "step": 0.1, "label": "Minimum seconds between updates"},
    ]},
    {"section": "Public captions (internet)", "items": [
        {"key": "public.enabled", "type": "bool", "label": "Send captions to the public page",
         "help": "Off by default. Anyone with the link can read what the mic hears while this is on, "
                 "so leave it off for prayer time or pre-service chatter. Companion: /api/public/on and /api/public/off"},
        {"key": "public.url", "type": "str", "label": "Relay address",
         "help": "Where relay/relay.py is served, e.g. https://example.org/captions"},
        {"key": "public.key", "type": "password", "label": "Relay key",
         "help": "Must match RELAY_KEY on the server."},
        {"key": "public.history_lines", "type": "int", "min": 0, "max": 50, "label": "Earlier lines shown to late joiners",
         "help": "0 = phones that join late see only new lines."},
    ]},
    {"section": "Hub", "items": [
        {"key": "hub.autostart", "type": "bool", "label": "Start transcribing when the Mac boots"},
        {"key": "hub.history_lines", "type": "int", "min": 10, "max": 2000, "step": 10, "label": "Lines kept for late-joining tablets"},
        {"key": "hub.admin_password", "type": "password", "label": "Settings password (user: admin)",
         "help": "Blank = no login. Start/Stop/Clear and the Companion API stay open either way."},
        {"key": "hub.port", "type": "int", "ui": "number", "min": 1024, "max": 65535, "label": "Web port", "restart": "hub"},
    ]},
]
FIELDS = {i["key"]: i for s in SCHEMA for i in s["items"]}
MASK = "••••••••"      # secrets are never sent back to the browser

app = FastAPI(title="Church Captions Hub")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.middleware("http")
async def revalidate(request: Request, call_next):
    # Pages and scripts change with updates; without this, phones and tablets kept running a cached
    # old reader. "no-cache" still allows 304s via the ETag, so it costs a round-trip, not a download.
    resp = await call_next(request)
    if not request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-cache")
    return resp


def cfg_get(key):
    sec, name = key.split(".", 1)
    return CONFIG[sec].get(name)


def coerce(field: dict, value):
    t = field["type"]
    if t == "bool":
        return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "on", "yes")
    if t in ("int", "float"):
        v = int(round(float(value))) if t == "int" else float(value)
        return max(field.get("min", v), min(field.get("max", v), v))
    if t == "list":
        items = value if isinstance(value, list) else str(value).splitlines()
        return [str(x).strip() for x in items if str(x).strip()]
    if t == "map":
        if isinstance(value, dict):
            return {str(k).strip(): str(v).strip() for k, v in value.items() if str(k).strip()}
        out = {}
        for line in str(value).splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip().strip('"'), v.strip().strip('"')
                if k:
                    out[k] = v
        return out
    if t == "select" and value not in field["options"] and not str(value).startswith("mlx-community/"):
        raise ValueError(f"unknown option {value}")
    return "" if value is None else str(value).strip()


class Hub:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.history: list[dict] = []          # finalized lines, newest last
        self.partial: str = ""
        self.loop: asyncio.AbstractEventLoop | None = None
        self.vocab = Vocab(CONFIG["vocab"], LEXICON_PATH)
        self.transcriber = Transcriber(CONFIG["stt"], CONFIG["audio"], self.on_segment, self.vocab)
        self.pro = ProPresenterPusher(CONFIG["propresenter"])
        self.public = PublicRelay(CONFIG["public"], lambda: self.running)
        self.busy = ""                          # e.g. "loading model" while a restart runs

    @property
    def running(self):
        return self.transcriber.running

    # Called from the STT thread -> hop onto the event loop
    def on_segment(self, text: str, final: bool):
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._handle(text, final), self.loop)

    async def _handle(self, text: str, final: bool):
        text = text.strip()
        if not text:
            return
        if final:
            self.partial = ""
            self.history.append({"text": text, "t": time.time()})
            self.history = self.history[-int(CONFIG["hub"].get("history_lines", 200)):]
            await self.broadcast({"type": "final", "text": text})
            await self.pro.push(self.history)
        else:
            self.partial = text
            await self.broadcast({"type": "partial", "text": text})

    async def broadcast(self, msg: dict):
        self.public.send(msg)
        data = json.dumps(msg)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def overlay_settings(self) -> dict:
        return {k: CONFIG["overlay"].get(k) for k in ("lines", "size", "bottom", "fade_s", "box_opacity")}

    def snapshot(self) -> dict:
        return {"type": "snapshot", "running": self.running, "history": [h["text"] for h in self.history],
                "partial": self.partial, "overlay": self.overlay_settings()}

    async def start(self):
        if not self.running:
            self.busy = "starting"
            try:
                await asyncio.to_thread(self.transcriber.start)   # may load/download a model
            except Exception as e:
                self.transcriber.last_error = f"{type(e).__name__}: {e}"
            finally:
                self.busy = ""
            await self.broadcast({"type": "status", "running": self.running})

    async def stop(self):
        if self.running:
            await asyncio.to_thread(self.transcriber.stop)
            await self.broadcast({"type": "status", "running": False})


hub = Hub()


@app.on_event("startup")
async def _startup():
    hub.loop = asyncio.get_running_loop()
    hub.public.start()
    hub.public.announce()      # a hub restart brings the public page back to the right state
    if CONFIG["hub"].get("autostart", False):
        asyncio.create_task(hub.start())


# ---------- optional login for settings ----------
def require_admin(request: Request):
    pw = CONFIG["hub"].get("admin_password") or ""
    if not pw:
        return
    auth = request.headers.get("authorization", "")
    if auth.startswith("Basic "):
        try:
            user, _, given = base64.b64decode(auth[6:]).decode().partition(":")
            if user == "admin" and secrets.compare_digest(given, pw):
                return
        except Exception:
            pass
    raise HTTPException(401, "login required", headers={"WWW-Authenticate": 'Basic realm="Captions settings"'})


# ---------- pages ----------
@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/overlay")
def overlay():
    return FileResponse(ROOT / "static" / "overlay.html")


@app.get("/reader")
def reader():
    return FileResponse(ROOT / "static" / "reader.html")


@app.get("/settings")
def settings_page(request: Request):
    require_admin(request)
    return FileResponse(ROOT / "static" / "settings.html")


# ---------- websocket ----------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    hub.clients.add(ws)
    await ws.send_text(json.dumps(hub.snapshot()))
    try:
        while True:
            await ws.receive_text()  # clients don't send anything meaningful; keeps the socket alive
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)


# ---------- control API (GET and POST both work so Companion/curl/browser bookmarks are easy) ----------
@app.api_route("/api/start", methods=["GET", "POST"])
async def start():
    await hub.start()
    return {"running": hub.running, "error": hub.transcriber.last_error}


@app.api_route("/api/stop", methods=["GET", "POST"])
async def stop():
    await hub.stop()
    return {"running": False}


@app.api_route("/api/clear", methods=["GET", "POST"])
async def clear():
    hub.history.clear()
    hub.partial = ""
    hub.transcriber.full_transcript.clear()
    await hub.broadcast({"type": "clear"})
    await hub.pro.clear()
    return {"cleared": True}


@app.api_route("/api/focus", methods=["GET", "POST"])
async def focus(book: str = ""):
    """Set the book being preached: /api/focus?book=PHI (or a name, "Philippians"); empty clears."""
    code = ""
    b = book.strip().lower()
    if b:
        for x in hub.vocab.lex["books"]:
            if b in (x["code"].lower(), x["name"].lower(), *x["aliases"]):
                code = x["code"]
        if not code:
            raise HTTPException(400, f"unknown book {book!r}")
    CONFIG["vocab"]["focus_book"] = code
    if not code:
        hub.vocab.clear_auto_focus()
    save_config()
    return {"focus_book": code, "active": hub.vocab.focus_codes()}


@app.api_route("/api/public/on", methods=["GET", "POST"])
async def public_on():
    return await _set_public(True)


@app.api_route("/api/public/off", methods=["GET", "POST"])
async def public_off():
    return await _set_public(False)


@app.api_route("/api/public/toggle", methods=["GET", "POST"])
async def public_toggle():
    """One Companion button: flips public captions. The response says which way it went."""
    return await _set_public(not CONFIG["public"].get("enabled"))


async def _set_public(on: bool):
    CONFIG["public"]["enabled"] = on
    save_config()
    hub.public.announce()
    return hub.public.state()


@app.get("/api/status")
def status():
    t = hub.transcriber
    return JSONResponse({"running": hub.running, "busy": hub.busy, "error": t.last_error,
                         "clients": len(hub.clients), "lines": len(hub.history), "device": t.device_name(),
                         "level_db": round(t.level_db, 1), "speaking": t.speaking, "dropped": t.dropped,
                         "focus": hub.vocab.focus_codes(), "public": hub.public.state()})


@app.get("/api/devices")
def devices():
    return hub.transcriber.list_devices()


@app.get("/api/transcript", response_class=PlainTextResponse)
def transcript():
    """Full session transcript as plain text (for a sermon transcript download)."""
    return "\n".join(l["text"] for l in hub.transcriber.full_transcript)


# ---------- settings API ----------
def save_config():
    with CONFIG_PATH.open("w") as f:
        _yaml.dump(CONFIG, f)


@app.get("/api/config")
def get_config(request: Request):
    require_admin(request)
    values = {k: (MASK if FIELDS[k]["type"] == "password" and cfg_get(k) else cfg_get(k)) for k in FIELDS}
    values = json.loads(json.dumps(values, default=lambda o: dict(o) if hasattr(o, "items") else list(o)))
    return {"schema": SCHEMA, "values": values, "devices": hub.transcriber.list_devices(),
            "vocab": hub.vocab.state()}


@app.post("/api/config")
async def set_config(request: Request):
    require_admin(request)
    patch = await request.json()
    changed, errors, restart = [], {}, set()
    for key, raw in patch.items():
        field = FIELDS.get(key)
        if not field:
            errors[key] = "not a setting"
            continue
        if field["type"] == "password" and raw == MASK:
            continue                                     # untouched masked field
        try:
            value = coerce(field, raw)
        except (ValueError, TypeError) as e:
            errors[key] = str(e)
            continue
        if value == cfg_get(key):
            continue
        sec, name = key.split(".", 1)
        CONFIG[sec][name] = value
        changed.append(key)
        if field.get("restart"):
            restart.add(field["restart"])
    if changed:
        save_config()
    if "stt" in restart and hub.running:
        await hub.stop()
        await hub.start()
    if any(k.startswith("overlay.") for k in changed):
        await hub.broadcast({"type": "settings", "overlay": hub.overlay_settings()})
    if any(k.startswith("public.") for k in changed):
        hub.public.announce()
    if "hub.history_lines" in changed:
        hub.history = hub.history[-int(CONFIG["hub"]["history_lines"]):]
    return {"changed": changed, "errors": errors, "restart_hub": "hub" in restart,
            "running": hub.running, "error": hub.transcriber.last_error, "vocab": hub.vocab.state()}


@app.post("/api/lexicon/rebuild")
async def rebuild_lexicon(request: Request):
    require_admin(request)
    r = await asyncio.to_thread(subprocess.run, [sys.executable, str(ROOT.parent / "tools" / "build_lexicon.py")],
                                capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise HTTPException(500, r.stderr[-500:])
    hub.vocab.__init__(CONFIG["vocab"], LEXICON_PATH)
    return {"ok": True, "output": r.stdout.strip(), "vocab": hub.vocab.state()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=CONFIG["hub"]["bind"], port=int(CONFIG["hub"]["port"]), log_level="info")
