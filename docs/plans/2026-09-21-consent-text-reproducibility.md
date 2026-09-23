# Consent text reproducibility: a published-document ledger in the database

**Status:** Draft · 2026-09-21
**Follows:** [2026-09-19-legal-documents.md](2026-09-19-legal-documents.md) ·
amends [ADR 0011](../adr/0011-legal-documents.md)

## Goal

`consents.document_sha256` exists so that the exact wording a patient agreed to
can be produced years later. Today it cannot be, and the development database
proves it.

Afterwards:

- Every digest that can be written into `consents` names bytes the API can
  still serve. The database enforces it, not a convention.
- A patient (or a regulator, or counsel) following a link from a consent record
  reads **the bytes that were on the screen**, and is told plainly when those
  bytes are no longer the current wording.
- Changing a published document's text requires a migration. Editing a file and
  its recorded digest in one commit stops the API from starting instead of
  silently re-pointing old consent rows at new wording.
- `research_consent_scopes` is covered by row-level security by having a
  `patient_id`, not by having no column the isolation test looks for.

## Evidence: what is actually wrong

Run against the development database on 2026-09-21 (read-only):

```
 document_version |                 document_sha256                  | count
------------------+--------------------------------------------------+-------
 chd-2026-09      | 95f1203ff97d4930bc57aa2adee4a8358289d836ea3f...  |     9   <- unresolvable
 chd-2026-09      | 188a1cc1575cab899b2b9cec222a030592ebacf9d10...  |     9
 privacy-2026-09  | 22bc6124136d33243c99561f5fd36e922d7057c75b6...  |     9   <- unresolvable
 privacy-2026-09  | 6eb6642accabc882a2373c72ec44091983c4ba5abde...  |     9
 tos-2026-09      | fc77de9e77df177b093203286a1640110c8f8bdaffc...  |     9   <- unresolvable
 tos-2026-09      | 450b7d1254ec252dcd2d11023ec6a4cc3b6312e0c05...  |     9
(54 rows total; 27 point at bytes nothing can produce)
```

`git log -- apps/api/src/eoehelp_api/identity/legal/` returns exactly one
commit (`c6c1820`), so the pre-legal-review bytes behind those three orphan
digests were **never committed**. They are not recoverable from the repository,
from the API, or from history. The feature's central promise failed on its first
wording change, in the same week it shipped, and nothing noticed — because the
only witness to "what was published" was the same commit that changed it.

Three separate holes produced that:

1. `verify_integrity()` compares each file to a digest that lives in the same
   file tree. Editing both together passes.
2. `GET /legal/documents/{id}` resolves a version id to *whatever bytes that
   version has now*. There is no way to ask for a specific text, and no
   indication that the text on screen differs from the text that was agreed to.
3. Nothing constrains what may be written into `consents.document_sha256`. Any
   64 hex characters are accepted, including the digest of another document or
   of text that no longer exists.

## Clinical basis

No clinical computation and no instrument. Two patient-facing strings are added
and both are descriptive statements of fact about the record, not instructions:

- Older-wording notice (icon plus text, `role="note"`): **"This is an earlier
  wording of this document. It is kept so that a consent recorded against it can
  still be read."**, with a link labelled **"Read the current wording"**.
- The existing superseded-version notice is unchanged.

Nothing here tells a patient to do anything, and no clinical claim changes. No
clinical confirmation is pending for this change.

## Decision: the structural shape, not the code-only one

The database reviewer offered two shapes. This plan takes the **structural**
one — a `legal_documents` reference table populated by migration, with a
composite foreign key from `consents` — with one change to its detail (below).

Why, in the order that decided it:

1. **The code-only option keeps the same single witness.** Its improvement is
   real (the API could serve a superseded revision) but the defect that actually
   occurred — file and digest changed in one commit — still passes every check,
   because every check lives in the commit. A ledger written by a migration is
   the only artifact in this system that a later commit cannot rewrite: once it
   has run, the rows are in the deployed database, and a build that disagrees
   with them can be made to fail at boot.
2. **A foreign key is a guarantee; a test is a reminder.** With the composite FK,
   "a consent row names a published revision of the right document" is true of
   every row that exists, including rows written by code paths nobody
   anticipated (a future re-consent endpoint, a research consent, a fixture, a
   hand-run backfill). The 27 bad rows were written by exactly such a path.
3. **It costs one table with five rows and one index.** Everything else already
   exists. The reference-data pattern (`GRANT SELECT` to `app_runtime`, no RLS)
   is already established by `ingredient_catalog` and `clinical_instruments`, and
   the isolation suite already has a test for it.
4. **It makes the publishing rule operational instead of aspirational.**
   "Republishing needs a migration" becomes literally true, and the migration
   file is a dated, reviewed record of what was published and when.

The change to the reviewer's detail: a row is a **revision**, not a document, so
the primary key is `(version, content_sha256)` rather than `version`. A version
id may legitimately carry more than one set of bytes — see the publishing rules
below — and a `version` primary key would forbid the one case that actually
happens in this product today.

## The publishing rules this design enforces

These answer the three questions the defect raises.

**A revision is the unit of evidence:** `(consent_type, version, content_sha256)`.
A revision is *published* when a migration inserts it into `legal_documents`.

1. **A material change is a new version id.** New rights, obligations, wording
   with different meaning, a new effective date: `tos-2026-09` →
   `tos-2027-03`. Existing patients are no longer covered, and the (deferred)
   re-consent flow re-prompts. This is the intended friction and it is unchanged.
2. **A correction to a draft is a new revision of the same version id.** While a
   document is a draft it is being corrected constantly — the eight legal-review
   corrections are the example, and forcing a new public version id for each
   typo would churn ids that patients see and that the ledger records. So a
   version may accumulate revisions `r1, r2, …` while it is a draft, each with
   its own file, its own digest, and its own ledger row. Consents pinned to `r1`
   keep resolving to `r1`'s bytes.
3. **A reviewed revision is frozen.** Once a revision is `attorney_reviewed`, no
   further revision may be added under the same version id: rule 1 applies
   instead. This is checkable from the registry, because review status moves onto
   the revision — a test asserts that no revision other than the newest carries
   `attorney_reviewed`.
4. **Retention.** A reviewed revision's file stays in the repository
   permanently. A draft revision's file may be retired *only when no consent row
   references it*, and the foreign key is what makes that a fact rather than a
   claim: retiring means a migration that deletes the ledger row, which the
   database refuses while a consent points at it. For the three current files,
   whose only consents are synthetic, that means nothing has to be kept that
   nobody agreed to.
5. **Before the first deployment — today — migrations may still be edited in
   place, and the development database is rebuilt instead.** That is the only
   window in which the ledger is rewritable, and it closes at the first deploy.
   Said explicitly in the migration docstring so the next person does not
   generalise from it.

### What this means for the re-consent flow (still deferred, not built here)

Nothing in this plan builds it, but two of its decisions are now easier and one
is now explicit:

- The "is this patient covered?" predicate has two candidate forms: latest
  granted consent per required type matches the current **version**, or matches
  the current **digest**. The digest form is now cheap and exact. Recommended
  default in *Open questions*.
- Its "here is what you agreed to before" link becomes
  `/legal/<document_sha256>`, which is what makes the comparison honest. That URL
  exists after this change.
- The account screen and the withdrawal path are unaffected, except that the
  account screen gets the same digest link. Both stay out of scope.

## Scope

**In scope**

- `legal_documents` reference table, populated by migration, with a composite FK
  from `consents (consent_type, document_version, document_sha256)`.
- A startup reconciliation between the registry and the ledger.
- The registry becomes revision-aware; the three document files are renamed to
  `<version>.r1.md` (bytes, and therefore digests, unchanged).
- `GET /api/v1/legal/documents/{document_id}` resolves a content digest;
  `LegalDocumentRead` gains `current_content_sha256`.
- The web document page gains the older-wording notice.
- `research_consent_scopes` gains `patient_id`, the standard `patient_isolation`
  policy, and a composite FK binding it to its parent consent's patient.
- ADR 0011 amended.
- Regenerated OpenAPI contract and web types.

**Out of scope**

- The re-consent flow, the account screen, and the consent-withdrawal path. All
  three remain deferred with their existing open questions.
- Recovering the 27 orphaned development consent rows. Their bytes were never
  committed; they cannot be recovered, and the remedy is to rebuild the
  development database.
- Any change to the three documents' text. This change must not alter a byte of
  them, and the digests in the registry and in migration 0006 are the proof.
- Storing document text in the database. The files stay the source; the ledger
  stores digests only. Text in two places is two things to keep in step.

## Design

### Data model and migrations

Everything below goes into the **existing** migrations, edited in place, because
nothing is deployed and the development database must be rebuilt anyway (the
stale rows make the new foreign key unsatisfiable). `alembic downgrade` is not
a remedy here: see the migration docstring requirement below.

#### New table `legal_documents` (in `0006_consent_document_digest.py`)

Model: `apps/api/src/eoehelp_api/identity/legal_document.py`, class
`PublishedLegalDocument`. A row is one published revision; the table is named for
what it is a ledger of, and the primary key carries the revision.

| Column | Type | Notes |
|---|---|---|
| `version` | `String(64)`, NOT NULL | `tos-2026-09`; must match `consents.document_version`'s type exactly for the FK |
| `content_sha256` | `String(64)`, NOT NULL | lowercase hex of the file's bytes |
| `consent_type` | `consent_type` enum, NOT NULL | `pg_enum(ConsentType, "consent_type")`; in the migration, `postgresql.ENUM(..., name="consent_type", create_type=False)` |
| `published_at` | `TIMESTAMPTZ`, NOT NULL, `server_default=func.now()` | when the migration inserted it; provenance the registry cannot hold |

Constraints, all named explicitly so a later migration can find them:

- `PrimaryKeyConstraint("version", "content_sha256", name="pk_legal_documents")`
- `UniqueConstraint("consent_type", "version", "content_sha256",
  name="uq_legal_documents_consent_type_version_content_sha256")` — the FK target.
- `CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'",
  name="content_sha256_is_hex")` → `ck_legal_documents_content_sha256_is_hex`.
- `CheckConstraint("version ~ '^[a-z0-9-]{3,64}$'", name="version_is_a_url_id")`
  → `ck_legal_documents_version_is_a_url_id`. A version id is a path segment in
  `/legal/{id}`; the route already restricts the shape and the database should
  agree rather than trust it.

Deliberately **not** in this table: `title`, `slug`, `effective_on`,
`review_status`. Each of them duplicates the registry, none of them has a reader
in the database, and every duplicated column is a drift surface — which is the
class of bug this whole change exists to remove. Review status in particular
changes without the bytes changing (an attorney reviews text that is already
published), so a stored copy would be stale the day it mattered.

#### The foreign key from `consents`

```python
ForeignKeyConstraint(
    ["consent_type", "document_version", "document_sha256"],
    [
        "legal_documents.consent_type",
        "legal_documents.version",
        "legal_documents.content_sha256",
    ],
    name="fk_consents_document_revision_legal_documents",
)
```

No `ON DELETE` / `ON UPDATE` clause: the default `NO ACTION` is the guarantee —
a published revision cannot be removed from the ledger while a consent names it.

Three columns rather than two, because the third one is free (both columns
already exist on both sides, at the cost of one unique index) and it closes a
class of mislabelled evidence: a consent row of type `privacy_policy` can no
longer point at the terms of service's digest.

**No index on the child side.** The only operation that would use one is a
migration-time `DELETE` from a five-row parent table, on a child table where
every application query already filters by `patient_id` through
`ix_consents_current`. That operation must be correct, not fast.

#### Backfill and the stale-row guard (rework of 0006's upgrade)

Order inside `upgrade()`:

1. `create_table("legal_documents", …)`.
2. Insert the published revisions from a module-level literal
   `PUBLISHED_REVISIONS: tuple[tuple[str, str, str], ...]` — `(consent_type,
   version, content_sha256)`. This replaces the existing `DIGESTS` dict, so the
   digests are declared once in the migration and used for both the ledger and
   the backfill.
3. `add_column("consents", document_sha256 nullable=True)`.
4. Backfill from the ledger rather than from per-version literals:
   ```sql
   UPDATE consents c
      SET document_sha256 = d.content_sha256
     FROM legal_documents d
    WHERE d.version = c.document_version
      AND d.consent_type = c.consent_type
      AND c.document_sha256 IS NULL
   ```
   Valid only because 0006 publishes exactly one revision per version. A later
   publication migration **never** backfills; the docstring says so.
5. The existing uncovered-version guard (the implementer's in-flight change),
   unchanged.
6. `alter_column(… nullable=False)`.
7. The existing hex check constraint.
8. **New: the stale-digest guard, before the FK is added.** Rows whose
   `(consent_type, document_version, document_sha256)` is not in the ledger
   would make `create_foreign_key` fail with an opaque message. Query them
   first and raise a `RuntimeError` listing *versions and counts only* — never a
   patient id, never a digest belonging to a row this migration cannot explain —
   with the remedy: before deployment, rebuild the development database
   (`make clean && make up && make seed`); after deployment, publish the missing
   revision's bytes and add them to a migration, because deleting a consent row
   is destroying a legal record.
9. `create_foreign_key(… "fk_consents_document_revision_legal_documents" …)`.
10. Grants, in the existing `DO $$` block alongside the implementer's
    `REVOKE UPDATE, DELETE ON consents`:
    ```sql
    GRANT SELECT ON legal_documents TO app_runtime;
    REVOKE UPDATE, DELETE ON research_consent_scopes FROM app_runtime;
    ```
    `legal_documents` gets `SELECT` only. 0001's `GRANT … ON ALL TABLES` covered
    only the tables that existed then, so a new table starts with no grants —
    the pattern 0002's docstring already records.

`downgrade()` drops the FK, the check constraint, the column, and the table, in
that order. The docstring the implementer is adding about what a downgrade
destroys must also say that dropping `legal_documents` discards the record of
what was ever published, and that re-upgrading reconstructs only the revisions
listed in this file.

#### The honesty limit of the backfill, stated in the docstring

Step 4 assigns the *current* digest of a version to every row that has none.
That is only truthful because every such row is synthetic, pre-deployment data.
Against a database holding real consents it would fabricate evidence: it would
assert that patients agreed to bytes nobody has checked they ever saw. The
docstring must say this in those terms, because the next person to write a
backfill of this kind will read this one first.

#### `research_consent_scopes` (in `0001_initial_identity_and_consent.py`)

Confirming the reviewer, and it belongs in **this** change: the table is empty
(verified), it lives in the same model file and the same migration family, it is
already going through database and security review for the FK work, and the cost
of doing it later is a data migration on live consent evidence.

- Add `patient_id: uuid NOT NULL` to the table definition in 0001.
- Replace the single-column FK to `consents.id` with a composite one:
  ```python
  ForeignKeyConstraint(
      ["consent_id", "patient_id"],
      ["consents.id", "consents.patient_id"],
      ondelete="CASCADE",
      name="fk_research_consent_scopes_consent_id_consents",
  )
  ```
  which requires `UniqueConstraint("id", "patient_id", name="uq_consents_id_patient_id")`
  on `consents`. Without it, a denormalised `patient_id` is an unchecked claim,
  and a row claiming the wrong patient would be *visible to the wrong patient*
  under the new policy — the denormalisation would have created the leak it was
  added to prevent.
- **No separate FK to `patients`.** The composite FK already guarantees a real
  patient and gives one cascade path (`patients → consents → research_consent_scopes`).
  A second path to the same rows is noise in a schema whose deletion semantics
  have to be explainable in a privacy policy.
- Add `"research_consent_scopes"` to `RLS_TABLES` in 0001, which gives it
  `ENABLE ROW LEVEL SECURITY` and `CREATE POLICY patient_isolation … USING
  (patient_id = NULLIF(current_setting('app.current_patient_id', true), '')::uuid)`
  — the same single policy style as every other patient-owned table.

Rejecting the alternative explicitly: a `consent_id IN (SELECT id FROM consents)`
policy would be a second policy style in a schema whose isolation story is
currently one sentence long, it would make this table's isolation depend on
`consents`' policy being right, and it would leave
`test_every_patient_owned_table_has_row_level_security` passing by omission —
which is how this was found.

Model changes in `identity/consent.py`: the new column and constraint, and the
`scopes` relationship cascade narrows from `"all, delete-orphan"` to
`"save-update, merge"`. Deletion is the database's job through the cascade
above, and with `DELETE` revoked from `app_runtime` an ORM-issued delete would
now fail at runtime instead of being merely unnecessary.

### The registry becomes revision-aware

`identity/documents.py`:

```python
@dataclass(frozen=True)
class Revision:
    """One published set of bytes for a version."""
    sha256: str                     # lowercase hex of the file's bytes
    review_status: ReviewStatus


@dataclass(frozen=True)
class LegalDocument:
    consent_type: ConsentType
    version: str
    slug: str
    title: str
    effective_on: date
    # Oldest first, never empty. revisions[-1] is the current text; earlier
    # entries are bytes a consent row may still name.
    revisions: tuple[Revision, ...]

    @property
    def current(self) -> Revision: ...
    @property
    def sha256(self) -> str: ...            # current.sha256 — existing callers unchanged
    @property
    def review_status(self) -> ReviewStatus: ...   # current.review_status
    def path_for(self, sha256: str) -> Path:       # legal/<version>.r<n>.md, n = index + 1
    @property
    def path(self) -> Path: ...
```

`review_status` moves onto the revision. That is what makes rule 3 checkable
from a static registry: a reviewed revision that is not the newest means reviewed
bytes were superseded under the same version id, which is exactly the thing that
must never happen. It also lets a patient reading older bytes see the draft
notice that was true of *those* bytes.

Files are renamed `tos-2026-09.md` → `tos-2026-09.r1.md` (and the other two).
Contents must not change: the digests in the registry and in 0006 stay valid,
and a diff showing a pure rename is the proof. `pyproject.toml`'s
`legal/*.md` package-data glob still matches.

New and changed module functions:

- `resolve(document_id: str) -> ResolvedRevision | None`, where
  `ResolvedRevision` is `(document: LegalDocument, revision: Revision)`. A
  64-character lowercase hex id is looked up across every revision of every
  document; anything else falls through to the existing `by_id`, whose
  version-versus-slug semantics stay exactly as the implementer refined them.
- `published_revisions() -> tuple[tuple[ConsentType, str, str], ...]` — the flat
  `(consent_type, version, sha256)` ledger the reconciliation and the migration
  agreement test compare against.
- `text_for(sha256)` / `blocks_for(sha256)` replace `text(version)` /
  `blocks(version)`, keyed by digest and still `@cache`d. Keying by version was
  part of the defect: it made "the bytes" un-nameable.
- `verify_integrity()` now walks **every revision of every document**: the file
  exists, hashes to its recorded digest, and parses; digests are unique across
  the whole registry; `revisions` is non-empty; and no revision other than the
  newest is `attorney_reviewed`.

The module docstring's rule 1 is wrong today ("a correction is a new file with a
new version id … `verify_integrity` … so editing a published document is a boot
failure"). Replace it with the four publishing rules above and the recipe for
publishing a revision: add the file, add the `Revision`, add a migration that
inserts the ledger row, run it.

### Startup reconciliation

`identity/legal_document.py`:

```python
async def verify_published_revisions(session: AsyncSession) -> None
```

Reads `SELECT consent_type, version, content_sha256 FROM legal_documents` and
compares it with `documents.published_revisions()` in both directions:

- **A ledger row with no registry entry** → `RuntimeError`: this build cannot
  produce bytes the database says were published. That is the failure the
  current design cannot see, and the one that actually happened.
- **A registry revision with no ledger row** → `RuntimeError`: publish it with a
  migration first. Safe to require, because migrations run before the API in
  every environment (compose runs `alembic upgrade head && uvicorn`; the deploy
  plan runs a one-shot migration task before the service).

Called from `main.lifespan`, after `verify_integrity()` and
`enforce_review_status()`, inside `session_scope()` (no patient scope; the table
has no RLS). Messages carry version ids and digests only — both are public — and
never a row count from `consents`.

This adds a database dependency to startup, so the API will not boot while the
database is unreachable. That is deliberate: every route but `/health` and
`/legal` is useless without it, and an evidence check that an outage can skip is
not a control. The alternative (log a warning and serve) was rejected for that
reason and is recorded in *Open questions* in case the user disagrees.

Architecture: `identity` already depends on `db`, which is foundation, so
`tests/test_architecture.py` needs no change. The query is not patient data and
has no patient scope, so it does not belong in a patient-scoped repository; it
sits next to the model it reads, and no router touches it.

### API

`GET /api/v1/legal/documents/{document_id}` — `document_id` may now also be a
64-character content digest. The existing path pattern (`^[a-z0-9-]+$`,
`max_length=64`) already admits one, so the contract's path parameter does not
change.

- version id or slug → the current revision (unchanged behaviour).
- content digest → **that** revision's bytes.
- unknown id or digest → 404 `"No such document."` (unchanged, discloses nothing).

`LegalDocumentRead` gains one field:

```python
current_content_sha256: str   # digest of the version's current revision
```

`content_sha256` and `review_status` on a `LegalDocumentRead` now describe the
**revision that was returned**, not the version. Both are documented in the
schema docstrings, because that distinction is the whole feature.
`LegalDocumentSummary` is unchanged: the list endpoint only ever returns current
revisions, where the two digests are equal by definition.

`Cache-Control` continues to follow review status, now the returned revision's:
`public, max-age=3600` when reviewed, `no-store` for a draft. A digest-addressed
response is immutable and could be cached forever, but a single rule that reads
"drafts are never cached" is worth more than the saved round trip while every
document is a draft.

`make openapi` then `make api-types`, which regenerate
`packages/openapi/schema.json` and `apps/web/src/app/api-client/schema.d.ts`.

### Services

`identity/onboarding_service.py` is unchanged: `current_for(...)` still returns a
`LegalDocument` and `document.sha256` is still the current digest.

`synthetic/writer.py` is unchanged for the same reason, and its rows now satisfy
the foreign key by construction.

Naming note for the in-flight audit-metadata change: the consent audit metadata
key should be `document_sha256`, matching the column it records, rather than
`content_sha256`. The API field stays `content_sha256`, because it describes the
document's content rather than a consent's reference to it. If the implementer
has already written `content_sha256` into the metadata and its test, either is
defensible — pick one and let the test say so.

### Frontend

`apps/web/src/app/features/legal/legal-document.ts` and its template:

- When `content_sha256 !== current_content_sha256`, render the older-wording
  notice above the content: icon plus text, `role="note"`, the string in
  *Clinical basis*, and a link labelled "Read the current wording" pointing at
  `/legal/<id>` (the version id already in the response). 44px target, visible
  focus ring, existing tokens in both themes, nothing conveyed by colour alone.
- The existing superseded-version notice is unchanged and may appear alongside
  it; a patient can be reading old bytes of an old version.
- `legal.service.ts` keeps its `Map` cache keyed by the requested id; a digest
  is just another key, and every revision is immutable so the cache stays sound.
- The route `/legal/:documentId` is unchanged.

No screen links to a digest URL yet, because the account screen is deferred. The
endpoint is what the deferred screen and the deferred re-consent flow both need,
and it is what makes a consent record legible to the person who made it. The web
cost of admitting it now is the one notice above.

## Security and privacy

- **No patient data is added or exposed.** `legal_documents` holds public
  document ids and digests of public text. It gets `GRANT SELECT` to
  `app_runtime` and no RLS, which is the established reference-data pattern
  (`ingredient_catalog`, `clinical_instruments`) and is covered by an existing
  isolation test, extended here.
- **`research_consent_scopes` gains isolation it did not have.** `patient_id`
  plus `patient_isolation` puts it inside the same backstop as every other
  patient-owned table, and the composite FK stops the denormalised key from
  disagreeing with its parent consent. `app_runtime` loses `UPDATE` and `DELETE`
  on it, matching the append-only treatment of `consents`.
- **A new runtime failure mode:** a consent insert whose triple is unpublished
  now raises an integrity error. It surfaces as the existing 500 handler, which
  logs the exception type and the route template only — no digest, no patient id,
  no body.
- **Nothing new is logged or audited.** The startup check logs nothing on
  success and raises with public identifiers on failure. The audit trail is
  untouched by this plan.
- No new third party, no new outbound call, no new free text, no new encryption
  surface.

## Testing

**`apps/api/tests/identity/test_legal_documents.py` (extended)**

- Every revision of every document: the file exists, hashes to its recorded
  digest, and parses. This replaces the current per-document version.
- Revision digests are unique across the whole registry.
- No revision other than the newest is `attorney_reviewed` (publishing rule 3).
- `resolve()` returns the current revision for a slug and for a version id, the
  exact revision for a digest, and `None` for an unknown id, an unknown digest,
  and an uppercase digest.
- `document.sha256` is `revisions[-1].sha256`, and `document.path` is
  `<version>.r<len(revisions)>.md`.

**`apps/api/tests/identity/test_legal_ledger.py` (new, database-backed)**

- `SELECT consent_type, version, content_sha256 FROM legal_documents` equals
  `documents.published_revisions()` exactly. **This is the test that would have
  caught the defect**: it fails the moment a file's bytes and the registry change
  without a migration.
- `verify_published_revisions(session)` passes against the migrated database.
- With the registry monkeypatched to drop a revision, it raises, and the message
  names the version and digest.
- With the registry monkeypatched to add an unpublished revision, it raises.

**`apps/api/tests/identity/test_legal_router.py` (extended)**

- Fetching by the current revision's digest returns the same body as fetching by
  slug, with `content_sha256 == current_content_sha256`.
- With a two-revision document (monkeypatch `DOCUMENTS` and `LEGAL_DIRECTORY` to
  a `tmp_path`, and call `text_for.cache_clear()` / `blocks_for.cache_clear()` in
  the fixture): fetching the older digest returns the older blocks and a
  different `current_content_sha256`; fetching the slug returns the newer.
- An unknown 64-hex digest returns 404 with the same message as an unknown slug.
- `Cache-Control` follows the returned revision's review status.

**`apps/api/tests/identity/test_consent_constraints.py` (the constraint-rejection
tests already in flight, extended)** — raw SQL as the owner session, each
expecting an `IntegrityError`:

- a known version with an unpublished digest;
- a published digest under the wrong version;
- a published `(version, digest)` pair under the wrong `consent_type`;
- a non-hex digest (the existing check constraint);
- and the positive case: the triple onboarding writes is accepted.

**`apps/api/tests/db/test_patient_isolation.py`**

- The raw consent fixture currently inserts `'tos-2026-01'` with
  `repeat('a', 64)`. That now violates the foreign key and **must** be changed to
  a published triple from `documents.current_for(ConsentType.TERMS_OF_SERVICE)`.
  Fixtures that invent evidence are how the invariant got lost in the first
  place.
- `test_reference_data_is_read_only_for_the_application` extended to
  `legal_documents`: `SELECT` returns the published rows; `INSERT`, `UPDATE`, and
  `DELETE` are refused with "permission denied".
- New: a patient scoped to Alice cannot read a `research_consent_scopes` row
  belonging to Bob, and cannot insert one against Bob's consent (row-level
  security violation). Rows are seeded as the owner.
- `test_every_patient_owned_table_has_row_level_security` keeps its assertion
  (`== ["audit_log"]`) and now covers `research_consent_scopes` because it has a
  `patient_id` — the point of the change.

**`apps/api/tests/db/test_consent_grants.py` (the grants test already in flight, extended)** — `app_runtime` holds
`SELECT` only on `legal_documents`; no `UPDATE`/`DELETE` on `consents` or
`research_consent_scopes`; `INSERT` on both is retained.

**Web** — `legal-document.spec.ts`: the older-wording notice renders only when
the two digests differ, carries an icon and text, and links to the current
version; the superseded notice is unaffected.

**Contract** — `make openapi`, `make api-types`; CI's drift check proves both
are committed.

**Manual, once** — `make clean && make up && make seed`, then fetch
`/api/v1/legal/documents/<a seeded consent's document_sha256>` and confirm it
returns that document. This is the end-to-end statement of the guarantee.

No analytics, so no synthetic ground truth applies.

## Interaction with the fixes already in flight

Checked against the six changes the implementer is making in the same commit:

| In-flight change | Interaction |
|---|---|
| Revoke `UPDATE`/`DELETE` on `consents` from `app_runtime`, with a grants test | **Compatible and reinforcing.** It also makes "retiring a revision" a migration-only act, which is what rule 4 needs. Extend the same test and the same `DO $$` block as described above. |
| Explicit backfill guard in 0006 | **Keep, with the backfill reworked** to read from `legal_documents` (one declaration of the digests instead of two). The guard's logic is unchanged; the stale-digest guard is a second, later check, not a replacement. |
| Constraint-rejection tests | **Extend** with the three foreign-key cases above. |
| `content_sha256` in the consent audit metadata | **No conflict.** One naming nit, recorded under *Services*; either name is fine if the test agrees. |
| `document_sha256` on `ConsentRecord` | **No conflict — this design depends on it.** It is how a consent record produces the digest that `/legal/{digest}` resolves. |
| Docstring about what `downgrade 0006` destroys | **Keep and extend** to the ledger table, as described under the migration. |

Nothing in this plan requires undoing any of them.

## ADR

Amend `docs/adr/0011-legal-documents.md` rather than writing a new ADR: the
decision area is the same and the original ADR is the record of what was built.
Add an **Amendment — 2026-09-21** section that:

- corrects the Decision paragraph "**A published document's bytes never
  change.** The registry pins each file's sha256, and `verify_integrity()`
  checks every digest at startup" — the check compares a file with a digest that
  travels in the same commit, so it detects corruption and packaging mistakes,
  not a deliberate rewrite;
- corrects the Consequence "A new version is a new file, a new registry entry,
  and a new digest. There is no in-place edit, by construction" — there was, and
  27 development consent rows recorded it;
- states the new mechanism in one paragraph: a revision is
  `(consent_type, version, content_sha256)`, it is published by a migration into
  `legal_documents`, `consents` carries a composite foreign key to it, documents
  are readable by digest, and the API refuses to start when the build and the
  ledger disagree;
- states the four publishing rules, including that a draft may gain revisions
  under the same version id while a reviewed revision may not;
- adds the consequence that publishing text now requires a migration, and that
  `research_consent_scopes` is inside row-level security by carrying a
  `patient_id`.

## Open questions

1. **Does a re-consent prompt on any digest change, or only on a version
   change?** The evidence argues for the digest: a patient agreed to bytes. The
   cost is that a typo correction re-prompts everyone.
   *Default:* compare digests, and rely on publishing rule 3 to make the two
   equivalent in practice for reviewed documents — a reviewed document changes
   only by a new version anyway. Decide it when the re-consent flow is built; it
   is a product and legal call, not an engineering one.
2. **Must a superseded revision's file stay in the repository forever?**
   *Default:* a reviewed revision, yes. A draft revision, only while a consent
   references it — which the foreign key enforces, so retiring one is a
   deliberate, reviewable migration rather than a deletion nobody notices. For
   the three current drafts, nothing has to be kept.
3. **The 27 orphaned development consent rows.** Their bytes were never
   committed and cannot be reproduced.
   *Default:* rebuild the development database (`make clean && make up &&
   make seed`). There is no option that preserves them honestly, and this is the
   last moment when discarding them costs nothing.
4. **Should the API refuse to start when the ledger cannot be read?**
   *Default:* yes, fail closed. The alternative is to log and serve, which makes
   the check skippable by an outage.
5. **Do beta patients' consents to draft documents count as consent the operator
   will rely on?** This decides whether draft revisions must be retained like
   reviewed ones.
   *Default:* they do not — drafts are for testing, the production gate keeps
   them out of production, and every beta patient is re-prompted at launch. If
   the user intends to rely on them, rule 4 tightens to "retain everything" and
   the beta build needs the re-consent flow first.

## Review log

| Round | Reviewer | Verdict | What changed |
|---|---|---|---|
| 1 | architect (self-check) | Draft ready for implementation | Written after verifying the defect directly against the development database (54 consent rows, 27 pointing at three digests that resolve to nothing) and against `git log`, which shows the superseded bytes were never committed and are unrecoverable. **Clinical soundness:** no computation, no instrument; the two new patient-facing strings are descriptive statements about the record and prescribe nothing. **Patient isolation:** no new patient-owned data; `legal_documents` is reference data with `GRANT SELECT` and no RLS, matching `ingredient_catalog`; the change *adds* isolation to `research_consent_scopes`, which had none, with the standard single policy style and a composite FK so the denormalised `patient_id` cannot disagree with its parent — the alternative subquery policy is rejected in writing. **Privacy and PHI:** only public ids and digests are added, logged, or raised in errors; the stale-row guard reports versions and counts, never patient ids or digests it cannot explain; no new third party. **Architecture:** the ledger model and its check sit in `identity` beside the registry, `identity` already depends on the foundation, the router keeps its query-free shape, and only schemas are returned. **Data model:** the invariant is a foreign key rather than a test, constraints are named with `op.f()`/explicit names, nothing is stored that the registry already owns, and the in-place migration edits are justified by the pre-deployment window and by the dirty development database. **API contract:** one added field, the path parameter's shape unchanged, regeneration required. **Frontend:** one notice, icon plus text, existing tokens, 44px target; no chart, so no chart alternative. **Testing:** the migration-versus-registry agreement test is named as the one that would have caught the defect, plus reconciliation failure paths, three foreign-key rejection cases, the isolation fixture that must stop inventing a digest, and the cross-patient test for the newly protected table. **Scope:** re-consent, the account screen and the withdrawal path stay out, with a note on what each will need. **Decisions:** five open questions with defaults, led by the re-consent trigger, which is the user's call. Not resolved here: whether beta consents to drafts are relied upon (question 5), which is what decides retention. |
| 2 | implementer | Built | Everything in scope, with the user's decisions on the open questions: **rebuild the development database** (question 3 — "I dont care about data at this point. We can always build new patients"), and therefore **draft consents are not relied upon** (question 5, the architect's default), which keeps retention at "a draft revision's file may be retired once no consent references it". Questions 1, 2 and 4 take the architect's defaults, and the re-consent trigger stays a product decision for when that flow is built. **Deviations, all small.** The enum insert needed an explicit `CAST(:consent_type AS consent_type)`: a bound parameter arrives as varchar and Postgres will not coerce it to a native enum. `identity/consent.py` imports `PublishedLegalDocument` for its registration side effect, because the composite foreign key names a table SQLAlchemy cannot resolve otherwise — without it anything importing `Consent` alone, the seeder included, fails at mapper configuration. `verify_integrity` now checks registry shape (non-empty revisions, unique digests, the frozen-revision rule) in a first pass before reading any file, so a violation of publishing rule 3 reports itself rather than surfacing as a digest mismatch. The consent audit metadata key stays **`content_sha256`** rather than the architect's suggested `document_sha256`: the plan and two reviewers already name it that way, it matches the API field, and the test says so. **One thing the plan did not anticipate:** 0001's row-level security loop iterated a literal `("consents",)` rather than `RLS_TABLES`, so adding `research_consent_scopes` to that constant did nothing — the loop now reads the constant, which is also why the table had no policy while the constant above it implied one. **Verified end to end** on a rebuilt database: the ledger holds the three revisions, `research_consent_scopes` reports `relrowsecurity = t` while `legal_documents` correctly does not, and fetching `/api/v1/legal/documents/<a seeded consent's document_sha256>` returns that document's 77 blocks with `content_sha256 == current_content_sha256`. Checks: full API suite, 66 web tests, ruff, mypy, contract and web types regenerated. |
