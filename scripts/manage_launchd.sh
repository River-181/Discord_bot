#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.mangsang.orbit.assistant"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
OUT_LOG="$ROOT_DIR/data/logs/launchd.out.log"
ERR_LOG="$ROOT_DIR/data/logs/launchd.err.log"

mkdir -p "$ROOT_DIR/data/logs"

write_plist() {
  cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>WorkingDirectory</key>
  <string>${ROOT_DIR}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${ROOT_DIR}/.venv/bin/python</string>
    <string>-m</string>
    <string>bot.app</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
    <key>TZ</key>
    <string>Asia/Seoul</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${OUT_LOG}</string>
  <key>StandardErrorPath</key>
  <string>${ERR_LOG}</string>
</dict>
</plist>
PLIST
}

install() {
  write_plist
  launchctl bootout "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
  launchctl enable "gui/$(id -u)/${LABEL}"
  launchctl kickstart -k "gui/$(id -u)/${LABEL}"
  echo "installed label=${LABEL} plist=${PLIST_PATH}"
}

uninstall() {
  launchctl bootout "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true
  rm -f "$PLIST_PATH"
  echo "uninstalled label=${LABEL}"
}

status() {
  launchctl print "gui/$(id -u)/${LABEL}" | sed -n '1,120p'
}

restart() {
  install
  status
}

case "${1:-}" in
  install) install ;;
  uninstall) uninstall ;;
  restart) restart ;;
  status) status ;;
  *)
    echo "usage: $0 {install|uninstall|restart|status}"
    exit 1
    ;;
esac
