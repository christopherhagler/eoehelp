#!/usr/bin/env bash
# Regenerate the Angular types from the committed OpenAPI contract, or check.
#
# Run with npx rather than added to package.json: openapi-typescript 7 declares a
# peer dependency on typescript ^5, and this project is on 6. It is a codegen
# tool that never participates in the app build, so pinning it here keeps an
# unsatisfiable peer constraint out of the lock file.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

TYPES="apps/web/src/app/api-client/schema.d.ts"

generate() {
    local out="$1"
    # --userns=keep-id keeps the generated file owned by the caller, and podman
    # rejects the flag outside rootless mode — which is how a CI runner running
    # as root executes this.
    local userns=()
    if [[ "$(podman info --format '{{.Host.Security.Rootless}}' 2>/dev/null)" == "true" ]]; then
        userns=(--userns=keep-id)
    fi
    podman run --rm -v "$REPO_ROOT:/repo" -w /repo/apps/web "${userns[@]}" \
        -e HOME=/tmp -e npm_config_cache=/tmp/.npm node:24-bookworm-slim \
        npx -y openapi-typescript@7.13.0 ../../packages/openapi/schema.json -o "$out"
}

if [[ "${1:-}" == "--check" ]]; then
    # Removed however this exits: generate reaches the npm registry on every
    # run, and a failure there would otherwise strand a partial file in src/.
    trap 'rm -f "$REPO_ROOT/${TYPES}.check"' EXIT
    generate "src/app/api-client/schema.d.ts.check"
    if ! diff -q "$REPO_ROOT/$TYPES" "$REPO_ROOT/${TYPES}.check" >/dev/null; then
        die "$TYPES is out of date. Run: just api-types"
    fi
    log "the web types are current"
else
    generate "src/app/api-client/schema.d.ts"
    log "wrote $TYPES"
fi
