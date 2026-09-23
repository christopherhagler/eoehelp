# Shared helpers for the scripts the justfile and CI both call.
#
# Sourced, never executed. Every script that sources this sets its own
# `set -euo pipefail` first, so a failure here cannot be swallowed by a caller
# that forgot.

# The repository root, wherever the caller happened to be standing.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_ROOT

log() { printf '\033[36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "$1 is not installed. ${2:-}"
}

# Explicit about the compose file, so a script works from any directory. Every
# other path here is absolute through $REPO_ROOT; this one was the exception,
# and it matters because CI's api job runs with a working directory of
# apps/api — where `podman compose` finds no configuration and reports it in
# terms that never mention this project.
compose() {
    podman compose -f "$REPO_ROOT/compose.yaml" "$@"
}

# sha256 over the given files, lowercase hex, one value for the set. macOS ships
# shasum rather than sha256sum, and CI runs on Linux, so both are handled.
#
# Hashes each file's name and digest rather than the concatenated bytes: the
# concatenation loses the file boundaries and the names, so moving a line
# between two files, or adding an empty one, would not change the result. That
# is the value stage 2 uses to decide whether to rebuild the image the tests
# then run against, so it has to mean "these files, with these contents".
sha256_of() {
    [[ $# -gt 0 ]] || die "sha256_of needs at least one file"
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$@" | sha256sum | cut -d' ' -f1
    else
        shasum -a 256 "$@" | shasum -a 256 | cut -d' ' -f1
    fi
}

# Fails with an instruction rather than a connection error, which is what the
# error actually means nine times out of ten.
#
# Filtered by podman rather than piped into `grep -q`: grep exits at the first
# match and closes the pipe, podman takes SIGPIPE, and under `set -o pipefail`
# the pipeline reports 141 — so this claimed the stack was down about one call
# in five while it was demonstrably up. Never pipe into `grep -q` here.
container_running() {
    [[ -n "$(podman ps --quiet --filter "name=^$1$" 2>/dev/null)" ]]
}

require_stack() {
    container_running eoehelp-postgres-1 \
        || die "the stack is not running. Start it with: just up"
}
