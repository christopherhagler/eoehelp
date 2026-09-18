"""Symptom burden scoring.

In Python rather than a database trigger, and pure rather than session-bound, so
it can be unit-tested against hand-computed fixtures. The algorithm will be
revised under clinical review, and a revision must be a code change with tests
attached, not an invisible change in query behaviour.

Two properties matter more than the arithmetic:

1. **Every score carries its components.** A single number a patient cannot
   interrogate is not trustworthy, and a clinician asked to act on it will want
   to know what produced it. `SymptomBurden.components` is surfaced through the
   API and printed on the report.

2. **Insufficient data returns no score, never a low one.** Three answered days
   out of fourteen looks like remission if you divide by fourteen. Refusing to
   score is the honest output, and it is also what keeps the product descriptive
   rather than suggestive.

**The DSQ formula**, as published (Dellon ES et al., "Development and field
testing of a novel patient-reported outcome measure of dysphagia in patients
with eosinophilic esophagitis", Aliment Pharmacol Ther 2013):

- Question 2 (did food go down slowly or get stuck): yes = 2 points.
- Question 3 (what it took to get relief at the worst episode): 0 cleared on
  its own, 1 drank liquid, 2 coughed or gagged, 3 vomited, 4 sought medical
  attention.
- Daily maximum 6. The score is the sum of daily points times 14, divided by
  the number of valid diary days: 0-84.
- Pain on swallowing is not part of this total. It is reported alongside it.

PENDING CONFIRMATION, kept here because this is where a wrong answer does
damage: the minimum number of valid days for a window to be scored (7 below;
some trials have required more), the exact question wording against the v4.0
instrument, and the licence, which must be confirmed in writing before any score
is shown to a clinician.
"""

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from eoehelp_api.models.clinical import SymptomEntry
from eoehelp_api.models.enums import DysphagiaRelief, EntryMethod

DSQ_CODE = "DSQ"
DSQ_VERSION = "v4.0"

# 14 days is the DSQ's own scoring window, and it is also roughly the shortest
# span over which an EoE treatment change shows up.
DSQ_WINDOW_DAYS = 14

# Below this, the window is reported as unscorable (see the note above).
DSQ_MIN_ANSWERED_DAYS = 7

DSQ_MAX_SCORE = 84
DSQ_MAX_DAILY_SCORE = 6

# Question 2: food went down slowly or got stuck.
DYSPHAGIA_POINTS = 2

# Question 3: what it took to get relief, in the instrument's own order.
RELIEF_POINTS: dict[DysphagiaRelief, int] = {
    DysphagiaRelief.CLEARED_ON_ITS_OWN: 0,
    DysphagiaRelief.DRANK_LIQUID: 1,
    DysphagiaRelief.COUGHED_OR_GAGGED: 2,
    DysphagiaRelief.VOMITED: 3,
    DysphagiaRelief.SOUGHT_MEDICAL_ATTENTION: 4,
}


@dataclass(frozen=True)
class SymptomBurden:
    """A scored window, or an explicit refusal to score one."""

    period_start: date
    period_end: date
    instrument_code: str
    instrument_version: str
    days_in_window: int
    days_logged: int
    days_scorable: int
    score: float | None
    components: dict[str, Any]

    @property
    def is_scorable(self) -> bool:
        return self.score is not None


def daily_score(entry: SymptomEntry) -> int | None:
    """DSQ points for one day, 0-6, or None when the day cannot be scored.

    A day without solid food is not a symptom-free day — it is a day the
    instrument cannot ask its question about. Counting it as zero would flatter
    the score of someone living on shakes, which is precisely the patient doing
    worst. A solid-food day with question 2 unanswered is not valid either.
    """
    if not entry.ate_solid_food or entry.dysphagia_occurred is None:
        return None
    if not entry.dysphagia_occurred:
        return 0
    relief = RELIEF_POINTS[entry.dysphagia_relief] if entry.dysphagia_relief else 0
    return DYSPHAGIA_POINTS + relief


def score_window(
    entries: Iterable[SymptomEntry],
    *,
    period_end: date,
    window_days: int = DSQ_WINDOW_DAYS,
    min_answered_days: int = DSQ_MIN_ANSWERED_DAYS,
) -> SymptomBurden:
    """Score the `window_days` ending on `period_end` inclusive.

    Entries outside the window are ignored rather than rejected, so a caller can
    pass a wider fetch without pre-filtering.

    Normalised by scorable days and scaled back to the full window, which is what
    keeps a patient who logged 10 days comparable to one who logged 14 instead of
    appearing to have two-thirds the symptoms.
    """
    period_start = period_end - timedelta(days=window_days - 1)
    in_window = [e for e in entries if period_start <= e.entry_date <= period_end]

    scores = [s for s in (daily_score(e) for e in in_window) if s is not None]

    components: dict[str, Any] = {
        "dysphagia_days": sum(1 for e in in_window if e.dysphagia_occurred),
        "no_solid_food_days": sum(1 for e in in_window if not e.ate_solid_food),
        "odynophagia_days": sum(1 for e in in_window if e.odynophagia),
        # Question 3 answers, so a clinician can see what drives the number: ten
        # days of drinking water through it is not one emergency visit.
        "relief": {
            relief.value: sum(1 for e in in_window if e.dysphagia_relief is relief)
            for relief in DysphagiaRelief
        },
        "er_visit_days": sum(1 for e in in_window if e.food_impaction_er_visit),
        "avoidance_days": sum(1 for e in in_window if e.avoided_foods_today),
        "modification_days": sum(1 for e in in_window if e.modified_foods_today),
        "slow_eating_days": sum(1 for e in in_window if e.ate_unusually_slowly),
        "backfilled_days": sum(1 for e in in_window if e.entry_method is EntryMethod.BACKFILL),
        "worst_daily_score": max(scores) if scores else None,
    }

    if len(scores) < min_answered_days:
        components["unscorable_reason"] = "fewer_than_minimum_scorable_days"
        components["minimum_scorable_days"] = min_answered_days
        score = None
    else:
        score = round(min(statistics.fmean(scores) * window_days, DSQ_MAX_SCORE), 1)

    return SymptomBurden(
        period_start=period_start,
        period_end=period_end,
        instrument_code=DSQ_CODE,
        instrument_version=DSQ_VERSION,
        days_in_window=window_days,
        days_logged=len(in_window),
        days_scorable=len(scores),
        score=score,
        components=components,
    )


def score_trend(
    entries: Sequence[SymptomEntry],
    *,
    period_end: date,
    points: int,
    window_days: int = DSQ_WINDOW_DAYS,
) -> list[SymptomBurden]:
    """Rolling windows ending on each of the last `points` days, oldest first.

    The chart the report leads with. Computed here rather than in the client so
    the PDF and the screen cannot disagree about the same patient's trend.
    """
    return [
        score_window(
            entries,
            period_end=period_end - timedelta(days=offset),
            window_days=window_days,
        )
        for offset in reversed(range(points))
    ]
