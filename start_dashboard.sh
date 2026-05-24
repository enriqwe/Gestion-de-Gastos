#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8081}"
LOG="$ROOT/dashboard-server.log"
PIDFILE="$ROOT/state/dashboard-server.pid"
mkdir -p "$ROOT/state"

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "SERVER_ALREADY_RUNNING http://127.0.0.1:$PORT/"
  exit 0
fi

pkill -f "http.server $PORT .*gastos-repository" 2>/dev/null || true
PORT="$PORT" setsid python3 "$ROOT/dashboard_server.py" > "$LOG" 2>&1 < /dev/null &
echo "$!" > "$PIDFILE"
echo "SERVER_OK http://127.0.0.1:$PORT/"
