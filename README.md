# eoehelp.org

A personal health record for people living with **eosinophilic esophagitis (EoE)**.

Patients log symptoms daily in under a minute, the system assembles a clinical
summary their gastroenterologist can actually use, and — only with explicit
opt-in — a de-identified version of that data becomes a research resource for a
disease that is persistently short of one.

> eoehelp is a personal health record that patients control. It is **not** a
> medical record system and does **not** provide medical advice.

## Quick start

Everything runs in containers under **Podman**. You need `podman` and nothing else.

```bash
make up
```

| Service | URL | Notes |
|---|---|---|
| Web | http://localhost:4200 | Angular 22 dev server |
| API | http://localhost:8000/docs | FastAPI, interactive docs outside production |
| Mailhog | http://localhost:8025 | Catches every magic-link email; no mail leaves your machine |

Sign in at http://localhost:4200/sign-in with any address, then open Mailhog to
click the link. Registration and login are the same action by design.

```bash
make test            # API suite, in a container
make openapi         # regenerate the committed API contract
make verify-promote  # prove image promotion preserves the digest (needs skopeo)
make help            # everything else
```

`verify-promote` is the only target with an extra dependency (`brew install
skopeo`). It stands up two throwaway registries and proves that promoting an image
between them preserves its digest — the property that lets production run the
exact artifact that was tested rather than a rebuild of it. See
[ADR 0006](docs/adr/0006-buildah-and-skopeo.md).

## Why it is built this way

EoE is managed on longitudinal evidence — how often food sticks, which
eliminations held, what each biopsy showed. Three decisions follow from that and
explain most of the codebase:

**Validated instruments, not invented scales.** The daily log follows the
Dysphagia Symptom Questionnaire, the measure used as an endpoint in the
budesonide and dupilumab trials. A bespoke 1–10 slider produces a number no
gastroenterologist trusts and no journal accepts.

**Identity and clinical observation are separate table groups.** Research export
reads the clinical side through a pseudonym and never joins to identity. That is
what keeps de-identified export a query rather than a schema migration.

**No doctor accounts.** Reports are shared through revocable, expiring links. A
clinician logging in to use this as part of care delivery would likely make the
operator a HIPAA business associate; a patient handing over their own record does
not. The share-link design is what holds that line.

## Layout

```
apps/api        FastAPI service — routers, services, repositories, models
apps/web        Angular 22 SPA — standalone components, signals, zoneless
packages/openapi  Committed API contract; CI fails if it drifts from the code
infra           Container and database bootstrap
docs/adr        Decision records, including the ones that carry legal weight
```

## Security properties

These are enforced and tested, not aspirational. `apps/api/README.md` has the
full list; the load-bearing ones:

- **Patient data is reached only through scoped repositories.** Routes are
  `/me/*`, and `patient_id` comes from the verified access token — never from a
  path or body parameter, which removes the IDOR bug class rather than guarding
  against it.
- **Row-level security is a backstop.** The app connects as a role that owns no
  tables, scoped per transaction with `set_config(..., is_local => true)`. Tests
  assert that an unscoped query returns zero rows and that scope cannot leak
  across a pooled connection.
- **Audit rows commit in the same transaction as the change they describe**, and
  the application role holds `INSERT` only.
- **PHI never reaches logs.** Redaction is by field name and is covered by tests.
- **Access tokens live in memory; refresh tokens in an httpOnly cookie.** Reuse
  of a rotated refresh token revokes the entire token family.

## Status

- **M0 (foundations): complete.** Containerized stack, identity and consent
  schema, magic-link authentication, audit trail, row-level security, and CI.
- **M1 (daily tracking): complete.** Onboarding with versioned consent, the
  DSQ-based daily log and 14-day score, medications with RRULE-based adherence,
  account deletion, and a synthetic history generator (`make seed`).
- **Food and ingredient logging: complete.** An allergen-tagged ingredient
  catalog, patient-defined ingredients, and recent foods for fast re-logging. See
  [ADR 0007](docs/adr/0007-food-and-ingredient-logging.md), including the limits
  on what a future food-trigger insight may claim.

Next are the clinical context tables (M2), then the doctor report, the
food-symptom insight, and the progress dashboards (M3).

## Before this serves a real patient

Launch is gated on items that are not code: an independent penetration test,
attorney-reviewed terms and the Washington My Health My Data Act disclosure,
clinical advisor sign-off on the report, a third-party accessibility audit,
entity formation, and insurance. They are listed in the project plan and should
be treated as blocking.
