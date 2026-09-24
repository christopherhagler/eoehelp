#!/usr/bin/env bash
# The web checks, exactly as CI runs them.
#
# They run in the `deps` image, which owns node_modules. Previously each call
# did `npm ci` into a named volume — a volume that was populated once and never
# updated, which is how the dev server ended up running against dependencies
# from weeks earlier. The image is rebuilt when package-lock.json or any
# config file it copies changes, and not otherwise.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

# Built every call, not only when missing: `podman image exists` on the moving
# tag is true as soon as anything has ever been built, so a package-lock.json or
# tsconfig change would otherwise keep running the old image and report success.
# It costs 0.2 s when the image is already current.
web_node() {
    local image
    image="$(
        "$REPO_ROOT/scripts/build-images.sh" web-deps | sed -n 's/^WEB_DEPS_IMAGE=//p'
    )"
    [[ -n "$image" ]] || die "build-images.sh did not report a web-deps image"
    podman run --rm \
        -v "$REPO_ROOT/apps/web/src:/build/src:z" \
        -v "$REPO_ROOT/apps/web/public:/build/public:z" \
        -w /build "$image" "$@"
}

case "${1:-}" in
    check)
        web_node sh -c "npm run -s format:check \
            && npx ng test --watch=false && npx ng build --configuration production"
        ;;
    test)
        web_node npx ng test --watch=false
        ;;
    format)
        # Writes back through the mount, so the host tree is what changes.
        web_node npm run -s format
        ;;
    build)
        web_node npx ng build --configuration production
        ;;
    *)
        die "usage: web-checks.sh check|test|format|build"
        ;;
esac
