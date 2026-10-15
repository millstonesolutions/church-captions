#!/usr/bin/env bash
# Install or update the public caption relay on a Linux server (run as root, from a checkout):
#   sudo bash relay/install.sh
# Copies relay.py and the reader page to /opt/church-captions-relay, keeps an existing key,
# installs the systemd unit and (re)starts it on 127.0.0.1:8788. Put a TLS proxy in front -
# see "Public captions" in the README for the Caddy lines.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST=/opt/church-captions-relay
ENV=/etc/church-captions-relay.env

install -d -m 755 "$DEST/static"
install -m 644 "$SRC/relay.py" "$DEST/relay.py"
install -m 644 "$SRC/../hub/static/reader.html" "$SRC/../hub/static/caption-client.js" "$DEST/static/"

if [ ! -s "$ENV" ]; then
  if [ -n "${RELAY_KEY:-}" ]; then key="$RELAY_KEY"; else key="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"; fi
  umask 077
  printf 'RELAY_KEY=%s\nRELAY_BIND=127.0.0.1\nRELAY_PORT=8788\n' "$key" > "$ENV"
  echo "New relay key written to $ENV - put the same key in the hub's settings (Public captions > Relay key)."
fi
chmod 600 "$ENV"

install -m 644 "$SRC/church-captions-relay.service" /etc/systemd/system/church-captions-relay.service
systemctl daemon-reload
systemctl enable church-captions-relay >/dev/null
systemctl restart church-captions-relay
sleep 1
curl -fsS http://127.0.0.1:8788/healthz && echo && echo "relay running"
