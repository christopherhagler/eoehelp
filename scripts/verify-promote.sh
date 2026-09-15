#!/usr/bin/env bash
#
# Proves the deploy pattern this project depends on: build an image once, then
# promote the *identical digest* between registries instead of rebuilding.
#
# Production must run the exact artifact that was tested. A rebuild for
# production produces a different digest, which means the thing serving patients
# was never the thing that passed the tests — an audit weakness, and the first
# question anyone reviewing the pipeline will ask.
#
# Two throwaway registries stand in for the staging and production ECRs. Nothing
# here needs AWS, so this runs in CI and on a laptop identically.
#
#   ./scripts/verify-promote.sh [image-tag]

set -euo pipefail

IMAGE="${1:-eoehelp-api:ci}"
REPO_NAME="eoehelp-api"
SRC_PORT="${SRC_PORT:-5001}"
DST_PORT="${DST_PORT:-5002}"
SRC_CTR="eoehelp-verify-src"
DST_CTR="eoehelp-verify-dst"

# Pick whatever is present. buildah pushes straight out of container storage;
# podman shares that same storage, so either can supply the image.
if command -v buildah >/dev/null 2>&1; then
  PUSHER="buildah"
elif command -v podman >/dev/null 2>&1; then
  PUSHER="podman"
else
  echo "error: need buildah or podman to push the built image" >&2
  exit 1
fi

# Registries have to actually run, so this step needs a runtime even though the
# build and publish path does not.
if command -v podman >/dev/null 2>&1; then
  RUNTIME="podman"
elif command -v docker >/dev/null 2>&1; then
  RUNTIME="docker"
else
  echo "error: need podman or docker to run the throwaway registries" >&2
  exit 1
fi

if ! command -v skopeo >/dev/null 2>&1; then
  echo "error: skopeo not found." >&2
  echo "  macOS: brew install skopeo" >&2
  echo "  Linux: apt-get install -y skopeo" >&2
  exit 1
fi

cleanup() {
  $RUNTIME rm -f "$SRC_CTR" "$DST_CTR" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> starting throwaway registries (:$SRC_PORT staging, :$DST_PORT production)"
cleanup
$RUNTIME run -d --name "$SRC_CTR" -p "127.0.0.1:${SRC_PORT}:5000" registry:2 >/dev/null
$RUNTIME run -d --name "$DST_CTR" -p "127.0.0.1:${DST_PORT}:5000" registry:2 >/dev/null

for port in "$SRC_PORT" "$DST_PORT"; do
  for _ in $(seq 1 40); do
    if curl -fsS "http://127.0.0.1:${port}/v2/" >/dev/null 2>&1; then break; fi
    sleep 1
  done
  curl -fsS "http://127.0.0.1:${port}/v2/" >/dev/null \
    || { echo "error: registry on :$port never became ready" >&2; exit 1; }
done

SRC="127.0.0.1:${SRC_PORT}/${REPO_NAME}"
DST="127.0.0.1:${DST_PORT}/${REPO_NAME}"

echo "==> pushing $IMAGE to the staging registry with $PUSHER"
$PUSHER push --tls-verify=false "$IMAGE" "docker://${SRC}:candidate"

digest_of() {
  skopeo inspect --tls-verify=false --format '{{.Digest}}' "docker://$1"
}

SRC_DIGEST="$(digest_of "${SRC}:candidate")"
echo "    staging digest: $SRC_DIGEST"

# --all copies the manifest verbatim, which is what preserves the digest. Without
# it, skopeo may re-encode and the digest changes — defeating the whole exercise.
# The source is referenced by digest, not tag, so the promoted artifact is pinned
# rather than whatever the tag happens to point at when the copy runs.
echo "==> promoting by digest to the production registry"
skopeo copy --all \
  --src-tls-verify=false --dest-tls-verify=false \
  "docker://${SRC}@${SRC_DIGEST}" \
  "docker://${DST}:released"

DST_DIGEST="$(digest_of "${DST}:released")"
echo "    production digest: $DST_DIGEST"

if [ "$SRC_DIGEST" != "$DST_DIGEST" ]; then
  echo "::error::promotion changed the digest — production would not be running the tested image"
  echo "  staging:    $SRC_DIGEST"
  echo "  production: $DST_DIGEST"
  exit 1
fi

# The manifest format has to survive promotion too, or ECS gets an image it may
# refuse even though the digest matched.
MEDIA_TYPE="$(skopeo inspect --raw --tls-verify=false "docker://${DST}:released" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["mediaType"])')"
echo "    production media type: $MEDIA_TYPE"

case "$MEDIA_TYPE" in
  application/vnd.docker.distribution.manifest.v2+json) ;;
  *) echo "::error::promoted image is $MEDIA_TYPE, expected a Docker v2 manifest"; exit 1 ;;
esac

echo ""
echo "promotion verified: one build, two registries, identical digest"
echo "  $SRC_DIGEST"
