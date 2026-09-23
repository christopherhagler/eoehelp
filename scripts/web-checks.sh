#!/usr/bin/env bash
# The web checks, exactly as CI runs them.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

web_node() {
    podman run --rm -v "$REPO_ROOT/apps/web:/app:z" \
        -v eoehelp_web_node_modules:/app/node_modules -w /app node:24-bookworm-slim "$@"
}

case "${1:-}" in
    check)
        web_node sh -c "npm ci --silent && npm run -s format:check \
            && npx ng test --watch=false && npx ng build --configuration production"
        ;;
    test)
        web_node sh -c "npm ci --silent && npx ng test --watch=false"
        ;;
    format)
        web_node sh -c "npm ci --silent && npm run -s format"
        ;;
    build)
        web_node sh -c "npm ci --silent && npx ng build --configuration production"
        ;;
    *)
        die "usage: web-checks.sh check|test|format|build"
        ;;
esac
