#!/usr/bin/env bash
# Regenerate the committed OpenAPI contract, or check it is current.
#
# Written to a temporary file first: a failed export must not leave an empty
# contract behind for the next command to generate types from.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

CONTRACT="$REPO_ROOT/packages/openapi/schema.json"
require_stack

export_schema() {
    compose exec -T api python -c "\
import json; from eoehelp_api.main import create_app; \
print(json.dumps(create_app().openapi(), indent=2, sort_keys=True))"
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
