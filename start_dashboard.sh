#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8081}"
LOG="$ROOT/dashboard-server.log"

if pgrep -f "dashboard_server.py" >/dev/null; then
  echo "SERVER_ALREADY_RUNNING http://127.0.0.1:$PORT/"
  exit 0
fi

pkill -f "http.server $PORT .*gastos-repository" 2>/dev/null || true
PORT="$PORT" setsid python3 "$ROOT/dashboard_server.py" > "$LOG" 2>&1 < /dev/null &
echo "SERVER_OK http://127.0.0.1:$PORT/"
