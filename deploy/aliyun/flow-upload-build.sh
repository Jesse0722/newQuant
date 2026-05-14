#!/usr/bin/env bash
set -euo pipefail

: "${ECS_HOST:?set ECS_HOST}"

ECS_USER="${ECS_USER:-root}"
APP_DIR="${APP_DIR:-/opt/newquant}"
HTTP_PORT="${HTTP_PORT:-80}"
COMMIT_ID="${COMMIT_ID:-$(git rev-parse --short HEAD)}"
ARCHIVE="/tmp/newquant-${COMMIT_ID}.tgz"
REMOTE_ARCHIVE="/tmp/newquant-${COMMIT_ID}.tgz"

tar \
  --exclude='.git' \
  --exclude='backend/venv' \
  --exclude='backend/data' \
  --exclude='frontend/node_modules' \
  --exclude='frontend/dist' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache' \
  -czf "$ARCHIVE" .

ssh "$ECS_USER@$ECS_HOST" "mkdir -p '$APP_DIR/releases/$COMMIT_ID' '$APP_DIR/data'"
scp "$ARCHIVE" "$ECS_USER@$ECS_HOST:$REMOTE_ARCHIVE"

ssh "$ECS_USER@$ECS_HOST" "
set -euo pipefail
rm -rf '$APP_DIR/releases/$COMMIT_ID'
mkdir -p '$APP_DIR/releases/$COMMIT_ID'
tar -xzf '$REMOTE_ARCHIVE' -C '$APP_DIR/releases/$COMMIT_ID'
rm -f '$REMOTE_ARCHIVE'
cp '$APP_DIR/backend.env' '$APP_DIR/releases/$COMMIT_ID/backend.env'
ln -sfn '$APP_DIR/data' '$APP_DIR/releases/$COMMIT_ID/data'
ln -sfn '$APP_DIR/releases/$COMMIT_ID' '$APP_DIR/current'
cd '$APP_DIR/current'
HTTP_PORT='$HTTP_PORT' docker compose -f docker-compose.ecs.yml up -d --build
docker image prune -f
docker compose -f docker-compose.ecs.yml ps
"

rm -f "$ARCHIVE"
