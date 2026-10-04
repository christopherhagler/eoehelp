#!/usr/bin/env bash
# Push a locally built image to a registry and print the digest it landed under.
#
# The digest is the point. Everything downstream — promotion, the task
# definition, a rollback — references the image by `@sha256:`, never by a tag,
# because a tag can be moved under a running service and a digest cannot.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

IMAGE="${1:?usage: publish.sh LOCAL_IMAGE DESTINATION}"
DEST="${2:?usage: publish.sh LOCAL_IMAGE DESTINATION}"

require_cmd skopeo

log "pushing $IMAGE to $DEST"
# --all: copy every manifest in the list. Single-architecture today, but a
# manifest list that is silently flattened is the kind of difference that only
# shows up on the machine that cannot run the image.
skopeo copy --all "containers-storage:$IMAGE" "docker://$DEST"

digest="$(skopeo inspect --format '{{.Digest}}' "docker://$DEST")"
[[ -n "$digest" ]] || die "could not read back a digest for $DEST"
log "published $DEST"
printf '%s\n' "$digest"
