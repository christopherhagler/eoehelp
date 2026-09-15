# ADR 0001 — No doctor accounts; reports are shared by link

**Status:** Accepted · 2026-09-15

## Context

eoehelp holds identifiable health data but is intended to operate as a
patient-owned personal health record rather than as a covered entity or a
business associate under HIPAA. That posture determines vendor obligations,
cost, and how much compliance machinery the project must carry.

The distinction is not about the data. It is about the relationship. A patient
keeping their own health record and choosing to show it to someone is
categorically different from an operator supplying a system that a clinic uses
to deliver care.

## Decision

**No clinician login, in any form, until the project is ready to sign BAAs.**

Patients share a generated report through a revocable, expiring link. The
recipient needs no account. The report is a frozen snapshot, not a live view.

## Consequences

- Vendor BAAs are not required by the relationship. (We hold AWS's anyway — it is
  free and self-serve — but nothing depends on it.)
- Clinicians read the report with zero friction, which is the difference between
  it being used and ignored.
- We cannot build panel views, clinician dashboards, or provider-initiated data
  entry. These are genuinely valuable and are genuinely off the table.
- **Adding doctor accounts is a compliance decision, not a feature decision.** It
  triggers the full BAA workstream, a legal review of the operator relationship,
  and very likely SOC 2. Anyone proposing it should read this ADR first.

## Alternatives rejected

**Doctor accounts with a BAA from day one.** Defensible, but it front-loads
significant cost and legal work onto a product with no users yet, and the
clinician-adoption problem is not solved by giving them another login.

**Read-only clinician accounts as a "lighter" option.** The relationship, not
the permission level, is what creates the obligation. This would carry the same
exposure while feeling safer, which makes it worse than the explicit version.
