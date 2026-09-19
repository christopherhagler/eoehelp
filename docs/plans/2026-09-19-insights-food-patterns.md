# Insights: symptom trend and food patterns

**Status:** Implemented · 2026-09-19

## Goal

A patient opens **Insights** and sees two things they cannot see today:

1. **How they have been doing over time:** the DSQ 14-day score across the
   last 90 days as a line, with a table alternative.
2. **Which foods their log links to symptom days, and which it does not.**
   Each of the nine allergen groups gets one plain statement, backed by the
   counts behind it. Frequently eaten ingredients and additive classes show
   their counts only in v1 (see *Method*, step 9):
   - "Symptom days were more common after milk: 9 of 14 days, against 3 of
     40 otherwise."
   - "No pattern seen for egg across 60 days you ate it" (shown only when the
     log had enough data to see one).
   - "Can't tell yet for soy: symptom days after it 4 of 11, other days 9 of
     70. More days are needed to see a pattern either way."
   - "Wheat was in almost every day's food, so there are no days without it
     to compare against."

The patient's question is "what might be causing this?". The honest answer
from a diary is a short list of things worth raising with their
gastroenterologist, not a verdict. The feature is designed around that.

## Clinical basis

- **The outcome.** A *symptom day* is a scorable DSQ day (solid food eaten)
  with a daily DSQ score above 0, meaning food went down slowly or got stuck.
  Pain on swallowing is kept separate, as in the DSQ, and is not part of this
  analysis. Days without solid food are excluded, not counted as clear.
- **Exposure is lagged.** EoE is a delayed, non-IgE reaction. A day counts as
  *exposed* to X when X was logged on that day or on either of the two days
  before it (lag 0–2). The default is 2 days, and the API accepts 0–3.
  *Pending clinical confirmation:* the default lag and the range offered.
- **How missing food logs are handled.** A day is *analyzable* when it has a
  solid-food symptom entry, food was logged that day, and food was logged on
  at least L of the L + 1 days in its window (2 of 3 at the default). An
  unlogged day inside the window counts as "not eaten".
  - **This is not automatically conservative.** It would be if logging were
    unrelated to symptoms, but it may not be. In the generator's trigger-free
    patients, fully logged windows had a symptom rate of 0.379 against 0.314
    for partly logged ones, and about 14 points more exposure to every group.
  - **The 28-day blocks absorb this.** Within blocks, the Mantel–Haenszel
    risk difference between the two kinds of window is 0.000 in the
    generator. Real patients may log differently, and the synthetic
    trigger-free gate cannot show how they log. So each report carries a
    per-patient diagnostic:
    - `complete_window_share`
    - `logging_gap`: the within-block Mantel–Haenszel risk difference in
      symptom rate between fully and partly logged windows

    The first review of real (consented, de-identified) usage checks
    `logging_gap` across patients before the feature leaves beta; it is
    release gate 6. If a gap shows up, the fallback is already measured:
    stratifying by block × completeness cost 3 points of recall and 5 of
    precision in the generator.
  - **The stricter rule is not an option.** Requiring every window day to be
    logged left a median of 58 usable days a year in the power study, too
    few to assess anything.
- **Symptoms track inflammation poorly.** Eosinophilic inflammation can be
  active with no symptoms. So the feature never calls a food safe, never says
  "not an issue", and never recommends eating or avoiding anything. The
  strongest statement it makes is "no pattern seen across N days". Every
  screen carries this caveat.
- **Descriptive, not prescriptive.** This keeps the feature within general
  wellness and clinical decision support and outside FDA device rules. The
  wording in *Frontend* below is the complete set of statements the screen
  can make. *Pending clinical and legal sign-off* on that wording.
- **Biopsy-confirmed reintroduction outranks all of this.** Food challenges
  land in M2, and when they exist they will be shown above passive patterns.
  They are out of scope here.

## Method

Every setting below came from power studies on **tuning seeds 1000–2199**
(1,200 patients: `power_study_v2.py`, then `power_study_v3.py`) and is now
fixed. The pre-registered gates run on disjoint **held-out seeds** (see
*Validation*), and they run the production `insights.food_patterns` code, not
the prototype. The prototype lacked the short-block merge and the co-exposure
step. A change to any setting needs a new architect review and a new
held-out range.

For one patient, at lag L (default 2), for each of the **nine allergen
groups** X:

1. **Days.** Take the analyzable days in the last **540 days**, or the whole
   history if it is shorter. Each day has an outcome (a symptom day or a
   clear day) and an exposure to X (yes or no across the lag window).
2. **Blocks.** Split the days into **28-day calendar blocks**, counted back
   from the window's end. If the oldest block covers fewer than 14 calendar
   days, it merges into the next block. Blocks absorb slow changes (a new
   treatment, a flare, the season, a change in logging habits), so that time
   is not credited to a food.
3. **Status, in this order:**
   1. **No baseline:** 90% or more of the analyzable days are exposed.
   2. **Not enough data:** fewer than 8 exposed or 8 unexposed days *within
      informative blocks* (blocks holding both exposed and unexposed days).
   3. Otherwise, the group is tested (steps 4–6).
4. **The test: an exact within-block circular-shift test.**
   - **How it works.** Within each block, the exposure sequence is laid over
     the block's analyzable days in date order. Unanalyzable days are
     skipped, so the sequence has gaps. The sequence is then shifted
     circularly, wrapping around within the block, by every offset from 0
     to n − 1 with equal weight. Blocks shift independently.
   - **The statistic** is the number of exposed symptom days. Its exact null
     distribution is the convolution of the blocks' shift distributions: no
     random draws, one-sided, and standard library only.
   - **Why this test.** A shift keeps the day-to-day structure of both
     series (exposure runs from a three-day window, symptom runs from a
     flare) and breaks only their alignment. Using all offsets makes it a
     valid randomization test. At p < 0.05 it flagged 3.0% of trigger-free
     candidates, against the 8.7% the architect measured for the
     normal-approximation CMH test.
   - **Rejected:** a variant that left out short shifts. Once those shifts
     are dropped, the remaining shifts no longer form a group, so the test
     loses its validity. With it, 40% of trigger-free patients got flags.
5. **Many comparisons.** Benjamini–Hochberg runs across the groups that reach
   testing (at most nine) at
   **q = 0.05**. That is stricter than round 2's q = 0.10. Testing only the
   groups doubles recall, and the stricter q holds precision at about 81%.
6. **Size.** The effect is the Mantel–Haenszel risk difference (RD) across
   informative blocks, with the Sato variance. The standard error is
   inflated by 1.7 (√3, the length of an exposure run at lag 2) for serial
   dependence. The upper bound (UB) is one-sided at 95%.
   - **Flagged:** q ≤ 0.05 and RD ≥ **10 points**.
   - **No pattern seen:** UB < 10 points. The status appears only when the
     data could have shown an effect of that size.
   - **Can't tell yet:** everything else, with the counts.
7. **Co-exposure,** for each flagged X. Another group Y *qualifies* when:
   - Y ≠ X, and
   - Y is **enriched** on X's days: P(Y | X) − P(Y | not X) is at least
     0.25.

   Y does not need a baseline of its own; it only has to meet this rule.
   - **Why this measure, and only this one.** Suppose Y adds β_Y to the
     chance of a symptom day. Then Y raises X's apparent excess by β_Y ×
     (P(Y | X) − P(Y | not X)), the omitted-variable bias of a risk
     difference. So the enrichment measures how much of X's excess Y can
     account for. At 0.25, a Y with its own effect of up to 40 points can
     produce the 10-point floor unaided. Below 0.25, Y cannot plausibly
     explain a flag, however often it is eaten.
   - **Near-daily groups rarely qualify, and that is correct.** When Y is
     on most days whether or not X is (milk on about 92% of days at lag
     2), the enrichment is small, so Y cannot be what makes X's days worse.
     The no-baseline status already tells the patient that such a group
     cannot be assessed. Round 3 claimed the opposite, and that claim was
     wrong.
   - **Rejected: an "absence side".** P(not Y | not X) − P(not Y | X) is
     algebraically identical to the presence side, so it adds nothing.
   - **Rejected: conditioning the other way.** The rule tie(X, Y) =
     max(P(Y | X) − P(Y | not X), P(X | Y) − P(X | not Y)) was measured on
     the tuning seeds.
     - **Why it fails.** Both terms are the same covariance, the first
       divided by X's variance and the second by Y's. For a near-daily Y,
       Y's variance is tiny, so the second term is large even when Y
       explains nothing.
     - **What it did.** Of 252 flags, it named milk or wheat on 142, and
       only 18 of those were true triggers. It pinned 120 true-trigger
       flags on a group that was not a trigger. Strict precision fell from
       78% to 38%, and it rescued one more false flag than the presence
       rule.
     - **An odds ratio** has the same weakness on a near-daily group, and
       it is unstable on small cells.

   For the qualifying Y with the largest enrichment, the step compares days
   with X but not Y against days with neither, with the same test and the
   same bound.
   - **"May be explained by Y":** the X-without-Y contrast meets all of
     these:
     - at least 8 days on each side, within its informative blocks
     - a Sato variance above zero
     - a UB below 10 points
     
     That is positive evidence of no excess without Y, the same rule as "no
     pattern". The variance guard is the one step 8 uses. A contrast whose
     informative blocks hold no symptom days, or only symptom days, has
     variance 0, so its UB equals its RD. That can pass the bound on no
     information at all.
   - **"Often eaten with Y":** anything else. That covers:
     - too few days to separate the two
     - a zero-variance contrast
     - a contrast that settles nothing either way

     The note's wording ("can't yet tell which of the two goes with the
     symptom days") is true in all three cases.
   - **No note:** the X-without-Y contrast is itself significant
     (p ≤ 0.05).

   The product plan (5a) prefers multivariable adjustment. Contrasts are
   chosen instead for three reasons:
   - With about 250 days and near-collinear groups (wheat on 95% of days),
     a penalized regression's coefficients are unstable.
   - A regression would need numpy.
   - A contrast can be stated to the patient in counts.
8. **Same-day note,** for each flagged X at L ≥ 1. The step runs at lag 1
   and above; at lag 0 there is no earlier window, so it is skipped. The
   comparison is recomputed with the window moved back one day (days d−L to
   d−1), within the same blocks. The same-day note is added only when the
   shifted comparison meets all of these:
   - **Enough days:** at least 8 exposed and 8 unexposed days within its
     informative blocks. These are the minimums used for statuses (step 3)
     and for "explained by" (step 7).
   - **Some information:** a Sato variance above zero. A comparison with no
     symptom days, or only symptom days, in its informative blocks has a
     zero-width bound, which says nothing.
   - **A low bound:** its UB is below 10 points.

   Together these are positive evidence that nothing is seen without the
   same day's food, which is the pattern reverse causation leaves: soft
   foods chosen on bad days. Without the minimums, a single earlier-exposed
   day in one block gave a UB of 0.021 and fired the note on one day of
   "evidence". When any condition fails, there is no note and the flag
   stands as it is. Losing significance alone never triggers the note. It
   is not a separate hypothesis test and is outside the BH family.
9. **Ingredients and additive classes: counts only in v1.** For the 40 most
   frequently eaten ingredients (each on at least 8 analyzable days) and for
   every additive class present, the response carries the exposed and
   unexposed symptom-day counts at the same lag, with **no status and no
   test**.
   - **Why:** in round 2, ingredient-level flags were wrong about 86% of the
     time. Carriers such as bread for an egg trigger were flagged. "No
     pattern seen" also went to 6% of ingredients that contained a planted
     trigger.
   - **What would change it:** a status at ingredient level needs its own
     method, comparing each ingredient against days free of its own groups,
     and its own gates. That is future work.
   - **How the screen presents it:** the counts are labelled plainly as
     counts. A preservative the patient is curious about can still be looked
     at.

No p-values or ratios are shown. The response carries `q_value` and the risk
difference for the report and for review.

### What the analysis can and cannot do (measured)

Power study v3: 1,200 tuning patients, 1,153 planted triggers, the chosen
settings. The two precision rows come from different runs:
- **Uncredited precision** is from `power_study_v3.py`, which has no
  co-exposure step.
- **Strict precision** adds the step 7 rule from the co-exposure
  measurement (see the review log). It is counted as *How precision counts a
  flag* defines.

| Measure | Result |
|---|---|
| Median analyzable days | 258 |
| Planted triggers flagged (recall) | 203 of 1,153 (18%) |
| Precision, uncredited (flags that are true triggers) | 203 of 252 (81%) |
| Precision, strict (with co-exposure notes) | 197 of 252 (78%) |
| Flags given a co-exposure note | 38 of 252; 11 rescue a false flag, 17 name a non-trigger on a true flag |
| True triggers reported "no pattern seen" | 21 of 1,153 (2%) |
| Non-trigger groups flagged, among those assessed | 49 of 1,340 (3.7%) |
| Trigger-free patients with any flag, 18-month histories | 6 of 246 (2.4%) |
| Trigger-free patients with any flag, 12-month histories (≥ 30 analyzable days) | 12 of 246 (4.9%) |
| Trigger-free candidates with p < 0.05 | 3.0% |
| Correct flags given the same-day note | 0 of 203 |

"Assessed" means the group reached a flagged or "no pattern" status.

**Is the recall low because of the method or the data?** Mostly the data.
The generator's trigger adds one severity level with a cap. So a trigger is
invisible whenever the patient is already at the worst level, and that is
often the first months before treatment works. Patients also avoid their
triggers half the time, and milk is exposed on about 92% of days at lag 2.
Even the architect's oracle run, which had every day's true diet and a less
conservative test, found only 30%.

This matches the clinical reality the plan starts from: EoE reactions are
delayed and symptoms follow inflammation loosely. A day-level diary can
surface only strong, consistent patterns.

**What the feature does about it.** It is built to be right when it speaks,
not to find everything:
- **About 4 in 5 flags are right:** 81% are true triggers, and 78% under
  the strict count with co-exposure notes.
- **Every group's counts are visible**, as are the ingredient and additive
  counts, so the patient and their gastroenterologist can read the raw
  pattern themselves.
- **"No pattern seen" appears only when powered.**
- **The screen says all of this** in its "How this works" section.

A clinician-guided elimination and reintroduction, with biopsy (M2), stays
the way triggers are actually established. The screen points there.

Shipping at this recall is a product decision, and it is listed under *For
the user*.

**Is the generator's effect clinically plausible?** Partly.
- *Plausible:* treatment-dependent visibility, partial avoidance, and a lag
  of days.
- *Not modelled:* reactions that build over weeks, dose effects, and
  reverse causation.

These omissions make the synthetic check optimistic about lag and silent on
reverse causation, which is why step 8 exists. Changing the generator to
make the method look better would be tuning, and is not done.

### Validation (pre-registered)

`tests/insights/test_validation.py` runs the production analysis on three
cohorts:

- **Held-out:** seeds **5000–6199** (1,200 patients), today pinned to
  2026-09-01, 18 months each, lag 2.
- **Trigger-free, 18 months:** the first **1,000** trigger-free patients
  found by scanning seeds upward from 20000.
- **Trigger-free, 12 months:** the first **1,000** trigger-free patients
  scanning upward from 40000, restricted to those with at least 30
  analyzable days.

The adapter from `HistoryPlan` to `AnalysisDay` lives in the test module.
Nothing outside `synthetic` may import the generator. The thresholds are
module constants, set from power study v3 with margin, and are never lowered
to pass.

| Metric | Cohort | Tuning value | Must be |
|---|---|---|---|
| Recall | held-out | 18% | ≥ 13% |
| Precision, strict (see below) | held-out | 78% | ≥ 72% |
| True triggers reported "no pattern seen" | held-out | 2% | ≤ 5% |
| Non-trigger groups flagged, among those assessed | held-out | 3.7% | ≤ 6% |
| Correct flags given the same-day note | held-out | 0% | ≤ 10% |
| Patients with any flag | trigger-free 18 months | 2.4% | ≤ 6% |
| Patients with any flag | trigger-free 12 months | 4.9% | ≤ 8% |
| Candidates with p < 0.05 | trigger-free 18 months | 3.0% | ≤ 5% |

**How precision counts a flag:**
- **Correct:** the flagged group is a true trigger and carries no note, or
  its note names a true trigger. A non-trigger flag whose note names a true
  trigger is also correct: the patient is pointed at the right food.
- **Incorrect:** everything else, including a true trigger whose note
  names a non-trigger. That note points the patient at the wrong food.

The precision gate keeps its round-3 threshold of 72%. Against the strict
tuning value of 78%, the margin is about 2.3 standard errors at roughly 250
flags. Ingredients and additives carry no statuses, so they have no gates.
Their counts are covered by unit tests.

The run takes about 20 ms per patient (about 3,200 patients, roughly a
minute). Its measured values are printed and copied into this plan's review
log.

## Scope

**In scope**
- `GET /api/v1/me/insights/food-patterns` and the pure analysis behind it.
- The Insights screen: the trend line and the food patterns, with the method
  and its limits explained on the page.
- A fourth navigation item, **Insights**.

**Out of scope, planned later**
- The rest of the progress dashboard (see "Progress dashboards" in the
  product plan): symptom calendar heatmap, adherence over time, before-and-after
  treatment comparison, and date-range presets.
- Food challenges and biopsy-confirmed outcomes (M2), and the doctor-report
  section (M3). The response shape is built so the report can reuse it.
- "May contain" as a weaker exposure. v1 counts only declared and
  ingredient-level exposure, and states that on the screen.
- Weighting label ingredients above the patient's own account (product
  plan item 5). Both count equally in v1.
- Storing results. They are computed on request (see *Performance*).

## Design

### Package and dependency rules (ADR 0010)

A new **`insights`** package combines the symptom and food domains. It sits
above them, the place ADR 0010 reserves for views that combine domains.
`tests/test_architecture.py` gains one rule: `insights` may import the
foundation, `audit`, `identity`, `symptoms`, `food`, and `deps` (its router
only). "No clinical domain imports insights" is already enforced by
`test_clinical_domains_do_not_import_each_other`.

```
insights/
  __init__.py
  food_patterns.py   # pure: days in, statuses out; no database, no clock
  statistics.py      # pure: shift test, Mantel-Haenszel RD + Sato variance, BH
  service.py         # windows, lag validation, assembly, audit (uses domain repositories)
  schemas.py         # response models
  router.py          # GET /me/insights/food-patterns
```

`food_patterns.py` takes plain dataclasses (`AnalysisDay`: date, symptom day
or not, and the sets of groups, ingredient keys, and additive classes
exposed), so the synthetic plans and the database feed it the same way.

### Data

No schema changes and no migration. The service reads through the existing
patient-scoped repositories. There is no new cross-domain repository:

- `SymptomEntryRepository.list_between`: the daily DSQ outcome via
  `symptoms.scoring`, reused rather than reimplemented.
- `FoodRepository.list_items_between`: items with their ingredient rows and
  their `product`, whose declared allergens count as exposure.

The derivation of an item's exposures moves to one new function,
`food/exposure.py: exposures(item) -> ItemExposure`, which returns groups,
canonical keys, and additive classes. `food/presenters.py` is refactored to
use it for per-row groups. That keeps the catalog, custom, and label rules
(including classification at read time) in one place.

### Candidates

- **Allergen groups:** all 9, and the only ones tested.
- **Ingredients:** canonical keys eaten on at least 8 analyzable days,
  capped at the 40 most frequent, as counts only.
- **Additive classes:** every class present, as counts only.

Composite catalog dishes ("mayonnaise") contribute their usual groups, like
the food log's "usually" chips. The screen notes that dishes vary by recipe.

### API

`GET /api/v1/me/insights/food-patterns?lag_days=2`

- `lag_days` is an integer from 0 to 3, default 2. Anything else returns 422.
- The window is the 540 days ending on the patient's today, in their
  timezone (`entry_dates.patient_today`).
- Rate-limited at 30 per minute, because the analysis costs more than a list
  read.

Response `FoodPatternReport`:
```
method_version: "fp-1"                  # bumps when the method changes
window_start, window_end: date
lag_days: int
analyzable_days: int                    # days that met the logging rule
complete_window_share: float            # share of analyzable days with every window day logged
logging_gap: float | null               # within-block MH RD, full vs partial windows (diagnostic)
symptom_days: int
logged_days: int                        # symptom entries in the window, for context
groups | ingredients | additives: list[FoodPattern]

FoodPattern:
  key: str                              # "milk", "en:e385", "preservative"
  label: str                            # display name
  status: "flagged" | "no_pattern" | "cant_tell" | "not_enough_data" | "no_baseline"
          | "counts_only"               # ingredients and additives in v1
  exposed_days, exposed_symptom_days: int
  unexposed_days, unexposed_symptom_days: int
  explained_by: str | null              # co-exposure: the group that may explain it
  often_with: str | null                # co-exposure too thin to tell
  same_day_only: bool                   # flagged only when same-day food counts
  risk_difference: float | null         # Mantel-Haenszel, informative blocks
  q_value: float | null                 # for review and the report; the screen never shows it
```
Statuses are sorted flagged first, then no pattern, can't tell, not
enough data, and no baseline, then by exposed days.

After the API changes, `make openapi` and `make api-types` regenerate the
contract and the web types.

**Audit:** one `insights.food_patterns.read` row per request. Its metadata is
the lag and the counts of flagged and assessable candidates, never which
foods.

### Performance

18 months of logging is at most about 540 symptom entries and a few
thousand ingredient rows. The prototype ran at about 15 ms per patient for
the whole analysis. The test suite
asserts a 200 ms budget on an 18-month synthetic patient. If real use proves
otherwise, results can be cached per patient keyed on the latest `updated_at`.
That is not built now.

### Frontend

- **Route and navigation:** `/insights`, a new
  `features/insights/insights.ts` with its template. The bottom navigation
  gains a fourth item, **Insights** (icon `insights`). An `InsightsService`
  wraps the endpoint.
- **Hero band:** "Insights", then the 90-day DSQ trend drawn as an inline SVG
  line. It reuses the existing `GET /me/symptoms/burden/trend?points=90`
  (`scoring.score_trend`, and `SymptomService.burdenTrend()` on the web). The
  line has: a 2px stroke, the current value labelled at the end, a hairline
  baseline, and a hover tooltip per point. Unscorable windows show as gaps,
  never as zero. A "Show as table" toggle lists dates and scores. There is no
  chart library: one line does not justify a dependency. *Deliberate
  deviation:* the product plan named ECharts for charts. That decision moves
  to the progress dashboard, where the charts are richer.
- **Food patterns card:**
  - A segmented control: Allergen groups | Ingredients | Additives. The
    Ingredients and Additives tabs open with one line: "Counts only. There
    are too many ingredients to test reliably from a diary, so these show
    what happened without a verdict." Those tabs differ from the groups tab
    in four ways:
    - rows are sorted by how often the item was eaten, never by the gap
      between rates
    - there is no status icon or statement
    - the "compared within each 4-week stretch" line is left off, because
      it is not true there
    - the meters are neutral grey, not the tested groups' colours
  - A lag selector: "Count foods from: the same day | up to 1 day before |
    up to 2 days before (default) | up to 3 days before".
  - One row per candidate: the statement (exact wording below), the two rates
    as paired horizontal meters labelled "After eating it" and "Other days"
    with their counts ("9 of 14 days"), and the co-exposure note. Colour is
    never the only signal: every status has an icon and its text.
  - Under the counts, one line: "Totals over the last 18 months, or your
    whole log if it is shorter. The comparison is
    made within each 4-week stretch, so a treatment change doesn't distort
    it." The line explains why the status can differ from what the raw
    totals suggest.
  - An expandable **"How this works, and its limits"** section:
    - lag, and the logging rule
    - 4-week comparison, in plain words
    - that many foods are checked at once
    - that most foods will read "can't tell yet"
    - that a diary finds only strong, consistent patterns
    - that symptoms don't always follow inflammation
    - that supervised elimination and reintroduction is how triggers are
      confirmed
- **States:**
  - Loading.
  - An error.
  - Too little data overall: fewer than 30 analyzable days shows "Log food
    and symptoms for a few more weeks", with the current counts.
  - Nothing flagged: "No food stands out in your log so far", followed by
    the list.

**The complete set of statements** (pending sign-off):
- flagged: "Symptom days were more common after {X}: {a} of {n₁} days,
  compared with {c} of {n₀} other days."
- flagged, explained by: the flagged sentence, plus "{X} was usually eaten
  with {Y}, which may account for this."
- flagged, often with: the flagged sentence, plus "{X} was often eaten with
  {Y}, so this log can't yet tell which of the two goes with the symptom
  days." The wording covers both too few days and an unsettled contrast.
- flagged, same day only: the flagged sentence, plus "This only shows up
  when counting food from the same day, which can happen when softer foods
  are chosen on bad days."
- no pattern: "No pattern seen across {n₁} days you ate {X}." (shown only
  when powered; see Method, step 6)
- can't tell: "Can't tell yet. Symptom days after {X}: {a} of {n₁}. Other
  days: {c} of {n₀}. More days are needed to see a pattern either way."
- not enough data: "Not enough data yet: {X} was eaten on {n₁} logged
  days."
- counts only (ingredients, additives): "Symptom days after {X}: {a} of
  {n₁}. Other days: {c} of {n₀}." No verdict is attached.
- no baseline: "{X} was in almost every day's food, so there are no days
  without it to compare."
- Always shown: "These are patterns in your own log, not a diagnosis.
  Symptoms don't always follow inflammation, so a food with no pattern here
  can still matter. Talk to your gastroenterologist before changing what
  you eat."

## Security and privacy

- Patient-scoped repository, a `/me` route, and RLS on the tables read. The
  isolation test suite gains a case: patient B's request never counts
  patient A's entries or foods.
- The audit trail and logs hold counts only. Which food was flagged is PHI
  and never leaves the response.
- There is no new third party, and the computation runs in-process.

## Testing

- **`tests/insights/test_statistics.py`:**
  - the shift test's exact distribution against brute-force enumeration of
    every shift combination, on small blocks
  - the Mantel–Haenszel risk difference and Sato variance against a
    hand-computed stratified example
  - Benjamini–Hochberg against a published worked example
  - edge cases: a single block, a block with no exposed days, constant
    outcomes, and all-zero rows
- **`tests/insights/test_food_patterns.py`** (pure):
  - the lag window
  - the logging rule: an analyzable day needs the day itself logged and L
    of its L + 1 window days logged
  - the status order: no baseline before the minimums, and the minimums
    counted within informative blocks only
  - the oldest short block merging into the next
  - the size floor on the Mantel–Haenszel risk difference
  - "no pattern" only when powered, otherwise "can't tell"
  - the same-day note:
    - it needs positive evidence, never lost significance alone, and is
      skipped at lag 0
    - a fixture whose excess sits entirely on same-day exposure must fire
      the note, with at least 8 exposed and 8 unexposed days in the shifted
      window's informative blocks
    - the reviewer's case must not fire the note: one informative block
      holding a single earlier-exposed day (UB 0.021)
    - 7 exposed or 7 unexposed days in the shifted window must not fire it;
      8 and 8 may
    - a shifted window with zero Sato variance (no symptom days, or only
      symptom days, in its informative blocks) must not fire it
  - ingredients and additives come back as counts only, with no status
  - co-exposure:
    - enrichment P(Y | X) − P(Y | not X) ≥ 0.25 qualifies Y, and the
      boundary is tested at 0.24 and 0.25
    - a near-daily Y (about 92% of days) that is only slightly more common
      on X's days does not qualify, even when X is flagged and Y is
      never eaten on X-free days. That is the case the rejected reverse
      conditioning would have let through.
    - a Y without a baseline qualifies when it meets the enrichment rule
    - the qualifying Y with the largest enrichment is the one named
    - "explained" requires at least 8 and 8 days, a Sato variance above
      zero, and the powered bound
    - a restricted set with 8 or more days on each side but no symptom days
      on either side gives variance 0 and UB 0. It must come back "often
      with", not "explained". So must one where every day is a symptom day.
    - "often with" covers too few days, a zero-variance contrast, and an
      unsettled contrast
    - no note when the X-without-Y contrast is significant
  - stratification: a time-confounded fixture, where the food changes
    alongside treatment, is not flagged
  - ingredient and additive levels built from label rows
- **`tests/insights/test_validation.py`:** the pre-registered held-out and
  trigger-free runs (see *Validation*), and the performance budget.
- **An end-to-end check:** one synthetic patient written through
  `synthetic.writer`, then analysed through the API, must match the pure
  analysis of the same plan.
- **`tests/insights/test_api.py`:**
  - the endpoint shape
  - `lag_days` validation (422)
  - an audit row holding counts only
  - the rate limit
  - the timezone window
  - composite dishes counted as "usually" exposures
- **`tests/food/`:** `exposures()` for catalog, custom, and label rows, with
  the presenter's output unchanged by the refactor.
- **`tests/db/test_patient_isolation.py`:** the new cross-patient case.
- **`tests/test_architecture.py`:** the `insights` rules.
- **Web specs:**
  - the SVG trend puts gaps for unscorable windows and never draws them at
    zero
  - each status renders its statement verbatim
  - no status icon or verdict renders on a counts-only row, and those rows
    sort by exposed days
  - the lag selector refetches
  - the empty and too-little-data states
- **Screenshots** at phone width, light and dark, as the workflow requires.

## Open questions and release gates

**Clinical sign-off required before this reaches a real patient.** These are
release gates, recorded where the code already demands them:
1. **The allergen-group mapping of the ingredient catalog.** The
   `AllergenGroup` docstring in `food/enums.py` requires clinical review
   "before it drives any patient-facing insight". This feature is that
   insight.
2. **The classifier's allergen rules and the additive classes** in
   `food/products/vocabulary.py`. The same requirement applies.
3. **The DSQ items from ADR 0009:** the licence, the minimum number of
   valid days, and the question wording. The response is built to feed the
   doctor report.
4. **The method's clinical parameters:** the default lag (2 days) and the
   range (0–3), the minimum of 8 exposed and 8 unexposed days, and the
   10-point size floor.
5. **The statement wording**, signed off by clinical and legal review.
6. **A logging-gap review:** the first review of real usage checks
   `logging_gap` before the feature leaves beta. See *How missing food logs
   are handled*.

Until these are signed off, the feature ships to development and staging
with synthetic data only. That is the state of the whole product today.

7a. **Wording sign-off: "not enough data" when the short side is the days
    without the food.** A group eaten on about 85% of days can be "not
    enough data" because of too few days *without* it. It then reads "Not
    enough data yet: milk was eaten on 200 logged days", which is confusing.
    The architect's suggested variant, choosing by which side is short:
    "Not enough data yet: {X} was eaten on {n₁} logged days, and there were
    only {n₀} days without it to compare." Held for the clinical and legal
    wording review (gate 5) rather than changed now.

**For the user (the defaults below apply unless you decide otherwise):**

7. **Recall.** The screen flags about 1 in 5 planted triggers, and about
   4 in 5 of its flags are right. Milk and wheat will often read "eaten
   almost every day". Is a conservative screen, one that is rarely wrong but
   often says "can't tell yet", what you want? *Default: yes.*
8. **Ingredients and additives as counts only in v1.** Preservatives and
   other additives show what happened on the days they were eaten, without a
   verdict. *Default: yes, until an ingredient-level method passes its own
   gates.*
9. **Navigation.** Should Insights appear before a patient has 30 analyzable
   days, or only after? *Default: always shown, with the "log a few more
   weeks" state.*

## Review log

| Round | Reviewer | Verdict | What changed |
|---|---|---|---|
| 1 | architect | CHANGES REQUESTED | Six blocking findings: validation impossible (no patient reached 120 days; recall 8.5%), CMH anti-conservative (8.7% nulls under p < .05), "no pattern" on most true triggers, co-exposure keyed on prevalence, no cross-level false-alarm control, missing clinical gates. Revised: power study on tuning seeds; relaxed logging rule; 540-day window; exact within-block circular-shift test; BH across all levels; powered "no pattern" plus "can't tell"; enrichment-based co-exposure with restricted contrasts; floor on the MH risk difference; same-day sensitivity; held-out and trigger-free pre-registration; clinical release gates. Reused domain repositories and a shared `food/exposure.py`; named the trend source; recorded the inline-SVG deviation. |
| 2 | architect | CHANGES REQUESTED | Round-1 findings all resolved. New blocking findings: ingredient flags about 14% precise, with "no pattern" on 6% of trigger-containing ingredients, and precision not gated; the same-day note fired on 82% of true flags. Revised after power study v3: statuses and tests for the nine groups only; ingredients and additives as counts only; BH at q = 0.05 over the groups; a precision gate; the same-day note only on positive evidence (the UB of the shifted window below the floor), skipped at lag 0, with a gate; co-exposure Y needs no baseline and "explained" uses the powered bound; a 12-month trigger-free cohort; corrected logging-rule text; shift mechanics specified; recall and counts-only listed as user decisions. |
| 3 | architect | APPROVED | A and B resolved; the architect reproduced the tuning table exactly and measured the completeness-stratified variant (worse, so not adopted). Advisory items taken before implementation: enrichment measured on either side, so a near-daily trigger can be named; a `logging_gap` diagnostic and a real-data review gate; counts-only rows sorted by frequency with no status or stratification claim; a fixture proving the same-day note fires; the precision counting rule made explicit. |
| 3a | architect, as designer | Design fix during implementation | The round-3 "absence side" was algebraically the presence side, and its aim (naming a near-daily Y) was wrong. By the omitted-variable bias of a risk difference, Y accounts for X's excess only through P(Y \| X) − P(Y \| not X). Step 7 is back to that rule alone, and the claim is withdrawn. The proposed max(P(Y\|X) − P(Y\|¬X), P(X\|Y) − P(X\|¬Y)) rule was measured on tuning seeds 1000–2199 against the presence rule (252 flags, strict credit): it named milk or wheat 142 times (18 true), misattributed 120 true flags, and gave strict precision 38%. The presence rule gave 78% strict and 85% lenient, with 38 notes, 11 false flags rescued, and 17 true flags misattributed. It is kept. The "often with" wording now covers both of its cases. The precision gate's tuning value is restated as 78% strict, with the 72% threshold unchanged. Co-exposure tests are updated. |
| 4 | implementer | Implemented | Pre-registered gates run on the held-out cohorts with the production code: recall 17.7% (≥ 13%), strict precision 78.2% (≥ 72%), true triggers "no pattern" 1.7% (≤ 5%), non-trigger groups flagged 3.6% (≤ 6%), same-day note on true flags 0.0% (≤ 10%), any flag among trigger-free patients 3.4% at 18 months (≤ 6%) and 2.9% at 12 months (≤ 8%), trigger-free p < 0.05 3.5% (≤ 5%). All pass. Small deviations: the cross-patient check lives in `tests/insights/test_api.py`, because `tests/db/test_patient_isolation.py` tests row-level security at the table level and this feature adds no table; the groups tab is labelled "Allergens", because "Allergen groups" was clipped at phone width; the generator adapter lives in `tests/helpers.py` so the validation and end-to-end tests share it; `FoodPattern` carries an internal `p_value` for the calibration gate, which never reaches the API. |
| 4a | architect, as designer | Design fix from code review | Step 8, the same-day note, had no minimum, so one informative block holding a single earlier-exposed day gave UB 0.021 and fired the note on one day of "evidence". The note now also needs at least 8 exposed and 8 unexposed days within the shifted window's informative blocks, the minimums of step 3 and step 7. It also needs a non-zero Sato variance, because a shifted window with no symptom days, or only symptom days, gives a zero-width bound that says nothing. When a condition fails, there is no note and the flag stands. Both conditions can only make the note fire less often. The note affects no status, flag, or precision count, so the held-out results in row 4 stand: the same-day gate measured 0.0% against ≤ 10%. No rerun was needed. The tests are extended for the reviewer's case, the 7/8 boundary, and zero variance. |
| 4b | architect, as designer | Design fix from code review | Step 7's "explained by Y" had the same gap as step 8. A restricted X-without-Y set with 8 or more days on each side but no symptom days gives Sato variance 0 and UB 0, so it read "explained" on no information. The implementation (`_co_exposure`) did not guard it. "Explained" now also needs a Sato variance above zero, the guard step 8 uses. A zero-variance contrast becomes "often eaten with Y", whose wording ("can't yet tell which of the two goes with the symptom days") is true there. Co-exposure tests are extended for the no-symptom and all-symptom cases. Expected effect: none on the precision gate. Strict precision credits a note that names a true trigger whether it is "explained" or "often with", and this change only moves notes between the two. Recall, statuses, and the other gates do not depend on the note type. The implementer reruns the held-out validation to confirm and records the results in the next row. |
| 5 | code-reviewer | FIX REQUIRED → fixed | Blocking findings fixed. The two missing disclosures ("may contain" is not counted; dish recipes vary) were added to "How this works". Two over-reassuring sentences were softened ("less likely", with the limit stated). A lag-change race was fixed with a generation counter, and a spec now resolves two changes out of order. Enrichment is now compared exactly with `Fraction`: 7/20 − 2/20 was 0.2499… in floats, and a boundary test covers it. The missing tests were added: the size floor (test pinned significant, 5 points not flagged, 20 points flagged) and "often with" on an unsettled contrast. Advisory items taken: `window_start` always means the 540-day window's start (documented in `schemas.py`); the trend summary says "latest" and gives its date, and the axis labels moved left so they cannot collide with the end label; the redundant `aria-label` on rows was removed, and a polite live region announces reloads; an empty-tab spec; the rate-limit docstring and the schema comments were corrected; BH wording clarified to "the groups that reach testing". Rows 4a and 4b (architect) added the minimum-days and variance guards to the same-day note and to "explained by", both now implemented and tested. Held-out rerun after all changes: identical to row 4 on every gate. Not taken: keying authenticated rate limits on the principal instead of the address. The module docstring already warns about proxy configuration, and it is a cross-cutting change for its own review. |
| 6 | code-reviewer | PASS | All round-1 blocking findings confirmed fixed, and the architect's guards verified. Advisory items taken after the pass: no stale reload announcement, and no stale counts after a failed reload (the old report is cleared); the rate-limit docstring now says "one client"; a shared `_enough_days` helper; a test pins `window_start` to the full 540-day window. |
