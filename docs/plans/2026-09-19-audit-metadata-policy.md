# What the audit trail may contain

**Status:** Draft · 2026-09-19

## Goal

`CLAUDE.md`, ADR 0002, the model docstring in `audit/models.py`, and all three
legal documents say the audit trail holds field names and counts, never values.
The code does not do that. Found by the legal reviewer while checking the
documents against the code:

| Site | Values stored today |
|---|---|
| `medications/service.py:114,150,244` | `medication_code`, `frequency`, `stop_reason`, dose `status`, `on_date` |
| `symptoms/service.py:107,167,187` | `entry_date`, `entry_method`, `range_start`, `range_end` |
| `food/service.py:169,225,430` | `eaten_on`, `meal`, `entry_method`, `range_start`, `range_end` |
| `insights/service.py:111` | `flagged`, `assessed` — counts of clinical findings |
| `identity/onboarding_service.py:108` | `timezone` |

Audit rows also keep `ip_address` and `user_agent`, and they deliberately outlive
the account. So today, after a patient exercises a deletion right, the operator
still holds against a durable `patient_id`: which drugs they took, why they
stopped, which days they logged symptoms and food, their timezone, their IP
addresses, and their browser strings. That is consumer health data retained after
a deletion request, which is the single most challengeable thing in the system,
and it makes a statement in the privacy policy false.

Afterwards: one rule, written down, enforced at the write path, checked
statically in CI, and described accurately in the documents. And an account
deletion leaves a trail that can still answer "was this record accessed, by whom,
when" without holding anything about the patient's health.

**The root cause is the shape of the guard, not any individual call site.**
`audit/service.py:_safe_metadata` is a deny-list over key *names*
(`PHI_FIELD_NAMES`, `*_encrypted`) that passes every other scalar through. A
deny-list cannot enforce "no values", because the next field name nobody thought
of is admitted by default. The fix is an allow-list.

## Clinical basis

No clinical computation. Two constraints from outside the code set the
requirements:

- **The trail must survive deletion to be worth having.** It answers "was this
  person's record accessed, and by whom" — the question a breach response and a
  My Health My Data Act accountability request both start from. Deleting the
  trail with the account would also delete the record *of the deletion*, which is
  the evidence the right was honoured. ADR 0002 and the `delete_account`
  docstring already commit to this, and it stays.
- **Anything in the trail that describes the patient's health is retained health
  data.** MHMD's definition of consumer health data is broad and reaches
  inferences and linked identifiers, so "which drug, on which day, from which IP"
  sitting against a persistent patient id after a deletion request is exposure
  with no expiry and no consent.

Those pull in opposite directions only if the trail's content is confused with
the trail's purpose. It is not: **the access question needs who, when, what kind
of record, which row, and whether it succeeded. It never needs the record's
contents.**

*Pending clinical confirmation:* nothing. *For counsel:* the residue described
under *What deletion leaves behind* and the retention period in open question 2.

## Scope

**In scope**

- The rule, as an allow-list registry in `audit/metadata.py`, enforced by
  `audit.record`.
- Correcting all eleven call sites listed above.
- Nulling `ip_address` and `user_agent` for the patient's rows inside the account
  deletion transaction, and the column-level grant that permits exactly that and
  nothing more.
- A static test that every `metadata=` key at every call site is in the registry.
- ADR 0012, an amendment to ADR 0002, the `audit/models.py` docstring, and the
  `CLAUDE.md` rule line so the written claim matches the code.

**Out of scope**

- **A pruning job for old audit rows**, and a general age-based scrub of
  `ip_address`/`user_agent` across all rows. Both need a scheduler the stack does
  not have (no cron, no worker). Recommended retention is open question 2; the
  deletion-time scrub below is synchronous and needs no scheduler.
- **A patient-facing activity view.** The trail is not exposed through the API
  today and this does not change that.
- Changing what the `audit_log` columns are, beyond the two that get nulled.
- The legal documents themselves. See *Relationship to the legal documents*.

## Design

### The rule

> Audit metadata may describe **the request and the shape of what changed**. It
> may never describe **the patient's health, body, behaviour, or whereabouts**.

Four corollaries settle every case in this codebase, and they are the sentences
to put in the ADR:

1. **If the value is also on the row, the audit copy adds legibility only while
   the row exists, and becomes residue once it is deleted.** That is the whole
   argument against `medication_code`, `frequency`, `stop_reason`, `status`,
   `meal`, `entry_method`, and `timezone`. While the account exists, the row
   itself answers "which drug" far better than a copy in the trail; after
   deletion, the copy is the only thing left, and it is the thing that should not
   be.
2. **Rows are identified by id, not by date.** Every clinical table has a UUID
   primary key, and `resource_id` already carries it. `entry_date` and `eaten_on`
   look like structure because they are natural keys, but `resource_id` makes
   them redundant for identification while they remain a dated behavioural
   timeline for a named patient id. So: **no dates in metadata at all**, at any
   precision. `occurred_at` — when the access happened — stays, because it
   describes the access rather than the patient.
3. **A count is permitted when it counts records or parts of a record; it is
   forbidden when it counts clinical findings or states.** `returned: 84` and
   `ingredient_count: 7` describe volume and shape, which is what tells a breach
   response how much was read. `flagged: 3` and `assessed: 6` are derived
   clinical conclusions about the patient and answer nothing about access.
4. **Ids and presence flags are permitted.** A UUID is already a pseudonym and
   becomes a dangling pointer once its row is deleted; `has_notes: true` says a
   field was populated, not what it said.

For date ranges on list reads, the replacement is **`window_days`**: "84 symptom
entries were read across a 30-day window" preserves the scope of the access —
which is what a notification has to characterise — without recording which days
the patient lived through. This is a deliberate trade: support can no longer read
"which day did they edit" out of the trail and must use `resource_id`. That cost
is worth naming and accepting.

### The registry

New module `audit/metadata.py` — `audit` imports only the foundation (ADR 0010),
and this module imports nothing at all, so the rule sits below every domain:

```python
class MetadataType(StrEnum):
    FIELD_NAMES = "field_names"   # list[str] of schema field names
    COUNT = "count"               # int >= 0, of records or parts of a record
    FLAG = "flag"                 # bool
    ID = "id"                     # str(UUID)
    TERM = "term"                 # a value from a fixed non-patient vocabulary
    DIGEST = "digest"             # 64-char lowercase hex

# Every key the audit trail may ever hold, with why it is not patient content.
# Adding a key is a deliberate, reviewable change — the same friction as
# RLS_TABLES in a migration.
AUDIT_METADATA_KEYS: Final[dict[str, MetadataType]] = {
    "fields": MetadataType.FIELD_NAMES,      # which fields changed, never their values
    "returned": MetadataType.COUNT,          # how many rows a read returned: access scope
    "window_days": MetadataType.COUNT,       # the span a read covered, not which days
    "ingredient_count": MetadataType.COUNT,
    "label_ingredient_count": MetadataType.COUNT,
    "custom_ingredients_created": MetadataType.COUNT,
    "biopsy_sites": MetadataType.COUNT,
    "lag_days": MetadataType.COUNT,          # an analysis parameter, chosen in the request
    "has_notes": MetadataType.FLAG,
    "has_prescriber_note": MetadataType.FLAG,
    "has_erefs": MetadataType.FLAG,
    "has_dilation": MetadataType.FLAG,
    "has_facility": MetadataType.FLAG,
    "include_ended": MetadataType.FLAG,      # a filter in the request
    "medication_id": MetadataType.ID,
    "family_id": MetadataType.ID,
    "consent_type": MetadataType.TERM,       # which agreement, not a health fact
    "document_version": MetadataType.TERM,
    "product_source": MetadataType.TERM,     # which upstream dataset, not the patient
    "reason": MetadataType.TERM,             # why an auth attempt was refused
    "content_sha256": MetadataType.DIGEST,
}
```

`TERM` needs a bound or it becomes a hole: a term must be one of a closed set
declared beside the key (`ALLOWED_TERMS: dict[str, frozenset[str]]`), so
`reason` cannot one day carry a sentence. `consent_type` and `product_source`
take their enum values; `document_version` matches the document-id pattern.

### Enforcement at the write path

`audit/service.py:_safe_metadata` becomes allow-list based:

- A key not in `AUDIT_METADATA_KEYS` is **dropped**, and `audit.metadata_rejected`
  is logged with the key name only.
- A value of the wrong type for its key is dropped the same way.
- Two shape guards independent of the registry, so a registry entry cannot be
  misused: reject any string matching `^\d{4}-\d{2}-\d{2}` (a date leaking in as
  a `TERM`), and any string longer than 64 characters (almost certainly content).
- When `settings.environment == "local"` — development and the test suite — a
  rejection **raises** `AuditMetadataError` instead of only being dropped, so a
  mistake fails immediately rather than silently degrading the trail.

Dropping rather than raising in deployed environments is deliberate: the audit
row commits in the same transaction as the business write, so raising in
production would turn a metadata typo into a failed symptom save. Dropping is
fail-safe for privacy, which is the property being protected, and the static test
below means a bad key cannot reach production in the first place.

`PHI_FIELD_NAMES` and the `*_encrypted` check stay as a second layer. They now
catch nothing (an allow-list already excludes those keys), and that is the point
of defence in depth.

### The call sites

| File and site | Now | Becomes |
|---|---|---|
| `medications/service.py:114` create | `medication_code`, `frequency`, `has_prescriber_note` | `fields` (payload field names), `has_prescriber_note` |
| `medications/service.py:150` stop | `medication_code`, `stop_reason` | `fields: ["ended_on", "stop_reason"]` |
| `medications/service.py:183` remove | `medication_code` | no metadata — `resource_id` is the medication |
| `medications/service.py:199` list | `returned`, `include_ended` | unchanged |
| `medications/service.py:244` log dose | `medication_code`, `status`, `on_date` | `medication_id` |
| `medications/service.py:270` undo dose | `medication_id` | unchanged |
| `symptoms/service.py:107` create/update | `entry_date`, `entry_method`, `fields`, `has_notes` | `fields`, `has_notes` |
| `symptoms/service.py:167` list | `range_start`, `range_end`, `returned` | `window_days`, `returned` |
| `symptoms/service.py:187` delete | `entry_date` | no metadata |
| `food/service.py:169` delete item | `eaten_on` | no metadata |
| `food/service.py:225` list range | `range_start`, `range_end`, `returned` | `window_days`, `returned` |
| `food/service.py:430` save item | `eaten_on`, `meal`, `entry_method`, three counts, `product_source` | the three counts, `product_source` |
| `food/service.py:204,267,295` | `fields`, `returned` | unchanged |
| `insights/service.py:111` | `lag_days`, `flagged`, `assessed` | `lag_days` |
| `procedures/service.py:181,201,209` | presence flags and `biopsy_sites` | unchanged |
| `identity/onboarding_service.py:108` | `fields`, `timezone` | `fields` |
| `identity/auth_service.py:94,109,172,318` | `reason`, `family_id` | unchanged |

Six of the seventeen sites are already compliant, including every one in
`procedures`, which is evidence the rule is livable rather than aspirational.

`insights/service.py` loses the `flagged`/`assessed` computation entirely, so the
two `sum(...)` lines above the audit call go with it.

### What deletion leaves behind

`delete_account` gains one step, in the same transaction, before the user is
deleted: `UPDATE audit_log SET ip_address = NULL, user_agent = NULL WHERE
patient_id = :patient_id`.

Those two columns are the strongest link from the surviving trail to a living
person — an IP resolves to a subscriber, a user agent to a device — and they have
the shortest useful life: their investigative value is measured in weeks, while
the residual risk lasts forever. Nulling them at deletion is the cheap, complete,
synchronous version of the age-based scrub in open question 2.

**This requires a grant change, and it narrows the append-only property, so it is
stated precisely.** `app_runtime` today holds `INSERT` only on `audit_log`
(`UPDATE` and `DELETE` are revoked). The migration adds
`GRANT UPDATE (ip_address, user_agent) ON audit_log TO app_runtime` — a
**column-level** grant, which is the right Postgres tool here. What the trail
says happened (`action`, `resource_type`, `resource_id`, `patient_id`,
`actor_user_id`, `occurred_at`, `outcome`, `metadata`) stays un-updatable and
un-deletable by the application, so a compromised app still cannot erase or
rewrite the record of its own access. It could null attribution columns across
the trail, which is a real if secondary loss — and an attacker at that level can
already write arbitrary rows. The alternative, an out-of-band maintenance job
under a second role, buys back that sliver at the cost of a scheduler the stack
does not have and an honest-but-awkward "we scrub within 24 hours" in the privacy
policy. Synchronous and complete wins.

**What remains after deletion, stated plainly**, because the privacy policy has
to say it and "field names only" is not an adequate description:

- when each action happened, whether it succeeded, and the kind of record it
  touched (`symptom_entry`, `endoscopy`, `medication`)
- random ids: the patient id, the actor user id, the resource id — every row they
  pointed at is gone, so they are pseudonyms with nothing behind them
- the shape metadata above: field names, counts, presence flags

The accepted residue is **categorical**: a reader can tell the account logged
symptom entries and recorded endoscopies. That is irreducible — you cannot answer
"was their data accessed" without naming what kind of data — and it is the
deliberate trade for having a breach-response trail at all. The alternative,
deleting the rows with the account, destroys both the breach-response capability
and the evidence that the deletion happened, and is rejected. Counsel should see
this paragraph; it is open question 1.

### Documentation to correct in the same change

- **ADR 0012, new:** "What the audit trail may contain" — the rule, the four
  corollaries, the allow-list registry, the column-level grant and what it costs,
  and the accepted residue after deletion.
- **ADR 0002:** amend the audit paragraph to point at 0012 and to stop implying
  the trail is entirely un-updatable.
- **`audit/models.py` docstring:** "`metadata_` carries changed field *names*
  only, never PHI values" becomes the real rule, with a pointer to
  `audit/metadata.py`.
- **`CLAUDE.md`:** "No PHI in logs, errors, or the audit trail: field names and
  counts only" becomes "…: the audit trail may describe the request and the shape
  of a change, never the patient's health, behaviour, or whereabouts (ADR 0012)."

## Security and privacy

- **Isolation is unchanged.** No new table, no new patient-owned data, no new
  route. `audit_log` has no RLS (it is not readable through the API at all) and
  that does not change.
- **The grant is narrowed to two columns by name.** A test proves `app_runtime`
  can update those two and still cannot update `action` or `metadata`, or delete
  any row.
- **The trail's tamper-evidence is preserved** where it matters: sequential ids,
  no deletes, no updates to what happened.
- **Logs.** A rejected metadata key is logged by *name*, never with its value —
  the same rule as the rest of `observability.py`.
- **Net effect on stored PHI:** strictly less. No call site gains a value; eleven
  lose one.

## Testing

**`apps/api/tests/audit/test_metadata_policy.py`**

- **The static scan, which is the test that matters.** Walk the AST of every
  module under `eoehelp_api/`, find `audit.record(...)` calls, and assert that
  every key of a `metadata=` dict literal is in `AUDIT_METADATA_KEYS`. A
  non-literal `metadata=` argument fails with "metadata must be a dict literal at
  the call site", because a trail whose possible contents cannot be read off the
  code is not auditable. Same technique as `tests/test_architecture.py`, and it
  covers call sites no runtime test exercises.
- Every registry key has an entry in `ALLOWED_TERMS` if its type is `TERM`.
- `_safe_metadata` drops an unknown key, drops a wrongly typed value, drops a
  date-shaped string, drops a string over 64 characters — and in each case the
  returned dict contains neither the key nor the value.
- With `environment == "local"`, each of those raises `AuditMetadataError`.
- A parametrised test over the forbidden values from the defect table
  (`medication_code`, `entry_date`, `timezone`, `flagged`, `meal`,
  `entry_method`, `stop_reason`, `on_date`) asserting each is rejected. This is
  the regression test for the reported defect, named value by value.

**`apps/api/tests/db/test_audit_grants.py`** (new, connecting as `app_runtime`,
in the style of `test_patient_isolation.py`, which passes meaninglessly as the
owner)

- `app_runtime` can `UPDATE audit_log SET ip_address = NULL, user_agent = NULL`.
- `app_runtime` cannot update `action`, `metadata`, `patient_id`, or `outcome`.
- `app_runtime` cannot `DELETE` from `audit_log`.

**`apps/api/tests/identity/test_onboarding.py`** (extended — deletion already has
coverage there)

- After `delete_account`, the patient's audit rows still exist, and every one has
  `ip_address IS NULL` and `user_agent IS NULL`.
- The surviving rows contain no value from the forbidden list: assert the union of
  all `metadata` keys across the patient's rows is a subset of the registry, and
  that `account.delete` itself is present.
- The existing assertions that the trail survives deletion stay as they are.

**Per-domain service tests** — each of the eleven changed sites gets its
assertion updated to the new metadata. Where a test currently asserts
`metadata["medication_code"] == ...`, it asserts the key is absent, which keeps
the defect from being reintroduced by a revert.

## Relationship to the legal documents

**Two features, not one, and this one goes first.**

It is a separate change because it touches five domain services, the audit
service, a grants migration, two ADRs, a model docstring, and `CLAUDE.md` — a
diff that has nothing in common with writing three documents, and that the code
reviewer judges against different criteria. Folding them together would produce a
commit nobody can review well.

It goes first because **the documents cannot be written truthfully until it
lands.** The dependency is concrete: the privacy policy's retention section and
all three documents' description of the audit trail must describe the corrected
behaviour, including the *What deletion leaves behind* list above in place of
"field names and counts only". The legal-documents plan's review log records the
dependency in the same revision as this plan.

There is no risk of the wrong text reaching a patient in the meantime, because
production refuses to boot while the documents are drafts — but "no patient sees
it" is not the standard. The standard is that a claim in a legal document is true
when it is written.

## Open questions

1. **The residue after deletion.** *For counsel:* is the categorical residue
   described under *What deletion leaves behind* — time, kind of record, random
   ids, shape metadata, no values, no IP, no user agent — defensible as
   retained-for-security-and-accountability under MHMD's deletion right, and is
   the privacy policy's disclosure of it sufficient?
   *Default:* keep it and disclose it precisely. The alternative destroys the
   evidence that the deletion happened.
2. **How long audit rows are kept at all.** Nothing prunes them today, so the
   answer is currently "forever", and the privacy policy should not say that.
   *Default:* state a 2-year retention for the access trail in the policy and
   implement pruning when a scheduler exists (M4). If the user prefers not to
   promise what is not yet built, the fallback is to state that rows are kept
   while the service operates and that a retention limit is being introduced —
   honest, and weaker.
3. **Should the `ip_address`/`user_agent` scrub also run on age, for living
   accounts?** It is the same privacy argument without a deletion request.
   *Default:* yes, at 90 days, once a scheduler exists. Not in this change.

## Review log

| Round | Reviewer | Verdict | What changed |
|---|---|---|---|
| 1 | architect | Draft ready for implementation | Written in response to the legal reviewer's finding that the audit trail stores clinical values while four documents and `CLAUDE.md` say it does not. Decided: an allow-list registry rather than the current deny-list, because a deny-list admits every field name nobody anticipated; no dates in metadata at any precision, since `resource_id` already identifies the row and a date timeline is behavioural data about a named patient id; date ranges become `window_days`, which preserves the scope of an access without recording which days the patient lived through; counts permitted for records and parts of records, forbidden for clinical findings, which removes `flagged`/`assessed`; `ip_address` and `user_agent` nulled inside the deletion transaction via a column-level grant, chosen over an out-of-band job because the stack has no scheduler and a synchronous scrub needs no "within 24 hours" caveat in the policy. Accepted and documented rather than hidden: the categorical residue after deletion, which is irreducible if the trail is to answer the access question at all. Enforcement is at the write path (drop and warn always, raise in `local`) plus a static AST scan of every call site, because runtime tests do not reach every audit call. Recommended as its own feature, landing before the legal documents, since a document claim must be true when it is written. |
