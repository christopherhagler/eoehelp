# ADR 0007 — Food and ingredient logging, and the limits on what it may claim

**Status:** Accepted · 2026-09-16
**Relates to:** [ADR 0002](0002-patient-data-isolation.md) (patient data isolation)

## Context

Patients asked to log what they eat, down to the ingredient, so that the product
can later show which foods may be a problem. In EoE that question matters more
than in most conditions: elimination diets are a first-line treatment, and the
groups they remove (milk, wheat, egg, soy, nuts, seafood) are decided per group.

Two things make the design less obvious than a list of meals:

- A food-symptom analysis is only as good as the exposure record it reads, and a
  mutable record quietly changes the answer after the fact.
- What the product may *say* about a food is constrained by the disease, by
  statistics, and by FDA device regulation, in that order.

## Decision

### Data model

- **`ingredient_catalog`** is reference data keyed by slug. Each row has
  `allergen_groups[]` and lower-case search `aliases`. It's seeded by migration
  0004 and has no row-level security; the application role can read it and not
  write it. The group assignments are **pending clinical confirmation**, as the
  DSQ weights are.
- **`custom_ingredients`** is patient-owned and under RLS. A row is created
  implicitly when a typed name matches nothing in the catalog (names *and*
  aliases), so a typed "flour" still counts as wheat.
- **`food_log_items`** holds one row per eaten food: day, meal, name, and
  `entry_method`, which is derived the same way as for symptom entries.
- **`food_log_item_ingredients`** is a snapshot of the item's ingredients at log
  time. It carries `patient_id` so RLS binds without a join.

**Ingredients are a snapshot, not a recipe reference.** If a log item pointed at a
mutable "my usual pizza", editing the recipe would rewrite every past day,
including days an analysis had already read. Allergen *tags* are the exception:
they describe what an ingredient is, so correcting one ("the relish contains soy")
corrects history on purpose.

**Catalog and patient ingredients are separate tables.** A single table with a
nullable owner looked simpler, but it has two problems:

- `TRUNCATE patients CASCADE` would wipe the reference rows too.
- It needs split RLS policies, so the application can read catalog rows without
  being able to delete them.

Separate tables make both problems impossible, at the cost of one "exactly one
of" check constraint on the join table.

**Re-logging uses recent foods, not saved recipes.** Recent foods are derived from
history, so there is nothing for the patient to manage, and the list follows what
they actually eat.

**The backfill window is shared with symptoms** (`services/entry_dates.py`). A
patient catching up after a flare fills in both halves of a day; accepting one
and refusing the other would be incoherent.

**The audit trail records shape, never content.** It stores day, meal, and counts,
but no food or ingredient names.

### What a future food insight may claim

The trigger report is planned for M3 and not built. These constraints bind it:

1. **Reactions are delayed.** EoE is non-IgE-mediated, so exposure must be modelled
   with lag windows, not same-day correlation.
2. **Never "safe".** Eosinophilic inflammation can be active without symptoms, so
   a symptom log cannot clear a food. The strongest allowed wording is "no
   association seen across N exposures in your logs". Biopsy-confirmed
   reintroduction outranks any correlation.
3. **Descriptive only.** The report may say "symptom days were more common after
   meals containing milk (9 of 14 vs 3 of 40)". It must never say "avoid milk".
   The clinical advisor and counsel approve the wording.
4. **Statistics.**
   - Control for multiple comparisons.
   - Show counts, not p-values.
   - Require minimum exposed and unexposed days.
   - Report foods eaten almost daily as "can't assess".
5. **Co-exposure must be handled, not ignored.** The synthetic generator already
   shows the failure: for a patient whose planted trigger is milk, a naive
   exposed-versus-unexposed comparison ranks *wheat* higher, because macaroni
   cheese, quesadillas, and cheese and crackers carry both. A method that can't
   separate co-eaten groups will blame the wrong one.

### Ground truth

The synthetic generator plants hidden trigger groups per patient. They are held
on the plan and never written to the database, and some patients get none, as a
false-alarm check. Eating a trigger raises symptom severity for that day and the
two after. A test asserts the planted signal is recoverable from the logged data
on average. Any analysis must report its recall and false-positive rate against
these patients before a real patient sees its output.

## Consequences

- Five new endpoints under `/me/foods`, plus a catalog at `/foods/ingredients`.
  All are covered by the cross-patient tests.
- A new isolation test asserts that **every** table with a `patient_id` column has
  RLS enabled. `audit_log` is the one exception, because it is protected by its
  grant. The next patient-owned table is covered without anyone remembering to
  add it.
- The generator's copy of the catalog's group assignments is checked against the
  database in CI, so the two cannot drift silently.
- Food names and custom ingredient names are free text and are excluded from
  research export, like notes.
