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
