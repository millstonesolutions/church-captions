// Shared caption client for the overlay and reader pages. Reconnects automatically.
// On the church network it uses the hub's WebSocket; served by the public relay
// (relay/relay.py sets window.CAPTIONS_SSE) it uses Server-Sent Events instead.
function dispatchCaption(handlers, m) {
  if (m.type === "snapshot") handlers.snapshot?.(m);
  else if (m.type === "final") handlers.final?.(m.text);
  else if (m.type === "partial") handlers.partial?.(m.text);
  else if (m.type === "clear") handlers.clear?.();
  else if (m.type === "status") handlers.running?.(m.running);
  else if (m.type === "settings") handlers.settings?.(m);
}

function connectCaptions(handlers) {
  if (window.CAPTIONS_SSE) {
    const es = new EventSource(window.CAPTIONS_SSE);   // the browser retries on its own
    es.onopen = () => handlers.status?.(true);
    es.onmessage = ev => dispatchCaption(handlers, JSON.parse(ev.data));
    es.onerror = () => handlers.status?.(false);
    return;
  }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  let ws, timer, ping;
  function open() {
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => { clearTimeout(timer); ping = setInterval(() => ws.readyState === 1 && ws.send("."), 15000); handlers.status?.(true); };
    ws.onmessage = ev => dispatchCaption(handlers, JSON.parse(ev.data));
    ws.onclose = () => { clearInterval(ping); handlers.status?.(false); timer = setTimeout(open, 1500); };
    ws.onerror = () => ws.close();
  }
  open();
}
