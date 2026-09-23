#!/usr/bin/env bash
# The API checks, exactly as CI runs them. One definition, called by `just` and
# by CI, so "green locally" and "green in CI" are the same claim.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

TEST_IMAGE=eoehelp-api-test

# Overridable so CI can call this script rather than re-implementing it, which
# is the whole point of the scripts layer: CI runs against a `services:`
# Postgres on localhost with host networking, not against the compose stack.
TEST_NETWORK="${TEST_NETWORK:-eoehelp_default}"
TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql+asyncpg://eoehelp:eoehelp@postgres:5432/eoehelp}"

build_test_image() {
    podman build -q -t "$TEST_IMAGE" --target test "$REPO_ROOT/apps/api" >/dev/null
}

case "${1:-}" in
    lint)
        # Both halves, and the whole tree rather than src/ alone: CI runs
        # `ruff check . && ruff format --check .`, and a narrower local command
        # means alembic/ and formatting drift only ever fail on the remote.
        build_test_image
        podman run --rm "$TEST_IMAGE" sh -c "ruff check . && ruff format --check ."
        ;;
    format)
        build_test_image
        podman run --rm -v "$REPO_ROOT/apps/api:/src:z" "$TEST_IMAGE" \
            sh -c "ruff check --fix --exit-zero --quiet /src && ruff format /src && ruff check /src"
        ;;
    typecheck)
        build_test_image
        podman run --rm "$TEST_IMAGE" mypy src
        ;;
    test)
        shift
        build_test_image
        # The compose stack is the local prerequisite; on a runner there is no
        # such container and the database is reached another way.
        if [[ "$TEST_NETWORK" == "eoehelp_default" ]]; then
            require_stack
        fi
        podman run --rm --network "$TEST_NETWORK" \
            -e DATABASE_URL="$TEST_DATABASE_URL" \
            -e ENVIRONMENT=local \
            "$TEST_IMAGE" pytest -q "$@"
        ;;
    *)
        die "usage: api-checks.sh lint|format|typecheck|test [pytest args]"
        ;;
esac
