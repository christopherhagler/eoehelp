#!/usr/bin/env bash
# Drive the production-shaped stack the way a patient would, through the edge.
#
# This is the only check that exercises the path production actually uses: one
# origin, the SPA's `${origin}/api/v1` resolution, the runtime images, real
# secrets, and the API connected as app_runtime with row-level security binding.
# Every other test runs against the development stack, where none of that is
# true.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

EDGE="${1:-http://localhost:8080}"
DIRECT_API="${2:-}"
MAILHOG="${MAILHOG_URL:-http://localhost:8026}"
STAMP="$(date +%s)-$$"
EMAIL="smoke-$STAMP@example.com"
# Unique per run too: MAGIC_LINKS_PER_EMAIL is 3 per 15 minutes, so fixed
# addresses make the fourth run of an afternoon fail for a reason that has
# nothing to do with the change being tested.
SPOOF_EMAIL="smoke-spoof-$STAMP@example.com"
DIRECT_EMAIL="smoke-direct-$STAMP@example.com"

# A token lands in here, so not a predictable name in a shared directory.
ONBOARDED="$(mktemp)"
trap 'rm -f "$ONBOARDED"' EXIT

require_cmd curl
require_cmd python3

step() { printf '\033[36m  →\033[0m %s\n' "$*"; }

# Asked of compose rather than assumed: the container name depends on which
# provider podman shells out to (docker-compose uses dashes, podman-compose
# uses underscores), and a wrong name here reported itself as "no audit row was
# written", which is a lie about what broke. Errors are not swallowed.
audit_ip() {
    local cid
    # compose.prod.yaml requires the image refs, so resolve them the same way
    # prod-stack.sh does rather than assuming the caller exported them.
    eval "$("$REPO_ROOT/scripts/build-images.sh" runtime web-runtime)"
    export API_RUNTIME_IMAGE WEB_RUNTIME_IMAGE
    cid="$(podman compose --env-file "$REPO_ROOT/infra/images.env" \
        -f "$REPO_ROOT/compose.prod.yaml" ps -q postgres 2>/dev/null | head -1)"
    [[ -n "$cid" ]] || fail "could not find the production-shaped postgres container"
    podman exec "$cid" psql -U eoehelp -d eoehelp -qtA \
        -c "SELECT ip_address FROM audit_log WHERE action = 'auth.magic_link.request' ORDER BY id DESC LIMIT 1" \
        | tr -d ' \n'
}
fail() { printf '\033[31m  ✗\033[0m %s\n' "$*"; exit 1; }

api() {
    local method="$1" path="$2" body="${3:-}" token="${4:-}"
    local args=(-sS -X "$method" -H 'Content-Type: application/json')
    [[ -n "$token" ]] && args+=(-H "Authorization: Bearer $token")
    [[ -n "$body" ]] && args+=(-d "$body")
    curl "${args[@]}" "$EDGE/api/v1$path"
}

step "the edge serves the SPA"
curl -fsS "$EDGE/" | grep -q "<app-root" || fail "the SPA did not come back through the edge"

step "the edge routes /api/v1 to the API"
curl -fsS "$EDGE/api/v1/legal/documents" | grep -q "tos-" \
    || fail "the legal documents did not come back through the edge"

step "sign in by magic link"
status="$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
    -H 'Content-Type: application/json' -d "{\"email\":\"$EMAIL\"}" \
    "$EDGE/api/v1/auth/magic-link")"
if [[ "$status" == "429" ]]; then
    fail "rate limited (5 magic-link requests per 15 minutes per address). \
Run 'just down-prod && just up-prod', or wait."
fi
[[ "$status" == "202" ]] || fail "the magic-link request returned $status"
token=""
for _ in $(seq 1 30); do
    body="$(curl -fsS "$MAILHOG/api/v2/search?kind=to&query=$EMAIL" || true)"
    token="$(printf '%s' "$body" \
        | python3 -c 'import json,re,sys
items = json.load(sys.stdin).get("items") or []
for item in items:
    text = item["Content"]["Body"].replace("=\r\n", "").replace("=3D", "=")
    found = re.findall(r"token=([A-Za-z0-9_\-]{20,})", text)
    if found:
        print(found[0]); break' 2>/dev/null || true)"
    [[ -n "$token" ]] && break
    sleep 1
done
[[ -n "$token" ]] || fail "no magic-link email arrived"

access="$(api POST /auth/magic-link/verify "{\"token\":\"$token\"}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
[[ -n "$access" ]] || fail "the magic link did not verify"

step "complete onboarding"
api POST /me/onboarding '{"display_name":"Smoke","birth_year":1990,
    "sex_at_birth":"undisclosed","timezone":"UTC",
    "consents":{"terms_of_service":true,"privacy_policy":true,
    "consumer_health_data":true}}' "$access" > /tmp/onboarded.json
access="$(python3 -c 'import json; print(json.load(open("/tmp/onboarded.json"))["access_token"])')"

step "write a symptom entry and read it back"
today="$(date -u +%Y-%m-%d)"
curl -fsS -X PUT -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $access" \
    -d '{"ate_solid_food":true,"dysphagia_occurred":false}' \
    "$EDGE/api/v1/me/symptoms/$today" >/dev/null || fail "the symptom entry was refused"
api GET "/me/symptoms/$today" "" "$access" | grep -q '"entry_date"' \
    || fail "the symptom entry did not read back"

# The audit trail is what a breach response reads, so it has to be true, and a
# client must not be able to choose what it says. Asserted against the row that
# was actually written, not against a status code.
step "a spoofed X-Forwarded-For does not reach the audit trail"
forged="203.0.113.55"
curl -fsS -X POST -H 'Content-Type: application/json' \
    -H "X-Forwarded-For: $forged" \
    -d "{\"email\":\"$SPOOF_EMAIL\"}" \
    "$EDGE/api/v1/auth/magic-link" >/dev/null
sleep 1
recorded="$(audit_ip)"
[[ "$recorded" != "$forged" ]] \
    || fail "the audit trail recorded a client-supplied address ($recorded)"
[[ -n "$recorded" ]] || fail "no audit row was written for the magic-link request"
printf '\033[2m     recorded %s, not the forged %s\033[0m\n' "$recorded" "$forged"

# The other half, and the reason the API is published on 8001 at all: reaching
# it directly bypasses the edge's header rewrite, and the spoof lands in the
# audit trail. Deployed, the API must be unreachable except through the edge —
# a security group, not a convention.
if [[ -n "$DIRECT_API" ]]; then
    step "reaching the API directly does accept a spoofed header (why it must not be exposed)"
    curl -fsS -X POST -H 'Content-Type: application/json' \
        -H 'X-Forwarded-For: 198.51.100.77' \
        -d "{\"email\":\"$DIRECT_EMAIL\"}" \
        "$DIRECT_API/api/v1/auth/magic-link" >/dev/null
    sleep 1
    direct="$(audit_ip)"
    [[ "$direct" == "198.51.100.77" ]] \
        || fail "expected the direct path to accept the spoof, got $direct — re-check FORWARDED_ALLOW_IPS"
    printf '\033[2m     recorded %s, which is why only the edge may be reachable\033[0m\n' "$direct"
fi

printf '\033[32m  ✓\033[0m smoke passed against %s\n' "$EDGE"
