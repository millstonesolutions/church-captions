#!/bin/zsh
# Build "Church Captions.app" - a double-click launcher that runs run.command from this checkout
# (start the hub if needed, then open the settings page) - and install it in /Applications.
#   zsh tools/make_launcher.sh [destination folder, default /Applications]
# Re-run after moving the checkout: the app points at this folder's run.command.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-/Applications}"
APP="$DEST/Church Captions.app"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

chmod +x "$ROOT/run.command"

# AppleScript applet: run the script detached so the app quits at once and the hub keeps running.
cat > "$WORK/main.applescript" <<EOF
do shell script quoted form of "$ROOT/run.command" & " >/dev/null 2>&1 &"
EOF
rm -rf "$APP"
osacompile -o "$APP" "$WORK/main.applescript"

# Icon: draw at 1024, scale to every size an .icns needs.
swift "$ROOT/tools/launcher_icon.swift" "$WORK/icon.png" "$ROOT/hub/static/fonts/Lato-Black.ttf"
mkdir "$WORK/icon.iconset"
for s in 16 32 128 256 512; do
  sips -z $s $s "$WORK/icon.png" --out "$WORK/icon.iconset/icon_${s}x${s}.png" >/dev/null
  sips -z $((s * 2)) $((s * 2)) "$WORK/icon.png" --out "$WORK/icon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$WORK/icon.iconset" -o "$APP/Contents/Resources/applet.icns"
rm -f "$APP/Contents/Resources/Assets.car"        # otherwise the default script icon wins

PL="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleName Church Captions" "$PL"
/usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string com.millstonesolutions.churchcaptions.launcher" "$PL" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.millstonesolutions.churchcaptions.launcher" "$PL"
/usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$PL" 2>/dev/null || true

codesign --force --deep --sign - "$APP" 2>/dev/null       # ad-hoc: editing the bundle broke osacompile's signature
touch "$APP"                                             # nudge Finder/Dock to pick up the new icon
echo "Installed $APP -> $ROOT/run.command"
