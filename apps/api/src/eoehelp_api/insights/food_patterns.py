"""Which allergen groups a patient's log links to symptom days, and which it does not.

Pure: days in, statuses out; no database and no clock, so the synthetic
generator's plans and the database feed it the same way, and the validation
tests run the code that ships. The method, and the evidence for each setting,
is in docs/plans/2026-09-19-insights-food-patterns.md. Every constant below
was fixed by a power study before validation and is gated on held-out data;
changing one needs a new design review.

What it never does: call a food safe, recommend eating or avoiding anything,
or test an ingredient or additive (those are counts only in v1).
"""

import enum
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from fractions import Fraction

from eoehelp_api.food.enums import AllergenGroup
from eoehelp_api.insights import statistics
from eoehelp_api.insights.statistics import Block

METHOD_VERSION = "fp-1"

HORIZON_DAYS = 540
BLOCK_DAYS = 28
# An oldest block covering less than this merges into the next one.
MIN_BLOCK_COVERAGE_DAYS = 14
DEFAULT_LAG_DAYS = 2
MAX_LAG_DAYS = 3

NO_BASELINE_SHARE = 0.9
MIN_INFORMATIVE_DAYS = 8
Q_LEVEL = 0.05
FLOOR = 0.10
# Serial dependence: one meal feeds a window of lag + 1 days; √3 at lag 2.
SE_INFLATION = 1.7
CO_EXPOSURE_ENRICHMENT = Fraction(1, 4)
MAX_INGREDIENTS = 40


class PatternStatus(enum.StrEnum):
    FLAGGED = "flagged"
    NO_PATTERN = "no_pattern"
    CANT_TELL = "cant_tell"
    NOT_ENOUGH_DATA = "not_enough_data"
    NO_BASELINE = "no_baseline"
    COUNTS_ONLY = "counts_only"


STATUS_ORDER = list(PatternStatus)


@dataclass(frozen=True)
class DayFood:
    """What the patient's logged food on one day exposed them to."""

    groups: frozenset[AllergenGroup] = frozenset()
    ingredients: frozenset[str] = frozenset()
    additives: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PatternInput:
    window_end: date
    # Scorable DSQ days only: True for a symptom day, False for a clear one.
    outcomes: Mapping[date, bool]
    # Only days with food logged appear here.
    foods: Mapping[date, DayFood]
    # Symptom entries in the window, scorable or not, for context.
    logged_days: int = 0


@dataclass(frozen=True)
class FoodPattern:
    key: str
    status: PatternStatus
    exposed_days: int
    exposed_symptom_days: int
    unexposed_days: int
    unexposed_symptom_days: int
    explained_by: AllergenGroup | None = None
    often_with: AllergenGroup | None = None
    same_day_only: bool = False
    risk_difference: float | None = None
    q_value: float | None = None
    # Kept for validation of the method's calibration; never leaves the service.
    p_value: float | None = None


@dataclass(frozen=True)
class PatternReport:
    # Always the 540-day window's first day, whether or not the log reaches back
    # that far; analyzable_days says how much of it had data.
    window_start: date
    window_end: date
    lag_days: int
    analyzable_days: int
    symptom_days: int
    logged_days: int
    complete_window_share: float | None
    logging_gap: float | None
    groups: list[FoodPattern] = field(default_factory=list)
    ingredients: list[FoodPattern] = field(default_factory=list)
    additives: list[FoodPattern] = field(default_factory=list)


@dataclass(frozen=True)
class _Day:
    day: date
    symptom: bool
    block: int
    complete: bool
    # Exposure across the whole lag window, and across it without the day itself.
    exposure: DayFood
    earlier: DayFood


def _union(foods: list[DayFood]) -> DayFood:
    return DayFood(
        groups=frozenset().union(*(f.groups for f in foods)),
        ingredients=frozenset().union(*(f.ingredients for f in foods)),
        additives=frozenset().union(*(f.additives for f in foods)),
    )


def _analyzable_days(data: PatternInput, lag: int) -> tuple[date, list[_Day]]:
    start = data.window_end - timedelta(days=HORIZON_DAYS - 1)
    candidates = sorted(d for d in data.outcomes if start <= d <= data.window_end)
    days: list[tuple[date, bool, bool, DayFood, DayFood]] = []
    for day in candidates:
        window = [day - timedelta(days=k) for k in range(lag + 1)]
        logged = [data.foods[w] for w in window if w in data.foods]
        # The day itself logged, and L of its L + 1 window days: an unlogged day
        # inside the window counts as not eaten (see the plan, "How missing food
        # logs are handled").
        if day not in data.foods or len(logged) < lag:
            continue
        earlier = [data.foods[w] for w in window[1:] if w in data.foods]
        days.append(
            (day, data.outcomes[day], len(logged) == lag + 1, _union(logged), _union(earlier))
        )
    if not days:
        return start, []

    # Blocks run back only as far as the log does, so a short history's oldest
    # block is measured from its first analyzable day.
    effective_start = max(start, days[0][0])
    oldest = (data.window_end - effective_start).days // BLOCK_DAYS
    coverage = (data.window_end - effective_start).days % BLOCK_DAYS + 1
    merge_oldest = oldest > 0 and coverage < MIN_BLOCK_COVERAGE_DAYS

    def block_of(day: date) -> int:
        block = (data.window_end - day).days // BLOCK_DAYS
        return oldest - 1 if merge_oldest and block == oldest else block

    return start, [
        _Day(day, symptom, block_of(day), complete, exposure, earlier)
        for day, symptom, complete, exposure, earlier in days
    ]


def _blocks(days: list[_Day], exposed: list[bool]) -> list[Block]:
    by_block: dict[int, tuple[list[int], list[int]]] = defaultdict(lambda: ([], []))
    for day, is_exposed in zip(days, exposed, strict=True):
        exposure, outcome = by_block[day.block]
        exposure.append(int(is_exposed))
        outcome.append(int(day.symptom))
    return [by_block[b] for b in sorted(by_block)]


def _counts(days: list[_Day], exposed: list[bool]) -> tuple[int, int, int, int]:
    e = [d for d, x in zip(days, exposed, strict=True) if x]
    u = [d for d, x in zip(days, exposed, strict=True) if not x]
    return len(e), sum(d.symptom for d in e), len(u), sum(d.symptom for d in u)


def _enrichment(days: list[_Day], x: AllergenGroup, y: AllergenGroup) -> Fraction:
    """P(Y | X) - P(Y | not X): how much more often Y is eaten on X's days.

    This is exactly how much of X's excess Y can account for. If Y adds b to the
    chance of a symptom day, it inflates X's risk difference by b times this
    enrichment (omitted-variable bias). At the 0.25 threshold, a Y with its own
    effect of up to 40 points can produce the 10-point floor unaided. A
    near-daily group with little enrichment cannot explain a flag, which is why
    wheat does not attach itself to everything. Measuring enrichment the other
    way round, or taking the larger of the two, was measured to pin 120 of 252
    true flags on the wrong food (see the plan's review log, round 3a).
    """
    with_x = [d for d in days if x in d.exposure.groups]
    without_x = [d for d in days if x not in d.exposure.groups]
    if not with_x or not without_x:
        return Fraction(0)
    # Exact: a float difference can put an exact quarter just below the threshold.
    y_given_x = Fraction(sum(y in d.exposure.groups for d in with_x), len(with_x))
    y_given_not_x = Fraction(sum(y in d.exposure.groups for d in without_x), len(without_x))
    return y_given_x - y_given_not_x


def _co_exposure(
    days: list[_Day], x: AllergenGroup
) -> tuple[AllergenGroup | None, AllergenGroup | None]:
    """(explained_by, often_with) for a flagged group.

    For the most enriched qualifying Y, days with X but not Y are compared with
    days with neither. No excess there, shown with the powered bound, means Y may
    explain X. A clear excess means X stands on its own. Anything in between,
    including too few Y-free days, means this log can't yet tell the two apart.
    """
    enriched = [(y, _enrichment(days, x, y)) for y in AllergenGroup if y != x]
    qualifying = [(y, e) for y, e in enriched if e >= CO_EXPOSURE_ENRICHMENT]
    if not qualifying:
        return None, None
    y = max(qualifying, key=lambda pair: pair[1])[0]

    # X without Y, against days with neither.
    without_y = [d for d in days if y not in d.exposure.groups]
    exposed = [x in d.exposure.groups for d in without_y]
    blocks = _blocks(without_y, exposed)
    rd = statistics.mantel_haenszel_rd(blocks)
    # "Explained" is a claim of no excess without Y, so it needs real evidence:
    # the minimums, some information, and a bound below the floor.
    if _informative(rd) and rd is not None and rd.upper_bound(SE_INFLATION) < FLOOR:
        return y, None
    if _enough_days(rd) and statistics.shift_test(blocks) <= Q_LEVEL:
        return None, None
    return None, y


def _enough_days(rd: statistics.RiskDifference | None) -> bool:
    return (
        rd is not None
        and rd.exposed_days >= MIN_INFORMATIVE_DAYS
        and rd.unexposed_days >= MIN_INFORMATIVE_DAYS
    )


def _informative(rd: statistics.RiskDifference | None) -> bool:
    """Enough days on each side, and some information in them.

    A comparison whose informative blocks hold no symptom days (or only symptom
    days) has zero variance, so its bound collapses onto the estimate and would
    "rule out" an effect while saying nothing.
    """
    return _enough_days(rd) and rd is not None and rd.variance > 0


def _same_day_only(days: list[_Day], x: AllergenGroup, lag: int) -> bool:
    """True only on positive evidence that nothing is seen without the same day's food.

    The note weakens a real flag, so it needs at least the evidence a status
    does: the minimums, some information, and a bound below the floor. One
    earlier-exposed day giving a tight-looking bound is not evidence.
    """
    if lag == 0:
        return False
    rd = statistics.mantel_haenszel_rd(_blocks(days, [x in d.earlier.groups for d in days]))
    return _informative(rd) and rd is not None and rd.upper_bound(SE_INFLATION) < FLOOR


def _group_patterns(days: list[_Day], lag: int) -> list[FoodPattern]:
    results: dict[AllergenGroup, FoodPattern] = {}
    tested: list[tuple[AllergenGroup, float, statistics.RiskDifference]] = []
    for group in AllergenGroup:
        exposed = [group in d.exposure.groups for d in days]
        counts = _counts(days, exposed)
        if days and counts[0] / len(days) >= NO_BASELINE_SHARE:
            results[group] = FoodPattern(group.value, PatternStatus.NO_BASELINE, *counts)
            continue
        blocks = _blocks(days, exposed)
        rd = statistics.mantel_haenszel_rd(blocks)
        if (
            rd is None
            or rd.exposed_days < MIN_INFORMATIVE_DAYS
            or rd.unexposed_days < MIN_INFORMATIVE_DAYS
        ):
            results[group] = FoodPattern(group.value, PatternStatus.NOT_ENOUGH_DATA, *counts)
            continue
        tested.append((group, statistics.shift_test(blocks), rd))

    q_values = statistics.benjamini_hochberg([p for _, p, _ in tested])
    for (group, p, rd), q in zip(tested, q_values, strict=True):
        counts = _counts(days, [group in d.exposure.groups for d in days])
        if q <= Q_LEVEL and rd.estimate >= FLOOR:
            explained_by, often_with = _co_exposure(days, group)
            results[group] = FoodPattern(
                group.value,
                PatternStatus.FLAGGED,
                *counts,
                explained_by=explained_by,
                often_with=often_with,
                same_day_only=_same_day_only(days, group, lag),
                risk_difference=rd.estimate,
                q_value=q,
                p_value=p,
            )
        elif rd.upper_bound(SE_INFLATION) < FLOOR:
            results[group] = FoodPattern(
                group.value,
                PatternStatus.NO_PATTERN,
                *counts,
                risk_difference=rd.estimate,
                q_value=q,
                p_value=p,
            )
        else:
            results[group] = FoodPattern(
                group.value,
                PatternStatus.CANT_TELL,
                *counts,
                risk_difference=rd.estimate,
                q_value=q,
                p_value=p,
            )

    return sorted(results.values(), key=lambda p: (STATUS_ORDER.index(p.status), -p.exposed_days))


def _counts_only(days: list[_Day], keys: list[str], attribute: str) -> list[FoodPattern]:
    patterns = []
    for key in keys:
        exposed = [key in getattr(d.exposure, attribute) for d in days]
        patterns.append(FoodPattern(key, PatternStatus.COUNTS_ONLY, *_counts(days, exposed)))
    # By how often it was eaten, never by the gap between rates: these are not tested.
    return sorted(patterns, key=lambda p: (-p.exposed_days, p.key))


def _logging_gap(days: list[_Day]) -> tuple[float | None, float | None]:
    if not days:
        return None, None
    share = sum(d.complete for d in days) / len(days)
    rd = statistics.mantel_haenszel_rd(_blocks(days, [d.complete for d in days]))
    return share, (rd.estimate if rd is not None else None)


def analyse(data: PatternInput, *, lag: int = DEFAULT_LAG_DAYS) -> PatternReport:
    if not 0 <= lag <= MAX_LAG_DAYS:
        raise ValueError(f"lag must be between 0 and {MAX_LAG_DAYS}")
    window_start, days = _analyzable_days(data, lag)

    frequency: dict[str, int] = defaultdict(int)
    for d in days:
        for key in d.exposure.ingredients:
            frequency[key] += 1
    ingredients = [
        key
        for key, count in sorted(frequency.items(), key=lambda kv: (-kv[1], kv[0]))
        if count >= MIN_INFORMATIVE_DAYS
    ][:MAX_INGREDIENTS]
    additives = sorted({a for d in days for a in d.exposure.additives})

    share, gap = _logging_gap(days)
    return PatternReport(
        window_start=window_start,
        window_end=data.window_end,
        lag_days=lag,
        analyzable_days=len(days),
        symptom_days=sum(d.symptom for d in days),
        logged_days=data.logged_days,
        complete_window_share=share,
        logging_gap=gap,
        groups=_group_patterns(days, lag),
        ingredients=_counts_only(days, ingredients, "ingredients"),
        additives=_counts_only(days, additives, "additives"),
    )
