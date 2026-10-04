#!/usr/bin/env bash
# Assertions about a built image, lifted out of ci.yml so they run locally too.
#
# The last two close the final-stage hazard: apps/api/Dockerfile's `test` stage
# descends from `runtime`, so a build with no --target yields the test image.
# Rather than reorder the file — which would cost the property that the suite
# runs against the image that ships — the invariant is asserted.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

[[ $# -gt 0 ]] || die "usage: verify-image.sh IMAGE [IMAGE...]  (build one first: just build runtime)"

failures=0
check() {
    local label="$1"; shift
    if "$@" >/dev/null 2>&1; then
        printf '  \033[32m✓\033[0m %s\n' "$label"
    else
        printf '  \033[31m✗\033[0m %s\n' "$label"
        failures=$((failures + 1))
    fi
}

for image in "$@"; do
    podman image exists "$image" \
        || die "no such image: $image. Build it first: just build runtime"
    echo "$image"

    # podman rather than skopeo: skopeo reads the host's container storage, and
    # on macOS the images live inside the podman machine's VM, so the same
    # command that works in CI fails locally. podman talks to whichever store is
    # in use, so one script covers both.
    media_type="$(podman image inspect --format '{{.ManifestType}}' "$image")"
    check "Docker v2 manifest ($media_type)" \
        grep -q 'application/vnd.docker.distribution.manifest' <<<"$media_type"

    arch="$(podman image inspect --format '{{.Architecture}}' "$image")"
    check "arm64 ($arch)" grep -q 'arm64' <<<"$arch"

    user="$(podman image inspect --format '{{.Config.User}}' "$image")"
    check "runs unprivileged (user=${user:-root})" test -n "$user"

    # What the image claims to be, asserted rather than inferred. Inferring
    # "this is a runtime image" from the absence of a stage label meant the web
    # image was asked for a Python interpreter, and an image carrying no label
    # at all would pass by being unrecognised.
    stage="$(podman image inspect --format '{{index .Labels "org.eoehelp.stage"}}' "$image" 2>/dev/null || true)"
    component="$(podman image inspect --format '{{index .Labels "org.eoehelp.component"}}' "$image" 2>/dev/null || true)"

    case "$stage" in
        test|dev)
            # Expected to carry test tooling; nothing further to assert.
            ;;
        *)
            [[ -n "$component" && "$component" != "<no value>" ]] \
                || die "$image carries no org.eoehelp.component label. Add one to its runtime stage, or this image ships unasserted."

            check "no test tooling" podman run --rm "$image" \
                sh -c '! command -v pytest && ! command -v ruff && ! command -v mypy'
            check "no tests directory" podman run --rm "$image" sh -c '! test -e /app/tests'

            if [[ "$component" == "api" ]]; then
                # The installed package, not a source tree. The suite runs with
                # PYTHONPATH=/app/src, which precedes site-packages, so every
                # test imports the source and the installed package is never
                # executed by anything — which is how an image whose installed
                # __init__.py was zero bytes passed every check and then failed
                # at startup.
                check "the installed package imports" podman run --rm "$image" \
                    /opt/venv/bin/python -c \
                    'import eoehelp_api; assert eoehelp_api.__version__, "no __version__"'
                check "the installed app builds" podman run --rm "$image" \
                    /opt/venv/bin/python -c 'from eoehelp_api.main import create_app; create_app()'
                # A migration file that was never shipped fails here rather than
                # on the first deploy.
                check "alembic can read its revisions" podman run --rm "$image" \
                    /opt/venv/bin/alembic -c alembic.ini heads
            fi
            ;;
    esac

    # No credential may reach an image layer or a build arg. GPG_KEY is the
    # upstream Python signing key and is public, so it is named rather than
    # matched loosely.
    secrets="$(podman image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$image" \
        | grep -Ei '(SECRET|PASSWORD|_KEY=)' | grep -v '^GPG_KEY=' || true)"
    check "no secrets in the image environment" test -z "$secrets"
done

[[ "$failures" -eq 0 ]] || die "$failures assertion(s) failed"
log "all image assertions passed"
