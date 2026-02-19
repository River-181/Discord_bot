#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT_DIR"
BACKEND_PORT="${DASHBOARD_BACKEND_PORT:-8080}"
FRONTEND_PORT="${DASHBOARD_FRONTEND_PORT:-8501}"
BACKEND_PID_FILE="$ROOT_DIR/tools/dashboard/backend.pid"
FRONTEND_PID_FILE="$ROOT_DIR/tools/dashboard/frontend.pid"
LOG_DIR="$ROOT_DIR/tools/dashboard/logs"
mkdir -p "$LOG_DIR"

start_backend() {
  if [ -f "$BACKEND_PID_FILE" ]; then
    pid=$(cat "$BACKEND_PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
      echo "backend already running pid=$pid"
      return
    fi
    rm -f "$BACKEND_PID_FILE"
  fi

  PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}" \
    nohup .venv/bin/uvicorn tools.dashboard.backend.dashboard_backend:app \
    --host 127.0.0.1 --port "$BACKEND_PORT" \
    > "$LOG_DIR/backend.out.log" 2>&1 &
  pid=$!
  echo "$pid" > "$BACKEND_PID_FILE"
  echo "backend started pid=$pid"
}

start_frontend() {
  if [ -f "$FRONTEND_PID_FILE" ]; then
    pid=$(cat "$FRONTEND_PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
      echo "frontend already running pid=$pid"
      return
    fi
    rm -f "$FRONTEND_PID_FILE"
  fi

  # Ensure dashboard modules are importable from repo root.
  PYTHONPATH_VALUE="$ROOT_DIR"
  if [ -n "${PYTHONPATH:-}" ]; then
    PYTHONPATH_VALUE="$ROOT_DIR:$PYTHONPATH"
  fi
  DASHBOARD_BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}" \
    PYTHONPATH="$PYTHONPATH_VALUE" \
    nohup .venv/bin/streamlit run "$ROOT_DIR/tools/dashboard/frontend/app.py" \
    --server.port "$FRONTEND_PORT" \
    > "$LOG_DIR/frontend.out.log" 2>&1 &
  pid=$!
  echo "$pid" > "$FRONTEND_PID_FILE"
  echo "frontend started pid=$pid"
}

case "${1:-start}" in
  start)
    start_backend
    start_frontend
    ;;
  *)
    echo "usage: $0 [start]"
    ;;
esac
