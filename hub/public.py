"""Forward captions to the public relay (relay/relay.py) so phones off the church network can follow.

Off unless `public.enabled` is on - turned on from the settings page or Companion
(/api/public/on). Everything goes out as outbound HTTPS POSTs with a shared key, so the
church router needs no open ports. While on, a heartbeat every 20 s keeps the relay's page
live; if the hub stops sending, the relay takes the captions down on its own after ~75 s.

Lines that can't be delivered are dropped rather than queued - a phone catching up with a
backlog of stale lines is worse than a short gap.
"""
import asyncio
import time

import httpx

HEARTBEAT_S = 20


class PublicRelay:
    def __init__(self, cfg: dict, is_running):
        self.cfg = cfg                      # live `public` section of config.yaml
        self.is_running = is_running        # () -> bool: is the hub transcribing
        self.viewers = 0
        self.ok = None                      # None = never tried, True/False = last result
        self.error = ""
        self.last_ok = 0.0
        self._q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._client = httpx.AsyncClient(timeout=6.0)
        self._task = None

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled")) and bool(self.cfg.get("url")) and bool(self.cfg.get("key"))

    def start(self):
        self._task = asyncio.create_task(self._run())

    def send(self, msg: dict):
        """Queue a hub message (final/partial/clear/status) for the relay."""
        if not self.enabled or msg.get("type") not in ("final", "partial", "clear", "status"):
            return
        try:
            self._q.put_nowait(msg)
        except asyncio.QueueFull:
            pass

    def announce(self):
        """Tell the relay the current state now (after a toggle or a hub start/stop)."""
        msg = {"type": "status", "running": self.enabled and self.is_running(),
               "history_lines": int(self.cfg.get("history_lines", 0))}
        if self.cfg.get("url") and self.cfg.get("key"):
            try:
                self._q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def state(self) -> dict:
        return {"enabled": self.enabled, "ok": self.ok, "error": self.error, "viewers": self.viewers,
                "url": (self.cfg.get("url") or "").rstrip("/") + "/" if self.cfg.get("url") else ""}

    async def _post(self, batch: list[dict]):
        url = self.cfg.get("url", "").rstrip("/") + "/publish"
        try:
            r = await self._client.post(url, json=batch, headers={"Authorization": f"Bearer {self.cfg.get('key', '')}"})
            if r.status_code == 200:
                j = r.json()
                self.viewers, self.ok, self.error, self.last_ok = int(j.get("viewers", 0)), True, "", time.time()
            else:
                self.ok, self.error = False, f"relay answered {r.status_code}" + (" (wrong key?)" if r.status_code == 401 else "")
        except Exception as e:
            self.ok, self.error = False, f"{type(e).__name__}: {e}"[:200]

    async def _run(self):
        last_beat = 0.0
        while True:
            try:
                msg = await asyncio.wait_for(self._q.get(), timeout=2)
                batch = [msg]
                while not self._q.empty():
                    batch.append(self._q.get_nowait())
                # A newer partial or final supersedes an older partial - skip the stale ones.
                kept = [m for i, m in enumerate(batch)
                        if m["type"] != "partial" or not any(n["type"] in ("partial", "final") for n in batch[i + 1:])]
                await self._post(kept)
            except asyncio.TimeoutError:
                pass
            if self.enabled and time.time() - last_beat >= HEARTBEAT_S:
                last_beat = time.time()
                await self._post([{"type": "heartbeat", "running": self.is_running(),
                                   "history_lines": int(self.cfg.get("history_lines", 0))}])
