# ADR 0010 — Organize code by domain, with dependency rules that are tested

**Status:** Accepted · 2026-09-18

## Context

The API started with one folder per layer: `routers/`, `services/`,
`repositories/`, `models/`, and `schemas/`. That worked for three tables. By
the time food, product labels, medications, and procedures had landed, it
had four problems:

- **A change to one feature touched five folders.** Adding a food field meant
  editing `models/food.py`, `schemas/food.py`, `repositories/food.py`,
  `services/food.py`, and `routers/food.py`.
- **One enum module held every domain's enums**, so nothing showed which enums
  belonged to which tables.
- **Helpers were copied.** There were four copies of the Postgres enum helper,
  plus six inline versions, and four copies of "today in the patient's
  timezone". Test modules imported helpers from each other.
- **Nothing enforced the boundaries the design depends on.** Identity must stay
  separable from clinical data, and patient data must be reached only through
  scoped repositories. Both rules were written down but not checked.

The web app had the same drift: data services were in `core/`, and food and
medication components were in `shared/`. The food editor had grown to 849 lines.

## Decision

### API: one package per domain

```
eoehelp_api/
  config.py  observability.py      settings; logging with PHI scrubbing
  db/                              declarative base, pg_enum, session, RLS scope
  core/                            security, errors, rate limits, entry dates
  audit/                           the append-only trail
  identity/                        users, patients, consent, sign-in
  symptoms/  medications/          the clinical domains, each holding
  food/      procedures/             models, enums, schemas, repository,
                                     service, and router
  food/products/                   Open Food Facts and USDA label data
  reference/                       reference data the client needs
  deps.py  health.py  main.py      request wiring and app assembly
  models.py                        the model registry Alembic reads
  synthetic/                       development data generator
```

Inside a domain, each module keeps one job:

- **router**: HTTP only. It maps requests and responses, and never builds a
  query.
- **service**: the rules, such as backfill windows, adherence, and scoring.
- **repository**: the only code that queries patient-owned tables. It is built
  with the patient id from the verified token, so no statement can leave the
  patient filter out. That removes the IDOR bug class (ADR 0002, layer one).
  Reference catalogs are read here too, through plain functions.
- **schemas**: the Pydantic types for requests and responses. ORM objects are
  never returned.

A domain adds a module only when it needs one: `symptoms/scoring.py`,
`procedures/erefs.py`, `medications/schedules.py`, `food/presenters.py`.

### Dependency rules

Dependencies point one way:

1. The foundation (`config`, `observability`, `db`, `core`) imports nothing
   above it.
2. `audit` imports only the foundation.
3. `identity` never imports a clinical domain. Research export reads clinical
   data through a pseudonym, and this rule keeps that possible.
4. Clinical domains never import each other. Views that combine them, such as
   the doctor report and the dashboards, will be new packages above them.
5. `deps` and `health` are imported only by routers and the app.
6. Routers do not import query builders.
7. Nothing outside `synthetic` imports it.

`tests/test_architecture.py` checks each rule against the import graph, so a
violation fails CI instead of surfacing later as an import cycle.

### Things deliberately left alone

- **Migrations stay self-contained.** Each one repeats its own RLS and grant
  statements instead of calling a shared helper. A migration has to keep doing
  exactly what it did when it first ran, and a shared helper would change
  every old migration whenever the helper was edited.
- **Identity keeps descriptive module names** (`auth_router`, `me_router`,
  `patient_schemas`), because it has two routers and two sets of schemas.
  Splitting it into sub-packages would add nesting and make nothing clearer.

### Tests

The tests use the same domain folders as the source (`tests/food/`,
`tests/symptoms/`, and so on). Shared builders such as `days_ago`, `food_item`,
and `app_role_url` live in `tests/helpers.py`, and test modules never import
from each other. Recorded fixtures sit next to the tests that use them.

### Web

```
src/app/
  core/api/          base URL, generated types, error messages
  core/auth/         session, guard, interceptor
  core/              dates, patient and reference data
  features/<area>/   pages, plus each domain's data service and components
  shared/            domain-free pieces: logo, month picker
  api-client/        generated from the OpenAPI contract, never edited
```

The food editor is split into three components:

- **product picker**: search, barcode entry, and scanning
- **product label**: shows the label, with declared, may-contain, and inferred
  allergens
- **editor**: meal, name, and the patient's own ingredients

The picker's fields are not part of the food form, so pressing Enter in them no
longer saves the meal.

Prettier covers TypeScript and HTML. CI runs `npm run format:check` in place of
a lint step that never ran anything. Prettier is not used on SCSS, because it
reflows Material theme maps badly.

## Consequences

- A feature change stays inside one package. Code review follows the domain,
  not the layer.
- Adding a domain means adding a package, a line in `V1_ROUTERS`, and its
  models in `models.py`.
- The architecture tests will fail a legitimate new dependency until the rule
  is changed. That is intended: widening a boundary should be a visible
  decision in a diff, not a side effect.
