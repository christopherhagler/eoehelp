#!/usr/bin/env bash
# Build the images, tagged by the content they are built from.
#
# The tag is a digest of everything that determines the image, so an image that
# already exists is never rebuilt and an image built from different inputs can
# never reuse a tag. That removes two failure modes of a moving tag like `:dev`:
# a stale image silently serving old code, and a rebuild nothing needed costing
# 20 s before every check.
#
# Three properties the hash must have, each learned from getting it wrong:
#
#   - Stable across invocations. Nothing derived from the PID, the clock or a
#     temporary path may enter it.
#   - Repo-relative. Two clones in different directories must compute the same
#     tag for the same content, or the tag is useless as a cache key.
#   - Distinct per target. `test` and `runtime` are built from the same source
#     but are not the same image, so the target name is part of the hash.
#     Without it `runtime` finds `test`'s tag present, skips its build, and the
#     shipping artifact becomes the test image.
#
# Source is hashed from the working tree, not the git index: an uncommitted edit
# must move the tag, or the skip serves an image that does not match the files
# on disk.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

NO_CACHE=""
CACHE_FROM=""
CACHE_TO=""
TARGETS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-cache) NO_CACHE="--no-cache" ;;
        --cache-from) shift; CACHE_FROM="$1" ;;
        --cache-to) shift; CACHE_TO="$1" ;;
        dev|test|runtime|web-deps|web-runtime|all) TARGETS+=("$1") ;;
        *) die "usage: build-images.sh [dev|test|runtime|web-deps|web-runtime|all] [--no-cache] [--cache-from REF] [--cache-to REF]" ;;
    esac
    shift
done
[[ ${#TARGETS[@]} -gt 0 ]] || TARGETS=(all)
[[ "${TARGETS[0]}" == "all" ]] && TARGETS=(dev test runtime web-deps web-runtime)

# The checksum tool, chosen once. Not a `cmd-a || cmd-b` fallback: if the first
# emits some output and then fails, the second appends a second listing to the
# same stream, and the whole property being protected is that one input gives
# one tag.
if command -v sha256sum >/dev/null 2>&1; then
    SHA=(sha256sum)
else
    SHA=(shasum -a 256)
fi

# sha256 of the working-tree contents of every file under the given paths,
# tracked or not, excluding what .gitignore excludes. Paths are repo-relative
# because the command runs from the repository root, so two clones in different
# directories compute the same tag.
hash_paths() {
    (
        cd "$REPO_ROOT"
        # --error-unmatch: a path that no longer exists otherwise drops out
        # silently, and the hash quietly stops covering it.
        git ls-files --error-unmatch -- "$@" >/dev/null
        git ls-files -z --cached --others --exclude-standard -- "$@" | xargs -0 "${SHA[@]}"
    )
}

content_tag() {
    local target="$1"; shift
    { printf 'target=%s\n' "$target"; hash_paths "$@"; } | "${SHA[@]}" | cut -c1-12
}

build_one() {
    local name="$1" context="$2" target="$3" tag="$4" var="$5"
    local ref="localhost/${name}:${tag}"
    if podman image exists "$ref"; then
        log "$name:$target up to date ($tag)"
    else
        log "building $name:$target ($tag)"
        # shellcheck disable=SC2086 # the cache flags are intentionally unquoted
        podman build $NO_CACHE \
            ${CACHE_FROM:+--cache-from "$CACHE_FROM"} \
            ${CACHE_TO:+--cache-to "$CACHE_TO"} \
            --format docker --target "$target" -t "$ref" "$context" >/dev/null
    fi
    # A moving tag follows the content tag, so compose and people have a stable
    # name while the content tag is what identifies the build.
    podman tag "$ref" "localhost/${name}:${target}"
    printf '%s=%s\n' "$var" "$ref"
}

# The inputs that decide each image. Source is deliberately absent from `dev`
# and `web-deps`: neither copies it, so a source edit must not move their tag.
API_DEPS=(apps/api/pyproject.toml apps/api/README.md apps/api/Dockerfile)
API_SOURCE=(apps/api/src apps/api/alembic apps/api/alembic.ini)
WEB_DEPS=(
    apps/web/package.json apps/web/package-lock.json apps/web/Dockerfile
    apps/web/angular.json apps/web/tsconfig.json apps/web/tsconfig.app.json
    apps/web/tsconfig.spec.json apps/web/.postcssrc.json apps/web/.prettierrc
    apps/web/.prettierignore
)

for target in "${TARGETS[@]}"; do
    case "$target" in
        dev)
            build_one eoehelp-api apps/api dev \
                "$(content_tag dev "${API_DEPS[@]}")" API_DEV_IMAGE
            ;;
        runtime)
            build_one eoehelp-api apps/api runtime \
                "$(content_tag runtime "${API_DEPS[@]}" "${API_SOURCE[@]}")" API_RUNTIME_IMAGE
            ;;
        test)
            # tests/ is an input here and nowhere else: a new test must rebuild
            # the image that runs the tests.
            build_one eoehelp-api apps/api test \
                "$(content_tag test "${API_DEPS[@]}" "${API_SOURCE[@]}" apps/api/tests)" \
                API_TEST_IMAGE
            ;;
        web-deps)
            build_one eoehelp-web apps/web deps \
                "$(content_tag deps "${WEB_DEPS[@]}")" WEB_DEPS_IMAGE
            ;;
        web-runtime)
            # The builder stage does `COPY . .`, so the input is the whole
            # directory rather than an enumerated subset that can fall behind.
            build_one eoehelp-web apps/web runtime \
                "$(content_tag web-runtime apps/web)" WEB_RUNTIME_IMAGE
            ;;
    esac
done
