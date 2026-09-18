# ADR 0002 — Three independent layers of patient data isolation

**Status:** Accepted · 2026-09-15

## Context

The worst realistic failure in this system is one patient reading another's
health record. A single forgotten `WHERE` clause in a future endpoint should not
be sufficient to cause it.

## Decision

Three layers, each independently sufficient to prevent cross-patient reads.

**1. Structurally scoped access.** Patient-facing routes are `/me/*`. There is no
`/patients/{id}/...`, so there is no "which patient" question to answer wrongly.
`patient_id` is read from the verified access token and nowhere else.
Repositories take a scope at construction and apply it in a shared base query.

**2. Postgres row-level security.** The application connects as `app_runtime`,
which **owns no tables** — owners and superusers bypass RLS, so an
owner-connected app would make every policy inert. Scope is set per transaction
with `set_config('app.current_patient_id', :id, true)`.

`set_config(..., is_local => true)` rather than `SET LOCAL` because only the
function form accepts a bind parameter, so the id is never interpolated into SQL.
Transaction scope is the load-bearing part: a session-scoped `SET` would survive
on the pooled connection and hand the next request the previous patient's scope —
the isolation mechanism itself becoming the disclosure.

Policies use `NULLIF(current_setting(..., true), '')::uuid`, so an unscoped
session yields NULL, matches nothing, and returns zero rows.

**3. Tests that prove it.** `tests/db/test_patient_isolation.py` connects as
`app_runtime` — as the owner these tests would pass while proving nothing — and
asserts that an unscoped query returns nothing, that naming another patient's id
explicitly still returns nothing, and that scope does not survive into a
subsequent transaction on the same connection.

Not-found is always `404`, never `403`: a 403 confirms the record exists, which
is itself a disclosure.

## Consequences

- Every new patient-owned table must be added to `RLS_TABLES` in the migration
  and given a policy. This is a real ongoing obligation.
- Connection pooling must stay transaction-scoped.
- A missing filter degrades to "returns nothing" rather than "returns everything".

## Alternatives rejected

**Application filtering alone.** One bug away from a breach, and the bug is
invisible in review because the code looks correct.

**RLS alone.** Pushes authorization into policies that are hard to test and easy
to disable accidentally by connecting as the wrong role.
