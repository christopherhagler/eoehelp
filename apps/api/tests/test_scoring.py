"""DSQ scoring, against hand-computed expectations.

Pure unit tests with no database: the arithmetic is where silent wrongness turns
into a clinical error, and it should be provable without a fixture harness. The
expected values follow the published formula (Dellon et al. 2013): question 2
yes = 2, question 3 = 0-4, score = sum x 14 / valid days.
"""

from datetime import date, timedelta

import pytest

from eoehelp_api.core.entry_dates import EntryMethod
from eoehelp_api.symptoms import scoring
from eoehelp_api.symptoms.enums import DysphagiaRelief
from eoehelp_api.symptoms.models import SymptomEntry

END = date(2026, 9, 16)

R = DysphagiaRelief
# Sentinel for "question 2 answered no", distinct from "not answered" (None).
CLEAR = "clear"


def entry(
    day_offset: int,
    *,
    ate_solid_food: bool = True,
    relief: DysphagiaRelief | str | None = CLEAR,
    pain: int | None = None,
    method: EntryMethod = EntryMethod.SAME_DAY,
    er_visit: bool = False,
    avoided: bool = False,
) -> SymptomEntry:
    """A symptom entry `day_offset` days before the window end.

    `relief` is question 3's answer, which implies question 2 was yes; `CLEAR`
    means question 2 was no; None means question 2 was not answered.
    """
    stuck: bool | None
    if not ate_solid_food or relief is None:
        stuck, answer = None, None
    elif relief == CLEAR:
        stuck, answer = False, None
    else:
        stuck, answer = True, DysphagiaRelief(relief)
    return SymptomEntry(
        entry_date=END - timedelta(days=day_offset),
        ate_solid_food=ate_solid_food,
        dysphagia_occurred=stuck,
        dysphagia_relief=answer,
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
    def test_a_clear_day_scores_zero(self) -> None:
        assert scoring.daily_score(entry(0)) == 0

    @pytest.mark.parametrize(
        ("relief", "expected"),
        [
            # Question 2 yes is 2 points; question 3 adds 0-4 in the instrument's order.
            (R.CLEARED_ON_ITS_OWN, 2),
            (R.DRANK_LIQUID, 3),
            (R.COUGHED_OR_GAGGED, 4),
            (R.VOMITED, 5),
            (R.SOUGHT_MEDICAL_ATTENTION, 6),
        ],
    )
    def test_a_dysphagia_day_scores_two_plus_what_relief_took(
        self, relief: DysphagiaRelief, expected: int
    ) -> None:
        assert scoring.daily_score(entry(0, relief=relief)) == expected

    def test_pain_is_not_part_of_the_dsq_total(self) -> None:
        """The DSQ scores pain separately; folding it in inflates the number and
        makes it incomparable with trial results."""
        assert scoring.daily_score(entry(0, relief=R.DRANK_LIQUID, pain=3)) == 3
        assert scoring.daily_score(entry(0, pain=2)) == 0

    def test_the_daily_maximum_is_six(self) -> None:
        worst = entry(0, relief=R.SOUGHT_MEDICAL_ATTENTION, pain=3)
        assert scoring.daily_score(worst) == scoring.DSQ_MAX_DAILY_SCORE == 6

    def test_a_day_without_solid_food_is_unscorable_not_zero(self) -> None:
        # The distinction that matters: someone living on shakes is not
        # symptom-free, and scoring them as zero would say they were.
        assert scoring.daily_score(entry(0, ate_solid_food=False)) is None

    def test_an_unanswered_question_two_is_unscorable_not_zero(self) -> None:
        assert scoring.daily_score(entry(0, relief=None)) is None


class TestWindowScore:
    def test_the_worst_possible_fortnight_is_the_published_maximum(self) -> None:
        entries = [entry(d, relief=R.SOUGHT_MEDICAL_ATTENTION) for d in range(14)]
        burden = scoring.score_window(entries, period_end=END)
        assert burden.score == float(scoring.DSQ_MAX_SCORE) == 84.0
        assert burden.days_scorable == 14

    def test_a_symptom_free_fortnight_scores_zero(self) -> None:
        entries = [entry(d) for d in range(14)]
        assert scoring.score_window(entries, period_end=END).score == 0.0

    def test_a_worked_example(self) -> None:
        # 14 valid days: 4 cleared on their own (2 each), 2 needed a drink
        # (3 each), 1 vomited (5), 7 clear (0). Sum 8 + 6 + 5 = 19.
        # Score = 19 x 14 / 14 = 19.0.
        entries = [entry(d, relief=R.CLEARED_ON_ITS_OWN) for d in range(4)]
        entries += [entry(d, relief=R.DRANK_LIQUID) for d in range(4, 6)]
        entries += [entry(6, relief=R.VOMITED)]
        entries += [entry(d) for d in range(7, 14)]
        assert scoring.score_window(entries, period_end=END).score == 19.0

    def test_partial_logging_is_normalised_to_the_full_window(self) -> None:
        # 7 valid days: 3 cleared on their own (2 each) and 4 needing a drink
        # (3 each) is 18 points; 18 x 14 / 7 = 36.0. Normalising keeps a
        # patient who logged seven days comparable to one who logged fourteen.
        entries = [entry(d, relief=R.CLEARED_ON_ITS_OWN) for d in range(3)]
        entries += [entry(d, relief=R.DRANK_LIQUID) for d in range(3, 7)]
        burden = scoring.score_window(entries, period_end=END)
        assert burden.days_scorable == 7
        assert burden.score == 36.0

    def test_too_few_days_returns_no_score_rather_than_a_flattering_one(self) -> None:
        entries = [entry(d, relief=R.VOMITED) for d in range(6)]
        burden = scoring.score_window(entries, period_end=END)
        assert burden.score is None
        assert burden.is_scorable is False
        assert burden.components["unscorable_reason"] == "fewer_than_minimum_scorable_days"

    def test_unscorable_days_do_not_count_toward_the_minimum(self) -> None:
        entries = [entry(d, relief=R.CLEARED_ON_ITS_OWN) for d in range(6)]
        entries += [entry(d, ate_solid_food=False) for d in range(6, 14)]
        burden = scoring.score_window(entries, period_end=END)
        assert burden.days_logged == 14
        assert burden.days_scorable == 6
        assert burden.score is None

    def test_entries_outside_the_window_are_ignored(self) -> None:
        inside = [entry(d) for d in range(14)]
        outside = [entry(d, relief=R.SOUGHT_MEDICAL_ATTENTION) for d in range(14, 30)]
        burden = scoring.score_window(inside + outside, period_end=END)
        assert burden.days_logged == 14
        assert burden.score == 0.0

    def test_components_explain_the_score(self) -> None:
        entries = [entry(d, relief=R.DRANK_LIQUID, avoided=True) for d in range(7)]
        entries.append(entry(7, relief=R.SOUGHT_MEDICAL_ATTENTION, er_visit=True, pain=2))
        entries.append(entry(8, ate_solid_food=False, method=EntryMethod.BACKFILL))
        components = scoring.score_window(entries, period_end=END).components
        assert components["dysphagia_days"] == 8
        assert components["relief"] == {
            "cleared_on_its_own": 0,
            "drank_liquid": 7,
            "coughed_or_gagged": 0,
            "vomited": 0,
            "sought_medical_attention": 1,
        }
        assert components["avoidance_days"] == 7
        assert components["er_visit_days"] == 1
        assert components["odynophagia_days"] == 1
        assert components["no_solid_food_days"] == 1
        assert components["backfilled_days"] == 1
        assert components["worst_daily_score"] == 6


class TestTrend:
    def test_trend_runs_oldest_to_newest(self) -> None:
        entries = [entry(d, relief=R.CLEARED_ON_ITS_OWN) for d in range(20)]
        points = scoring.score_trend(entries, period_end=END, points=5)
        assert len(points) == 5
        assert [p.period_end for p in points] == [
            END - timedelta(days=offset) for offset in reversed(range(5))
        ]
