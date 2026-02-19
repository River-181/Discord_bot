#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
BACKEND_PID_FILE="$ROOT_DIR/tools/dashboard/backend.pid"
FRONTEND_PID_FILE="$ROOT_DIR/tools/dashboard/frontend.pid"

stop_pid_file() {
  local path="$1"
  local label="$2"
  if [ ! -f "$path" ]; then
    echo "$label: no pid file"
    return
  fi

  local pid
  pid="$(cat "$path")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" || true
    echo "$label stopped pid=$pid"
  else
    echo "$label pid missing: $pid"
  fi
  rm -f "$path"
}

stop_pid_file "$BACKEND_PID_FILE" "backend"
stop_pid_file "$FRONTEND_PID_FILE" "frontend"
