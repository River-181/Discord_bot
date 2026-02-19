#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
BACKEND_PID_FILE="$ROOT_DIR/tools/dashboard/backend.pid"
FRONTEND_PID_FILE="$ROOT_DIR/tools/dashboard/frontend.pid"

check() {
  local path="$1"
  local label="$2"
  if [ ! -f "$path" ]; then
    echo "$label: stopped"
    return
  fi

  local pid
  pid="$(cat "$path")"
  if kill -0 "$pid" 2>/dev/null; then
    echo "$label: running pid=$pid"
  else
    echo "$label: dead pid=$pid"
  fi
}

check "$BACKEND_PID_FILE" "backend"
check "$FRONTEND_PID_FILE" "frontend"
