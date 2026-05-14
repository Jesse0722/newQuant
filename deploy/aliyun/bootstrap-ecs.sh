#!/usr/bin/env bash
set -euo pipefail

: "${ECS_HOST:?set ECS_HOST}"
: "${IMAGE_REGISTRY:?set IMAGE_REGISTRY}"
: "${ACR_REGISTRY:?set ACR_REGISTRY}"
: "${ACR_USERNAME:?set ACR_USERNAME}"

ECS_USER="${ECS_USER:-root}"
APP_DIR="${APP_DIR:-/opt/newquant}"
HTTP_PORT="${HTTP_PORT:-80}"

if [[ -z "${ACR_PASSWORD:-}" ]]; then
  read -r -s -p "ACR password: " ACR_PASSWORD
  echo
fi

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

cp docker-compose.prod.yml "$tmp_dir/docker-compose.prod.yml"
cp deploy/aliyun/deploy.sh "$tmp_dir/deploy.sh"
cp deploy/aliyun/backend.env.example "$tmp_dir/backend.env"

cat > "$tmp_dir/.env.deploy" <<EOF
ACR_REGISTRY=$ACR_REGISTRY
ACR_USERNAME=$ACR_USERNAME
ACR_PASSWORD=$ACR_PASSWORD
IMAGE_REGISTRY=$IMAGE_REGISTRY
HTTP_PORT=$HTTP_PORT
EOF

ssh "$ECS_USER@$ECS_HOST" "mkdir -p '$APP_DIR/data'"
scp "$tmp_dir/docker-compose.prod.yml" "$tmp_dir/deploy.sh" "$tmp_dir/backend.env" "$tmp_dir/.env.deploy" "$ECS_USER@$ECS_HOST:$APP_DIR/"
ssh "$ECS_USER@$ECS_HOST" "chmod +x '$APP_DIR/deploy.sh' && ls -la '$APP_DIR'"
