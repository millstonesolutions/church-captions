"""Optional: push the latest caption lines into a ProPresenter 7 Message.

ProPresenter's REST API (Settings > Network > enable, note the port) lets you trigger a
pre-built Message with token values. Build a Message named e.g. "Captions" with a single
text token named "text", style it with a theme, and point this at it.

Settings are read from the live config on every push, so the web GUI can turn this on/off.
Endpoint shapes follow https://openapi.propresenter.com/ — confirm against your Pro7 version.
"""
import asyncio
import time

import httpx


class ProPresenterPusher:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._last = 0.0
        self._client = httpx.AsyncClient(timeout=2.0)
        self._lock = asyncio.Lock()

    def _base(self):
        return f"http://{self.cfg.get('host', '127.0.0.1')}:{self.cfg.get('port', 1025)}/v1"

    async def push(self, history: list[dict]):
        if not self.cfg.get("enabled") or not history:
            return
        async with self._lock:
            wait = float(self.cfg.get("min_interval_s", 0.5)) - (time.time() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            text = "\n".join(h["text"] for h in history[-int(self.cfg.get("lines", 2)):])
            body = [{"name": self.cfg.get("token", "text"), "text": {"text": text}}]
            try:
                await self._client.post(f"{self._base()}/message/{self.cfg.get('message_id', 'Captions')}/trigger",
                                        json=body)
            except Exception as e:
                print(f"[propresenter] push failed: {e}")
            self._last = time.time()

    async def clear(self):
        if not self.cfg.get("enabled"):
            return
        try:
            await self._client.get(f"{self._base()}/message/{self.cfg.get('message_id', 'Captions')}/clear")
        except Exception as e:
            print(f"[propresenter] clear failed: {e}")
