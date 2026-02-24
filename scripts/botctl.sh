#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MANAGE_BOT="$ROOT_DIR/scripts/manage_bot.sh"
MANAGE_LAUNCHD="$ROOT_DIR/scripts/manage_launchd.sh"

usage() {
  cat <<'EOF'
usage: ./scripts/botctl.sh <command> [--launchd]

commands:
  start     Start bot
  stop      Stop bot
  restart   Restart bot
  deploy    Validate .Agent workspace and restart bot
  status    Show status
  logs      Tail logs

options:
  --launchd Use launchd mode instead of local daemon mode

examples:
  ./scripts/botctl.sh start
  ./scripts/botctl.sh stop
  ./scripts/botctl.sh logs
  ./scripts/botctl.sh restart --launchd
  ./scripts/botctl.sh deploy --launchd
EOF
}

if [ "${1:-}" = "" ]; then
  usage
  exit 1
fi

command="$1"
shift || true

mode="daemon"
if [ "${1:-}" = "--launchd" ]; then
  mode="launchd"
  shift || true
fi

if [ "${1:-}" != "" ]; then
  usage
  exit 1
fi

if [ "$mode" = "launchd" ]; then
  case "$command" in
    start) "$MANAGE_LAUNCHD" install ;;
    stop) "$MANAGE_LAUNCHD" uninstall ;;
    deploy) "$ROOT_DIR/.Agent/scripts/validate.sh" && "$MANAGE_LAUNCHD" restart ;;
    restart) "$MANAGE_LAUNCHD" restart ;;
    status) "$MANAGE_LAUNCHD" status ;;
    logs) tail -n 120 -f "$ROOT_DIR/data/logs/launchd.err.log" ;;
    *) usage; exit 1 ;;
  esac
  exit 0
fi

case "$command" in
  start) "$MANAGE_BOT" start ;;
  stop) "$MANAGE_BOT" stop ;;
  deploy) "$ROOT_DIR/.Agent/scripts/validate.sh" && "$MANAGE_BOT" restart ;;
  restart) "$MANAGE_BOT" restart ;;
  status) "$MANAGE_BOT" status ;;
  logs) tail -n 120 -f "$ROOT_DIR/data/logs/bot.log" ;;
  *) usage; exit 1 ;;
esac
