"""Pre-registered validation of the food-pattern method against planted triggers.

The synthetic generator plants 0-2 trigger groups per patient and never writes
them anywhere the analysis can see. This module runs the production analysis on
cohorts that played no part in choosing its settings (the tuning seeds were
1000-2199), and holds it to thresholds fixed before any of these cohorts were
run. See docs/plans/2026-09-19-insights-food-patterns.md, "Validation".

The thresholds are never lowered to make this pass. If the method misses one,
the method goes back to the architect.
"""

import statistics as stats
import time
from dataclasses import dataclass
from datetime import date

import pytest

from eoehelp_api.food.enums import AllergenGroup
from eoehelp_api.insights import food_patterns
from eoehelp_api.insights.food_patterns import PatternInput, PatternReport, PatternStatus
from eoehelp_api.synthetic.generator import HistoryGenerator
from eoehelp_api.synthetic.plans import HistoryPlan
from helpers import synthetic_pattern_input

TODAY = date(2026, 9, 1)
LAG = 2

HELD_OUT_SEEDS = range(5000, 6200)
TRIGGER_FREE_18_FROM = 20000
TRIGGER_FREE_12_FROM = 40000
TRIGGER_FREE_COHORT = 1000
MIN_ANALYZABLE_12 = 30

# Pre-registered gates (plan, "Validation"). Tuning values in comments.
MIN_RECALL = 0.13  # 18%
MIN_PRECISION = 0.72  # 78% strict
MAX_NO_PATTERN_ON_TRUE = 0.05  # 2%
MAX_NON_TRIGGER_FLAGGED = 0.06  # 3.7%
MAX_SAME_DAY_ON_TRUE = 0.10  # 0%
MAX_ANY_FLAG_18 = 0.06  # 2.4%
MAX_ANY_FLAG_12 = 0.08  # 4.9%
MAX_NULL_P = 0.05  # 3.0%


def pattern_input(plan: HistoryPlan) -> PatternInput:
    return synthetic_pattern_input(plan, TODAY)


@dataclass
class Tally:
    planted: int = 0
    found: int = 0
    no_pattern_on_true: int = 0
    flags: int = 0
    correct_flags: int = 0
    true_flags: int = 0
    same_day_on_true: int = 0
    non_trigger_assessed: int = 0
    non_trigger_flagged: int = 0

    def add(self, report: PatternReport, triggers: frozenset[AllergenGroup]) -> None:
        planted = {t.value for t in triggers}
        for p in report.groups:
            true = p.key in planted
            note = p.explained_by or p.often_with
            if true:
                self.planted += 1
                self.no_pattern_on_true += p.status is PatternStatus.NO_PATTERN
            if p.status is PatternStatus.FLAGGED:
                self.flags += 1
                # Correct: a true trigger with no note or a note naming a true
                # trigger, or a non-trigger whose note points at a true one.
                # A true trigger whose note names a non-trigger points the
                # patient at the wrong food, so it counts against.
                named_true = note is not None and note.value in planted
                self.correct_flags += (true and (note is None or named_true)) or (
                    not true and named_true
                )
                if true:
                    self.found += 1
                    self.true_flags += 1
                    self.same_day_on_true += p.same_day_only
            if not true and p.status in (PatternStatus.FLAGGED, PatternStatus.NO_PATTERN):
                self.non_trigger_assessed += 1
                self.non_trigger_flagged += p.status is PatternStatus.FLAGGED


def _trigger_free(start: int, months: int, min_days: int = 0) -> list[PatternReport]:
    reports: list[PatternReport] = []
    seed = start
    while len(reports) < TRIGGER_FREE_COHORT:
        plan = HistoryGenerator(seed=seed, today=TODAY).generate(months=months)
        seed += 1
        if plan.hidden_triggers:
            continue
        report = food_patterns.analyse(pattern_input(plan), lag=LAG)
        if report.analyzable_days >= min_days:
            reports.append(report)
    return reports


@pytest.fixture(scope="module")
def held_out() -> Tally:
    tally = Tally()
    for seed in HELD_OUT_SEEDS:
        plan = HistoryGenerator(seed=seed, today=TODAY).generate(months=18)
        tally.add(food_patterns.analyse(pattern_input(plan), lag=LAG), plan.hidden_triggers)
    return tally


@pytest.fixture(scope="module")
def trigger_free_18() -> list[PatternReport]:
    return _trigger_free(TRIGGER_FREE_18_FROM, months=18)


@pytest.fixture(scope="module")
def trigger_free_12() -> list[PatternReport]:
    return _trigger_free(TRIGGER_FREE_12_FROM, months=12, min_days=MIN_ANALYZABLE_12)


def _any_flag(reports: list[PatternReport]) -> float:
    flagged = sum(any(p.status is PatternStatus.FLAGGED for p in r.groups) for r in reports)
    return flagged / len(reports)


def _report(name: str, value: float, gate: str) -> None:
    # Printed with -s, for copying into the plan's review log.
    print(f"\n[validation] {name}: {value:.1%} (gate {gate})")


class TestHeldOutCohort:
    def test_recall(self, held_out: Tally) -> None:
        recall = held_out.found / held_out.planted
        _report("recall", recall, f">= {MIN_RECALL:.0%}")
        assert recall >= MIN_RECALL

    def test_precision(self, held_out: Tally) -> None:
        precision = held_out.correct_flags / held_out.flags
        _report("precision (strict)", precision, f">= {MIN_PRECISION:.0%}")
        assert precision >= MIN_PRECISION

    def test_true_triggers_are_rarely_called_no_pattern(self, held_out: Tally) -> None:
        rate = held_out.no_pattern_on_true / held_out.planted
        _report("no pattern on true triggers", rate, f"<= {MAX_NO_PATTERN_ON_TRUE:.0%}")
        assert rate <= MAX_NO_PATTERN_ON_TRUE

    def test_non_triggers_are_rarely_flagged(self, held_out: Tally) -> None:
        rate = held_out.non_trigger_flagged / held_out.non_trigger_assessed
        _report("non-trigger groups flagged", rate, f"<= {MAX_NON_TRIGGER_FLAGGED:.0%}")
        assert rate <= MAX_NON_TRIGGER_FLAGGED

    def test_the_same_day_note_rarely_doubts_a_true_flag(self, held_out: Tally) -> None:
        rate = held_out.same_day_on_true / held_out.true_flags
        _report("same-day note on true flags", rate, f"<= {MAX_SAME_DAY_ON_TRUE:.0%}")
        assert rate <= MAX_SAME_DAY_ON_TRUE


class TestTriggerFreeCohorts:
    def test_few_18_month_patients_see_any_flag(self, trigger_free_18: list[PatternReport]) -> None:
        rate = _any_flag(trigger_free_18)
        _report("any flag, trigger-free 18 months", rate, f"<= {MAX_ANY_FLAG_18:.0%}")
        assert rate <= MAX_ANY_FLAG_18

    def test_few_12_month_patients_see_any_flag(self, trigger_free_12: list[PatternReport]) -> None:
        rate = _any_flag(trigger_free_12)
        _report("any flag, trigger-free 12 months", rate, f"<= {MAX_ANY_FLAG_12:.0%}")
        assert rate <= MAX_ANY_FLAG_12

    def test_the_test_is_calibrated_under_the_null(
        self, trigger_free_18: list[PatternReport]
    ) -> None:
        p_values = [p.p_value for r in trigger_free_18 for p in r.groups if p.p_value is not None]
        rate = sum(p < 0.05 for p in p_values) / len(p_values)
        _report("candidates with p < 0.05, trigger-free", rate, f"<= {MAX_NULL_P:.0%}")
        assert rate <= MAX_NULL_P


def test_an_18_month_log_is_analysed_within_budget() -> None:
    plan = HistoryGenerator(seed=5000, today=TODAY).generate(months=18)
    data = pattern_input(plan)
    timings = []
    for _ in range(5):
        started = time.perf_counter()
        food_patterns.analyse(data, lag=LAG)
        timings.append(time.perf_counter() - started)
    assert stats.median(timings) < 0.2
