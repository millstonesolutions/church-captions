// Shared WebSocket client for the overlay and reader pages. Reconnects automatically.
function connectCaptions(handlers) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  let ws, timer, ping;
  function open() {
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => { clearTimeout(timer); ping = setInterval(() => ws.readyState === 1 && ws.send("."), 15000); handlers.status?.(true); };
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === "snapshot") handlers.snapshot?.(m);
      else if (m.type === "final") handlers.final?.(m.text);
      else if (m.type === "partial") handlers.partial?.(m.text);
      else if (m.type === "clear") handlers.clear?.();
      else if (m.type === "status") handlers.running?.(m.running);
      else if (m.type === "settings") handlers.settings?.(m);
    };
    ws.onclose = () => { clearInterval(ping); handlers.status?.(false); timer = setTimeout(open, 1500); };
    ws.onerror = () => ws.close();
  }
  open();
}
