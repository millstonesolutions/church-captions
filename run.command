#!/bin/zsh
# Start the caption hub (or just open it if it is already running), then show the settings page.
# Used by both the Finder double-click and "Church Captions.app" (tools/make_launcher.sh).
cd "$(dirname "$0")"
PORT=$(.venv/bin/python -c "import yaml;print(yaml.safe_load(open('config.yaml'))['hub']['port'])" 2>/dev/null || echo 8787)
URL="http://127.0.0.1:$PORT/settings"
LOG=captions.log

up() { curl -s -m 2 -o /dev/null "http://127.0.0.1:$PORT/api/status"; }

# Chrome when installed, otherwise the default browser.
show() {
  if [ -d "/Applications/Google Chrome.app" ]; then
    open -a "Google Chrome" "$URL"
  else
    open "$URL"
  fi
}

note() { osascript -e "display notification \"$1\" with title \"Church Captions\"" 2>/dev/null; }

if up; then
  show
  exit 0
fi

if [ ! -x .venv/bin/python ]; then
  osascript -e 'display alert "Church Captions is not installed yet" message "Run the Install steps in the README (create .venv and pip install -r requirements.txt) in the church-captions folder." as critical' 2>/dev/null
  exit 1
fi

note "Starting captions - the settings page opens in a few seconds."
echo "$(date '+%Y-%m-%d %H:%M:%S') launcher: starting hub" >> "$LOG"
# stdin closed so nothing can stop it waiting on a terminal; caffeinate keeps the Mac awake
# (not lid-closed sleep) for exactly as long as the hub runs.
nohup .venv/bin/python hub/server.py >> "$LOG" 2>&1 < /dev/null &
PID=$!
nohup caffeinate -ims -w "$PID" >/dev/null 2>&1 < /dev/null &

for i in {1..60}; do
  sleep 1
  if up; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') launcher: hub up after ${i}s" >> "$LOG"
    show
    exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    break
  fi
done

echo "$(date '+%Y-%m-%d %H:%M:%S') launcher: hub did not start" >> "$LOG"
osascript -e "display alert \"Captions didn't start\" message \"The last lines of captions.log in $(pwd) say why.\" as critical" 2>/dev/null
open -R "$LOG"
exit 1
