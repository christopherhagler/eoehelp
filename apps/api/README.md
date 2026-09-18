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

One package per domain. See
[ADR 0010](../../docs/adr/0010-code-organization.md) for the reasoning and the
dependency rules that `tests/test_architecture.py` enforces.

| Path | Responsibility |
|---|---|
| `config.py`, `observability.py`, `db/`, `core/` | Foundation: settings, PHI-scrubbed logging, sessions and RLS scope, security, errors |
| `audit/` | The append-only audit trail, written in the caller's transaction |
| `identity/` | Users, patients, consent, sign-in; never imports clinical code |
| `symptoms/`, `medications/`, `food/`, `procedures/` | Clinical domains, each with its models, schemas, repository, service, and router |
| `reference/` | Reference data the client needs to send valid requests |
| `deps.py`, `health.py`, `main.py` | Request wiring and app assembly |
| `models.py` | Model registry; a model not imported here is invisible to Alembic |

Within a domain, routers only map HTTP, services hold the rules, repositories
are the only code that queries patient-owned tables, and schemas are the only
types returned. ORM objects never are.

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
