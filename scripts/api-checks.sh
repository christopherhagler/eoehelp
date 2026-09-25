#!/usr/bin/env bash
# The API checks, exactly as CI runs them. One definition, called by `just` and
# by CI, so "green locally" and "green in CI" are the same claim.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

# Overridable so CI can call this script rather than re-implementing it, which
# is the whole point of the scripts layer: CI runs against a `services:`
# Postgres on localhost with host networking, not against the compose stack.
TEST_NETWORK="${TEST_NETWORK:-eoehelp_default}"
TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql+asyncpg://eoehelp:eoehelp@postgres:5432/eoehelp}"

# Through build-images.sh, so there is one answer to "where does an image come
# from" and the content tag decides whether a rebuild is needed. Previously this
# ran its own `podman build` on every lint, type-check and test: always correct,
# because it always rebuilt, but it paid for a rebuild nothing needed.
test_image() {
    "$REPO_ROOT/scripts/build-images.sh" test | sed -n 's/^API_TEST_IMAGE=//p'
}

case "${1:-}" in
    lint)
        # Both halves, and the whole tree rather than src/ alone: CI runs
        # `ruff check . && ruff format --check .`, and a narrower local command
        # means alembic/ and formatting drift only ever fail on the remote.
        podman run --rm "$(test_image)" sh -c "ruff check . && ruff format --check ."
        ;;
    format)
        podman run --rm -v "$REPO_ROOT/apps/api:/src:z" "$(test_image)" \
            sh -c "ruff check --fix --exit-zero --quiet /src && ruff format /src && ruff check /src"
        ;;
    typecheck)
        podman run --rm "$(test_image)" mypy src
        ;;
    migrations)
        # Both directions on every change: a health-data migration that cannot
        # be reversed turns a bad deploy into permanent data loss.
        podman run --rm --network "$TEST_NETWORK" \
            -e DATABASE_URL="$TEST_DATABASE_URL" -e ENVIRONMENT=local \
            "$(test_image)" sh -c "alembic upgrade head && alembic downgrade base && alembic upgrade head"
        ;;
    test)
        shift
        image="$(test_image)"
        # The compose stack is the local prerequisite; on a runner there is no
        # such container and the database is reached another way.
        if [[ "$TEST_NETWORK" == "eoehelp_default" ]]; then
            require_stack
        fi
        podman run --rm --network "$TEST_NETWORK" \
            -e DATABASE_URL="$TEST_DATABASE_URL" \
            -e ENVIRONMENT=local \
            "$image" pytest -q "$@"
        ;;
    *)
        die "usage: api-checks.sh lint|format|typecheck|migrations|test [pytest args]"
        ;;
esac
