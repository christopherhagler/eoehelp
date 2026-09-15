# eoehelp API

FastAPI service backing eoehelp.org. Patient-owned EoE symptom tracking, clinical
report generation, and (later) consent-gated de-identified research export.

## Running

Everything runs in containers; from the repository root:

```bash
podman compose up --build
```

- API: http://localhost:8000 (`/docs` outside production)
- Mailhog, which captures every magic-link email: http://localhost:8025

Migrations run automatically on container start. To run them by hand:

```bash
podman compose exec api alembic upgrade head
```

## Tests

From the repository root:

```bash
make test       # builds the `test` image stage and runs pytest against the stack
make typecheck  # mypy
```

The runtime image deliberately excludes pytest and dev dependencies, so tests run
from the `test` stage — which is built *from* the runtime image, so what is
exercised is the artefact that actually ships.

## Layout

| Path | Responsibility |
|---|---|
| `routers/` | HTTP layer only — request/response mapping, no business logic |
| `services/` | Business logic: auth flows, scoring, report assembly, audit |
| `repositories/` | The only code that queries patient-owned tables, always scoped |
| `models/` | SQLAlchemy models; anything not imported in `models/__init__.py` is invisible to Alembic |
| `schemas/` | Pydantic DTOs — ORM objects are never returned directly |

## Invariants

These carry the security properties of the system and should not be relaxed
without reading `docs/adr/`.

1. **Patient data is reached only through a scoped repository.** Routes are
   `/me/*`; `patient_id` comes from the verified access token and never from a
   path or body parameter.
2. **Row-level security is a backstop, not the mechanism.** The app connects as
   `app_runtime`, which owns no tables, and scope is set with `SET LOCAL` inside
   the request transaction.
3. **Audit rows commit in the same transaction as the change they describe.**
4. **The audit log is INSERT-only** for the application role.
5. **Free-text clinical columns are encrypted in the application**, keyed outside
   the database, bound to the record id as additional authenticated data.
6. **Nothing PHI-bearing is logged.** `observability.scrub_event` redacts by field
   name and is covered by tests.
