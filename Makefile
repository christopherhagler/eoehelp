.DEFAULT_GOAL := help
COMPOSE := podman compose

.PHONY: help up down logs ps rebuild migrate revision test test-api image-test image-api \
        verify-promote lint format typecheck openapi api-types mail psql clean

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

up: ## Start the full stack (web, api, postgres, redis, mailhog)
	$(COMPOSE) up -d --build
	@echo ""
	@echo "  web      http://localhost:4200"
	@echo "  api      http://localhost:8000/docs"
	@echo "  mailhog  http://localhost:8025   (every magic-link email lands here)"

down: ## Stop the stack
	$(COMPOSE) down

clean: ## Stop the stack and delete its volumes (destroys local data)
	$(COMPOSE) down -v

logs: ## Tail logs from every service
	$(COMPOSE) logs -f

ps: ## Show service status
	$(COMPOSE) ps

rebuild: ## Rebuild images from scratch
	$(COMPOSE) build --no-cache

migrate: ## Apply database migrations
	$(COMPOSE) exec api alembic upgrade head

revision: ## Autogenerate a migration, then HAND-REVIEW it (m="message")
	@test -n "$(m)" || (echo "usage: make revision m=\"add symptom entries\"" && exit 1)
	$(COMPOSE) exec api alembic revision --autogenerate -m "$(m)"
	@echo ""
	@echo "Review the generated file before committing: autogenerate does not"
	@echo "emit RLS policies, grants, check constraints, or partial indexes."

test: test-api ## Run all tests

image-test: ## Build the API test image
	podman build -q -t eoehelp-api-test --target test apps/api

test-api: image-test ## Run the API test suite in a container
	podman run --rm --network eoehelp_default \
		-e DATABASE_URL=postgresql+asyncpg://eoehelp:eoehelp@postgres:5432/eoehelp \
		-e ENVIRONMENT=local \
		eoehelp-api-test pytest -q

# Both halves, and the whole tree rather than src/ alone: CI runs
# `ruff check . && ruff format --check .`, and a narrower local command means
# alembic/ and formatting drift only ever fail on the remote.
lint: image-test ## Lint the API exactly as CI does
	podman run --rm eoehelp-api-test sh -c "ruff check . && ruff format --check ."

format: image-test ## Apply ruff's formatting and safe fixes to the API
	podman run --rm -v "$(PWD)/apps/api:/src:z" eoehelp-api-test \
		sh -c "ruff check --fix /src && ruff format /src"

typecheck: image-test ## Type-check the API
	podman run --rm eoehelp-api-test mypy src

image-api: ## Build the API runtime image (the artifact that ships)
	podman build --format docker --target runtime -t eoehelp-api:local apps/api

verify-promote: image-api ## Prove promotion between registries preserves the image digest
	./scripts/verify-promote.sh eoehelp-api:local

# Run with npx rather than added to package.json: openapi-typescript 7 declares a
# peer dependency on typescript ^5, and this project is on 6. It is a codegen tool
# that never participates in the app build, so pinning it here keeps an
# unsatisfiable peer constraint out of the lock file.
api-types: ## Regenerate the Angular types from the committed OpenAPI contract
	podman run --rm -v "$(PWD):/repo" -w /repo/apps/web --userns=keep-id \
		-e HOME=/tmp -e npm_config_cache=/tmp/.npm node:24-bookworm-slim \
		npx -y openapi-typescript@7.13.0 ../../packages/openapi/schema.json \
		-o src/app/api-client/schema.d.ts

openapi: ## Regenerate the committed OpenAPI contract
	$(COMPOSE) exec -T api python -c "\
import json; from eoehelp_api.main import create_app; \
print(json.dumps(create_app().openapi(), indent=2, sort_keys=True))" \
		> packages/openapi/schema.json
	@echo "wrote packages/openapi/schema.json"

mail: ## Open the local mail catcher
	@open http://localhost:8025 2>/dev/null || echo "http://localhost:8025"

psql: ## Open a psql shell against the dev database
	$(COMPOSE) exec postgres psql -U eoehelp -d eoehelp
