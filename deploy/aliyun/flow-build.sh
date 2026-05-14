#!/usr/bin/env bash
set -euo pipefail

: "${ACR_REGISTRY:?set ACR_REGISTRY}"
: "${ACR_USERNAME:?set ACR_USERNAME}"
: "${ACR_PASSWORD:?set ACR_PASSWORD}"
: "${IMAGE_REGISTRY:?set IMAGE_REGISTRY}"

COMMIT_ID="${COMMIT_ID:-$(git rev-parse --short HEAD)}"

echo "$ACR_PASSWORD" | docker login "$ACR_REGISTRY" -u "$ACR_USERNAME" --password-stdin

docker build -f backend/Dockerfile \
  -t "$IMAGE_REGISTRY:backend-latest" \
  -t "$IMAGE_REGISTRY:backend-$COMMIT_ID" \
  .

docker build -f frontend/Dockerfile \
  -t "$IMAGE_REGISTRY:frontend-latest" \
  -t "$IMAGE_REGISTRY:frontend-$COMMIT_ID" \
  .

docker push "$IMAGE_REGISTRY:backend-latest"
docker push "$IMAGE_REGISTRY:backend-$COMMIT_ID"
docker push "$IMAGE_REGISTRY:frontend-latest"
docker push "$IMAGE_REGISTRY:frontend-$COMMIT_ID"
