# eoehelp

A patient-owned health record for eosinophilic esophagitis: FastAPI and
Postgres (row-level security) in `apps/api`, Angular 22 in `apps/web`, the
OpenAPI contract in `packages/openapi`, and decisions in `docs/adr`. Treat it
as a production medical-adjacent product.

## How features are built

Every new feature or substantial change goes through the reviewed workflow
in `.claude/skills/feature/SKILL.md` (`/feature <description>`):

1. The `architect` agent designs the feature and writes its plan in
   `docs/plans/`.
2. You implement the plan and run the checks CI runs. Design problems go
   back to the architect, not into improvised code.
3. The `code-reviewer` agent reviews the changes; fix until it passes.
4. Commit with the plan, push to `development`, and watch CI.

Small fixes (a typo, a one-line bug, a dependency bump) can skip the
architect, but still get a code review before committing.

## Commands

Everything runs in Podman containers; start the machine with
`podman machine start` if a command cannot connect.

- `make up`: start the stack (web :4200, API :8000, Mailhog :8025)
- `make test-api`, `make lint`, `make typecheck`, `make format`: API checks
- `make web-check`, `make web-format`: web formatting, tests, and build
- `make openapi` then `make api-types`: after any change to the API surface
- `make seed`: synthetic patients for local development

## Rules that carry weight

- Patient data is reached only through repositories scoped by the token's
  patient id, under `/me` routes. New tables get RLS policies and grants
  (ADR 0002).
- The package layout and its dependency rules are in ADR 0010 and enforced by
  `apps/api/tests/test_architecture.py`.
- No PHI in logs, errors, or the audit trail: field names and counts only.
- Clinical wording is descriptive, never prescriptive, and never calls a food
  "safe".
- Migrations can still be edited in place; nothing is deployed yet and
  backwards compatibility is not required.
- Push to `development`, never `main` unless asked.
