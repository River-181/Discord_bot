#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT_DIR/data/bot.pid"
LOG_DIR="$ROOT_DIR/data/logs"
LOG_FILE="$LOG_DIR/bot.log"
CMD_PATTERN="[Pp]ython.*-m bot.app"

mkdir -p "$LOG_DIR"

find_running_pids() {
  pgrep -f "$CMD_PATTERN" || true
}

first_running_pid() {
  local pids
  pids="$(find_running_pids)"
  if [ -n "$pids" ]; then
    echo "$pids" | head -n 1
  fi
}

newest_running_pid() {
  local pids
  pids="$(find_running_pids)"
  if [ -n "$pids" ]; then
    echo "$pids" | sort -n | tail -n 1
  fi
}

start() {
  local existing_pid
  local newest_pid
  local pids
  pids="$(find_running_pids)"
  existing_pid="$(first_running_pid)"
  if [ -n "$existing_pid" ]; then
    newest_pid="$(newest_running_pid)"
    for pid in $pids; do
      if [ "$pid" = "$newest_pid" ]; then
        continue
      fi
      kill "$pid" 2>/dev/null || true
      echo "stopped-extra pid=$pid"
    done
    echo "$newest_pid" > "$PID_FILE"
    echo "already-running pid=$newest_pid"
    return 0
  fi

  if [ -f "$PID_FILE" ]; then
    PID="$(cat "$PID_FILE")"
    if kill -0 "$PID" 2>/dev/null; then
      echo "already-running pid=$PID"
      return 0
    fi
    rm -f "$PID_FILE"
  fi

  cd "$ROOT_DIR"
  nohup .venv/bin/python -m bot.app </dev/null >> "$LOG_FILE" 2>&1 &
  disown || true
  PID=$!
  echo "$PID" > "$PID_FILE"
  sleep 1
  if kill -0 "$PID" 2>/dev/null; then
    echo "started pid=$PID log=$LOG_FILE"
  else
    echo "failed-to-start"
    return 1
  fi
}

stop() {
  local stopped_any=0
  if [ ! -f "$PID_FILE" ]; then
    running_pid="$(first_running_pid)"
    if [ -z "$running_pid" ]; then
      echo "not-running"
      return 0
    fi
    PID="$running_pid"
  else
    PID="$(cat "$PID_FILE")"
  fi

  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    sleep 1
    if kill -0 "$PID" 2>/dev/null; then
      kill -9 "$PID" || true
    fi
    echo "stopped pid=$PID"
    stopped_any=1
  else
    echo "stale-pid removed"
  fi
  rm -f "$PID_FILE"

  # Clean up duplicate unmanaged instances if they exist.
  for dup_pid in $(find_running_pids); do
    if [ "$dup_pid" = "$PID" ]; then
      continue
    fi
    kill "$dup_pid" 2>/dev/null || true
    stopped_any=1
    echo "stopped-extra pid=$dup_pid"
  done

  if [ "$stopped_any" -eq 0 ]; then
    echo "not-running"
  fi
}

status() {
  if [ -f "$PID_FILE" ]; then
    PID="$(cat "$PID_FILE")"
    if kill -0 "$PID" 2>/dev/null; then
      echo "running pid=$PID log=$LOG_FILE"
      return 0
    fi
  fi

  running_pid="$(first_running_pid)"
  if [ -n "$running_pid" ]; then
    echo "$running_pid" > "$PID_FILE"
    echo "running(external) pid=$running_pid log=$LOG_FILE"
    return 0
  fi

  if [ -f "$PID_FILE" ]; then
    stale_pid="$(cat "$PID_FILE")"
    echo "stopped(stale pid=$stale_pid)"
  else
    echo "stopped"
  fi
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  restart) stop || true; start ;;
  status) status ;;
  *)
    echo "usage: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac
