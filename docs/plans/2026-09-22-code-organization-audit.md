# Code organization audit, and the reorganization worth doing

**Status:** Draft · 2026-09-22

This is an audit first and a plan second. It reads the whole repository — both
applications, the tests, the migrations, the infrastructure files, the docs, and
the agent definitions under `.claude/` — against the rules the codebase states
about itself in ADR 0002 and ADR 0010, and against what `tests/test_architecture.py`
actually enforces.

The conclusion up front: **the structure is good and the enforcement is thin.**
The layout ADR 0010 describes is real, the clinical domains are exemplary, the
route convention holds without exception, and the web app's layering is already
correct. What has drifted is (a) `identity/`, which has silently become three
packages in one folder, (b) the boundary between "rules written down" and
"rules a test proves", which has widened as new packages were added, and (c) the
test suite, which has no owner for process-global state and therefore has an
order-dependent flake that is a symptom rather than a bug.

Nothing here requires a rewrite. The highest-value item is roughly 60 lines of
new test code.

## Goal

Not a patient-facing goal. The goal is that one maintainer can add the next
feature — the endoscopy screen, the doctor report, the research export — without
the structure fighting back, and that the rules the design depends on keep
holding after the conversation that wrote them is gone.

Two constraints shaped every recommendation:

- **One person maintains this.** Structure that needs discipline to hold will not
  hold. Every proposal below is either a move that cannot be undone by accident,
  or a test that fails when it is. Anything that would need remembering is in
  *Leave it*.
- **Nothing is deployed.** Migrations are editable in place and there is no
  backwards compatibility to preserve. Two findings (F9, F10) are cheap today and
  permanently expensive after the first real patient; they are marked
  **window closing**.

## Clinical basis

None. Nothing here changes an instrument, a threshold, a computation, or a word
a patient reads. Two findings (F4, F5) affect whether the PHI-scrubbing and
audit controls are proved by the suite as strongly as they appear to be, which
is a privacy matter rather than a clinical one.

## Scope

**In scope.** `apps/api` source and tests, `apps/api/alembic`, `apps/web`,
`packages/openapi`, `infra/`, `docs/`, `.claude/`.

**Explicitly out of scope.**

- **The Makefile/CI duplication.** Owned by
  `docs/plans/2026-09-19-build-system-and-deploy-path.md`. Not re-litigated. One
  finding (F10) hands that plan a question rather than answering it here.
- **The consent-text reproducibility work in the tree.** Read as part of the
  codebase, and it is sound. Two of its consequences are noted (F11a, F14) but
  **no move in this plan may start before that work is committed.**
- **Renaming for symmetry.** Several inconsistencies are deliberately left alone
  and listed in *Leave it* with the reason.
- **Performance, new features, and the launch-gate items.**

---

## Findings, ranked

Ranked by expected cost of leaving it, not by size. Each names where it is, what
breaks and when, and the specific change.

### Bucket A — do now, cheap

#### F1. The architecture test only constrains packages it has been told about; `reference/` is unconstrained · **highest value**

**Where.** `apps/api/tests/test_architecture.py`, `_violations()`:

```python
for module, path in _modules():
    package = _package(module)
    if package not in allowed:
        continue
```

A package absent from every `allowed` dict is skipped silently. The dicts name
`config`, `observability`, `db`, `core`, `audit`, `identity`, the four clinical
domains, and `insights`. Of the seventeen top-level names in the package,
`reference` is constrained by nothing at all, and `synthetic` is constrained only
as an importee (nothing may import it) and not as an importer.

**Why it matters.** `reference/router.py` already imports
`eoehelp_api.procedures.erefs` and `eoehelp_api.procedures.schemas`. That is
defensible — reference data served from the domain that owns the scale — but it
is not a *decision*, it is an absence. The rule ADR 0010 sells as its main
benefit ("the architecture tests will fail a legitimate new dependency until the
rule is changed; widening a boundary should be a visible decision in a diff") is
only true for packages someone remembered to list. The next package added — a
`reports/` for the doctor report, a `research/` for export — inherits the same
silence, and `research/` is precisely the package where an accidental import of
`identity` would undo the separation ADR 0010 rule 3 exists to protect.

This is a single maintainer's worst failure mode: a guardrail that looks present
and is not.

**The change.** Invert the default. Add to `test_architecture.py`:

```python
ALLOWED: dict[str, set[str]] = {
    "config": set(),
    "observability": set(),
    "db": {"config"},
    "core": {"config", "observability", "db"},
    "audit": FOUNDATION,
    "identity": FOUNDATION | {"audit", "deps"},
    **dict.fromkeys(CLINICAL, FOUNDATION | {"audit", "identity", "deps"}),
    "insights": FOUNDATION | {"audit", "identity", "deps", "symptoms", "food"},
    # Reference data the client needs. Reads the domains' own vocabulary
    # modules; owns no data and is read by nothing.
    "reference": FOUNDATION | {"deps", "procedures"},
    # A development tool. Reads everything, is imported by nothing (see
    # test_the_synthetic_generator_is_never_part_of_a_request).
    "synthetic": FOUNDATION | CLINICAL | {"identity", "audit"},
}

def test_every_package_has_a_stated_dependency_rule() -> None:
    """A new package must declare what it may import, or this fails.

    The rule that only binds packages someone remembered to list is the rule
    that will not be there for the one that matters.
    """
    packages = {_package(module) for module, _ in _modules()}
    unruled = packages - set(ALLOWED) - APPLICATION - {"__init__"}
    assert unruled == set(), (
        f"these packages have no dependency rule: {sorted(unruled)}. "
        "Add one to ALLOWED in this file, which is how widening a boundary "
        "becomes visible in a diff."
    )
```

Rewrite the existing per-rule tests to take their slice of `ALLOWED` so there is
one source of truth. Keep the per-rule tests: their names and docstrings are what
make a failure legible.

**Cost.** ~30 lines. No source changes.

---

#### F2. "Routers do not build queries" does not catch the way routers actually reach data

**Where.** `test_routers_do_not_build_queries` looks only for an import of
`select`, `insert`, `update`, `delete`, or `text` from `sqlalchemy`. Three
routers reach data without importing any of those:

| File | How |
|---|---|
| `identity/auth_router.py:131` | `await session.get(User, principal.user_id)` |
| `food/router.py:58` | `await repository.catalog_ingredients(session)` |
| `identity/me_router.py:49` | `await session.get(User, principal.user_id)` |

**Why it matters.** All three are safe today: the ids come from the verified
token, and the catalog is reference data. The problem is that the rule's *intent*
("queries belong to repositories, where every patient-owned statement is scoped
by construction") is not what the test checks. A future router writing
`await session.get(Endoscopy, endoscopy_id)` with `endoscopy_id` from the path
passes this test, and that is an IDOR — caught only by RLS, which ADR 0002 is
explicit is the backstop and not the mechanism.

**The change.** Extend the test to flag, in any module whose name ends in
`router`, any attribute call of `session.get(`, `session.execute(`,
`session.scalars(`, `session.add(`, or `session.delete(`. Allow the three
existing cases through a named, commented exemption set so that adding a fourth
is a visible line in a diff:

```python
# Reading the caller's own User by the id in the verified token, and the
# unowned ingredient catalog. Neither takes an id from the request.
ALLOWED_ROUTER_DATA_ACCESS = {
    ("identity.auth_router", "current_session"),
    ("identity.me_router", "complete_onboarding"),
    ("food.router", "list_catalog"),
}
```

**Cost.** ~25 lines. No source changes.

---

#### F3. The constraint-name drift test covers only CHECK constraints

**Where.** `apps/api/tests/db/test_patient_isolation.py`,
`test_database_constraint_names_match_the_models` — `WHERE k.contype = 'c'`.

**Why it matters.** Its own docstring explains the defect it exists to prevent:
migrations 0002–0005 once produced doubled names (`ck_x_ck_x_...`) that no later
migration could drop by the name the model gives. That failure mode applies
identically to unique constraints, foreign keys, primary keys, and indexes —
none of which are checked. Migrations are also inconsistent about `op.f()`
(0001: 1 use vs 24 literal names; 0004: 1 vs 20; 0005: 6 vs 19), which is exactly
the condition under which a name drifts from `db/base.py`'s `NAMING_CONVENTION`
without anyone noticing.

Two constraints legitimately deviate from the convention and are named explicitly
in the model — `ix_consents_current` and
`fk_consents_document_revision_legal_documents` — so a model-versus-database
comparison passes for both. That is the right shape: the comparison is
model-versus-database, not database-versus-convention.

**The change.** Widen the query to `k.contype IN ('c', 'u', 'f', 'p')` and add a
second comparison for indexes from `pg_indexes`, both against `Base.metadata`.
Keep it in `tests/db/` where it is.

**Cost.** ~30 lines. Expect it to pass on the first run; if it does not, the
failure is the finding.

---

#### F4. The test suite has no owner for process-global state — this is what the flake is made of

**Where.** `apps/api/tests/conftest.py`, and scattered `cache_clear()` calls.

This is not a bug to fix here. It is a structural statement: **nine pieces of
process-global state are mutated by the suite, three are reset by an autouse
fixture, one is reset by hand in one test file, and five are reset by nobody.**

| Global | Where | Reset by |
|---|---|---|
| `db.session._engine` / `_session_factory` | `db/session.py` | autouse `_isolate_engine_per_test` |
| `core.ratelimit.limiter` counters | `core/ratelimit.py` | autouse `_fresh_rate_limits` |
| `config.get_settings` lru_cache | `config.py` | session fixture, once |
| `identity.documents.text_for` / `blocks_for` `@cache` | `documents.py:274,287` | by hand in `test_legal_router.py`, twice |
| `identity.documents.DOCUMENTS` (monkeypatched) | 4 tests | `monkeypatch` |
| `identity.documents.LEGAL_DIRECTORY` (monkeypatched) | 1 test | `monkeypatch` |
| stdlib `logging` config | alembic `fileConfig` at session start, then `configure_logging` from one test | **nobody** |
| `structlog` global config + `cache_logger_on_first_use=True` | `observability.configure_logging` | **nobody** |
| `logging.Logger.disabled` and `.filters` on `uvicorn.access`, `slowapi` | `observability._silence_path_loggers` | **nobody** |
| `core.ratelimit.limiter.enabled` (frozen at import from settings) | `_build()` at import | **nobody** |
| `food.products.provider.get_food_data` lru_cache | `provider.py:175` | dependency override only |

**Why it matters, concretely.** `core/test_log_paths.py::TestLoggerConfiguration`
calls `configure_logging(environment="local", debug=False)` as a test action.
That call is not scoped to the test: it calls `logging.basicConfig`, sets
`logging.getLogger("uvicorn.access").disabled = True`, installs a
`_DropRequestPaths` filter on the slowapi loggers, and reconfigures `structlog`
globally. `tests/core/` sorts first, so in a full run almost the entire suite
executes *after* that mutation; run `pytest tests/identity` alone and it executes
*before* it. That is a difference between "passes alone" and "fails in a full
run" with no test naming the dependency.

The reported symptom — passes alone and in pairs, fails in a full run — is the
shape this produces. I am not claiming this is the whole flake; I am claiming the
suite has no place where a global is declared, so any such coupling is invisible
until it bites, and the next one will be too.

Three further consequences worth stating plainly, because they weaken controls
rather than merely tests:

1. **The app under test never runs its lifespan.** `httpx.ASGITransport` does not
   send lifespan events, so `configure_logging`, `documents.verify_integrity`,
   `documents.enforce_review_status`, and `legal_document.verify_published_revisions`
   are never exercised through `create_app()`. Each has a direct unit test, but
   nothing proves `lifespan` calls them, and boot order (logging configured
   *before* the first request) is never exercised.
2. **PHI scrubbing is proved at the function level only.**
   `tests/core/test_phi_scrubbing.py` calls `scrub_event` directly. No test emits
   a log line through `observability.get_logger(...)` and asserts the output is
   scrubbed. Combined with (1) and with `cache_logger_on_first_use=True`, whether
   `scrub_event` is even in the pipeline for a given logger depends on whether
   `configure_logging` ran before that logger's first use.
3. **Verify before acting:** `configure_logging` calls `logging.basicConfig(...)`
   but does not set `logger_factory=structlog.stdlib.LoggerFactory()`, so
   structlog's default `PrintLoggerFactory` may be in force and application log
   lines may never reach stdlib handlers at all. If that is so,
   `test_a_crafted_path_does_not_reach_any_log_record` passes because `caplog`
   sees nothing rather than because nothing leaked. **Check this first**
   (`python -c "import structlog; print(structlog.get_config()['logger_factory'])"`
   after `configure_logging`); if confirmed it is a separate small defect and
   belongs to its own change, not to this reorganization.

**The change.** Three parts, all in `tests/`:

(a) **One place that owns globals.** In `conftest.py`, replace the three separate
autouse fixtures with one autouse `_process_globals` fixture that resets every
entry in the table above, with a comment per line saying what it is and why it
must be reset. One fixture, one list, one place to add the next one.

(b) **A test that fails when a new global is not registered.** In the style of
`test_architecture.py` — this is the part that makes it hold for one maintainer:

```python
# tests/test_global_state.py
"""Every process-global in the application is reset between tests, or named here.

A cached function or module-level singleton that nobody resets is how a suite
acquires an order-dependent failure that passes alone and fails in a full run.
This test does not prevent the global; it prevents the *unregistered* global.
"""

RESET_BY_CONFTEST = {
    "eoehelp_api.config.get_settings",
    "eoehelp_api.core.security._cipher_for",
    "eoehelp_api.food.products.provider.get_food_data",
    "eoehelp_api.identity.documents.text_for",
    "eoehelp_api.identity.documents.blocks_for",
}

def test_every_cached_callable_is_registered() -> None:
    """Found by walking the package for functools cache wrappers."""
    ...
```

(c) **Give the app fixture a lifespan.** Either `asgi-lifespan`'s
`LifespanManager` (one dev dependency) or, cheaper and dependency-free, have the
`app` fixture `async with application.router.lifespan_context(application):`.
That makes the suite exercise the boot path, removes the accidental ordering
dependency on `test_log_paths.py`, and gives the startup checks their first
integration coverage.

**Cost.** ~80 lines of test code, one conftest rewrite, no source changes.
Expect (c) to surface one or two tests that were relying on the unconfigured
state; that is the finding paying for itself.

---

#### F5. `clean_tables` truncates a hand-maintained list of table names

**Where.** `apps/api/tests/conftest.py`, the `TRUNCATE users, patients, consents, …`
string.

**Why it matters.** A new patient-owned table that nobody adds to this string
leaks rows between tests. The failure is silent and appears as a flake in an
unrelated test days later — the same class of problem as F4, and the same
maintenance model (remember to edit a string) that F4 says will not hold.

The database-level catalogue test next door
(`test_every_patient_owned_table_has_row_level_security`) already demonstrates
the right pattern: it asks `pg_class` rather than listing tables, so "the next
table is covered without anyone editing this test".

**The change.** Derive the list from `Base.metadata`: truncate every table except
an explicit, commented `REFERENCE_TABLES` allowlist (`clinical_instruments`,
`medication_catalog`, `ingredient_catalog`, `legal_documents`, `alembic_version`),
and add one assertion that every name in that allowlist exists in the metadata —
so a renamed reference table fails loudly instead of being truncated.

**Cost.** ~15 lines.

---

#### F6. Test modules cannot share a basename across domain folders

**Where.** `apps/api/tests/` has no `__init__.py` files and pytest's default
`prepend` import mode is in use.

**Why it matters.** Basenames are currently unique by luck. Adding
`tests/food/test_api.py` next to the existing `tests/insights/test_api.py`
produces `import file mismatch` and a collection error, which reads as a broken
environment rather than as a naming collision. The suite's own convention —
domain folders mirroring source packages — makes duplicate basenames the natural
thing to write.

**The change.** In `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = "-q --strict-markers --import-mode=importlib"
pythonpath = ["tests"]   # keeps `from helpers import ...` working
```

**Cost.** Two lines. Run the suite once to confirm `helpers` still imports.

---

#### F7. The web app declares two different `AccessTokenResponse` and `SessionUser`

**Where.**

- `apps/web/src/app/core/api/api.ts` — hand-written `interface AccessTokenResponse`
  and `interface SessionUser`.
- `apps/web/src/app/core/api/api-types.ts` — `export type AccessTokenResponse = Schemas['AccessTokenResponse']`
  and the same for `SessionUser`, re-exported from the generated schema.

`core/auth/auth.service.ts:5` imports the hand-written pair. Every other file in
the app — 30 of them — imports from `api-types.ts`.

**Why it matters.** `api-types.ts`'s own docstring states the property being
bought: "a backend response-shape change therefore becomes a TypeScript error
here rather than a runtime surprise in a clinical screen". The session and
access-token contract — the one carrying `patient_id` and `onboarding_complete`,
which decide which routes a patient can reach — is the single part of the app
opted out of that guarantee. Rename `onboarding_complete` on the API and CI's
contract-drift job goes green while the guard silently starts treating every
patient as onboarded.

Two same-named types in the same folder is also the kind of thing that reads as
intentional to a future reader and is not.

**The change.** Delete both interfaces from `api.ts`; change
`auth.service.ts`'s import to `'../api/api-types'`. `api.ts` then holds only
`API_BASE_URL`; rename it `core/api/base-url.ts` in the same commit, or leave the
filename — either is fine, but do not leave two type declarations.

**Cost.** Three lines changed, one file shrinks. `npm run build` proves it.

---

#### F8. `authGuard` is exported and never used

**Where.** `apps/web/src/app/core/auth/auth.guard.ts:33`. `app.routes.ts` uses
only `onboardedGuard` and `onboardingPendingGuard`.

**Why it matters.** Minor, but it is an auth primitive: a future route that wants
"signed in but not necessarily onboarded" will reach for it, get a guard nothing
has ever exercised (F15: `core/` has no specs at all), and put it on a route.

**The change.** Delete it, or add the first route that needs it. Deleting is
right today — `requireSession` remains and is one line to wrap.

---

### Bucket B — do now, because the window closes

#### F9. Grants are decided in two places: a blanket grant in 0001, corrected three migrations later in 0006 · **window closing**

**Where.** `alembic/versions/0001_initial_identity_and_consent.py`:

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_runtime;
REVOKE UPDATE, DELETE ON audit_log FROM app_runtime;
```

and `alembic/versions/0006_consent_document_digest.py`, which then revokes what
0001 over-granted:

```sql
REVOKE UPDATE, DELETE ON consents FROM app_runtime;
REVOKE ALL ON alembic_version FROM app_runtime;
REVOKE UPDATE, DELETE ON research_consent_scopes FROM app_runtime;
```

Migrations 0002–0005 all grant per table, correctly, because `ON ALL TABLES` is a
snapshot and does not reach tables created later.

**Why it matters.** To answer "what may the application do to `consents`?" you
must read two migrations five revisions apart and mentally apply a revoke. Every
table that existed at 0001 — `users`, `patients`, `consents`,
`research_consent_scopes`, `magic_link_tokens`, `refresh_tokens`, `audit_log`,
`alembic_version` — got full DML by default and was then narrowed by exception.
That is the same "grant by default, narrow by exception" shape that
`infra/postgres/init/01-extensions.sql` already rejects in its own comment, and
for the same reason: it made each migration's considered grant cosmetic. The
`ALTER DEFAULT PRIVILEGES` defect that the comment describes was found only
because someone wrote `test_no_default_privileges_exist_in_the_application_database`.
The blanket `GRANT ON ALL TABLES` is the same mistake at a smaller scale, and it
is still in the tree.

Two facts make this specifically a *now* item. Nothing is deployed, so 0001 can
be edited in place. And `app_runtime`'s privileges are the last line between a
compromised application process and rewriting consent evidence — the thing the
whole legal-documents feature exists to make durable.

**The change.** In `0001`, replace the blanket grant with one explicit grant per
table, in the style of 0002–0005:

```sql
GRANT USAGE ON SCHEMA public TO app_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON users TO app_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON patients TO app_runtime;
GRANT SELECT, INSERT ON consents TO app_runtime;                  -- append-only
GRANT SELECT, INSERT ON research_consent_scopes TO app_runtime;   -- append-only
GRANT SELECT, INSERT, UPDATE, DELETE ON magic_link_tokens TO app_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON refresh_tokens TO app_runtime;
GRANT INSERT ON audit_log TO app_runtime;                         -- write-only trail
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_runtime;
-- alembic_version is deliberately absent: the application never reads it.
```

Then delete the three compensating `REVOKE`s from 0006 and its matching
`downgrade` grants, leaving 0006 with only `GRANT SELECT ON legal_documents`,
which is its own table.

**How it is proved.** No new test needed —
`tests/db/test_consent_grants.py` already asserts every one of these outcomes
(`consents` not updatable, `alembic_version` untouchable,
`research_consent_scopes` append-only, reference tables read-only,
`legal_documents` read-only). After the change those tests prove 0001 rather than
0006, which is where the statement belongs. Also rerun CI's
`alembic upgrade head && alembic downgrade base && alembic upgrade head`.

**Cost.** One migration edited, one trimmed, a database rebuild
(`make clean && make up && make seed`) that the in-flight work already required.

---

#### F10. The API runtime image installs native libraries for a dependency that does not exist · hand to the build plan

**Where.** `apps/api/Dockerfile`, runtime stage: `libpango-1.0-0`,
`libpangoft2-1.0-0`, `libcairo2`, `libgdk-pixbuf-2.0-0`, `libffi8`,
`shared-mime-info`, commented "WeasyPrint renders the clinical report PDF".
`grep -rn "weasyprint" apps/` returns nothing — it is in neither `pyproject.toml`
nor any source file.

**Why it matters.** Image size and, more to the point, attack surface: six native
libraries, several of them image and font parsers, shipped in the process that
holds patient records, for a feature not yet written. `pip-audit` in CI audits
Python packages and says nothing about these.

**Why it is not decided here.** `docs/plans/2026-09-19-build-system-and-deploy-path.md`
restructures the image layers and places these libraries in a `runtime-base`
stage (line 316). This is that plan's call, not this one's. **Action: raise it as
an open question on the build plan** — remove them until WeasyPrint is a declared
dependency, and add them in the same change that adds it.

---

### Bucket C — do when that area is next touched

#### F11. `identity/` is three packages in one folder · the largest structural finding

**Where.** `apps/api/src/eoehelp_api/identity/` — 18 flat modules, 2,414 lines,
plus `legal/*.md`. For comparison: `symptoms` is 8 files / 928 lines, `procedures`
8 / 987, `medications` 9 / 1,217. Measured split:

| Group | Modules | Lines |
|---|---|---|
| Legal documents | `documents.py`, `legal_document.py`, `legal_markdown.py`, `legal_router.py`, `legal_schemas.py`, `legal/*.md` | **917** |
| Account | `me_router.py`, `onboarding_service.py`, `patient.py`, `patient_schemas.py`, `user.py`, `consent.py` | **756** |
| Authentication | `auth_router.py`, `auth_schemas.py`, `auth_service.py`, `tokens.py`, `email.py` | **680** |
| Shared | `enums.py` | 57 |

Each group is the size of a whole clinical domain.

ADR 0010 explicitly decided against splitting identity: *"Identity keeps
descriptive module names (`auth_router`, `me_router`, `patient_schemas`), because
it has two routers and two sets of schemas. Splitting it into sub-packages would
add nesting and make nothing clearer."* That was true when it was written. It has
since acquired a **third** router, a **third** set of schemas, a markdown parser,
a model, a file-integrity registry, a startup reconciliation check, and a
directory of markdown documents. The premise of the decision has expired.

**Why it matters, and why legal in particular.** The legal documents are not
identity. They are public reference data: no session, no patient scope, no
repository, an unauthenticated router, and a table that deliberately has no RLS.
They live in `identity/` for one reason, stated in ADR 0011 — "the service that
holds a consent row can then produce the text behind it" — which is a *dependency*
argument, and dependencies are satisfied by direction, not by folder.

The concrete costs of the current arrangement:

- **`identity/enums.py` mixes three vocabularies.** `UserRole`, `UserStatus`,
  `SexAtBirth`, `ReviewStatus`, `ConsentType`, `ResearchScope` in one module. ADR
  0010's own opening argument against the layered layout was *"one enum module
  held every domain's enums, so nothing showed which enums belonged to which
  tables."* That smell has reappeared one level down.
- **`legal_document.py` is a model module that queries.** It defines
  `PublishedLegalDocument` and also `verify_published_revisions(session)`, which
  runs a `select`. No other model module in the codebase contains a query. This
  arrived with the in-flight work and is the one place where it made the
  organization slightly worse.
- **`main.py`'s lifespan reaches into a model module** to call it.
- The architecture test's `identity` rule cannot say anything useful, because
  "identity" now names three unrelated concerns.

**The change — the seam.** Create a top-level `legal/` package **below**
`identity`:

```
eoehelp_api/legal/
  __init__.py
  enums.py        ConsentType, ReviewStatus            (moved from identity/enums.py)
  models.py       PublishedLegalDocument               (from identity/legal_document.py)
  registry.py     Revision, LegalDocument, DOCUMENTS,  (from identity/documents.py)
                  current_for, resolve, text_for,
                  verify_integrity, enforce_review_status
  repository.py   verify_published_revisions           (the query, out of the model)
  markdown.py     the block grammar                    (from identity/legal_markdown.py)
  router.py       /legal/*                             (from identity/legal_router.py)
  schemas.py      the block DTOs                       (from identity/legal_schemas.py)
  documents/*.md  the text                             (from identity/legal/*.md)
```

Dependency direction: `legal` imports the foundation only; `identity` imports
`legal` (for `ConsentType` on the `consents` FK, and for `current_for` at
onboarding). `legal` never imports `identity`. Add to F1's `ALLOWED`:

```python
"legal": FOUNDATION,
"identity": FOUNDATION | {"audit", "deps", "legal"},
```

so the direction is proved rather than intended.

**What does *not* change.** No table names, no column names, no migration, no
route path, no OpenAPI schema, no response shape, no web code. `pyproject.toml`'s
`[tool.setuptools.package-data]` key changes from `"eoehelp_api.identity"` to
`"eoehelp_api.legal"`, and `documents/*.md` replaces `legal/*.md` —
`verify_integrity`'s own error message already tells the next reader to check
that key.

**Whether to split auth and account too.** Not yet, and possibly never. The
`auth`/`account` line is real but the two share `User`, and the friction is much
lower than legal's. Once `legal/` is out, `identity/` is 11 modules and ~1,440
lines — comparable to `food/`, and fine. Revisit only if a third router appears.

**Timing.** **Not before the consent-text reproducibility work is committed.**
This is a pure move of 917 lines that touches every file that plan is currently
changing. Do it as its own commit immediately after, with no behaviour change in
the same diff, so `git log --follow` and `make test-api` both tell a clean story.

---

#### F12. `identity` is the only area whose services build their own queries, and it has no repository

**Where.** `identity/onboarding_service.py` and `identity/auth_service.py` import
`select`/`update` and query directly. Every other domain has a
`repository.py`; `identity` has none. `deps.get_current_patient` also does
`session.get(Patient, principal.patient_id)`.

**Why it matters.** ADR 0002 layer one says: *"Repositories take a scope at
construction and apply it in a shared base query"* — the point being that
*"no statement can leave the patient filter out"*. In identity, that property is
held by convention instead:

```python
async def get_profile(self, patient_id: uuid.UUID) -> Patient:
    patient = await self._session.get(Patient, patient_id)
```

Every current caller passes `principal.patient_id` from the verified token, so
this is **safe today**. But the guarantee is "the caller passed the right id",
not "there is no wrong id to pass" — which is the difference ADR 0002 says
removes the bug class rather than guarding against it. Identity is the one place
where layer one is a promise rather than a shape. The account-deletion path runs
through here.

**The change.** When identity is next touched (naturally, right after F11):

- Add `identity/repository.py` with `PatientRepository(session, patient_id)`
  exposing `require_patient()`, `current_consents()`, and `add_consent()`, all
  scoped by construction like `SymptomEntryRepository`.
- `OnboardingService.get_profile` / `update_profile` / `current_consents` take
  the repository instead of an id.
- `AuthService` keeps its direct statements: it operates on `users`,
  `magic_link_tokens`, and `refresh_tokens`, which are keyed on `user_id` and not
  patient-owned, and its conditional-UPDATE concurrency control is the point of
  the code. State that exemption in the module docstring so it reads as a
  decision.
- `deps.get_current_patient` stays as it is — it is the request-wiring layer that
  *establishes* the scope, and its docstring already explains why.

---

#### F13. `OnboardingService` is four services

**Where.** `identity/onboarding_service.py`, 230 lines, one class with:
`complete()` (onboarding + consent + token issuance + audit), `get_profile()`,
`update_profile()`, `current_consents()`, `delete_account()`.

**Why it matters.** Account deletion is not onboarding. It is the My Health My
Data Act erasure right, it has the most delicate invariant in the file (the audit
trail must survive the rows it describes), and it is reached through a class
named for something else. `me_router` constructs `OnboardingService(session)`
four times for four different jobs. The next thing this area gains — consent
withdrawal, the account screen, re-consent — attaches to whichever of the four it
resembles, and the file keeps growing along a seam nobody chose.

**The seam.** Three modules, same package:

| Module | Holds | Lines today |
|---|---|---|
| `onboarding_service.py` | `complete()` and `OnboardedPatient` | ~110 |
| `profile_service.py` | `get_profile`, `update_profile` | ~40 |
| `account_service.py` | `current_consents`, `delete_account` | ~60 |

`current_consents` goes with `account_service` rather than `profile`: consent
state is what the account screen and the eventual withdrawal flow read, and it is
the natural home for re-consent.

**Timing.** Cheap, but it touches the files the in-flight work is changing. Do it
with F11 or the next time consent is edited — not on its own.

---

#### F14. The web app has no architecture test, and its layering is correct by accident

**Where.** `apps/web/src/app/`. Measured cross-feature imports:

| Feature | Imports from |
|---|---|
| `today/` | `food`, `medications`, `symptoms` |
| `log/` | `food`, `medications`, `symptoms` |
| `insights/` | `food`, `symptoms` |
| `onboarding/` | `legal` |
| `food/`, `symptoms/`, `medications/`, `legal/`, `auth/`, `landing/` | nothing outside themselves |

So `features/` actually holds two kinds of thing — **screens** (`today`, `log`,
`insights`, `onboarding`, `landing`, `auth`) and **domain modules** (`food`,
`symptoms`, `medications`, `legal`) — and the dependency direction is
consistently screens → domains, never the reverse and never domain → domain.
`shared/` imports only Angular. `core/` imports nothing from `features/`.
`api-client/` is imported by exactly one file, `core/api/api-types.ts`.

That is a good layering. Nothing states it and nothing checks it. It is the
mirror image of the API's situation before `test_architecture.py` existed, and
ADR 0010's own summary of why that test was written applies word for word:
*"Nothing enforced the boundaries the design depends on."*

**The change.** Add `apps/web/src/app/architecture.spec.ts` — a vitest spec that
reads the source tree with `node:fs` and asserts four rules. No new dependency.

```ts
// Screens compose domains; domains know nothing of screens. The generated
// client is reached through core/api only, so a schema change lands in one
// place. shared/ is domain-free by definition.
const SCREENS = ['today', 'log', 'insights', 'onboarding', 'landing', 'auth'];
const DOMAINS = ['food', 'symptoms', 'medications', 'legal'];

it('a domain feature does not import a screen or another domain', ...);
it('nothing outside core/api imports api-client', ...);
it('shared/ imports nothing from features/ or core/', ...);
it('core/ imports nothing from features/', ...);
```

Record the screen/domain distinction in ADR 0010's Web section at the same time —
it is a real part of the layout that the ADR does not currently describe.

**Cost.** ~60 lines of spec. This is the single highest-value web change in this
document.

---

#### F15. The web app's `core/` — session, guards, interceptor, dates — has no tests at all

**Where.** Spec coverage by file:

| Has a spec | No spec |
|---|---|
| `app.ts`, `food-editor`, `ingredient-text`, `product-picker`, `insights`, `pattern-text`, `trend-chart`, `legal-content`, `legal-document`, `dose-log`, `welcome` | **`core/auth/auth.service.ts`**, **`core/auth/auth.guard.ts`**, **`core/auth/auth.interceptor.ts`**, **`core/dates.ts`**, **`core/api/api-errors.ts`**, `core/patient.service.ts`, `core/reference.service.ts`, `food-log`, `today`, `log`, `medications`, and every data service |

**Why it matters.** The tested files are the presentation helpers — genuinely
well covered, and `pattern-text.spec.ts` in particular is the right kind of test
for clinical wording. The untested files are the ones where a defect is a
security or correctness incident rather than a cosmetic one:

- `auth.service.ts` holds the single-flight `restore()`/`refresh()` logic whose
  own comments explain that getting it wrong makes a legitimate reload *look to
  the server exactly like a stolen token being replayed* — which triggers
  server-side family revocation and signs the patient out everywhere. That
  interaction has no test on either side.
- `auth.interceptor.ts` decides which 401s trigger a refresh, by substring match
  against a hardcoded endpoint list.
- `core/dates.ts` is the browser's half of the timezone contract. Its docstring
  is explicit that `toISOString()` would make a Los Angeles patient at 8pm write
  a day that has not happened. It is pure, has no dependencies, and would take
  fifteen minutes to test exhaustively.
- `api-errors.ts` decides what a patient is told when a submission fails,
  including the rule that submitted values (their health data) are never echoed.

**The change.** Four spec files, in this order: `dates.spec.ts` (pure, trivial),
`api-errors.spec.ts` (pure, including "never echoes the value"),
`auth.interceptor.spec.ts`, `auth.service.spec.ts` (single-flight: assert two
concurrent `restore()` calls produce exactly one `POST /auth/refresh`). Do them
as that area is touched; do `dates` and `api-errors` now, they cost nothing.

---

#### F16. The web app is not in TypeScript strict mode

**Where.** `apps/web/tsconfig.json` sets `noImplicitOverride`,
`noPropertyAccessFromIndexSignature`, `noImplicitReturns`,
`noFallthroughCasesInSwitch` — but **not** `"strict": true`, and
`angularCompilerOptions` sets `strictInjectionParameters` and
`strictInputAccessModifiers` but **not** `strictTemplates`. Angular's own
generator emits both by default, so this is very likely an omission rather than a
decision.

**Why it matters.** The API is `mypy` strict and CI gates on it. The web app —
which renders eos/hpf counts, EREFS sub-scores, DSQ burden, and food-pattern
statuses — is not. Without `strictNullChecks`, an optional field from the
generated schema (`string | null`) assigns freely to `string`, which is exactly
how a missing value becomes a rendered `null` or a silently wrong number on a
clinical screen. Without `strictTemplates`, none of it is checked inside
templates, and `food-log.ts` uses an untyped `ng-template` outlet
(`let-item let-dark="dark"`) for its per-item action row.

**Encouraging evidence.** The codebase is already written as if strict were on:
across all of `src/app` (excluding the generated client) there are **zero**
occurrences of `: any` or `as any`, and **zero** non-null assertions. The cost of
turning it on is plausibly small.

**The change.** Measure first — `node_modules` is a podman volume here, so run it
in the container:

```
make web-check  # baseline
podman run --rm -v "$PWD/apps/web:/app:z" -v eoehelp_web_node_modules:/app/node_modules \
  -w /app node:24-bookworm-slim sh -c "npm ci --silent && npx tsc -p tsconfig.app.json --noEmit --strict"
```

Then enable `"strict": true` and `"strictTemplates": true`, fix what falls out,
and record the error count in this plan's review log as evidence. If it is more
than a day's work, enable `strict` alone first and `strictTemplates` when the
templates are next touched.

---

#### F17. `food-log.ts` carries a 250-line inline template while its siblings use `templateUrl`

**Where.** Nine components use `template:` inline, six use `templateUrl:`. The
split is broadly sensible — small presentational components inline, screens in
files — with one clear outlier: `features/food/food-log.ts` is 425 lines, most of
it an inline template, and it is a screen-level component sitting beside
`food-editor.ts`, which uses `food-editor.html`.

**Why it matters.** Only mildly: the file is the one place a food-log change has
to happen, and 250 lines of HTML inside a `.ts` file means Prettier's Angular
parser never touches it and the template is not diffed as a template.

**The change.** Extract `food-log.html` the next time that screen is edited. Do
not churn the other eight — the convention "screens get files, small components
stay inline" is fine and `food-log` is simply on the wrong side of it.

---

## Leave it

Be explicit about this. Each of these was examined and is right as it stands.
Changing any of them would be churn.

**The clinical domain packages.** `symptoms/`, `medications/`, `procedures/`, and
`food/` are the reference implementation of ADR 0010 and should be the model for
everything else. Router maps HTTP and nothing else; service holds rules;
repository is the only code that queries patient-owned tables and is scoped by
construction; schemas are the only types returned. `symptoms/repository.py`'s
`add()` even refuses to write another patient's row rather than silently
correcting it. `food/`'s extra modules (`exposure.py`, `presenters.py`) earn
their existence — `exposure.py` in particular is one definition of "what did this
food contain" shared by the display and the analysis, which is exactly the
duplication worth preventing.

**`insights/` as a package above the domains.** It reads through
`SymptomEntryRepository` and `FoodRepository` and adds no query of its own;
`food_patterns.py` is pure (days in, statuses out, no clock, no database) so the
synthetic validation runs the code that ships; `statistics.py` is standard
library only. The architecture test has a rule for it. This is the pattern the
doctor report and the dashboards should copy verbatim.

**The `/me` route convention.** Eleven routers, and there is no `/patients/{id}`
anywhere. Patient data is under `/me/*` in every case
(`/me`, `/me/symptoms`, `/me/foods`, `/me/medications`, `/me/endoscopies`,
`/me/insights`); everything else is unowned reference data or session management
(`/foods`, `/medications`, `/reference`, `/legal`, `/auth`). `/auth/session`
returns the user, not the patient, and belongs where it is. Not one exception.

**Migrations staying self-contained.** ADR 0010's reasoning holds and the tree
matches it: no migration imports application code, so F11's module moves require
no migration edits at all. That property is worth more than the repetition costs.
(F9 is not a counter-example — it asks for *fewer* cross-migration dependencies,
not a shared helper.)

**`db/`, `core/`, `audit/`.** 137, 356 and 165 lines. Each module does one thing.
`db/session.py`'s transaction-scoped `set_config` and `audit.record` taking the
caller's session are both load-bearing decisions with the reasoning written down
beside them.

**`food/products/`.** A sub-package for two external data sources, a label
parser, a vocabulary, and a shared record type — the only sub-package in the API,
and it is justified: seven modules that would otherwise double `food/`'s file
count, with a clean boundary (`provider.py` is the only thing the rest of `food`
talks to).

**`synthetic/`.** Correctly isolated (nothing imports it, proved by a test),
correctly refuses to run in production, and `writer.py` sets the RLS scope like
real code does. `plans.py`/`generator.py`/`writer.py` is the right three-way
split: planning is pure and testable without a database.

**The domain-mirrored test folders.** `tests/food/`, `tests/symptoms/`, and so on
matching the source packages is right, recorded fixtures sit next to the tests
that use them, and no test module imports another. Keep it.

**The layered isolation testing.** One catalogue-driven database test
(`test_every_patient_owned_table_has_row_level_security`, which asks `pg_class`
so the next table is covered without editing the test) plus a per-domain
API-level cross-patient test in symptoms, food, medications, insights, procedures
and onboarding. That is two independent layers, not duplication. The one
inconsistency — procedures' cross-patient test lives in `TestPrivacy` rather than
a `TestIsolation` class — is cosmetic; rename it if you are in the file anyway.

**The overlap between `test_patient_isolation.py` and `test_consent_grants.py`.**
Both touch reference-data grants, and it looks like duplication. It is not:
`test_patient_isolation` proves the *behaviour* (a write raises "permission
denied" as `app_runtime`), `test_consent_grants` proves the *grant* via
`has_table_privilege` **and** asserts the absence of default privileges in the
application database — which is the assertion whose absence let the real defect
live. Both files carry a docstring explaining why the other exists. Leave them.

**`tests/helpers.py` as a single module.** It does five unrelated jobs
(onboarding payloads, auth headers, dates, food builders, the `app_runtime` URL
rewrite, the synthetic→`PatternInput` conversion) and at 100 lines that is fine.
ADR 0010 chose it deliberately. Split it only if it doubles.

**Prettier without ESLint on the web app.** ADR 0010 decided this and explained
it (the previous lint step ran nothing). Do not reopen it. F14 and F16 deliver
most of what a linter would have caught, with less machinery.

**The inline-vs-file template mix** (beyond F17), the separate `to_read` methods
on services versus `food/presenters.py`, `config.py` at 164 lines, the ADR
numbering, `docs/plans/README.md`, and the `.claude/` agents and skill. The
agents and the skill are coherent, the review matrix in `SKILL.md` matches the
reviewers that exist, and the plans folder has a template that is actually used.
Nothing to do.

---

## The moves, in order

| # | Move | Touches | Risk | Do it |
|---|---|---|---|---|
| 1 | F1 — every package needs a stated dependency rule | `tests/test_architecture.py` | none | now |
| 2 | F2 — routers reach no data, enforced properly | `tests/test_architecture.py` | none | now |
| 3 | F6 — `--import-mode=importlib` + `pythonpath` | `pyproject.toml` | none | now |
| 4 | F5 — derive `clean_tables` from metadata | `tests/conftest.py` | none | now |
| 5 | F4 — one owner for process globals; app fixture runs the lifespan; `test_global_state.py` | `tests/conftest.py`, new test | low — may surface 1–2 real order deps | now |
| 6 | F3 — constraint-name test covers all constraint types | `tests/db/test_patient_isolation.py` | none | now |
| 7 | F7 + F8 — one declaration of the session types; delete `authGuard` | `core/api/api.ts`, `auth.service.ts`, `auth.guard.ts` | none | now |
| 8 | F9 — per-table grants in 0001; 0006 keeps only its own | `alembic/versions/0001`, `0006` | medium — rebuild the dev DB | **now, window closing** |
| 9 | F10 — hand the WeasyPrint libraries to the build plan | that plan's open questions | none | now |
| 10 | F15a — specs for `core/dates.ts` and `core/api/api-errors.ts` | new specs | none | now |
| 11 | F14 — web architecture spec + ADR 0010 Web section | new spec, ADR | none | now |
| 12 | **F11 — extract `legal/` from `identity/`** | 917 lines moved, `models.py`, `main.py`, `pyproject.toml`, ADR 0010 | medium — pure move, no behaviour change | **after the consent-text work is committed** |
| 13 | F12 + F13 — `identity/repository.py`; split `OnboardingService` | `identity/` | low | with 12, or next consent change |
| 14 | F16 — measure, then enable `strict` / `strictTemplates` | `tsconfig.json` + fallout | unknown until measured | next web change |
| 15 | F15b — specs for the auth service and interceptor | new specs | none | next auth change |
| 16 | F17 — extract `food-log.html` | one file | none | next food-log change |

Moves 1–11 are independent of each other and of the in-flight work; each is its
own commit. Moves 12–13 are one commit each and must not begin before the
consent-text reproducibility change is committed.

---

## Documentation that must change with the code

- **ADR 0010** needs three amendments, in the same commits as the code:
  1. The layout block does not list `insights/` (added later) or
     `identity/legal/`. Add `insights/` now; add `legal/` with move 12.
  2. The *Things deliberately left alone* paragraph — "identity keeps
     descriptive module names… splitting it into sub-packages would add nesting
     and make nothing clearer" — is superseded by move 12 for the legal half.
     Amend it rather than deleting it: record that it was true at two routers and
     stopped being true at three.
  3. The Web section should state the screen/domain distinction that F14's spec
     enforces.
- **`apps/api/README.md`**'s layout table needs the `legal/` row with move 12,
  and its invariant 1 ("patient data is reached only through a scoped
  repository") becomes literally true with F12 rather than true-with-an-exception.
- **This plan's review log** records the measured strict-mode error count from
  F16 and the outcome of F4's structlog check.

---

## Testing

There is no feature here, so "the tests that prove it" is mostly "the tests
*are* the change". Specifically:

- **Moves 1, 2, 3, 6, 11** are new or widened tests. Each must be shown to fail
  before it passes: temporarily add a forbidden import, an off-convention
  constraint name, a router `session.get` with a path id, and a
  `features/food` → `features/today` import, and confirm each is caught.
- **Move 5** is proved by the suite passing in a full run *and* by
  `pytest tests/identity`, `pytest tests/core`, and `pytest tests/insights`
  individually — the subsets whose behaviour currently differs. Additionally run
  the full suite twice in one session if that is practical.
- **Move 8** is proved by the existing `tests/db/test_consent_grants.py` (six
  assertions, unchanged) plus `tests/db/test_patient_isolation.py`, against a
  rebuilt database, plus CI's `upgrade head → downgrade base → upgrade head`.
- **Move 12** is proved by the full API suite passing with **zero test-file
  changes other than import paths**, and by `make openapi` producing a byte-
  identical `packages/openapi/schema.json`. If the contract moves, the move was
  not pure and something else changed.
- **Moves 7, 10, 14, 15, 16** are proved by `make web-check`.

---

## Open questions

1. **Add `pytest-randomly` (pinned) as a dev dependency, so ordering coupling
   fails immediately instead of eventually?**
   F4 removes the coupling that exists; it does not prevent the next one, and a
   single maintainer will not notice the next one until it wastes an afternoon.
   *Recommended default: yes.* Pin it exactly, like `ruff` and `mypy` are pinned
   and for the same stated reason, and have CI print the seed so a failure is
   reproducible. Cost: one dev dependency, and some real failures the first time
   it runs — which is the point.
2. **Is `legal/` the right name and the right level for move 12?**
   The alternatives are `consent/` (but the package is about documents, not
   consent, which stays in `identity`) and a `identity/legal/` sub-package (which
   keeps the misleading parentage and prevents the architecture test from stating
   the direction).
   *Recommended default: top-level `legal/`, with `ConsentType` and `ReviewStatus`
   moving into `legal/enums.py` and `identity` importing them.* If you would
   rather not move `ConsentType`, the alternative is to leave both enums in
   `identity/enums.py` and have `legal` import `identity.enums` — but that
   reverses the dependency and makes the boundary unprovable, so I would not.
3. **Does F9 (rewriting 0001's grants) happen now or never?**
   *Recommended default: now.* It needs a development database rebuild, which the
   in-flight consent work already required, and after the first real patient the
   only remaining option is another compensating migration — a third place
   where `consents`' privileges are decided.
4. **F16: accept whatever `strict` + `strictTemplates` costs, or timebox it?**
   *Recommended default: measure first, then decide.* The zero `any` / zero `!`
   result suggests it is cheap, but that is an inference, not a measurement.
   Enable `strict` regardless of the number; make `strictTemplates` conditional
   on it being under a day.
5. **Does the WeasyPrint native-library question (F10) belong to the build plan
   or here?**
   *Recommended default: the build plan*, since it is already restructuring those
   layers. Raise it there rather than editing the Dockerfile from this plan.

---

## Review log

| Round | Reviewer | Verdict | What changed |
|---|---|---|---|
| 1 | architect (self-check) | Draft ready | Audit written after reading both applications, all six migrations, all 31 API test modules and all 11 web specs, all web sources, the infrastructure files, every ADR, the plans folder, and the `.claude/` agents and skill. Measurements taken rather than estimated: package sizes (`identity` 18 files / 2,414 lines vs `symptoms` 8 / 928; the legal/account/auth split at 917/756/680), web cross-feature import map (screens → domains only, no domain → domain, `api-client` imported by exactly one file, `shared/` importing only Angular), web spec coverage file by file (all of `core/` untested), `op.f()` versus literal constraint names per migration (1/24, 5/11, 3/12, 1/20, 6/19, 4/8), zero `any` and zero non-null assertions in the web app, and the absence of `weasyprint` from `pyproject.toml` while its native libraries ship in the runtime image. **Clinical soundness:** nothing here changes an instrument, threshold, computation or patient-facing word; F4 is flagged because it affects how strongly the PHI-scrubbing control is *proved*, not what it does. **Patient isolation:** F2 and F12 are the isolation findings — the "routers do not query" rule misses `session.get`, and `identity` holds ADR 0002 layer one by convention rather than by construction; both are safe today and neither is structurally guaranteed. **Privacy and PHI:** F4 records that the app under test never runs its lifespan, so `configure_logging` is an ordering side effect and PHI scrubbing is proved only at function level; the structlog `logger_factory` question is stated as something to verify rather than asserted. **Architecture:** F1 is ranked first because a guardrail that silently skips unlisted packages is worse than none for a single maintainer, and `research/` is the package where that would cost the most. **Data model and migrations:** F9 is the window-closing item — grants decided in two places, five revisions apart, in the one table that is legal evidence; no shared migration helper is proposed, per ADR 0010. **API contract:** move 12 must produce a byte-identical `schema.json`; that is stated as its acceptance test. **Frontend:** F14 (architecture spec) ranked above F16 (strict mode) because it locks in layering that is currently correct and undefended; no accessibility or charting change is proposed. **Testing:** the flake is treated as evidence — the nine-item global-state table is the finding, the reset fixture and `test_global_state.py` are the response. **Scope:** the Makefile/CI duplication is out of scope by instruction and F10 is handed to that plan rather than decided; *Leave it* names fourteen things that were examined and should not be touched. **Decisions:** five open questions with defaults, led by `pytest-randomly` and the `legal/` naming. Not resolved here: the strict-mode cost, which needs `node_modules` inside the container to measure. **On the in-flight work:** it is sound and mostly improves matters; the one place it made organization worse is `identity/legal_document.py`, a model module that contains a query, which move 12 corrects by moving that query into `legal/repository.py`. |

## Decisions — 2026-09-22

The user chose the two buckets to act on, once the in-flight consent-ledger work
is committed:

- **The cheap enforcement fixes.** F1 (package-rule inversion), F2 (router
  data-access rule), F3 (constraint-name test), F4 (one owner for global state,
  `test_global_state.py`, and running the lifespan in the `app` fixture), F5
  (`clean_tables` derived from `Base.metadata`), F6 (`--import-mode=importlib`),
  F7 (delete the hand-written `AccessTokenResponse`/`SessionUser`), F8 (delete
  the unused `authGuard`), F14 (web architecture spec), F15a (specs for
  `core/dates.ts` and `api-errors.ts`).
- **F9, the grants rewrite**, because the window closes at the first deploy: 0001
  grants per table, 0006 drops its compensating revokes, and
  `tests/db/test_consent_grants.py` starts proving the right migration. The
  development database is rebuilt, which the in-flight work already required.
- **`pytest-randomly`, pinned**, with CI printing the seed (open question 1,
  default accepted). It is expected to fail on its first run; that is what it is
  for.

**Deferred, as the audit itself ranked them:** F11 (extract `legal/`), F12
(`identity/repository.py`), F13 (split `OnboardingService`), F16 (TypeScript
`strict`), F15b, F17. Open questions 2 and 4 go with them and stay unanswered
until that work starts. Open question 5 (the WeasyPrint system libraries) is
handed to `docs/plans/2026-09-19-build-system-and-deploy-path.md` as the audit
recommends.

**Already acted on, because it was a live defect rather than a reorganization:**
the audit's observation that `caplog` cannot see application log lines was
confirmed — `structlog.get_config()` reports `PrintLoggerFactory`, so nothing
the application logs becomes a stdlib record. `tests/core/test_log_paths.py`
asserted only over `caplog` and therefore passed by capturing nothing. It now
asserts against stdout as well, and carries a second test that logs a line and
proves the capture can see it. A security assertion that cannot fail is worse
than no assertion.

The broader half of that finding stands and is **not** fixed: `scrub_event` runs
only in structlog's pipeline, so anything a library logs through stdlib bypasses
PHI scrubbing entirely. That belongs with F4's owner-for-globals work.
