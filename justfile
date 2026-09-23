# eoehelp's command surface. `just --list` is the index.
#
# Every recipe is a thin wrapper: the work lives in scripts/, which CI calls
# directly, so "it passed locally" and "CI is green" are the same claim rather
# than two implementations that happen to agree.

[private]
default:
    @just --list

# ---- stack ----------------------------------------------------------------

# Start the full stack (web, api, postgres, redis, mailhog)
[group('stack')]
up:
    podman compose up -d --build
    @echo ""
    @echo "  web      http://localhost:4200"
    @echo "  api      http://localhost:8000/docs"
    @echo "  mailhog  http://localhost:8025   (every magic-link email lands here)"

# Stop the stack
[group('stack')]
down:
    podman compose down

# Stop the stack and delete its volumes (destroys local data)
[group('stack')]
clean:
    podman compose down -v

# Tail logs from every service, or one of them
[group('stack')]
logs service="":
    podman compose logs -f {{ service }}

# Show service status
[group('stack')]
ps:
    podman compose ps

# Check the things that go wrong before a command does
[group('stack')]
doctor:
    @scripts/doctor.sh

# ---- database -------------------------------------------------------------

# Apply database migrations
[group('db')]
migrate:
    podman compose exec api alembic upgrade head

# Autogenerate a migration, then HAND-REVIEW it
[group('db')]
revision message:
    podman compose exec api alembic revision --autogenerate -m "{{ message }}"
    @echo ""
    @echo "Review the generated file before committing: autogenerate does not"
    @echo "emit RLS policies, grants, check constraints, or partial indexes."

# Open a psql shell against the dev database
[group('db')]
psql:
    podman compose exec postgres psql -U eoehelp -d eoehelp

# Seed the dev database with synthetic patients
[group('db')]
seed patients="3" months="18" seed="1":
    podman compose exec -T api python -m eoehelp_api.synthetic \
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

# Apply ruff's formatting and safe fixes to the API
[group('api')]
format:
    @scripts/api-checks.sh format

# Type-check the API
[group('api')]
typecheck:
    @scripts/api-checks.sh typecheck

# Everything CI runs against the API
[group('api')]
check: lint typecheck test contract-check

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

# Build the API runtime image (the artifact that ships)
[group('images')]
build-api:
    podman build --format docker --target runtime -t eoehelp-api:local apps/api

# Wider than `build-api`, which builds only the shipping artifact. Stage 2 of
# the build plan replaces both with one script.

# Rebuild every compose image from scratch
[group('images')]
rebuild:
    podman compose build --no-cache

# Prove promotion between registries preserves the image digest
[group('images')]
verify-promote: build-api
    ./scripts/verify-promote.sh eoehelp-api:local

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
