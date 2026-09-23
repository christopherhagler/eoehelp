# ADR 0011 — Legal documents as hash-pinned files, gated on attorney review

**Status:** Accepted · 2026-09-19
**Plan:** [2026-09-19-legal-documents.md](../plans/2026-09-19-legal-documents.md)

## Context

Onboarding recorded consent to three documents — `tos-2026-09`,
`privacy-2026-09`, `chd-2026-09` — that did not exist. The checkboxes linked
nowhere, the sign-in page promised terms nobody could read, and a consent row
named a version with no text behind it. A consent record that cannot be tied to
wording is not a record.

Two further constraints shaped the answer. The operator is one individual in
Alabama with no company, so the liability wording has to be both strong and
plausibly enforceable. And Washington's My Health My Data Act requires a
separate consumer health data disclosure, prominently linked, with a private
right of action behind it.

## Decision

**The text lives in the API package, beside the version registry**, at
`identity/legal/*.md`. The service that holds a consent row can then produce the
text behind it. `pyproject.toml` declares the directory as package data, because
the runtime image installs a wheel while tests run from the source tree.

**A published document's bytes never change.** The registry pins each file's
sha256, and `verify_integrity()` checks every digest at startup. Correcting a
document means a new file with a new version id, never an edit.

**Each consent row stores the digest as well as the version.**
`consents.document_sha256` (migration 0006, with a hex check constraint) answers
"show me exactly what they agreed to" after a document has been superseded, and
detects the one failure the registry cannot: a file edited together with its
recorded digest.

**The text is parsed server-side into typed blocks.** A deliberately small
markdown grammar (`identity/legal_markdown.py`) accepts headings, paragraphs,
bullets, tables, bold, and links restricted to `https://`, `mailto:`, and
internal paths. Anything else raises. The web app renders typed blocks, so no
`innerHTML`, no sanitiser, and no markdown dependency exists on either side.

**Unreviewed drafts cannot reach a patient.**
`documents.enforce_review_status()` raises at startup when the environment is
production and any document required at onboarding is still a draft, in the
spirit of `Settings.enforce_production_safety`. Launch gate item 5 —
attorney-reviewed terms, privacy policy, and consumer health data disclosure —
becomes a deploy failure rather than a checklist item. The review status is also
in the API response, on the document page, in the onboarding dialog, and above
the consent checkboxes.

**The research participation document is deliberately absent.** Nothing can
grant that consent today and the export it would describe is M5, so
`current_for` raises for it: the first attempt to record one fails loudly
instead of pointing at text that describes software that does not exist.

## Why write draft legal text at all

The privacy policy and the consumer health data disclosure are factual
descriptions of a system only we know. An attorney cannot draft them from
nothing, and a generic template would be both worse and more expensive to
correct. Writing them is engineering work.

The terms of service are written as a brief for counsel: the load-bearing
clauses (assumption of risk, warranty disclaimer, liability limitation, the
carve-outs, and the arbitration section) in full, so the review is an edit
rather than a blank page. What makes that safe is the production gate, not a
disclaimer.

## Consequences

- A new version is a new file, a new registry entry, and a new digest. There is
  no in-place edit, by construction.
- **Re-consent does not exist yet**, and attorney review will change the text
  and therefore the version. It is the immediate follow-up and a prerequisite
  for the first beta patient. The production gate is what makes deferring it
  safe.
- The documents must stay true as the code changes. A claim that stops being
  true is a bug: the deletion sentence was corrected during implementation
  because no delete screen exists yet, and that is the failure mode to watch.
- Tests assert the statutory sections of the consumer health data policy, the
  load-bearing clauses of the terms, and each feature of the arbitration clause
  separately, because each is a separate reason a court would refuse to enforce
  it.
- The operator now carries an obligation the code does not enforce: an
  arbitration opt-out sent by a patient must be answered and filed against their
  consent record. It belongs in a runbook before a real patient sees the terms.

## Amendment — 2026-09-21: a published-document ledger in the database

Two statements in the Decision and Consequences above were **wrong**, and the
development database proved it within a week of shipping. They are corrected
here rather than edited away, because the reason they were wrong is the useful
part.

**"A published document's bytes never change. The registry pins each file's
sha256, and `verify_integrity()` checks every digest at startup."** The check
compares a file with a digest that travels in the same commit. It detects
corruption, a packaging mistake, and an accidental edit — not a deliberate
rewrite, which updates both together and passes.

**"A new version is a new file, a new registry entry, and a new digest. There is
no in-place edit, by construction."** There was one. The eight corrections from
the legal review were applied under the same three version ids, and 54 consent
rows in the development database ended up split across six `(version, digest)`
pairs: 27 of them naming bytes that were never committed and cannot be
recovered. The only witness to what had been published was the commit that
changed it.

### The mechanism now

A **revision** is `(consent_type, version, content_sha256)` and is the unit of
evidence. A revision is *published* when a migration inserts it into the
`legal_documents` ledger. `consents` carries a composite foreign key to that
ledger, so the database refuses any consent row naming a revision it has no
record of. Documents are readable by digest — `GET /legal/documents/<sha256>`
returns exactly those bytes — and the API refuses to start when the registry in
the build and the ledger in the database disagree in either direction.

The ledger is the second witness the source tree cannot provide: its rows were
written by a migration that has already run, and no later commit moves them.

### The publishing rules

1. A material change is a new version id, and existing patients must re-consent.
2. A correction to a **draft** is a new revision under the same version id, with
   its own file and its own ledger row. Consents pinned to an earlier revision
   keep resolving to that revision's bytes.
3. A **reviewed** revision is frozen: no further revision under that id, rule 1
   applies instead. `verify_integrity` enforces it.
4. A reviewed revision's file is kept permanently. A draft revision's file may be
   retired only when no consent references it, which the foreign key makes a
   fact rather than a promise.

### Consequences

- **Publishing text now requires a migration.** That is the intended cost: it
  makes "what was published" a dated, reviewed record rather than a property of
  whatever is checked out.
- **The API depends on the database at startup.** Deliberate — an evidence check
  an outage can skip is not a control, and migrations run before the API in
  every environment.
- **`research_consent_scopes` is inside row-level security**, by carrying a
  `patient_id` like every other patient-owned table, with a composite foreign
  key so the denormalised key cannot disagree with its parent consent. It had
  no policy at all, and passed the catalogue test by having no `patient_id` for
  that test to find.
- **The 27 orphaned development rows were discarded** with a database rebuild.
  No option preserved them honestly.
