#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/newquant}"
REPO_DIR="${REPO_DIR:-$APP_DIR/source}"
REPO_URL="${REPO_URL:-https://github.com/Jesse0722/newQuant.git}"
BRANCH="${BRANCH:-master}"
HTTP_PORT="${HTTP_PORT:-80}"
export HTTP_PORT

mkdir -p "$APP_DIR/releases" "$APP_DIR/data" "$APP_DIR/locks"
# Prevent overlapping deploys; never reset/clean an existing working checkout.
exec 9>"$APP_DIR/locks/deploy.lock"
flock -n 9 || { echo "Another deployment is running" >&2; exit 1; }
if [[ ! -d "$REPO_DIR/.git" ]]; then
  git clone --no-checkout "$REPO_URL" "$REPO_DIR"
fi
git -C "$REPO_DIR" fetch origin "$BRANCH"
revision="${DEPLOY_REVISION:-$(git -C "$REPO_DIR" rev-parse "origin/$BRANCH")}"
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid deployment revision" >&2; exit 1; }
git -C "$REPO_DIR" cat-file -e "$revision^{commit}"
git -C "$REPO_DIR" merge-base --is-ancestor "$revision" "origin/$BRANCH"
release_dir=$(mktemp -d "$APP_DIR/releases/${revision:0:12}.XXXXXX")
git -C "$REPO_DIR" archive "$revision" | tar -x -C "$release_dir"
cp "$APP_DIR/backend.env" "$release_dir/backend.env"
chmod 600 "$release_dir/backend.env"
ln -s "$APP_DIR/data" "$release_dir/data"
compose=(docker compose -p newquant -f "$release_dir/docker-compose.ecs.yml")
previous_backend=$(docker image inspect newquant-backend:latest --format '{{.Id}}' 2>/dev/null || true)
previous_frontend=$(docker image inspect newquant-frontend:latest --format '{{.Id}}' 2>/dev/null || true)
previous_scheduler=$(docker ps -q --filter label=com.docker.compose.project=newquant --filter label=com.docker.compose.service=scheduler)
for service in backend frontend; do
  container=$(docker ps -q --filter label=com.docker.compose.project=newquant --filter "label=com.docker.compose.service=$service")
  if [[ -n "$container" ]]; then
    running_image=$(docker inspect "$container" --format '{{.Image}}')
    if [[ "$service" == backend ]]; then previous_backend=$running_image; else previous_frontend=$running_image; fi
  fi
done
rollback_tag="rollback-${revision:0:12}-$(date +%s)"
if [[ -n "$previous_backend" ]]; then docker tag "$previous_backend" "newquant-backend:$rollback_tag"; fi
if [[ -n "$previous_frontend" ]]; then docker tag "$previous_frontend" "newquant-frontend:$rollback_tag"; fi

# Build before the maintenance window; build failure leaves services alone.
"${compose[@]}" build backend frontend
manifest=""
rollback() {
  status=${1:-$?}
  trap - ERR INT TERM HUP
  echo "Deployment failed; restoring database and previous images" >&2
  if ! "${compose[@]}" stop scheduler backend; then
    echo "Could not stop database writers; refusing automatic restore. Manual recovery required." >&2
    exit 1
  fi
  if [[ -n "$manifest" ]]; then
    if ! "${compose[@]}" run --rm -T --no-deps backend python scripts/deployment_database.py restore --manifest "$manifest"; then
      echo "Database restore failed; services remain stopped. Manual recovery required." >&2
      exit 1
    fi
  fi
  if [[ -n "$previous_backend" && -n "$previous_frontend" ]]; then
    docker tag "newquant-backend:$rollback_tag" newquant-backend:latest
    docker tag "newquant-frontend:$rollback_tag" newquant-frontend:latest
    cat > "$release_dir/rollback.yml" <<'YAML'
services:
  backend:
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/api/health"]
YAML
    rollback_compose=("${compose[@]}" -f "$release_dir/rollback.yml")
    if ! "${rollback_compose[@]}" up -d --no-build --wait backend frontend; then
      echo "Old images did not become healthy; manual recovery required." >&2
      exit 1
    fi
    if ! curl --fail --silent --show-error "http://127.0.0.1:$HTTP_PORT/api/pools" >/dev/null; then
      echo "Restored application failed business smoke; manual recovery required." >&2
      exit 1
    fi
    if [[ -n "$previous_scheduler" ]]; then "${rollback_compose[@]}" up -d --no-build scheduler; fi
  else
    echo "No previous images available; services remain stopped." >&2
  fi
  exit "$status"
}
trap rollback ERR
trap 'rollback 130' INT
trap 'rollback 143' TERM
trap 'rollback 129' HUP
"${compose[@]}" stop scheduler backend
manifest=$("${compose[@]}" run --rm -T --no-deps backend python scripts/deployment_database.py backup --directory /app/backend/data/deployment-backups)
"${compose[@]}" run --rm -T --no-deps backend python scripts/adopt_legacy_schema.py
"${compose[@]}" run --rm -T --no-deps backend python -m alembic -c /app/alembic.ini upgrade head
"${compose[@]}" run --rm -T --no-deps backend python scripts/deployment_database.py check
"${compose[@]}" up -d --no-build --wait backend frontend
curl --fail --silent --show-error "http://127.0.0.1:$HTTP_PORT/api/ready"
curl --fail --silent --show-error "http://127.0.0.1:$HTTP_PORT/api/messages/daily?ensure_seed=false" >/dev/null
"${compose[@]}" up -d --no-build scheduler
trap - ERR INT TERM HUP
ln -sfn "$release_dir" "$APP_DIR/current-release"
printf '%s\n' "$revision" > "$APP_DIR/deployed-revision"
"${compose[@]}" ps
# Retain rollback images/backups until an explicit retention job removes them.
