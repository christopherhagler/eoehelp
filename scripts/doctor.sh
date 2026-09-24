#!/usr/bin/env bash
# The things that actually go wrong here, checked in the order they bite.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

PINNED_JUST=1.58.0
# The image store is allowed to be large; what matters is how much of it is
# dead weight, because the VM disk filling surfaces as a confusing build error
# rather than as "out of space".
RECLAIMABLE_WARN_PERCENT=50
DISK_WARN_PERCENT=80

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
hint() { printf '  \033[2m·\033[0m \033[2m%s\033[0m\n' "$*"; }

echo "eoehelp doctor"

if podman info >/dev/null 2>&1; then
    ok "podman is reachable"
else
    warn "podman is not reachable — run: podman machine start"
    exit 1
fi

# The compose provider is a separate binary that podman shells out to; its
# absence is a plausible fresh-machine failure and an opaque one.
if podman compose version >/dev/null 2>&1; then
    ok "compose provider found"
else
    warn "no compose provider — podman compose needs docker-compose or podman-compose installed"
fi

# VM free space, which is the quantity that actually runs out. Reported rather
# than inferred from the image store's size.
# podman machine only exists where podman runs in a VM; on a Linux host the
# store is on the host filesystem, so fall back rather than silently skipping.
if disk="$(podman machine ssh 'df -h / | tail -1' 2>/dev/null)" \
    || disk="$(df -h / 2>/dev/null | tail -1)"; then
    used_percent="$(awk '{gsub(/%/, "", $5); print $5}' <<<"$disk")"
    summary="VM disk $(awk '{print $3 " used of " $2 " (" $5 ")"}' <<<"$disk")"
    if [[ -n "$used_percent" && "$used_percent" -ge "$DISK_WARN_PERCENT" ]]; then
        warn "$summary — reclaim with: just prune all"
    else
        ok "$summary"
    fi
fi

# A df failure is itself a finding — a corrupted image in the store reports
# here — so it is never swallowed.
# stderr captured separately: merged into stdout it becomes an extra line for
# the parser below and prints as a garbled pass.
df_errors="$(mktemp)"
trap 'rm -f "$df_errors"' EXIT
if df_output="$(podman system df --format '{{.Type}} {{.Size}} {{.Reclaimable}}' 2>"$df_errors")"; then
    while read -r line_raw; do
        [[ -z "$line_raw" ]] && continue
        # "Local Volumes" has a space in it, so read the fields from the end:
        # the last two are size and reclaimable, and everything before is type.
        reclaimable="$(awk '{print $(NF-1) " " $NF}' <<<"$line_raw")"
        size="$(awk '{print $(NF-2)}' <<<"$line_raw")"
        type="$(awk '{for (i = 1; i <= NF - 3; i++) printf "%s%s", $i, (i < NF - 3 ? " " : "")}' <<<"$line_raw")"
        percent="$(sed -n 's/.*(\([0-9]*\)%).*/\1/p' <<<"$reclaimable")"
        line="$type: $size total, $reclaimable reclaimable"
        if [[ "$type" == "Images" && -n "$percent" && "$percent" -ge "$RECLAIMABLE_WARN_PERCENT" ]]; then
            warn "$line — reclaim with: just prune all"
        elif [[ "$type" == "Local Volumes" ]]; then
            # Reclaimable, and deliberately never reclaimed: one of them holds
            # the development database.
            ok "$line (volumes are never pruned here — one of them is your database)"
        else
            ok "$line"
        fi
    done <<<"$df_output"
else
    warn "podman system df failed: $(cat "$df_errors")"
fi

# compose has no build: keys — it runs what build-images.sh produced — so a
# missing image is a confusing "no such image" rather than a rebuild.
for image in localhost/eoehelp-api:dev localhost/eoehelp-web:deps; do
    if podman image exists "$image"; then
        ok "$image present"
    else
        warn "$image missing — run: just build dev web-deps"
    fi
done

for name in eoehelp-postgres-1 eoehelp-api-1 eoehelp-web-1; do
    if container_running "$name"; then
        ok "$name is up"
    else
        warn "$name is not running — run: just up"
    fi
done

if command -v just >/dev/null 2>&1; then
    version="$(just --version | awk '{print $2}')"
    if [[ "$version" == "$PINNED_JUST" ]]; then
        ok "just $version"
    else
        # A pin nobody checks is a comment. Differences here are usually
        # harmless; being told is the point.
        warn "just $version, but this project pins $PINNED_JUST"
    fi
else
    warn "just is not installed — brew install just"
fi

if command -v skopeo >/dev/null 2>&1; then
    ok "skopeo present"
else
    warn "skopeo not installed (needed for verify-promote)"
fi

# Traps that have each cost an afternoon. Hints, not warnings: nothing is wrong
# right now, and a doctor that always prints warnings trains you to ignore it.
echo
hint "API serving stale code? its reload watcher missed an edit: podman restart eoehelp-api-1"
hint "web app bouncing to the landing page? Vite's cache is stale: podman restart eoehelp-web-1"
hint "never run two test suites at once: each drops and recreates its own database"
