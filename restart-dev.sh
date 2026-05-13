#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
START_SCRIPT="$ROOT_DIR/start-dev.sh"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

kill_by_port() {
  local port="$1"
  local pids
  pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "[kill] port $port -> $pids"
    kill $pids 2>/dev/null || true
    sleep 1
    local remain
    remain="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
    if [[ -n "$remain" ]]; then
      echo "[kill -9] port $port -> $remain"
      kill -9 $remain 2>/dev/null || true
    fi
  fi
}

kill_by_pattern() {
  local pattern="$1"
  local pids
  pids="$(pgrep -f "$pattern" || true)"
  if [[ -n "$pids" ]]; then
    echo "[kill] pattern '$pattern' -> $pids"
    kill $pids 2>/dev/null || true
    sleep 1
    local remain
    remain="$(pgrep -f "$pattern" || true)"
    if [[ -n "$remain" ]]; then
      echo "[kill -9] pattern '$pattern' -> $remain"
      kill -9 $remain 2>/dev/null || true
    fi
  fi
}

echo "[restart] stopping existing dev processes..."
kill_by_pattern "uvicorn app.main:app"
kill_by_pattern "vite --host 127.0.0.1"
kill_by_pattern "npm run dev -- --host 127.0.0.1"

kill_by_port "$BACKEND_PORT"
kill_by_port "$FRONTEND_PORT"

echo "[restart] starting services..."
if [[ ! -x "$START_SCRIPT" ]]; then
  echo "[error] $START_SCRIPT not found or not executable."
  exit 1
fi

exec "$START_SCRIPT"

