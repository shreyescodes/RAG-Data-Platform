#!/usr/bin/env bash
# Deploy one image version, and roll back by itself if it does not come up healthy.
#   ./deploy/deploy.sh sha-1a2b3c4      # deploy (CI calls this)
#   ./deploy/deploy.sh rollback         # go back to the previous version
#
# Images are pulled from GHCR; IMAGE_TAG is recorded in .deploy.env, and the
# version before it in .deploy.env.previous.
set -euo pipefail
cd "$(dirname "$0")/.."

HEALTH_TIMEOUT_SECONDS=${HEALTH_TIMEOUT_SECONDS:-300}
compose=(./deploy/compose.sh)

current_tag() { sed -n 's/^IMAGE_TAG=//p' "$1" 2>/dev/null || true; }

target=${1:?usage: deploy.sh <image-tag>|rollback}
previous=$(current_tag .deploy.env)
if [ "$target" = rollback ]; then
    target=$(current_tag .deploy.env.previous)
    [ -n "$target" ] || { echo "No previous version recorded." >&2; exit 1; }
fi

# Wait until every service with a healthcheck reports healthy.
wait_healthy() {
    local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS)) service id status
    for service in db backend frontend; do
        while :; do
            id=$("${compose[@]}" ps -q "$service")
            status=$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || echo missing)
            [ "$status" = healthy ] && break
            if [ "$SECONDS" -ge "$deadline" ]; then
                echo "$service is '$status' after ${HEALTH_TIMEOUT_SECONDS}s" >&2
                "${compose[@]}" logs --tail 50 "$service" >&2 || true
                return 1
            fi
            sleep 5
        done
        echo "$service: healthy"
    done
}

switch_to() {
    echo "IMAGE_TAG=$1" > .deploy.env
    "${compose[@]}" pull --quiet backend frontend
    "${compose[@]}" up -d --remove-orphans
    # Pick up Caddyfile edits (a bind-mounted file does not recreate the container).
    "${compose[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1 || true
}

echo "Deploying $target (was: ${previous:-nothing})"
switch_to "$target"

if wait_healthy; then
    [ -n "$previous" ] && [ "$previous" != "$target" ] && echo "IMAGE_TAG=$previous" > .deploy.env.previous
    # Drop unused images older than a week; any version can be pulled again.
    docker image prune -af --filter "until=168h" >/dev/null || true
    echo "Deployed $target"
    exit 0
fi

if [ -n "$previous" ] && [ "$previous" != "$target" ]; then
    echo "Rolling back to $previous" >&2
    switch_to "$previous"
    wait_healthy || echo "Rollback is not healthy either; check the logs." >&2
fi
exit 1
