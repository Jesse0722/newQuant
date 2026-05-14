#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/newquant}"
REPO_DIR="${REPO_DIR:-$APP_DIR/current}"
REPO_URL="${REPO_URL:-https://github.com/Jesse0722/newQuant.git}"
BRANCH="${BRANCH:-master}"

mkdir -p "$APP_DIR"

if [[ ! -d "$REPO_DIR/.git" ]]; then
  rm -rf "$REPO_DIR"
  git clone --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
fi

cd "$REPO_DIR"

git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"
git clean -fdx

cp "$APP_DIR/backend.env" "$REPO_DIR/backend.env"
mkdir -p "$APP_DIR/data"
ln -sfn "$APP_DIR/data" "$REPO_DIR/data"

HTTP_PORT="${HTTP_PORT:-80}" docker compose -f docker-compose.ecs.yml up -d --build
docker image prune -f
docker compose -f docker-compose.ecs.yml ps
