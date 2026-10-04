#!/usr/bin/env bash
# Copy a published image from one repository to another by digest, and prove the
# digest survived.
#
# This is the whole of ADR 0006's deploy rule: build once, test that artifact,
# then promote *it* rather than rebuilding. A rebuild for production would run
# something that was never tested, which is the audit weakness the rule exists
# to remove — and the reason the destination digest is read back and compared
# rather than assumed.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

SOURCE="${1:?usage: promote.sh SOURCE@sha256:... DESTINATION:tag}"
DEST="${2:?usage: promote.sh SOURCE@sha256:... DESTINATION:tag}"

require_cmd skopeo

case "$SOURCE" in
    *@sha256:*) ;;
    *) die "the source must be digest-pinned (…@sha256:…), not a tag: $SOURCE" ;;
esac

source_digest="${SOURCE##*@}"

log "promoting $source_digest to $DEST"
skopeo copy --all "docker://$SOURCE" "docker://$DEST"

landed="$(skopeo inspect --format '{{.Digest}}' "docker://$DEST")"
if [[ "$landed" != "$source_digest" ]]; then
    die "the digest changed in promotion: $source_digest became $landed. \
Something rebuilt or re-compressed the image; what would run is not what was tested."
fi

log "promoted unchanged: $landed"
printf '%s\n' "$landed"
