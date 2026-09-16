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

PENDING CLINICAL CONFIRMATION — recorded here rather than in a tracker because
this is where it would do damage. The DSQ's published 0-84 range implies six
points per day over fourteen days, and the mapping below (0-3 for dysphagia by
what the patient had to do, 0-3 for pain) reproduces that range. The exact item
weights and the minimum-days rule must be confirmed against the DSQ v4.0
scoring manual, and the licence confirmed in writing, before any score is shown
to a clinician. Until then this is a defensible reading, not an authoritative
implementation.
"""

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from eoehelp_api.models.clinical import SymptomEntry
from eoehelp_api.models.enums import DysphagiaSeverity, EntryMethod

DSQ_CODE = "DSQ"
DSQ_VERSION = "v4.0"

# 14 days is the DSQ's own scoring window, and it is also roughly the shortest
# span over which an EoE treatment change shows up.
DSQ_WINDOW_DAYS = 14

# Below this, the window is reported as unscorable. Half the window is the
# conventional floor for a diary instrument.
DSQ_MIN_ANSWERED_DAYS = 7

DSQ_MAX_SCORE = 84
DSQ_MAX_DAILY_SCORE = 6

# Graded by what the patient had to do about it. Observable, and comparable
# between patients in a way a 1-10 feeling is not.
DYSPHAGIA_POINTS: dict[DysphagiaSeverity, int] = {
    DysphagiaSeverity.NONE: 0,
    DysphagiaSeverity.MILD_SLOW: 1,
    DysphagiaSeverity.STUCK_SELF_RESOLVED: 2,
    DysphagiaSeverity.STUCK_INTERVENTION: 3,
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
    """Score one day 0-6, or None when the day cannot be scored.

    A day without solid food is not a symptom-free day — it is a day the
    instrument cannot ask its question about. Counting it as zero would flatter
    the score of someone living on shakes, which is precisely the patient doing
    worst.
    """
    if not entry.ate_solid_food:
        return None

    severity = entry.dysphagia_severity
    dysphagia = DYSPHAGIA_POINTS[severity] if severity is not None else 0
    pain = entry.odynophagia_severity or 0
    return min(dysphagia + pain, DSQ_MAX_DAILY_SCORE)


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
