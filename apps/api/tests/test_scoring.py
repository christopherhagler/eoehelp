"""DSQ scoring, against hand-computed expectations.

Pure unit tests with no database: the arithmetic is where silent wrongness turns
into a clinical error, and it should be provable without a fixture harness.
"""

from datetime import date, timedelta

import pytest

from eoehelp_api.models.clinical import SymptomEntry
from eoehelp_api.models.enums import DysphagiaSeverity, EntryMethod
from eoehelp_api.services import scoring

END = date(2026, 9, 16)


def entry(
    day_offset: int,
    *,
    ate_solid_food: bool = True,
    severity: DysphagiaSeverity | None = None,
    pain: int | None = None,
    method: EntryMethod = EntryMethod.SAME_DAY,
    er_visit: bool = False,
    avoided: bool = False,
) -> SymptomEntry:
    """A symptom entry `day_offset` days before the window end."""
    return SymptomEntry(
        entry_date=END - timedelta(days=day_offset),
        ate_solid_food=ate_solid_food,
        dysphagia_occurred=severity not in (None, DysphagiaSeverity.NONE),
        dysphagia_severity=severity,
        odynophagia=bool(pain),
        odynophagia_severity=pain,
        food_impaction_er_visit=er_visit,
        avoided_foods_today=avoided,
        modified_foods_today=False,
        ate_unusually_slowly=False,
        entry_method=method,
        instrument_code="DSQ",
        instrument_version="v4.0",
    )


class TestDailyScore:
    @pytest.mark.parametrize(
        ("severity", "expected"),
        [
            (None, 0),
            (DysphagiaSeverity.NONE, 0),
            (DysphagiaSeverity.MILD_SLOW, 1),
            (DysphagiaSeverity.STUCK_SELF_RESOLVED, 2),
            (DysphagiaSeverity.STUCK_INTERVENTION, 3),
        ],
    )
    def test_dysphagia_contributes_by_what_it_took_to_clear_it(
        self, severity: DysphagiaSeverity | None, expected: int
    ) -> None:
        assert scoring.daily_score(entry(0, severity=severity)) == expected

    def test_pain_adds_to_dysphagia(self) -> None:
        assert scoring.daily_score(entry(0, severity=DysphagiaSeverity.MILD_SLOW, pain=2)) == 3

    def test_daily_score_is_capped_at_six(self) -> None:
        worst = entry(0, severity=DysphagiaSeverity.STUCK_INTERVENTION, pain=3)
        assert scoring.daily_score(worst) == scoring.DSQ_MAX_DAILY_SCORE

    def test_a_day_without_solid_food_is_unscorable_not_zero(self) -> None:
        # The distinction that matters: someone living on shakes is not
        # symptom-free, and scoring them as zero would say they were.
        assert scoring.daily_score(entry(0, ate_solid_food=False)) is None


class TestWindowScore:
    def test_the_worst_possible_fortnight_is_the_published_maximum(self) -> None:
        entries = [
            entry(d, severity=DysphagiaSeverity.STUCK_INTERVENTION, pain=3) for d in range(14)
        ]
        burden = scoring.score_window(entries, period_end=END)
        assert burden.score == float(scoring.DSQ_MAX_SCORE)
        assert burden.days_scorable == 14

    def test_a_symptom_free_fortnight_scores_zero(self) -> None:
        entries = [entry(d, severity=DysphagiaSeverity.NONE, pain=0) for d in range(14)]
        assert scoring.score_window(entries, period_end=END).score == 0.0

    def test_partial_logging_is_normalised_to_the_full_window(self) -> None:
        # Three days at 1 and four days at 3 is 15 points over 7 scorable days;
        # 15/7 * 14 = 30.0. Normalising is what keeps a patient who logged seven
        # days comparable to one who logged fourteen.
        entries = [entry(d, severity=DysphagiaSeverity.MILD_SLOW) for d in range(3)]
        entries += [
            entry(d, severity=DysphagiaSeverity.STUCK_SELF_RESOLVED, pain=1) for d in range(3, 7)
        ]
        burden = scoring.score_window(entries, period_end=END)
        assert burden.days_scorable == 7
        assert burden.score == 30.0

    def test_too_few_days_returns_no_score_rather_than_a_flattering_one(self) -> None:
        entries = [entry(d, severity=DysphagiaSeverity.STUCK_INTERVENTION) for d in range(6)]
        burden = scoring.score_window(entries, period_end=END)
        assert burden.score is None
        assert burden.is_scorable is False
        assert burden.components["unscorable_reason"] == "fewer_than_minimum_scorable_days"

    def test_unscorable_days_do_not_count_toward_the_minimum(self) -> None:
        entries = [entry(d, severity=DysphagiaSeverity.MILD_SLOW) for d in range(6)]
        entries += [entry(d, ate_solid_food=False) for d in range(6, 14)]
        burden = scoring.score_window(entries, period_end=END)
        assert burden.days_logged == 14
        assert burden.days_scorable == 6
        assert burden.score is None

    def test_entries_outside_the_window_are_ignored(self) -> None:
        inside = [entry(d, severity=DysphagiaSeverity.NONE) for d in range(14)]
        outside = [
            entry(d, severity=DysphagiaSeverity.STUCK_INTERVENTION, pain=3) for d in range(14, 30)
        ]
        burden = scoring.score_window(inside + outside, period_end=END)
        assert burden.days_logged == 14
        assert burden.score == 0.0

    def test_components_explain_the_score(self) -> None:
        entries = [entry(d, severity=DysphagiaSeverity.MILD_SLOW, avoided=True) for d in range(7)]
        entries.append(entry(7, severity=DysphagiaSeverity.STUCK_INTERVENTION, er_visit=True))
        entries.append(entry(8, ate_solid_food=False, method=EntryMethod.BACKFILL))
        components = scoring.score_window(entries, period_end=END).components
        assert components["dysphagia_days"] == 8
        assert components["avoidance_days"] == 7
        assert components["er_visit_days"] == 1
        assert components["no_solid_food_days"] == 1
        assert components["backfilled_days"] == 1
        assert components["worst_daily_score"] == 3


class TestTrend:
    def test_trend_runs_oldest_to_newest(self) -> None:
        entries = [entry(d, severity=DysphagiaSeverity.MILD_SLOW) for d in range(20)]
        points = scoring.score_trend(entries, period_end=END, points=5)
        assert len(points) == 5
        assert [p.period_end for p in points] == [
            END - timedelta(days=offset) for offset in reversed(range(5))
        ]
