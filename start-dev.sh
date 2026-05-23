#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
HOST="${HOST:-127.0.0.1}"

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo ""
  echo "[shutdown] stopping services..."
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
  echo "[shutdown] done."
}

trap cleanup INT TERM EXIT

if [[ ! -d "$BACKEND_DIR" ]] || [[ ! -d "$FRONTEND_DIR" ]]; then
  echo "[error] please run this script from project root."
  exit 1
fi

if [[ ! -x "$BACKEND_DIR/venv/bin/uvicorn" ]]; then
  echo "[error] backend venv not found at backend/venv."
  echo "Run:"
  echo "  cd backend && python3.11 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "[error] frontend dependencies missing."
  echo "Run:"
  echo "  cd frontend && npm install"
  exit 1
fi

echo "[start] backend: http://${HOST}:${BACKEND_PORT}"
(
  cd "$BACKEND_DIR"
  ./venv/bin/uvicorn app.main:app --host "$HOST" --port "$BACKEND_PORT"
) &
BACKEND_PID=$!

echo "[start] frontend: http://${HOST}:${FRONTEND_PORT}"
(
  cd "$FRONTEND_DIR"
  npm run dev -- --host "$HOST" --port "$FRONTEND_PORT"
) &
FRONTEND_PID=$!

echo "[ready] backend pid=$BACKEND_PID, frontend pid=$FRONTEND_PID"
echo "Press Ctrl+C to stop both."

wait "$BACKEND_PID" "$FRONTEND_PID"
