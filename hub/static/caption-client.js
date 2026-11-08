// Shared caption client for the overlay and reader pages. Reconnects automatically.
// On the church network it uses the hub's WebSocket; served by the public relay
// (relay/relay.py sets window.CAPTIONS_SSE) it uses Server-Sent Events instead.
// Old Safari (iOS 12) cannot parse optional chaining, so handlers are called through this guard.
function callHandler(handlers, name, arg) { if (typeof handlers[name] === "function") handlers[name](arg); }

function dispatchCaption(handlers, m) {
  if (m.type === "snapshot") callHandler(handlers, "snapshot", m);
  else if (m.type === "final") callHandler(handlers, "final", m.text);
  else if (m.type === "partial") callHandler(handlers, "partial", m.text);
  else if (m.type === "clear") callHandler(handlers, "clear");
  else if (m.type === "status") callHandler(handlers, "running", m.running);
  else if (m.type === "settings") callHandler(handlers, "settings", m);
  else if (m.type === "focus") callHandler(handlers, "focus", m.books || []);
}

function connectCaptions(handlers) {
  if (window.CAPTIONS_SSE) {
    const es = new EventSource(window.CAPTIONS_SSE);   // the browser retries on its own
    es.onopen = () => callHandler(handlers, "status", true);
    es.onmessage = ev => dispatchCaption(handlers, JSON.parse(ev.data));
    es.onerror = () => callHandler(handlers, "status", false);
    return;
  }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  let ws, timer, ping;
  function open() {
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => { clearTimeout(timer); ping = setInterval(() => ws.readyState === 1 && ws.send("."), 15000); callHandler(handlers, "status", true); };
    ws.onmessage = ev => dispatchCaption(handlers, JSON.parse(ev.data));
    ws.onclose = () => { clearInterval(ping); callHandler(handlers, "status", false); timer = setTimeout(open, 1500); };
    ws.onerror = () => ws.close();
  }
  open();
}
