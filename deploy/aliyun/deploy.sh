#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/newquant}"

cd "$APP_DIR"

if [[ ! -f .env.deploy ]]; then
  echo "[deploy] missing $APP_DIR/.env.deploy"
  exit 1
fi

set -a
source .env.deploy
set +a

: "${ACR_REGISTRY:?set ACR_REGISTRY in .env.deploy}"
: "${ACR_USERNAME:?set ACR_USERNAME in .env.deploy}"
: "${ACR_PASSWORD:?set ACR_PASSWORD in .env.deploy}"
: "${IMAGE_REGISTRY:?set IMAGE_REGISTRY in .env.deploy}"

echo "$ACR_PASSWORD" | docker login "$ACR_REGISTRY" -u "$ACR_USERNAME" --password-stdin

docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker image prune -f

docker compose -f docker-compose.prod.yml ps
