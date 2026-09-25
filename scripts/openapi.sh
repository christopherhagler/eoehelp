#!/usr/bin/env bash
# Regenerate the committed OpenAPI contract, or check it is current.
#
# Written to a temporary file first: a failed export must not leave an empty
# contract behind for the next command to generate types from.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

CONTRACT="$REPO_ROOT/packages/openapi/schema.json"

EXPORT='import json, os; os.environ.setdefault("ENVIRONMENT", "local");
from eoehelp_api.main import create_app;
print(json.dumps(create_app().openapi(), indent=2, sort_keys=True))'

# Exporting the schema needs the application importable and nothing else: no
# database, no Redis, no running stack. Preferring the image means this works in
# CI, where there is no compose project, and locally with the stack down.
export_schema() {
    local image
    image="$(
        "$REPO_ROOT/scripts/build-images.sh" dev | sed -n 's/^API_DEV_IMAGE=//p'
    )"
    [[ -n "$image" ]] || die "build-images.sh did not report a dev image"
    podman run --rm \
        -v "$REPO_ROOT/apps/api/src:/app/src:ro,z" \
        -e ENVIRONMENT=local "$image" python -c "$EXPORT"
}

if [[ "${1:-}" == "--check" ]]; then
    tmp="$(mktemp)"
    trap 'rm -f "$tmp"' EXIT
    export_schema > "$tmp"
    if ! diff -q "$CONTRACT" "$tmp" >/dev/null; then
        diff -u "$CONTRACT" "$tmp" || true
        die "packages/openapi/schema.json is out of date. Run: just openapi"
    fi
    log "the OpenAPI contract is current"
else
    export_schema > "$CONTRACT.tmp"
    mv "$CONTRACT.tmp" "$CONTRACT"
    log "wrote packages/openapi/schema.json"
fi
