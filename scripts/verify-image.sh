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

    # A runtime image with test tooling in it is a runtime image built from the
    # wrong stage. The test and dev stages carry a label saying so, and are
    # skipped. Identified by label rather than by tag, because a content tag
    # carries no target name — and the case this catches is exactly
    # the one where the wrong image sits behind the right tag.
    is_test="$(podman image inspect --format '{{index .Labels "org.eoehelp.stage"}}' "$image" 2>/dev/null || true)"
    case "$is_test" in
        test|dev) ;;
        *)
            check "no test tooling" podman run --rm "$image" \
                sh -c '! command -v pytest && ! command -v ruff && ! command -v mypy'
            check "no tests directory" podman run --rm "$image" sh -c '! test -e /app/tests'
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
