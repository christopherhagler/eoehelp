#!/usr/bin/env bash
# Apply the database bootstrap that the postgres image runs from
# /docker-entrypoint-initdb.d on first start.
#
# One definition, used by compose (through the mount) and by CI (through this
# script). CI previously carried its own heredoc copy, which had already
# drifted: it created the app_runtime role and nothing else, so CI never applied
# GRANT CONNECT, the schema grant, or the three ALTER ROLE timeout settings that
# the local database has had since they were added.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

HOST="${1:-localhost}"
PORT="${2:-5432}"
INIT_SQL="$REPO_ROOT/infra/postgres/init/01-extensions.sql"

require_cmd psql "Install the postgresql client, or run this through the stack."
[[ -f "$INIT_SQL" ]] || die "missing $INIT_SQL"

log "applying $(basename "$INIT_SQL") to $HOST:$PORT"
PGPASSWORD="${PGPASSWORD:-eoehelp}" psql \
    -h "$HOST" -p "$PORT" -U "${PGUSER:-eoehelp}" -d "${PGDATABASE:-eoehelp}" \
    -v ON_ERROR_STOP=1 -f "$INIT_SQL"
