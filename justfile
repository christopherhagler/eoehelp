# eoehelp's command surface. `just --list` is the index.
#
# Every recipe is a thin wrapper: the work lives in scripts/, which CI calls
# directly, so "it passed locally" and "CI is green" are the same claim rather
# than two implementations that happen to agree.

# Base images are pinned in one file so local, CI and deployed cannot drift.
compose := "podman compose --env-file infra/images.env"

[private]
default:
    @just --list

# ---- stack ----------------------------------------------------------------

# Start the full stack (web, api, postgres, redis, mailhog)
[group('stack')]
up:
    @scripts/build-images.sh dev web-deps
    # On failure, show the migration output: `up -d` does not stream a one-shot
    # service's logs, so a failed migration otherwise aborts with no reason.
    @{{ compose }} up -d || ({{ compose }} logs migrate; exit 1)
    @echo ""
    @echo "  web      http://localhost:4200"
    @echo "  api      http://localhost:8000/docs"
    @echo "  mailhog  http://localhost:8025   (every magic-link email lands here)"

# Stop the stack
[group('stack')]
down:
    {{ compose }} down

# Stop the stack and delete its volumes (destroys local data)
[group('stack')]
clean:
    {{ compose }} down -v
    # Named explicitly: it is no longer declared in compose.yaml, so `down -v`
    # does not know about it, and nothing else would ever remove it.
    -podman volume rm -f eoehelp_web_node_modules

# Tail logs from every service, or one of them
[group('stack')]
logs service="":
    {{ compose }} logs -f {{ service }}

# Show service status
[group('stack')]
ps:
    {{ compose }} ps

# Check the things that go wrong before a command does
[group('stack')]
doctor:
    @scripts/doctor.sh

# ---- database -------------------------------------------------------------

# Apply database migrations
[group('db')]
migrate:
    {{ compose }} exec api alembic upgrade head

# Autogenerate a migration, then HAND-REVIEW it
[group('db')]
revision message:
    {{ compose }} exec api alembic revision --autogenerate -m "{{ message }}"
    @echo ""
    @echo "Review the generated file before committing: autogenerate does not"
    @echo "emit RLS policies, grants, check constraints, or partial indexes."

# Open a psql shell against the dev database
[group('db')]
psql:
    {{ compose }} exec postgres psql -U eoehelp -d eoehelp

# Seed the dev database with synthetic patients
[group('db')]
seed patients="3" months="18" seed="1":
    {{ compose }} exec -T api python -m eoehelp_api.synthetic \
        --patients {{ patients }} --months {{ months }} --seed {{ seed }}

# ---- api ------------------------------------------------------------------

# Arguments are re-split by the shell, so `just test -k "a and b"` does not
# survive as one argument. Use a single-word expression, or call
# scripts/api-checks.sh directly.

# Run the API test suite; extra arguments go to pytest
[group('api')]
test *args:
    @scripts/api-checks.sh test {{ args }}

# Lint the API exactly as CI does
[group('api')]
lint:
    @scripts/api-checks.sh lint

# Lint the shell scripts that are now the command surface
[group('api')]
shellcheck:
    podman run --rm -v "$PWD:/repo:z" -w /repo \
        $(grep '^SHELLCHECK_IMAGE=' infra/images.env | cut -d= -f2-) \
        -x --source-path=SCRIPTDIR scripts/*.sh

# Apply ruff's formatting and safe fixes to the API
[group('api')]
format:
    @scripts/api-checks.sh format

# Type-check the API
[group('api')]
typecheck:
    @scripts/api-checks.sh typecheck

# Everything CI runs against the API, plus shellcheck, which CI gains in stage 3
[group('api')]
check: lint shellcheck typecheck test contract-check

# ---- web ------------------------------------------------------------------

# Check the web app's formatting, tests, and production build, as CI does
[group('web')]
web-check:
    @scripts/web-checks.sh check

# Run the web tests alone
[group('web')]
web-test:
    @scripts/web-checks.sh test

# Apply Prettier to the web app
[group('web')]
web-format:
    @scripts/web-checks.sh format

# ---- contract -------------------------------------------------------------

# Regenerate the committed OpenAPI contract
[group('contract')]
openapi:
    @scripts/openapi.sh

# Regenerate the Angular types from the committed contract
[group('contract')]
api-types:
    @scripts/api-types.sh

# Regenerate both
[group('contract')]
contract: openapi api-types

# Assert both are current, which is exactly what CI checks
[group('contract')]
contract-check:
    @scripts/openapi.sh --check
    @scripts/api-types.sh --check

# ---- images ---------------------------------------------------------------

# Build images, tagged by content; skips anything already up to date
[group('images')]
build *targets:
    @scripts/build-images.sh {{ targets }}

# Rebuild every image from scratch, ignoring the content tags
[group('images')]
rebuild:
    @scripts/build-images.sh all --no-cache

# Prove promotion between registries preserves the image digest
[group('images')]
verify-promote:
    @scripts/build-images.sh runtime
    ./scripts/verify-promote.sh localhost/eoehelp-api:runtime

# Assert an image is what it claims: manifest, arch, unprivileged, no test tooling
[group('images')]
verify-image *images:
    @scripts/verify-image.sh {{ if images == "" { "localhost/eoehelp-api:runtime" } else { images } }}

# ---- ci -------------------------------------------------------------------
# The exact sequences CI runs, so "it passed locally" and "CI is green" are the
# same claim. CI calls these; nothing here is CI-only.

# Everything the api job runs, inside the image that gets tested
[group('ci')]
ci-api:
    @scripts/api-checks.sh lint
    @scripts/api-checks.sh typecheck
    @scripts/api-checks.sh test
    @scripts/api-checks.sh migrations
    @scripts/openapi.sh --check

# Everything the web job runs, inside the deps image
[group('ci')]
ci-web:
    @scripts/web-checks.sh check
    @scripts/api-types.sh --check

# Everything the images job runs: build what ships, then assert what it is
[group('ci')]
ci-images:
    @scripts/build-images.sh runtime web-runtime
    @scripts/verify-image.sh localhost/eoehelp-api:runtime localhost/eoehelp-web:runtime
    ./scripts/verify-promote.sh localhost/eoehelp-api:runtime

# ---- housekeeping ---------------------------------------------------------

# `just prune all` adds -a, which also removes images no container is using —
# most of what `just doctor` reports as reclaimable. Without it the reported
# number barely moves and the two commands appear to disagree.

# Reclaim dangling images, containers and build cache; `all` also unused images
[group('housekeeping')]
prune all="":
    podman system prune -f {{ if all == "all" { "-a" } else { "" } }}
    @podman system df

# Open the local mail catcher
[group('housekeeping')]
mail:
    @open http://localhost:8025 2>/dev/null || echo "http://localhost:8025"
