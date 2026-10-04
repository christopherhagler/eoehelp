#!/usr/bin/env bash
# Bring the production-shaped stack up or down.
#
# Separate from `just up-prod` so CI can use it without `just` needing to know
# about the images: it builds what ships, exports the refs compose reads, and
# waits for the edge to answer.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

COMPOSE_PROD=("podman" "compose" "--env-file" "$REPO_ROOT/infra/images.env" \
    "-f" "$REPO_ROOT/compose.prod.yaml")
EDGE_URL="${EDGE_URL:-http://localhost:8080}"

case "${1:-}" in
    up)
        [[ -f "$REPO_ROOT/infra/local-prod.env" ]] \
            || die "infra/local-prod.env is missing. Generate one: just secrets"

        # The images that ship, not the development ones.
        eval "$("$REPO_ROOT/scripts/build-images.sh" runtime web-runtime)"
        export API_RUNTIME_IMAGE WEB_RUNTIME_IMAGE

        "${COMPOSE_PROD[@]}" up -d \
            || { "${COMPOSE_PROD[@]}" logs migrate; exit 1; }

        # Both halves of the edge, not just one: /healthz is served by the web
        # container, so waiting on it alone reported ready while uvicorn was
        # still starting and the first API request through the edge got a 502.
        log "waiting for the edge at $EDGE_URL"
        for _ in $(seq 1 60); do
            if curl -fsS "$EDGE_URL/healthz" >/dev/null 2>&1 \
                && curl -fsS "$EDGE_URL/api/v1/legal/documents" >/dev/null 2>&1; then
                log "the production-shaped stack is up: $EDGE_URL"
                exit 0
            fi
            sleep 2
        done
        "${COMPOSE_PROD[@]}" ps
        die "the edge did not answer within 120s"
        ;;
    logs)
        eval "$("$REPO_ROOT/scripts/build-images.sh" runtime web-runtime)" 2>/dev/null || true
        export API_RUNTIME_IMAGE WEB_RUNTIME_IMAGE
        "${COMPOSE_PROD[@]}" logs --tail 80 api edge migrate web || true
        ;;
    down)
        # Images are exported so compose can resolve the references it needs to
        # identify the containers, even on the way down.
        eval "$("$REPO_ROOT/scripts/build-images.sh" runtime web-runtime)" 2>/dev/null || true
        export API_RUNTIME_IMAGE WEB_RUNTIME_IMAGE
        "${COMPOSE_PROD[@]}" down -v
        ;;
    *)
        die "usage: prod-stack.sh up|down|logs"
        ;;
esac
