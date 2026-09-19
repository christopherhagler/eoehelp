# Terms of service, privacy policy, and the consumer health data disclosure

**Status:** Draft · 2026-09-19

## Goal

Today the onboarding screen asks a patient to agree to three documents that do
not exist. The checkboxes link nowhere, the sign-in page says "you agree to our
terms and privacy policy" with nothing to read, and the `consents` table records
agreement to `tos-2026-09` with no text behind that string. That is the weakest
part of the product: a consent record that cannot be tied to wording is not a
record, and asking someone to agree to an unreadable document is the opposite of
informed consent.

Afterwards:

- A patient can read all three documents before they sign up, from the footer of
  every page, from the sign-in page, and from each onboarding checkbox — without
  losing what they typed into the onboarding form.
- Each consent row names a document version **and pins the exact bytes of its
  text** by digest, so what was agreed to is reproducible years later, including
  after the document is superseded.
- The documents describe what the code actually does: the encryption, the audit
  trail, the deletion path, the third parties that exist (Open Food Facts, USDA
  FoodData Central, the sign-in mail sender, Google Fonts), and the fact that no
  analytics run anywhere in the app.
- The terms carry the strongest assumption-of-risk, warranty-disclaimer, and
  liability-limitation wording that is plausibly enforceable for an individual
  operator, with honest carve-outs rather than over-broad clauses that invite a
  court to strike the whole section.
- The unreviewed drafts **cannot reach a real patient**: the API refuses to start
  in production while any required document is still a draft, and every screen
  that shows one carries a visible draft notice.

## Should we be writing legal text at all?

The instruction to consider this is right, and the answer differs by document.

**The privacy policy and the consumer health data disclosure: yes, we must write
them.** Both are, in substance, factual descriptions of a system — what is
collected, where it goes, who else receives it, how long it is kept, how
deletion works, what encryption covers. We are the only party who knows those
facts. An attorney cannot draft them from nothing; they correct and re-shape what
we supply. Handing counsel a generic template to fill in produces a worse
document and a larger bill, and Washington's My Health My Data Act (MHMD) makes
generic templates actively dangerous: its disclosure is prescriptive about
content and carries a private right of action. Writing the factual draft is
engineering work.

**The terms of service: yes, but as a requirements document, not as launch
text.** The liability allocation is the one place where non-lawyer drafting has
real downside. An over-broad exculpatory clause can be struck, and in some
states an unconscionable clause can taint the provision around it — so "the
strongest terms" is not the same as "the most aggressive wording", and getting
that right is a question of the governing state's case law. What we can do well
is state the facts the clauses must cover, use conservative and severable
standard language, and be explicit about the carve-outs the user has already
been told about (gross negligence, intentional misconduct, unwaivable statutory
claims). That is a better brief for counsel than a blank page, and it lets us
ship a complete product for beta.

**What makes writing drafts safe is the gate, not the disclaimer.** Any plan of
this kind that relies on "we'll remember to get these reviewed" is a plan to
launch with unreviewed terms. So this design makes it a startup assertion:
`environment == "production"` plus any required document still marked `draft` is
a `RuntimeError` at boot, in the same spirit as `Settings.enforce_production_safety`.
The launch gate item 5 (attorney-reviewed terms, privacy policy, and MHMD
disclosure) becomes something the code enforces.

**The alternative I rejected:** ship only a factual "how eoehelp handles your
data" page now and leave the three consent documents unwritten until counsel is
engaged. It is cheaper, but it leaves onboarding recording consent to nothing,
which is the current defect, and it means no beta patient can be onboarded at
all. Gated drafts are better than no documents.

## Clinical basis

No new clinical computation. The documents make claims about clinical data, and
those claims follow the rules already in force in this repo:

- **Descriptive, never prescriptive.** No document tells a patient to change a
  treatment or a diet. Where a decision is mentioned, it belongs to the patient
  and their clinicians (FDA general-wellness posture, product plan "Legal and
  clinical risks" item 3).
- **No food is ever called safe.** The terms state affirmatively that eoehelp
  cannot show a food is harmless, because eosinophilic inflammation can be active
  with no symptoms — the same constraint that shapes the insights feature
  (`docs/plans/2026-09-19-insights-food-patterns.md`).
- **The DSQ is a symptom measure, not a measure of inflammation.** Stated
  plainly in the terms so nobody reads a falling score as healing.
- **Emergencies.** "eoehelp is not monitored, and nobody sees your entries. If
  you cannot swallow or think food is stuck, contact your doctor or emergency
  services." Directing someone to emergency care is not a treatment
  recommendation and is standard for a product of this kind.
- **A clinician reading a shared report** is told, on the report itself (M3),
  that it is patient-reported and not a medical record. The terms say the reader
  exercises their own judgment and has no agreement with the operator.

*Pending clinical confirmation* (clinical advisor, before launch, alongside the
report sign-off):

1. The sentence that symptoms track inflammation poorly and that nothing in the
   app can show a food is harmless or that a patient is in remission.
2. The sentence describing what a DSQ-based score does and does not represent.
3. The emergency wording, which a gastroenterologist should phrase.

*Pending legal review*: everything in all three documents. See *Launch gate*.

## Scope

**In scope**

- Three document texts as markdown files in the API package: `tos-2026-09`,
  `privacy-2026-09`, `chd-2026-09`.
- A document registry in `identity/documents.py` carrying version, slug, title,
  effective date, review status, and the sha256 of the text; startup verification
  of every digest; a production gate on drafts.
- A constrained markdown-to-typed-blocks renderer, so the web app never uses
  `innerHTML`.
- A public, unauthenticated `/api/v1/legal` router: list the current documents,
  fetch one by slug or by version id (including superseded versions).
- `consents.document_sha256`, written by onboarding and by the synthetic writer,
  with a database check constraint.
- Web: `/terms`, `/privacy`, `/health-data`, `/legal/:documentId`; a reusable
  content renderer; a dialog used from onboarding; links in the shell footer, on
  the sign-in page, and on each onboarding checkbox; the draft notice.
- ADR 0011 recording the approach.
- Regenerated OpenAPI contract and web types.

**Dependency: the audit-metadata change lands first.**
`docs/plans/2026-09-19-audit-metadata-policy.md` corrects a defect the legal
reviewer found — the audit trail stores clinical values (drug, stop reason,
symptom dates, timezone) and keeps them, with IP address and user agent, after
account deletion, while this plan's documents and `CLAUDE.md` say it does not.
Two sections here describe the trail, so they cannot be written truthfully until
that change is in: the privacy policy's *What is collected* row for the activity
log, and its *How long it is kept* section. Everything else in this plan is
independent of it.

**Out of scope, deliberately**

- **Re-consent when a version is bumped.** There is no mechanism today to
  re-prompt an existing patient, and attorney review *will* change the text and
  therefore the version. This is the immediate follow-up feature and a
  prerequisite for the first beta patient; the production draft gate is what
  makes deferring it safe (no real patient can consent to a draft in the first
  place). Named in *Open questions* so it is scheduled, not forgotten.
- **The research participation document.** `research-2026-09` gets no text. See
  *Research participation* below.
- **An account screen** showing stored consents, a data export, and
  self-service deletion. The deletion API exists; no UI does. The privacy policy
  therefore describes the email route honestly rather than pointing at a screen
  that does not exist. Sequencing note: build that screen and an export
  *before* attorney review, so the reviewed text describes the finished product
  instead of needing a version bump the week after review.
- **Self-hosting the web fonts.** `apps/web/src/index.html` loads two
  stylesheets from Google Fonts on every page, including authenticated ones, and
  already carries a TODO to remove them. Removing them touches the design system
  and the icon font, which does not belong in this change. The privacy policy
  discloses the flow accurately instead, which is the honest option and keeps
  pressure on the TODO.
- **Making the legal pages indexable.** nginx sends `X-Robots-Tag: noindex` and
  `index.html` carries a `robots` meta tag for the whole SPA. MHMD requires a
  prominent homepage *link*, not indexing, so this is satisfied; opening up the
  marketing and legal routes to crawlers is a separate pre-launch task.
- Cookie banner: there is nothing to consent to. The only cookie is the
  `eoehelp_refresh` session cookie, which is strictly necessary. The privacy
  policy says so.
- A subprocessor register page and `/.well-known/security.txt` (M4).

## Design

### Where the text lives, and why there

The text lives in the API package, beside the version registry that onboarding
already reads:

```
apps/api/src/eoehelp_api/identity/
  documents.py            extended: the registry, loading, integrity, gating
  legal_markdown.py       new: the constrained markdown grammar → typed blocks
  legal_schemas.py        new: the response DTOs
  legal_router.py         new: the public routes
  legal/
    tos-2026-09.md        new
    privacy-2026-09.md    new
    chd-2026-09.md        new
```

Reasons, in order of weight:

1. **The consent record and the text must ship as one artifact.** `CURRENT_VERSIONS`
   lives in `identity`; splitting text from versions invites a build where the
   version constant and the document disagree.
2. **A stored version must stay reproducible.** Files are never edited after
   publication: a change is a new file with a new id. The registry pins each
   file's sha256 and the app verifies it at startup, so an edit to a published
   document is a boot failure, not a silent rewrite of history.
3. Putting them in the Angular app instead would mean the API could not produce
   the text behind a consent row it holds.

No new package, and therefore no change to `tests/test_architecture.py`:
`identity` already owns the public auth routes and still imports no clinical
domain.

`identity/legal/` is a data directory, not a package. **`pyproject.toml` must
declare it as package data**, or the wheel the runtime image installs will not
contain it:

```toml
[tool.setuptools.package-data]
"eoehelp_api.identity" = ["legal/*.md"]
```

This is a real trap: the test image sets `PYTHONPATH=/app/src`, so tests pass
from the source tree even when the wheel is missing the files, while the runtime
image imports the installed package. The startup integrity check below is what
catches it in every environment.

### The registry

`identity/documents.py` keeps its current job and gains the registry. Replace
`CURRENT_VERSIONS` and `RESEARCH_PARTICIPATION_VERSION` with:

```python
class ReviewStatus(StrEnum):          # identity/enums.py
    DRAFT = "draft"                   # written in-house, no lawyer has read it
    ATTORNEY_REVIEWED = "attorney_reviewed"

@dataclass(frozen=True)
class LegalDocument:
    consent_type: ConsentType
    version: str            # "tos-2026-09" — the public id, and what consents store
    slug: str               # "terms" — the stable public URL
    title: str              # "Terms of service"
    effective_on: date
    review_status: ReviewStatus
    sha256: str             # of the file's bytes, lowercase hex

DOCUMENTS: Final[tuple[LegalDocument, ...]] = (...)   # oldest first, per type
```

with these module functions:

- `current_for(consent_type) -> LegalDocument` — the newest document for a type
  by `effective_on`; raises `LookupError` when a type has none. Onboarding and
  the synthetic writer call this instead of indexing `CURRENT_VERSIONS`, because
  they now need the digest as well as the version.
- `by_id(document_id) -> LegalDocument | None` — accepts a version id or a slug.
- `current_documents() -> tuple[LegalDocument, ...]` — one per type.
- `text(document) -> str` and `blocks(document) -> tuple[LegalBlock, ...]`, both
  memoised at module level; documents are immutable, so parse once.
- `verify_integrity() -> None` — for every entry: the file exists, its sha256
  matches, and it parses under the grammar. Raises `RuntimeError` naming the
  version and the failure. **Called from `main.lifespan` before `yield`.**
- `enforce_review_status(environment) -> None` — in `production`, raises
  `RuntimeError` if any document required at onboarding is `DRAFT`. Also called
  from `main.lifespan`. It cannot live in `config.enforce_production_safety`,
  because the foundation must not import `identity` (ADR 0010).

The three ids stay exactly as they are (`tos-2026-09`, `privacy-2026-09`,
`chd-2026-09`) so existing dev consent rows remain valid.

The docstring at the top of `documents.py` keeps its point about version bumps
and gains the new one: a published file's bytes never change, because the
digest in this registry and in every consent row would stop matching.

### Research participation

`research-2026-09` is removed from the registry and no text is written for it.

Nothing can grant that consent today — there is no endpoint, `REQUIRED_AT_ONBOARDING`
excludes it, and the export it would describe is M5. A document describing an
export pipeline that does not exist would be inaccurate on the day it shipped,
would have to be re-drafted and re-versioned when M5 lands, and would go through
attorney review twice. Keep the `ConsentType.RESEARCH_PARTICIPATION` enum member
(the schema is designed for it) and let `current_for` raise for it, so the first
attempt to record a research consent fails loudly until a document exists. A
test asserts exactly that.

The other documents must therefore not promise research sharing as a current
option. The privacy policy says research sharing **is not available yet**, that
it will be opt-in, scoped, and withdrawable when it is, and that nothing is
shared with researchers today.

### The markdown grammar

`identity/legal_markdown.py`, roughly 150 lines, a deliberately small grammar
with fatal errors:

| Source | Block |
|---|---|
| `## Heading` / `### Heading` | `heading`, level 2 or 3, with a slugified `anchor` |
| blank-line-separated lines | `paragraph` (lines joined with a space) |
| `- item` lines, continuations indented two spaces | `bullets` |
| `Table: caption` then a pipe table with a `\|---\|` rule | `table` |

Inline: `**bold**` and `[text](href)`. `href` must be `https://`, `mailto:`, or
start with `/`. Headings are plain text — no inline markup. A literal `<` or `>`,
an unbalanced `**`, an unsupported href, an `#` heading (the title comes from the
registry), or a `####` heading raises `LegalTextError`. No escapes, no raw HTML,
no images, no ordered lists — sections are numbered in the heading text
("## 12. Limitation of liability").

Why parse server-side rather than ship markdown and render it in Angular: it
keeps `innerHTML` and a sanitiser out of a security-sensitive app entirely, puts
the document structure in the OpenAPI contract, and lets tests assert that a
statutorily required heading is present. The cost is one small parser with unit
tests, which is cheaper than a markdown dependency plus a sanitisation review.

### API

Router `identity/legal_router.py`, prefix `/legal`, tags `["legal"]`, added to
`V1_ROUTERS` in `main.py`. **Unauthenticated** — the terms have to be readable
before an account exists — and rate-limited with a new
`ratelimit.LEGAL_DOCUMENTS = "60/minute"`.

```
GET /api/v1/legal/documents            -> list[LegalDocumentSummary]   200
GET /api/v1/legal/documents/{document_id} -> LegalDocumentRead         200, 404
```

`document_id` is a version id (`tos-2026-09`) or a slug (`terms`). Slugs and
version ids are disjoint by test, so this is unambiguous, and it gives the web
app one call for "the current terms" and the same call for "the version I agreed
to in 2026". Unknown or unregistered id → 404 `"No such document."`.

Schemas in `identity/legal_schemas.py`:

```python
class LegalSpan(BaseModel):        text: str; bold: bool = False; href: str | None = None
class LegalHeading(BaseModel):     kind: Literal["heading"]; level: int; text: str; anchor: str
class LegalParagraph(BaseModel):   kind: Literal["paragraph"]; spans: list[LegalSpan]
class LegalBullets(BaseModel):     kind: Literal["bullets"]; items: list[list[LegalSpan]]
class LegalTable(BaseModel):       kind: Literal["table"]; caption: str | None
                                   header: list[str]; rows: list[list[list[LegalSpan]]]

LegalBlock = Annotated[LegalHeading | LegalParagraph | LegalBullets | LegalTable,
                       Field(discriminator="kind")]

class LegalDocumentSummary(BaseModel):
    id: str                  # the version, e.g. "tos-2026-09"
    consent_type: ConsentType
    slug: str
    title: str
    effective_on: date
    review_status: ReviewStatus
    content_sha256: str
    superseded_by: str | None

class LegalDocumentRead(LegalDocumentSummary):
    blocks: list[LegalBlock]
```

`superseded_by` is the id of a newer document of the same type, or null. It is
always null today and exists so that a patient following a link to the version
they agreed to is told it is no longer current. Returning it now avoids a
response-shape change later.

Cache headers, set on the response by the route: `public, max-age=3600` for
`attorney_reviewed`, `no-store` for `draft` (drafts change during review, and a
cached draft is confusing). The security middleware uses `setdefault` for
`Cache-Control`, so a header set by the route wins — this is the mechanism to
rely on, not to fight.

No audit rows: there is no patient, no PHI, and nothing to attribute.

### Data model and migration

`consents` gains one column. The version label alone does not answer "which
text"; a digest does, and it is the standard way e-signature records are kept.
It also detects the one failure the registry cannot: a published file edited
together with its registry digest, which would silently re-point every old
consent row at new wording.

`identity/consent.py`:

```python
document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
__table_args__ = (
    Index("ix_consents_current", "patient_id", "consent_type", "granted_at"),
    CheckConstraint("document_sha256 ~ '^[0-9a-f]{64}$'",
                    name="ck_consents_document_sha256_is_hex"),
)
```

Migration `alembic/versions/0006_consent_document_digest.py`, `down_revision =
"0005_procedures"`, self-contained per ADR 0010:

1. `op.add_column("consents", sa.Column("document_sha256", sa.String(64), nullable=True))`
2. One `UPDATE` backfilling by version, with the three digests as literals
   (a development database holds only rows against these three versions, and
   the literals double as a record of the digests at publication).
3. `op.alter_column(..., nullable=False)` — which fails loudly if any row was
   not covered, rather than inventing a value.
4. `op.create_check_constraint(op.f("ck_consents_document_sha256_is_hex"),
   "consents", "document_sha256 ~ '^[0-9a-f]{64}$'")`

Downgrade drops the constraint and the column. Compute the literals from the
finished files (`sha256sum`) as the last implementation step; tests run against
a freshly migrated database, so the backfill path is exercised only against real
dev data.

No new table, so no new RLS policy or grant: `consents` already has both from
migration 0001, and the existing isolation tests already cover it. State that in
the isolation test module rather than adding a new case.

### Services

`identity/onboarding_service.py`, in `complete()`: build each `Consent` from
`documents.current_for(consent_type)`, setting `document_version=document.version`
and `document_sha256=document.sha256`. The consent audit metadata gains
`content_sha256` alongside `consent_type` and `document_version` — a digest of
public text, not PHI.

`synthetic/writer.py` does the same, so seeded patients satisfy the new
constraint.

No other service changes. There is no new patient-owned data and no new query.

### Frontend

New feature area `apps/web/src/app/features/legal/`:

- **`legal.service.ts`** — `HttpClient`, `API_BASE_URL`, the pattern in
  `core/reference.service.ts`. `list()` and `document(id)`, with a
  `signal<Map<string, LegalDocumentRead>>` cache; documents are immutable, so a
  second view is free. No `withCredentials`; the auth interceptor attaches a
  token if one exists, which is harmless, and the endpoint ignores it.
- **`legal-content.ts`** — presentational, `input.required<LegalBlock[]>()`,
  `@switch (block.kind)`. Headings render `<h2 [id]="block.anchor">` / `<h3>`,
  paragraphs and list items render spans as `<span class="font-semibold">` or
  plain text, links render `<a>` with `target="_blank" rel="noopener noreferrer"`
  for `https://` and `mailto:`, and `routerLink` for internal paths. Tables
  render `<table>` with `<caption>` when present and `<th scope="col">`. No
  `innerHTML` anywhere.
- **`legal-document.ts`** — the routed page. `<h1>` from the title, a caption
  line with the effective date and the version id, the draft notice when
  `review_status === 'draft'`, a superseded notice with a link to the current
  version when `superseded_by` is set, a table of contents built from the
  level-2 headings (`<nav aria-labelledby>`), then `<app-legal-content>`, then
  links to the other current documents and the contact address. Sets the page
  title through `Title`. States: loading (spinner with `aria-busy`), error
  (message plus a retry button), not found (message plus links to the current
  documents).
- **`legal-dialog.ts`** — a thin `MatDialog` component taking a slug, reusing
  `legal-content`, with the document title as `<h2 mat-dialog-title>`
  (`aria-labelledby`), a scrollable `mat-dialog-content`, a 44px close button,
  and a "Open in a new tab" link. `MatDialog` traps focus, closes on Escape, and
  restores focus to the trigger.

Routes, inserted before the `**` wildcard in `app.routes.ts`, all public:

| Path | Title |
|---|---|
| `/terms` | Terms of service — eoehelp |
| `/privacy` | Privacy policy — eoehelp |
| `/health-data` | Consumer Health Data Privacy Policy — eoehelp |
| `/legal/:documentId` | set by the component |

The first three resolve through the slug; `/legal/:documentId` is the permanent
link for a specific version, which is what `GET /me/consents` values point at.

**Shell footer** (`app.html`): add a `<nav aria-label="Legal">` with
`Terms of service`, `Privacy policy`, and — with this exact label, because WA
requires the consumer-health-data policy to be prominently linked from the
homepage and distinct from the general privacy policy —
`Consumer Health Data Privacy Policy`, plus a `mailto:` contact link. Links get
`min-h-tap` and a visible focus ring; the footer is in the shell, so the
landing page satisfies the homepage-link requirement. Existing tokens only
(`text-muted`, `text-on-surface`), so both themes are covered.

**Sign-in** (`features/auth/sign-in.ts`): the footnote becomes "By continuing
you agree to the [terms of service] and the [privacy policy], and to the
[consumer health data disclosure]." with real links, keeping the existing "not a
medical record system, and does not provide medical advice" sentence.

**Onboarding** (`features/onboarding/welcome.html` / `.ts`):

- Each checkbox label's document name becomes
  `<a href="/terms" (click)="openDocument($event, 'terms')">terms of service</a>`.
  Two details matter. The handler calls `preventDefault()` **and
  `stopPropagation()`** — a link inside a `mat-checkbox` label otherwise toggles
  the checkbox as well as following the link, which would silently record
  agreement because the patient clicked to read. And the real `href` is kept so
  middle-click and "open in new tab" still work, and so it is a link to assistive
  technology.
- A dialog rather than a navigation, because the onboarding form state lives in
  signals: navigating away loses the birth year, diagnosis month, and timezone
  the patient just entered.
- Below the three checkboxes, a caption line naming the versions being agreed
  to, from `legal.list()`: "You are agreeing to the versions in force on 19
  September 2026 (tos-2026-09, privacy-2026-09, chd-2026-09)." This is what
  makes the stored record legible to the person creating it.
- **A conspicuous arbitration notice beside the terms checkbox**, static text, not
  behind a link: "The terms include an agreement to settle disputes by individual
  arbitration and to give up class actions and a jury trial. You can opt out
  within 30 days at no cost — see section 18 of the terms." Courts weigh whether
  a consumer had clear notice of an arbitration clause and its opt-out at the
  moment of acceptance, so this sentence is part of what makes section 18
  enforceable rather than a courtesy. It links to `/terms#18-resolving-a-dispute`
  using the anchor the parser generates for the heading.
- When any of the three is `draft`, a notice above the checkboxes: icon plus
  text, `role="note"`, "These documents are drafts and have not yet been
  reviewed by a lawyer. This build is for testing, not for real health
  information." Belt and braces behind the production gate.

**Accessibility (WCAG 2.2 AA).** One `<h1>` per page and no skipped heading
levels (the grammar allows only h2/h3, and a test asserts no document starts at
h3). Every notice is an icon plus text, never colour alone. 44px targets on
footer links, the dialog close button, and the table-of-contents links. Focus
visible on all of them. Tables get a caption and column scopes. Long text is
constrained to `max-w-prose`. No charts here, so no chart alternative is
required. `prefers-reduced-motion` is unaffected.

## The documents

The implementer writes the markdown from the outlines below. **The outlines are
the requirement; the load-bearing clauses are given verbatim and must not be
improvised.** Every factual claim below was read out of the code, and a claim
that stops being true is a bug in the document.

### Facts the documents state (all verified in this codebase)

| Claim | Source |
|---|---|
| Sign-in is by emailed link; no password is stored by default | `identity/auth_service.py`, ADR 0003 |
| Magic-link and refresh tokens are stored only as SHA-256 hashes | `core/security.py`, ADR 0003 |
| Session cookie `eoehelp_refresh`, httpOnly, Secure, SameSite=strict, scoped to `/api/v1/auth` | `deps.py`, `identity/auth_router.py` |
| Year of birth, not full date of birth | `identity/patient_schemas.py` |
| Free-text notes are encrypted in the application with AES-256-GCM, key held outside the database | `core/security.py`, `config.py` |
| Row-level security; an unscoped query returns nothing | ADR 0002, `db/session.py` |
| The audit trail records the time, the kind of record, random ids, the outcome, and shape metadata (field names, counts, presence flags) — never the patient's health, behaviour, or whereabouts — and survives account deletion with `ip_address` and `user_agent` nulled | `audit/`, `identity/onboarding_service.delete_account`, **after** `docs/plans/2026-09-19-audit-metadata-policy.md` lands |
| Deletion removes the account, profile, and clinical rows by cascade | `identity/onboarding_service.delete_account` |
| Consent rows keep IP address and user agent | `identity/consent.py` |
| Logs hold the route pattern, not the resolved path, and no request bodies | `main.py`, `observability.py` |
| Barcode and product searches are made by the server; Open Food Facts and USDA receive the search text or barcode and nothing about the patient | `food/products/*`, `pyproject.toml` comment |
| Barcode scanning uses the browser's own detector with camera permission; no image or video leaves the device, only the decoded number | `features/food/barcode-scanner.ts` |
| Sign-in email goes out over SMTP (Mailhog locally, SES when deployed) | `identity/email.py`, `config.py` |
| Google Fonts is requested by the browser on every page; `Referrer-Policy: strict-origin-when-cross-origin` means Google sees the origin, not the path | `apps/web/src/index.html`, `apps/web/nginx/security-headers.conf` |
| No analytics, advertising, or tracking code anywhere | no such dependency exists in `apps/web/package.json` |
| No clinician accounts; the only external access is a link the patient creates | ADR 0001 |
| 18 and over | `documents.MINIMUM_AGE_YEARS` |
| Research sharing does not exist yet | no research consent endpoint, no export |

### `tos-2026-09` — Terms of service

The document opens, before section 1, with a short conspicuous notice — verbatim,
and the first block in the file:

> **Please read these two things before you agree.** eoehelp is a record you
> keep, not medical care, and nobody reviews what you enter: what you do with it
> is your decision and your risk (sections 8 to 12). Disputes are resolved by
> **individual arbitration**, and you give up the right to a jury trial and to
> take part in a class action — **unless you opt out within 30 days**, which
> section 18.7 tells you how to do and which costs you nothing.

Conspicuous notice of an arbitration clause and its opt-out is part of what makes
the clause enforceable, so this block is not decoration and is not to be softened
or moved below the fold.

Numbered sections:

1. **Who runs eoehelp** — an individual in Alabama, United States, not a company;
   legal name, contact email, postal address (*open question 1*). The documents
   do not claim any entity, insurance, or certification that does not exist.
2. **What eoehelp is** — a personal health record the patient fills in; it
   stores and summarises what they enter; it is not a medical record system, not
   a medical device, and not a substitute for care. No clinician accounts exist;
   the only way anyone else sees the record is a link the patient creates.
3. **Not medical advice** — nobody reviews entries; nothing in the app tells
   anyone what to do about treatment or diet; the summaries describe the
   patient's own entries. Decisions belong with the patient and their
   gastroenterologist. Emergency wording per *Clinical basis*.
4. **Who can use it** — 18+; one account per person; the United States at
   launch (*open question 2*); entries are about yourself.
5. **Your account** — whoever controls the email address can sign in, so its
   security matters; tell us if that changes.
6. **Your data and your choices** — the patient owns what they enter; deletion
   is real and how to ask for it; research participation is separate, optional,
   and not available yet; sharing a report is the patient's decision, links
   expire and can be revoked, and a reader exercises their own judgment and has
   no agreement with the operator.
7. **What we ask of you** — do not keep records about another person without
   their involvement; no scraping or automated access; no attempt to reach
   another person's record or to probe security beyond reporting what you find
   to the security address.
8. **What the record can and cannot tell you** — eoehelp displays and summarises
   what was typed and cannot verify any of it; late or missed days change the
   summaries; the food-pattern analysis counts days in the patient's own diary,
   and because eosinophilic inflammation can be active with no symptoms, **no
   result in this app can show that a food is harmless or that the disease is
   inactive**; a DSQ-based score measures symptoms, not inflammation.
9. **Availability and loss of data** — best effort, no uptime commitment,
   outages and bugs happen, backups exist but are not a guarantee, keep your own
   copy of anything you cannot lose.
10. **Assumption of risk** — verbatim:

    > You use eoehelp at your own risk. You decide what to enter, when to enter
    > it, what to make of the summaries it produces, and whether to show any of
    > it to anyone. Those decisions, and anything that follows from them, are
    > yours. eoehelp does not review your entries, does not check them against
    > any clinical source, and has no way to tell when something you entered is
    > wrong or missing. It is a record of what you typed, not a finding about
    > your health. You accept the risk that the record or its summaries may be
    > incomplete, out of date, or wrong, that the service may be unavailable
    > when you need it, and that data may be lost. Decisions about your
    > treatment, your diet, and your care belong to you and your clinicians, and
    > this record should never be their only source.

11. **Disclaimer of warranties** — verbatim:

    > eoehelp is provided "as is" and "as available", without warranties of any
    > kind, whether express, implied, or statutory. To the fullest extent
    > permitted by law, the operator disclaims the implied warranties of
    > merchantability, fitness for a particular purpose, and non-infringement,
    > and makes no warranty that the service will be uninterrupted, timely,
    > secure, or error-free, that data will be preserved without loss, or that
    > any summary, score, or analysis it produces is accurate, complete, or
    > clinically meaningful. No advice or information, whether spoken or
    > written, creates any warranty. Some places do not allow the exclusion of
    > certain warranties, so parts of this section may not apply to you.

12. **Limitation of liability** — verbatim:

    > To the fullest extent permitted by law, the operator is not liable for any
    > indirect, incidental, special, consequential, exemplary, or punitive
    > damages, or for lost profits, lost data, loss of goodwill, or any personal
    > injury or medical expense, arising out of or relating to your use of
    > eoehelp, whether the claim is based in contract, tort (including
    > negligence), strict liability, or any other theory, and whether or not the
    > operator was advised of the possibility.
    >
    > The operator's total liability for all claims relating to eoehelp is
    > limited to the greater of (a) the total amount you paid for the service in
    > the twelve months before the claim arose, which for a free service is
    > zero, and (b) one hundred United States dollars (US$100). Voluntary
    > support payments are not payment for the service and do not raise this
    > limit.
    >
    > These limits allocate risk between us and are part of why eoehelp can be
    > offered at no charge. They apply even if a remedy fails of its essential
    > purpose. If any part of this section is held unenforceable, the rest of it
    > stands, and the unenforceable part applies to the greatest extent the law
    > allows.

13. **What this agreement does not do** — verbatim:

    > Nothing in this agreement limits liability for gross negligence,
    > wantonness, recklessness, or intentional misconduct; for fraud or
    > fraudulent misrepresentation; for death or personal injury caused by
    > negligence where that liability cannot be limited by law; or for anything
    > else that cannot be limited or excluded under the law that applies to you.
    >
    > Nothing in this agreement waives or limits your rights under Washington's
    > My Health My Data Act, including your right to bring a claim under it,
    > under Nevada SB370, under any state data-breach notification law, or under
    > the Federal Trade Commission's Health Breach Notification Rule. Where this
    > agreement and one of those laws disagree, the law governs.

    An affirmative section of this kind is unusual, and it is here on purpose:
    it matches the constraints the user has already been given, and a court
    asked to enforce sections 10 to 12 is more likely to do so when they are
    bounded than when they over-reach.

    **"Wantonness" is in the list for an Alabama-specific reason.** Alabama does
    not generally recognise degrees of negligence the way the phrase "gross
    negligence" assumes; the distinct cause of action is wantonness, and
    Alabama's willingness to enforce exculpatory and limitation clauses between
    private parties stops at wanton, reckless, or intentional conduct. Naming
    the term Alabama courts actually use is what makes the carve-out do its job.
    Keep "gross negligence" too, because a patient in another state may be
    bringing the claim. *For counsel:* confirm the carve-out language against
    current Alabama authority on exculpatory clauses.

14. **If you cause a problem** — a narrow indemnity: claims arising from
    unlawful use, or from entering another person's health information without
    their permission. Deliberately not the broad consumer indemnity, which is
    frequently unenforceable and makes section 12 look worse.
15. **Supporting the project** — voluntary; goes to the operator personally, not
    to a company or a charity; not tax-deductible; not a payment for the service;
    unlocks nothing; handled on a third-party page under that provider's own
    terms, and no card details reach eoehelp. Written as "if a way to support
    the project is offered" so the donations feature (product plan, *Donations*)
    lands without a version bump and a re-consent round.
16. **Changes to these terms** — a change means a new version with a new id; we
    ask you to agree again rather than treating continued use as agreement; the
    version you agreed to stays available at its own link.
17. **Ending your use** — delete at any time; the operator may suspend an
    account for abuse or unlawful use; if eoehelp shuts down, at least 30 days'
    notice by email and a copy of the record on request before deletion.
    (Worded as "on request", not "download", until the export exists.)
18. **Resolving a dispute** — verbatim below, in numbered sub-sections. The user
    chose to include binding individual arbitration with a class action waiver,
    **knowing this plan recommended against it** (*open question 4*, now
    decided). Governing law is Alabama (*open question 3*, now decided).
19. **Housekeeping** — severability, no waiver, entire agreement, notices by
    email to the account address, and assignment: the agreement may be assigned
    if the operator later forms a company for eoehelp.

#### Section 18, verbatim

The heading in the document is **"18. Resolving a dispute"**, and the sub-headings
below are level-3 headings so the table of contents and the required-heading test
can see them. Nothing here is to be reworded by the implementer; the only edits
are the `[POSTAL ADDRESS]`, `[COUNTY]`, and district placeholders from open
question 1.

> ### 18.1 Talk to us first
>
> Before starting an arbitration or a court case, you agree to send a written
> notice of dispute to [POSTAL ADDRESS] or to privacy@eoehelp.org, describing the
> problem, the email address on the account it concerns, and what you want. The
> operator agrees to do the same for any dispute with you, sent to your account
> email address. Both of us then agree to try in good faith to resolve it for 60
> days from the date the notice is sent. If it is not resolved in that time,
> either of us may begin arbitration. This step does not shorten any deadline
> either of us has for bringing a claim.
>
> ### 18.2 Agreement to arbitrate
>
> Except as sections 18.3, 18.6, and 18.7 provide, you and the operator agree
> that any dispute, claim, or controversy arising out of or relating to eoehelp
> or to these terms — including their formation, interpretation, performance,
> breach, termination, or enforceability — will be resolved by **binding
> individual arbitration rather than in court**, and that **each of us gives up
> the right to a trial by jury**.
>
> eoehelp is offered over the internet to people in many states, so this
> agreement involves interstate commerce, and the Federal Arbitration Act, 9
> U.S.C. § 1 and following, governs the interpretation and enforcement of this
> section 18.
>
> The arbitration will be administered by the American Arbitration Association
> under its Consumer Arbitration Rules as modified by this section, and decided
> by one arbitrator. Those rules and the form for starting a case are at
> www.adr.org. If the AAA will not administer the case, you and the operator will
> agree on another established administrator that applies consumer-protective
> rules, and if we cannot agree, a court may appoint one under 9 U.S.C. § 5.
>
> The arbitrator decides the dispute, may award any relief a court could award
> you individually — including damages, statutory damages, and attorney's fees
> where a statute provides for them — and must give a written decision explaining
> the essential findings and conclusions. The award may be entered as a judgment
> in any court with jurisdiction.
>
> The arbitration will be held by telephone or video, on written submissions
> alone, or in person in the county where you live, whichever you choose. **You
> will never have to travel to Alabama for an arbitration hearing.**
>
> ### 18.3 Small claims, and urgent orders
>
> Either of us may instead bring an individual claim in a small claims court that
> has jurisdiction over it, and doing so does not breach this section. Either of
> us may also ask a court for a temporary order to stop unauthorised access to,
> use of, or disclosure of data while a dispute is pending.
>
> ### 18.4 No class actions, and no class arbitration
>
> Arbitration under this section is individual only. Neither of us may bring a
> claim as a plaintiff or as a class member in any class, collective,
> consolidated, mass, or representative proceeding. The arbitrator may not
> combine the claims of more than one person and may not preside over any class
> or representative arbitration. The arbitrator may award relief only to the
> individual party who is seeking it, and only as far as is needed to remedy that
> party's own claim.
>
> ### 18.5 Who pays for the arbitration
>
> The operator will pay the filing, administrative, and arbitrator fees that the
> AAA Consumer Arbitration Rules assign to a business. If your claim is for
> US$10,000 or less and is not frivolous, the operator will also pay your share
> of the AAA filing fee. Each of us pays for our own lawyers and witnesses,
> unless a statute or the arbitrator's award provides otherwise; nothing here
> stops the arbitrator from awarding you costs or fees that a statute entitles
> you to.
>
> ### 18.6 If part of this section cannot be enforced
>
> If section 18.4 is held unenforceable as to a particular claim or as to a
> particular kind of relief, that claim or that request for relief is separated
> out and heard in a court named in section 18.8, and every other claim is still
> arbitrated. If section 18.4 is held unenforceable in full as to a dispute, then
> this section 18 does not apply to that dispute at all and it will be heard in a
> court named in section 18.8 — because neither of us has agreed to class
> arbitration. If any other part of this section is held unenforceable, the rest
> of this section still applies.
>
> ### 18.7 You can opt out of arbitration within 30 days
>
> **You may reject this arbitration agreement.** To do so, send written notice
> within **30 days of the date you first agree to these terms**, saying that you
> reject the arbitration agreement and giving the email address on your account.
> Send it to [POSTAL ADDRESS], or to privacy@eoehelp.org with the subject
> "Arbitration opt-out". A notice sent in time is effective on the date you send
> it, and the operator will confirm it to you in writing. The date you first
> agreed is part of your consent record, which you can ask for at any time.
>
> Opting out rejects **only this section 18**. The rest of these terms still
> apply, nothing about your account or your record changes, and the operator will
> not suspend, restrict, or refuse service because you opted out. If you opt out,
> disputes are heard in the courts named in section 18.8.
>
> If a later version of these terms changes this section 18, you get a fresh 30
> days from the date you agree to that version to opt out of the change, and a
> change never applies to a dispute for which a notice of dispute has already
> been sent.
>
> ### 18.8 Governing law, and the courts for anything not arbitrated
>
> These terms, and any dispute arising out of them or out of eoehelp, are
> governed by the law of the State of Alabama and by applicable federal law,
> without regard to conflict-of-laws rules — except that the Federal Arbitration
> Act governs section 18.
>
> For any dispute that is not arbitrated — because you opted out, because section
> 18.6 sends it to court, or because it is a small claims or urgent-order matter
> — you and the operator agree to the exclusive jurisdiction and venue of the
> state courts in [COUNTY] County, Alabama and of the United States District
> Court for the [NORTHERN / MIDDLE / SOUTHERN] District of Alabama, and each of
> us consents to personal jurisdiction there. Nothing in this paragraph takes
> away your right to bring a small claims case where you live, or the protection
> of a consumer-protection law of the state where you live that applies whatever
> the agreed choice of law says.
>
> ### 18.9 What this section does not do
>
> This section changes **where** a claim is heard, not **what** you are entitled
> to. It does not waive or limit any right you have under Washington's My Health
> My Data Act, including your right to bring a claim under it, under Nevada
> SB370, under any state data-breach notification law, or under the Federal Trade
> Commission's Health Breach Notification Rule, and it does not waive any other
> claim that cannot be waived by agreement. An arbitrator has the same authority
> as a court to award the remedies those laws provide. If the law requires a
> particular claim, or a request for relief on behalf of the general public, to
> be heard in court, that claim is heard in court under section 18.6.

**Why the clause is shaped this way.** Each feature is there because it is what
makes a consumer arbitration clause survive a challenge, rather than decoration:
a real 30-day opt-out with two channels and a written confirmation; a hearing in
the consumer's own county or by video, never in Alabama; the operator carrying
the AAA business-side fees; an explicit small claims carve-out; the statement
that opting out cannot cost you your account; and severance mechanics that never
push the operator into class arbitration. The FAA recital is not boilerplate
here: **Alabama Code § 8-1-41(3) makes an agreement to arbitrate a future dispute
unenforceable as a matter of Alabama law**, and it is the FAA that displaces that
rule where interstate commerce is involved — the point settled in an Alabama case,
*Allied-Bruce Terminix Cos. v. Dobson*, 513 U.S. 265 (1995). A clause that did
not recite interstate commerce and the FAA would be arguing against the operator's
own state statute. *For counsel:* confirm this is still the state of Alabama law
and that the recital is adequate.

**Recorded for the file: this was the user's decision against the plan's
recommendation.** The reasons for the original recommendation have not gone away,
and they are now risks rather than open questions: mass arbitration can cost an
individual operator far more than defending one lawsuit, because section 18.5
puts the business-side AAA fee on the operator for every claim filed, and 500
filings is a bill an individual cannot pay; and the clause cannot reach the MHMD
private right of action in any way that matters, which was much of the point of
having it.

**Questions counsel must answer about section 18, specifically:**

1. Is a predispute consumer arbitration agreement with a class waiver enforceable
   against an Alabama-resident operator's users today, and does the FAA recital
   plus *Allied-Bruce* reasoning hold up against Ala. Code § 8-1-41(3)?
2. **Is this a good trade at all for an individual with no entity and no
   insurance yet?** Specifically, does the mass-arbitration exposure created by
   section 18.5 outweigh the class action protection of 18.4, and would a
   batching provision under the AAA's mass-arbitration supplementary rules, or a
   pre-filing bellwether process, be worth adding?
3. Should the operator's promise to pay the consumer's filing fee for claims
   under US$10,000 stay? It helps enforceability and is the single largest
   mass-arbitration cost driver.
4. Which severance mechanic in 18.6 to keep: claim-level severance, the full
   "if the class waiver falls, arbitration falls" fallback, or both as drafted.
5. Is the 60-day informal-resolution period and the 30-day opt-out window right,
   and is an email opt-out channel acceptable or must it be postal only?
6. Does Washington Consumer Protection Act / MHMD relief, including relief sought
   on behalf of the general public, have to be carved out to court explicitly
   beyond what 18.9 says?
7. Venue: is naming a single Alabama county and federal district reasonable for a
   nationwide consumer product, or does it invite an unreasonable-venue attack on
   the non-arbitrated residue?

**Operational requirement this clause creates.** An opt-out the operator cannot
evidence is worse than no clause at all, and nothing in the product records one.
Two obligations follow, both for the operator rather than the code: opt-out
notices arriving at `privacy@eoehelp.org` must be answered in writing and filed
against the account's consent record, and the 30-day window is computed from the
`consents.granted_at` of the terms consent, which `GET /me/consents` already
exposes. This belongs in a runbook (`docs/runbooks/`, M4) and is listed under
*Open questions* item 9 so it is scheduled. An admin surface for it is a later
feature; a documented manual register is adequate at beta scale.

### `privacy-2026-09` — Privacy policy

1. **Who is responsible** — "eoehelp is run by one person in Alabama, not a
   company", contact details, that data is stored in the United States, and the
   note that HIPAA does not apply because eoehelp is not a health care provider
   or a business associate, while Washington and Nevada consumer health data law
   does. **Do not imply an Alabama equivalent exists:** Alabama has no
   comprehensive consumer privacy statute, so the rights described here come from
   Washington and Nevada law and from the choice to offer them to everyone, not
   from the operator's home state.
2. **What this policy covers** — the site and the app; the separate Consumer
   Health Data Privacy Policy states the same practices in the form Washington
   requires.
3. **What is collected and why** — a table with one row per category: account
   (email, hashed sign-in and session tokens, sign-in times), profile (display
   name, year of birth and why not the full date, optional sex at birth,
   diagnosis month, timezone and why it is load-bearing), health entries (daily
   symptom answers, foods and ingredients, medications and doses, endoscopy,
   biopsy and dilation details, free-text notes), consent records (version,
   time, IP address, browser user agent, and a digest of the exact text, with
   the reason: it is the evidence consent was given), activity log (which
   records were read or changed, when, from which address, with which browser,
   the outcome, and shape information about the change — the *names* of the
   fields, how many records, whether an optional field was filled in — **never
   the contents, and never anything about the patient's health, behaviour, or
   whereabouts**; see `docs/plans/2026-09-19-audit-metadata-policy.md` for the
   rule the code enforces), and technical logs (method, route pattern rather
   than the path, status, duration, request id).
4. **What is never collected** — no full date of birth, address, phone number,
   payment details, location, advertising identifiers, or device
   fingerprinting; no cookies other than the sign-in session cookie, which is
   named and explained. The camera is used only when the patient starts a
   barcode scan, the browser's own detector does the reading, and no image or
   video leaves the device — only the decoded number.
5. **Who else receives anything** — the honest short list, one row each:
   hosting provider (*open question 5*); the sign-in email sender; Open Food
   Facts and USDA FoodData Central, which receive a search phrase or a barcode
   **from our server** and no identifier, no account, and nothing about the
   patient; Google Fonts, which sees the browser's IP address, user agent, and
   the site's address but not the page, with the statement that the fonts will
   be hosted by us and the request removed. Then, flatly: no analytics, no
   advertising, no data brokers, nothing sold, nothing shared with insurers or
   employers, and no third party receives health entries.
6. **How it is protected** — TLS in transit; disk encryption at rest; free-text
   notes additionally encrypted in the application; row-level security so an
   unscoped query returns nothing; access limited to the operator for support
   and maintenance, with every access logged; and the honest limit that no
   system is perfectly secure.
7. **How long it is kept** — until deleted, and then, specifically: the account,
   the profile, and every health entry are removed; the activity log survives
   **with the IP address and browser string erased**, keeping only when each
   action happened, what kind of record it touched, random ids whose rows no
   longer exist, the outcome, and the shape information from section 3. Say why:
   it is the evidence that the deletion was carried out, and it is what answers
   "was my record ever accessed" if a breach is investigated later. Then the
   retention period for those rows (*open question 6a*), and that encrypted
   backups may hold deleted data until they expire (*open question 6*). **Do not
   write this section until the audit-metadata change has landed** — the list
   above is the behaviour after
   `docs/plans/2026-09-19-audit-metadata-policy.md`, not before it.
8. **Your choices** — see and correct in the app; ask for a copy by email;
   delete (the route that exists today); research sharing is not available and
   will be opt-in, scoped, and withdrawable when it is.
9. **If there is a breach** — notification of affected people and regulators
   without unreasonable delay. Name the three regimes that actually apply rather
   than gesturing at "applicable law": the **Alabama Data Breach Notification Act
   of 2018** (Ala. Code § 8-38-1 and following), whose definition of sensitive
   personally identifying information covers medical history, condition,
   treatment, and diagnosis, and which sets a 45-day notification deadline once a
   breach is determined to be reasonably likely to cause substantial harm, with
   notice to the Alabama Attorney General when more than 1,000 residents are
   affected; the breach-notification law of the state where the affected person
   lives; and the **FTC Health Breach Notification Rule**, which reaches a
   personal health record vendor that HIPAA does not cover. *For counsel:*
   confirm the Alabama Act's trigger and whether it attaches through the
   operator's residence, through the residence of affected individuals, or both,
   and confirm the 45-day and 1,000-resident thresholds are current. The stated
   deadlines are commitments the incident-response plan (M4) has to be able to
   meet, so they must be the real ones.
10. **Children** — 18+; an account found to belong to someone younger is
    deleted.
11. **Changes** — versioned, re-asked, old versions stay readable.
12. **Contact and complaints** — email, and for Washington residents the state
    Attorney General.

### `chd-2026-09` — Consumer Health Data Privacy Policy

A distinct document, distinctly linked, holding what MHMD (RCW 19.373) requires
and nothing extraneous. Section headings must exist for each of these, because a
test asserts them:

1. **About this policy** — what consumer health data means, that this is the
   policy Washington law requires, and that it covers Nevada SB370 too.
2. **The consumer health data we collect, and why** — table: category, examples,
   purpose, and how it is used.
3. **Where it comes from** — the patient's own entries, and the device camera
   when a barcode is scanned (the image never leaves the browser; only the
   decoded number is sent). No data brokers, no third-party sources, no
   purchased data.
4. **What we share** — **none of it, with no exceptions today**, followed by the
   processors that hold it on our behalf. Do **not** describe report sharing by
   link: it is in the product plan for M3 and **does not exist anywhere in the
   codebase**, and a disclosure of a sharing route that cannot happen is both
   wrong and the kind of error that undermines the whole document. Say instead
   that no feature for sharing with anyone exists yet, and that when one does it
   will be the patient's own decision and asked for separately (section 7).
5. **The third parties and affiliates it is shared with** — named categories:
   the hosting provider and the email sender, as processors. No affiliates,
   because there is no corporate group. The Open Food Facts and USDA lookups are
   described precisely here too: whether a barcode or search phrase sent from
   our server is a sharing of consumer health data is exactly the judgment
   counsel must make, and disclosing it is the safer default (*open question 7*).
   **Google Fonts belongs in this list as well** — the browser requests two
   stylesheets from Google on pages that display health data, so Google receives
   the IP address, the user agent, and the site's origin (not the path). The
   privacy policy discloses it; a reader comparing the two documents and finding
   it in only one would reasonably ask what else is missing.
6. **Your rights and how to use them** — confirm whether we collect or share,
   get a copy including the list of third parties, withdraw consent, and delete.
   How a request is authenticated, the 45-day response with a possible 45-day
   extension, how to appeal a refusal, and the Attorney General complaint route.
   **These rights are offered to everyone, wherever they live.** Washington and
   Nevada law require them for their residents and Alabama requires nothing, but
   running two standards means deciding a patient's rights from their claimed
   location, which is both error-prone and worse for the patient. Recorded here
   as a deliberate choice for counsel to confirm, not an accident of drafting.
7. **Consent** — separate, specific, opt-in, and never bundled. Be exact about
   what the consent recorded at onboarding actually covers, because the code and
   an earlier draft of this outline disagreed: **`ConsentType.CONSUMER_HEALTH_DATA`
   is consent to collect, and nothing else.** MHMD requires consent to collection
   and consent to sharing to be sought separately, and the product shares nothing
   — there is no share link, no research export, no recipient. So the document
   says: this consent covers collecting the data in order to keep the record; no
   sharing happens; and if a way to share is built, consent for it will be asked
   for separately, at that time, and can be refused without losing the account.
   **Do not add a second `ConsentType` now.** An unused
   `CONSUMER_HEALTH_DATA_SHARING` type sitting in the enum is an invitation for a
   future onboarding screen to collect it alongside the others, which is exactly
   the bundling the statute prohibits. The type is added by the feature that
   first shares something — the report share link (M3) — and that feature's plan
   owns both the type and the screen that asks for it. Recorded here so the
   sequencing is deliberate rather than an omission.
   Then: **we do not sell consumer health data** and would need a signed
   authorisation with the contents the statute prescribes, which we do not seek.
8. **No geofencing** — eoehelp does not use location at all and operates no
   geofence around any health facility.
9. **Nevada residents** — the equivalent statements under SB370.
10. **Contact.**

### How the drafts are marked as unreviewed

Four layers, in decreasing reliance:

1. **The production gate.** `documents.enforce_review_status("production")`
   raises at startup while any document required at onboarding is `draft`. A
   production deploy fails its health check. This is the one that matters.
2. **The API says so.** `review_status` is in both response schemas, so every
   client knows.
3. **Every screen shows it.** The document page and the dialog render a draft
   notice; onboarding shows one above the checkboxes.
4. **The registry and the ADR record it**, and the plan's launch gate lists what
   must happen.

The status is metadata, not text in the markdown, so the file holds only the
agreement itself.

### Launch gate, and the attorney review packet

This feature does not satisfy launch gate item 5; it produces its input. Before
the first real patient:

- A healthcare privacy attorney reviews all three documents. Their changes
  produce new versions (`tos-2026-11` or similar), which need the re-consent
  flow (*out of scope*, prerequisite for beta).
- The clinical advisor confirms the three sentences in *Clinical basis*.
- `review_status` flips to `attorney_reviewed` per document, in the same commit
  as the reviewed text and its new digest.

What to send counsel, in one packet: the three drafts; the *Facts the documents
state* table above, which is the technical description they would otherwise have
to interview us for; the list of third parties; the remaining open questions
below, which are the decisions we are explicitly not making ourselves; and — as
its own item, because it is the largest single legal risk in the documents and was
chosen against this plan's recommendation — **the seven questions about section 18
listed under *Section 18, verbatim*, including whether an arbitration clause is a
good trade at all for an individual with no entity and no insurance.** The Alabama
points flagged for confirmation are collected in open question 3.

## Security and privacy

- **No patient data is read or written by the new endpoints.** They serve public
  text. There is no repository, no session, and no patient scope — the only
  unauthenticated read surface besides auth, and it exposes nothing about anyone.
- **Patient isolation is unchanged.** No new table, so no new RLS policy or
  grant. The one column added to `consents` lives inside the existing policy and
  the existing grants to `app_runtime`.
- **PHI.** The new column holds a digest of public text. The consent audit
  metadata gains that digest and nothing else. Nothing in the new code paths can
  see a patient value: there is nothing patient-specific to see.
- **Logs.** The legal routes log through the existing middleware: route pattern,
  status, duration. `document_id` appears only in the route template, not
  resolved — and it is public text anyway.
- **No new third party.** Nothing is added to the subprocessor list; the
  feature's job is to describe the ones that exist.
- **Abuse surface.** Public GETs, rate-limited at 60/minute per address and
  cacheable, serving a few kilobytes from memory. The parse happens once at
  startup, so a request cannot trigger work proportional to anything.
- **Rendering.** Typed blocks, no `innerHTML`, no sanitiser, no markdown
  dependency on either side. Hrefs are restricted at parse time to `https://`,
  `mailto:`, and internal paths, so a document cannot introduce a `javascript:`
  link even by accident.
- **Integrity.** Startup verification of every digest means a corrupted,
  missing, or altered document file fails the boot instead of serving wrong
  wording to a patient about to consent.

## Testing

**API — `apps/api/tests/identity/test_legal_documents.py`**

- Every registry entry's file exists and its sha256 matches. This is the tamper
  and packaging check.
- `verify_integrity()` raises when a digest does not match (monkeypatch one
  entry) and when a file is missing.
- Every type in `REQUIRED_AT_ONBOARDING` has exactly one current document;
  `current_for(RESEARCH_PARTICIPATION)` raises.
- Version ids match `^[a-z]+-\d{4}-\d{2}$`; ids and slugs are each unique and
  the two sets are disjoint (the router depends on this).
- Every document parses; no `#` heading; the first heading is level 2; no
  literal `<` or `>`; every href is `https://`, `mailto:`, or internal.
- **Statutory headings:** parameterised over the required MHMD sections
  (collected and purpose, sources, shared, third parties and affiliates, rights
  and how to exercise them, consent and no sale, geofencing, contact) — each must
  appear as a heading in `chd-2026-09`.
- **Required ToS clauses:** headings for assumption of risk, disclaimer of
  warranties, limitation of liability, what the agreement does not do, and each
  of the nine sub-headings of section 18; the carve-out text must name gross
  negligence, wantonness, intentional misconduct, and the My Health My Data Act.
- **The arbitration clause keeps the parts that make it enforceable.** The terms
  must contain the conspicuous notice block before section 1, the words "opt out"
  within section 18.7, a 30-day window, both opt-out channels (the postal
  placeholder or address, and the email address), the small claims carve-out, the
  Federal Arbitration Act citation, and the statement that MHMD rights are not
  waived. Each is a separate assertion, because each is a separate reason a court
  would refuse to enforce the clause, and a well-meaning edit that shortens the
  section is exactly what this test is for.
- **Placeholders:** no `[POSTAL ADDRESS]`, `[COUNTY]`, or bracketed district
  placeholder may appear in a document whose `review_status` is
  `attorney_reviewed`. Drafts may contain them.
- **Wording guard:** no document contains prescriptive phrasing from an explicit
  list (`"safe food"`, `"is safe to eat"`, `"you should stop"`, `"we recommend"`,
  `"avoid "`, `"diagnose"`). A guard, not a proof, and cheap.
- `enforce_review_status("production")` raises while a required document is a
  draft, and passes for `local` and `staging`.

**API — `apps/api/tests/identity/test_legal_markdown.py`**

Unit tests per construct: h2 and h3 with anchors, paragraph line joining,
bullets with continuations, a table with and without a caption, bold, internal
and external links. And one raising test each for: `#` heading, `####` heading,
unbalanced `**`, a `javascript:` href, a literal `<`, and a table whose rule row
is missing.

**API — `apps/api/tests/identity/test_legal_router.py`**

- `GET /legal/documents` with no Authorization header returns 200 and the three
  current summaries, with `blocks` absent and `superseded_by` null.
- `GET /legal/documents/terms` and `/legal/documents/tos-2026-09` return the same
  document; `id` is the version in both.
- Unknown id returns 404 with a message that discloses nothing.
- A draft document responds `Cache-Control: no-store`; a reviewed one responds
  `public, max-age=3600` (monkeypatch the registry entry).
- No `Set-Cookie` on either route.

**API — `apps/api/tests/identity/test_onboarding.py` (extended)**

- Onboarding writes `document_sha256` equal to the registry digest for each of
  the three consents.
- The `consent.grant` audit metadata is exactly `consent_type`,
  `document_version`, `content_sha256`.
- A consent insert with a malformed digest is rejected by the database (proves
  the check constraint, not just Pydantic).

**Isolation** — `tests/db/test_patient_isolation.py` unchanged, with a comment
recording that the new column sits inside the existing `consents` policy. The
cross-patient suite already covers `/me/consents`.

**Contract** — `make openapi` and `make api-types`; CI's drift check proves the
new schemas are committed. Add the new type exports to
`apps/web/src/app/core/api/api-types.ts`.

**Web**

- `legal-content.spec.ts` — each block kind renders; bold spans get the weight
  class; an external link gets `rel="noopener noreferrer"` and an internal one
  uses `routerLink`; a table renders a caption and column scopes.
- `legal-document.spec.ts` — loading, error with retry, not-found; the draft
  notice appears only when `review_status` is `draft`; the superseded notice
  appears only when `superseded_by` is set; the table of contents lists the
  level-2 headings; the page title is set.
- `welcome.spec.ts` (new) — **clicking the terms link neither toggles the
  checkbox nor submits the form**, and it opens the dialog. This is the specific
  regression that would otherwise record consent because someone clicked to
  read. Also: the arbitration notice is rendered as visible static text next to
  the terms checkbox, not hidden behind a link or a collapsed panel, since the
  clause's enforceability rests partly on it having been shown.
- `app.spec.ts` (extended) — the footer contains all three links, with the
  Consumer Health Data Privacy Policy label exact.

**Synthetic data** — `make seed` still works, which exercises the writer's new
digest.

No analytics are involved, so there is no ground-truth validation to do here.

## ADR

`docs/adr/0011-legal-documents.md`, recording: versioned legal text as
hash-pinned files inside the API package, beside the consent version registry;
the per-consent digest and what it protects that the registry alone cannot; the
constrained markdown grammar and why no `innerHTML` path exists; the production
gate on unreviewed drafts as the enforcement of launch gate item 5; and the
decision not to write the research participation document until the export
exists. Consequences to name: a new document version means a new file plus a
registry entry plus a digest, never an edit, and it requires the re-consent flow
that does not exist yet.

## Open questions

Each has a recommended default so implementation is not blocked, and each is the
user's or counsel's decision, not ours.

1. **The operator's legal name, postal address, and county — still open, and now
   load-bearing.** The address is needed for the MHMD contact route, for the
   arbitration opt-out channel in section 18.7, and the county for the venue
   clause in 18.8. Publishing a home address is a real privacy cost for an
   individual; an opt-out address that does not work is worse than no arbitration
   clause at all.
   *Default:* full legal name plus a virtual mailbox or PO box in the operator's
   county, and `privacy@eoehelp.org` as the primary contact. The implementer uses
   `privacy@eoehelp.org` and leaves `[POSTAL ADDRESS]`, `[COUNTY]`, and the
   `[NORTHERN / MIDDLE / SOUTHERN]` district choice as marked placeholders; a
   test stops any of them reaching an `attorney_reviewed` document. Confirm
   `privacy@` and `security@` deliver mail before launch.
2. **Territory.** Config already assumes US-only product data.
   *Default:* the documents say eoehelp is offered to people in the United
   States and is not directed to the EU or UK, which avoids GDPR claims we are
   not equipped to honour.
3. **Governing law and venue — decided by the user, 2026-09-19: Alabama.**
   Section 18.8 names Alabama law and the Alabama courts; there is no `[STATE]`
   placeholder left. Three consequences are folded into the drafts above: the
   carve-out in section 13 now names **wantonness**, the Alabama term, because
   Alabama does not treat "gross negligence" as a separate degree of negligence
   and its enforcement of exculpatory clauses stops at wanton, reckless, and
   intentional conduct; section 18.2 recites interstate commerce and the Federal
   Arbitration Act, because **Ala. Code § 8-1-41(3)** would otherwise make a
   predispute arbitration agreement unenforceable under state law; and the
   privacy policy's breach section names the **Alabama Data Breach Notification
   Act of 2018** alongside other states' laws and the FTC Rule, while stating
   that Alabama has no comprehensive privacy statute, so nothing implies an
   Alabama equivalent of MHMD. The county and federal district remain in question
   1. *For counsel:* confirm each of those three points, and whether naming a
   single Alabama county as venue for a nationwide consumer product invites an
   unreasonable-venue challenge on the claims that are not arbitrated.
4. **Arbitration and class action waiver — decided by the user, 2026-09-19:
   include, against this plan's recommendation.** Section 18 is written out
   verbatim above with the features that make such a clause survive a consumer
   challenge: a genuine 30-day opt-out with two channels, a written
   confirmation, and no consequence for using it; hearings in the consumer's own
   county or by video and never in Alabama; the operator carrying the AAA
   business-side fees; a small claims carve-out; severance mechanics that never
   compel class arbitration; and an explicit statement that MHMD and other
   unwaivable statutory rights survive. The plan's original recommendation was to
   leave it out, and the reasons are now risks rather than questions: mass
   arbitration can cost an individual operator far more than one lawsuit, because
   section 18.5 puts the business-side fee on the operator per claim; and the
   clause cannot reach the MHMD private right of action. The seven questions
   counsel must answer are listed under *Section 18, verbatim*.
5. **What the privacy policy says about hosting today.** The AWS account in ADR
   0004 does not exist yet, and the policy must be true on the day it ships.
   *Default:* name the provider actually in use when the feature ships, and say
   the operator holds a HIPAA business associate agreement with them only once
   that is true.
6. **Backup retention, stated as a number.** Deleted data survives in backups
   until they expire, and the policy should say for how long.
   *Default:* 35 days, matching the RDS point-in-time-recovery window in ADR
   0004; correct it if the deployed configuration differs.
6a. **How long the activity log itself is kept.** Nothing prunes `audit_log`
   today, so the honest answer is "indefinitely", which the policy should not
   promise by omission. Carried from open question 2 of the audit-metadata plan
   so whichever document ships first states the same number.
   *Default:* say two years, and implement pruning when a scheduler exists (M4).
   If the user would rather not state a period that is not yet enforced, the
   fallback is to say the rows are kept while the service operates and that a
   limit is being introduced — honest, and weaker.
7. **Are the Open Food Facts and USDA lookups a sharing of consumer health
   data?** A barcode sent from our server, with no identifier, in response to a
   patient's scan.
   *Default:* disclose it in the consumer health data policy as described, and
   ask counsel whether it must be listed as sharing.
8. **Sequencing.** Two items should land before counsel reads the drafts, so the
   reviewed text describes the finished product: the account screen (view
   consents, request a copy, delete the record) and the re-consent flow for a
   version bump. Reviewing first means paying for review twice.
   *Default:* build the re-consent flow next, then the account screen, then send
   the packet.
9. **Who handles an arbitration opt-out, and where it is recorded.** Section 18.7
   promises a written confirmation and a 30-day window computed from the terms
   consent's `granted_at`. No code records an opt-out, and a promise the operator
   cannot evidence is worse than no clause.
   *Default:* a runbook entry (`docs/runbooks/`, M4) plus a manual register kept
   with the consent record, adequate at beta scale; an admin surface only if
   volume warrants it. This has to exist before the terms are shown to a real
   patient, not before launch in general.

## Review log

| Round | Reviewer | Verdict | What changed |
|---|---|---|---|
| 1 | architect (self-check) | Draft ready for implementation | Checked against every item in the architect's standard. **Clinical soundness:** no instrument or threshold is invented; the three EoE claims are marked pending clinical confirmation; the wording rules are descriptive-only and "safe" is forbidden by a test. **Patient isolation:** no new table, no new patient-owned data; the new `consents` column sits inside the existing policy and grants; new routes touch no patient data at all. **Privacy and PHI:** the added column and audit field are digests of public text; no free text is introduced; no new third party; the documents disclose the Google Fonts flow found in `index.html` rather than omitting it. **Architecture:** everything sits in `identity` beside the version registry, so `tests/test_architecture.py` needs no change; the router builds no query; only schemas are returned. **Data model:** the digest is constrained in the database by a regex check with an `op.f()` name, the migration is self-contained, and the backfill fails loudly rather than inventing a value. **API contract:** `make openapi` and `make api-types` are required steps; `superseded_by` is included now so the response shape does not change when a document is superseded. **Frontend:** signals, standalone components, existing tokens for both themes, 44px targets, notices as icon plus text, typed blocks so no `innerHTML` exists; the checkbox-link `stopPropagation` trap is called out and tested. **Testing:** statutory headings, required ToS clauses, the digest constraint, the production draft gate, the parser's failure paths, and the onboarding click regression are all named. **Scope:** re-consent, the account screen, the research document, and self-hosted fonts are explicitly out, each with a reason. **Decisions:** eight open questions with defaults, including two placeholders (`[POSTAL ADDRESS]`, `[STATE]`) that a test stops from reaching a reviewed document. Not resolved here: whether counsel will accept the $100 cap and the no-arbitration choice, which is question 4. |

| 2 | architect (revision after user decisions) | Draft ready for implementation | **Two open questions came back decided, and both changed the text.** *Question 4, arbitration:* the user chose to include binding individual arbitration with a class action waiver, **against this plan's recommendation**, which is now recorded as such rather than smoothed over. Section 18 is written out verbatim in nine sub-sections instead of a bullet: 60-day informal resolution; the arbitration agreement under AAA Consumer Rules with the Federal Arbitration Act recital; the class and class-arbitration waiver; fee allocation; severance mechanics that never compel class arbitration; a genuine 30-day opt-out with two channels, a written confirmation, and no consequence for using it; governing law and courts; and an explicit statement that MHMD, Nevada SB370, breach-notification and FTC Rule rights survive. Added a conspicuous notice block before section 1 of the terms and a static arbitration notice beside the onboarding checkbox, because notice at the moment of acceptance is part of what makes such a clause enforceable; tests now assert each individual feature of section 18, so a well-meaning edit cannot quietly remove the parts that make it survive. Added the seven questions counsel must answer about section 18, led by whether the mass-arbitration exposure created by 18.5 makes the clause a bad trade for an individual operator. Added open question 9: an opt-out the operator cannot evidence is worse than no clause, so a register and runbook must exist before a real patient sees the terms. *Question 3, governing law:* Alabama. Three Alabama-specific edits followed, none cosmetic — section 13's carve-out now names **wantonness**, because Alabama does not treat "gross negligence" as a separate degree of negligence and its enforcement of exculpatory clauses stops at wanton, reckless, and intentional conduct; section 18.2 recites interstate commerce and the FAA because **Ala. Code § 8-1-41(3)** would otherwise void a predispute arbitration agreement under state law (the preemption point settled in *Allied-Bruce Terminix v. Dobson*, 513 U.S. 265 (1995), itself an Alabama case); and the privacy policy's breach section now names the **Alabama Data Breach Notification Act of 2018**, whose definition of sensitive personally identifying information covers medical condition and treatment, with its 45-day and 1,000-resident thresholds, alongside other states' laws and the FTC Rule — while stating plainly that Alabama has no comprehensive privacy statute, so nothing implies an Alabama equivalent of MHMD. Also decided and flagged for counsel rather than buried: consumer-health-data rights are offered to everyone regardless of state, because deciding a patient's rights from their claimed location is error-prone and worse for the patient. The `[STATE]` placeholder is gone; `[POSTAL ADDRESS]`, `[COUNTY]`, and the federal district remain and all resolve from question 1, which is now load-bearing rather than cosmetic, since 18.7 needs an opt-out address that works. Not resolved: everything flagged for counsel, in particular whether the clause is enforceable in Alabama as drafted and whether it is a good trade at all. |
| 3 | implementer | Built | All three documents written, registry pinned by digest, migration 0006 with the published digests as literals, public `/legal` routes, the web pages, the onboarding dialog and notices, ADR 0011. Deviations, all small: the grammar allows a blank line between a table caption and its table, because the source reads better that way; the router converts blocks with `dataclasses.asdict`, since a block's spans are dataclasses too; `tests/db/test_patient_isolation.py` needed its raw consent fixture updated for the new NOT NULL column (a stand-in digest, not a published one), which is also the proof that the check constraint binds. Corrections the architect caught in my drafts and I applied: the deletion sentence now describes the email route that exists rather than a screen that does not; section 13 names wantonness and Nevada SB370; the conspicuous notice sits before section 1. Checks: 557 API tests, 63 web tests, ruff, mypy, contract regenerated; legal pages screenshotted in light and dark. |
| 4 | legal-reviewer | CHANGES REQUESTED | Verified against the code, so counsel need not recheck: token hashing, cookie flags, note encryption, year-of-birth, route-pattern-only logs, food lookups carrying no identifier, on-device barcode decoding, no analytics, no research sharing, real cascade deletion, the 18+ gate. Eight blocking findings, all of the same kind: sentences describing the system as planned rather than as it is. **Fixed in this commit:** report sharing by link described but absent from the codebase (removed from all three documents); hosting, US storage, at-rest encryption, backups and processor contracts asserted before any infrastructure exists (now stated as commitments, with the fact that nothing is deployed); Google Fonts missing from the consumer-health-data third-party list (added, and the "no third-party script" line reworded); the terms contradicting themselves about another person's health information, which a parent could read as permission to log a child (now one rule: your own data only); the privacy policy's "nobody receives your health entries" sitting above the hosting row (reworded); §12 now reads "subject to section 13"; the age claim, the location claim, the RLS scope claim, the user-agent omission, the font description, and the consumer-health-data definition all corrected; consent separateness now states the truth (collection only, nothing shared, sharing consent if sharing is added); the deletion clock split from the response clock. **Outstanding, with the architect:** the audit trail stores medication codes, stop reasons, dose status, entry dates, eaten-on dates, timezone, IP and user agent against a patient id, and survives deletion, which contradicts CLAUDE.md, ADR 0002's posture and all three documents. **Outstanding, deferred and recorded:** re-consent on a version bump; the account screen; the consent-withdrawal path and what it means; a third-party licence section (ODbL share-alike, the unconfirmed DSQ licence); `content_sha256` missing from the consent audit metadata and the onboarding digest tests unwritten; a draft marker inside each file's text; whether the production draft gate should extend to staging. Seven questions for counsel recorded in the reviewer's report. |
| 5 | implementer | Committed unreviewed | Committed with the wording fixes above so the work is not lost. The code review, the security review and the database review have NOT run on this feature; they are the first thing to do next. The documents remain drafts, and `enforce_review_status` still refuses to serve them in production. |
| 3 | architect (revision after the legal reviewer's code check) | Draft ready, with one dependency | The reviewer found that the audit trail stores clinical values — drug code, frequency, stop reason, dose status, symptom and food dates, timezone, and counts of flagged findings — and keeps them, with IP address and browser string, against a durable `patient_id` after account deletion, while these documents, ADR 0002 and `CLAUDE.md` all say it holds field names and counts only. That is a product defect, not a wording problem, so it is **its own plan and lands first**: `docs/plans/2026-09-19-audit-metadata-policy.md`. The rule decided there — metadata may describe the request and the shape of a change, never the patient's health, behaviour, or whereabouts; no dates at any precision, because `resource_id` already identifies the row; date ranges become `window_days`; counts of records allowed, counts of clinical findings not; `ip_address` and `user_agent` nulled inside the deletion transaction through a column-level grant — is now reflected in three places here: the *Facts the documents state* table, the privacy policy's activity-log row, and its retention section, which now lists precisely what survives a deletion instead of the inadequate "field names, no values". A *Dependency* note in *Scope* says those two sections must not be written before that change lands, because a claim in a legal document has to be true when it is written, not merely before a patient reads it. Added open question 6a: nothing prunes `audit_log`, so the policy must not promise a retention period by omission; default two years, with pruning when a scheduler exists. Also corrected two things in my own outlines that the reviewer's other findings exposed. The consumer-health-data policy must **not** describe report sharing by link — it is M3 in the product plan and does not exist in the codebase — and its third-party list must include **Google Fonts**, which the privacy policy discloses and this one omitted; a reader comparing the two would rightly ask what else is missing. On the consent-separateness question: `ConsentType.CONSUMER_HEALTH_DATA` is consent to **collect**, and the document now says so plainly, adding that nothing is shared and that consent to share will be asked for separately when something can be. **No second `ConsentType` now** — an unused `CONSUMER_HEALTH_DATA_SHARING` in the enum invites a future onboarding screen to collect it alongside the others, which is the bundling MHMD prohibits; it belongs to the feature that first shares something, and that feature's plan owns both the type and the screen. The remaining reviewer findings (hosting, at-rest encryption, backups and processor contracts asserted before any infrastructure exists) are wording the coordinator is correcting, and they are governed by open question 5, which already says to describe only what is true on the day the documents ship. |
