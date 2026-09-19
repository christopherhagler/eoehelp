"""The food-pattern analysis on constructed histories, one rule at a time."""

from collections.abc import Callable
from datetime import date, timedelta
from fractions import Fraction

import pytest

from eoehelp_api.food.enums import AllergenGroup
from eoehelp_api.insights import food_patterns
from eoehelp_api.insights.food_patterns import DayFood, PatternInput, PatternStatus

END = date(2026, 9, 1)
MILK = AllergenGroup.MILK
EGG = AllergenGroup.EGG


def day(offset: int) -> date:
    """`offset` days before the window's end; 0 is the patient's today."""
    return END - timedelta(days=offset)


def history(
    days: int,
    *,
    eats: Callable[[int], set[AllergenGroup]],
    symptom: Callable[[int], bool | None],
    logged: Callable[[int], bool] = lambda _o: True,
    ingredients: Callable[[int], set[str]] = lambda _o: set(),
    additives: Callable[[int], set[str]] = lambda _o: set(),
) -> PatternInput:
    outcomes: dict[date, bool] = {}
    foods: dict[date, DayFood] = {}
    for offset in range(days):
        answer = symptom(offset)
        if answer is not None:
            outcomes[day(offset)] = answer
        if logged(offset):
            foods[day(offset)] = DayFood(
                groups=frozenset(eats(offset)),
                ingredients=frozenset(ingredients(offset)),
                additives=frozenset(additives(offset)),
            )
    return PatternInput(window_end=END, outcomes=outcomes, foods=foods)


def pattern(report: food_patterns.PatternReport, group: AllergenGroup) -> food_patterns.FoodPattern:
    return next(p for p in report.groups if p.key == group.value)


def milk_weekly(offset: int) -> set[AllergenGroup]:
    return {MILK} if offset % 7 == 0 else set()


def lagged_reaction(days: int) -> Callable[[int], bool]:
    """A lag-2 reaction to weekly milk: the day it was eaten and the two after.

    Only milk inside the history counts, as it would for a real log: a reaction
    to food eaten before the record starts is invisible to the analysis.
    """
    return lambda offset: any((offset + k) % 7 == 0 and offset + k < days for k in range(3))


class TestAnalyzableDays:
    def test_the_lag_window_reaches_back_to_earlier_food(self) -> None:
        data = history(3, eats=lambda o: {MILK} if o == 2 else set(), symptom=lambda _o: False)
        at_lag_0 = pattern(food_patterns.analyse(data, lag=0), MILK)
        assert (at_lag_0.exposed_days, at_lag_0.unexposed_days) == (1, 2)
        # At lag 2, day 2's window (days 2-4) has one logged day of three, so
        # it is not analyzable; days 0 and 1 both reach back to day 2's milk.
        at_lag_2 = pattern(food_patterns.analyse(data, lag=2), MILK)
        assert (at_lag_2.exposed_days, at_lag_2.unexposed_days) == (2, 0)

    def test_a_day_without_its_own_food_log_is_not_analyzable(self) -> None:
        data = history(10, eats=lambda _o: set(), symptom=lambda _o: False, logged=lambda o: o != 4)
        report = food_patterns.analyse(data, lag=0)
        assert report.analyzable_days == 9

    def test_a_window_needs_l_of_its_l_plus_1_days_logged(self) -> None:
        # Logged every third day: at lag 2 each window holds one logged day.
        sparse = history(
            30, eats=lambda _o: set(), symptom=lambda _o: False, logged=lambda o: o % 3 == 0
        )
        assert food_patterns.analyse(sparse, lag=2).analyzable_days == 0
        # Missing every third day: two of three logged, so the logged days count.
        gappy = history(
            30, eats=lambda _o: set(), symptom=lambda _o: False, logged=lambda o: o % 3 != 1
        )
        report = food_patterns.analyse(gappy, lag=2)
        assert report.analyzable_days == 19
        assert report.complete_window_share is not None
        assert report.complete_window_share < 1

    def test_days_without_a_scorable_answer_are_left_out(self) -> None:
        data = history(10, eats=lambda _o: set(), symptom=lambda o: None if o < 3 else False)
        assert food_patterns.analyse(data, lag=0).analyzable_days == 7

    def test_an_oldest_block_under_two_weeks_merges_into_the_next(self) -> None:
        data = history(28 + 5, eats=lambda _o: set(), symptom=lambda _o: False)
        _start, days = food_patterns._analyzable_days(data, 0)
        assert {d.block for d in days} == {0}
        longer = history(28 + 20, eats=lambda _o: set(), symptom=lambda _o: False)
        _start, days = food_patterns._analyzable_days(longer, 0)
        assert {d.block for d in days} == {0, 1}

    def test_the_window_is_always_the_full_540_days(self) -> None:
        """Even when the log is shorter: analyzable_days says how much had data."""
        report = food_patterns.analyse(
            history(40, eats=lambda _o: set(), symptom=lambda _o: False), lag=0
        )
        assert report.window_start == END - timedelta(days=food_patterns.HORIZON_DAYS - 1)
        assert report.analyzable_days == 40

    def test_lag_outside_the_range_is_refused(self) -> None:
        data = history(5, eats=lambda _o: set(), symptom=lambda _o: False)
        with pytest.raises(ValueError, match="lag must be between"):
            food_patterns.analyse(data, lag=4)


class TestStatuses:
    def test_a_food_in_almost_every_window_has_no_baseline(self) -> None:
        data = history(
            60, eats=lambda o: set() if o == 30 else {MILK}, symptom=lambda o: o % 3 == 0
        )
        assert pattern(food_patterns.analyse(data, lag=0), MILK).status is PatternStatus.NO_BASELINE

    def test_the_minimums_count_only_blocks_that_hold_both_kinds_of_day(self) -> None:
        """Milk every day for four weeks, then never: forty days on each side, but
        no block compares the two, so there is nothing to test."""
        data = history(
            28 * 3, eats=lambda o: {MILK} if o < 28 else set(), symptom=lambda o: o % 4 == 0
        )
        result = pattern(food_patterns.analyse(data, lag=0), MILK)
        assert result.exposed_days >= 8
        assert result.unexposed_days >= 8
        assert result.status is PatternStatus.NOT_ENOUGH_DATA

    def test_a_consistent_lagged_reaction_is_flagged(self) -> None:
        data = history(28 * 8, eats=milk_weekly, symptom=lagged_reaction(28 * 8))
        result = pattern(food_patterns.analyse(data, lag=2), MILK)
        assert result.status is PatternStatus.FLAGGED
        assert result.q_value is not None
        assert result.q_value <= food_patterns.Q_LEVEL
        assert result.exposed_symptom_days == result.exposed_days
        assert result.unexposed_symptom_days == 0
        assert result.same_day_only is False
        # Nothing else was eaten, so nothing else can be tested.
        assert (
            pattern(food_patterns.analyse(data, lag=2), EGG).status is PatternStatus.NOT_ENOUGH_DATA
        )

    def test_no_pattern_is_reported_only_when_the_data_could_have_shown_one(self) -> None:
        unrelated = lambda o: o % 10 == 3  # noqa: E731 - a 10% symptom rhythm, independent of milk
        long = history(food_patterns.HORIZON_DAYS, eats=milk_weekly, symptom=unrelated)
        assert pattern(food_patterns.analyse(long, lag=2), MILK).status is PatternStatus.NO_PATTERN
        short = history(70, eats=milk_weekly, symptom=unrelated)
        assert pattern(food_patterns.analyse(short, lag=2), MILK).status is PatternStatus.CANT_TELL

    def test_a_treatment_change_is_not_credited_to_a_food(self) -> None:
        """Bread-heavy months before treatment worked, and little bread after.
        Symptom days track the period, not the bread."""

        def eats(offset: int) -> set[AllergenGroup]:
            before = offset >= 28 * 8
            return {AllergenGroup.WHEAT} if offset % 7 < (5 if before else 1) else set()

        def symptom(offset: int) -> bool:
            before = offset >= 28 * 8
            return offset % 10 < (6 if before else 1)

        data = history(28 * 16, eats=eats, symptom=symptom)
        result = pattern(food_patterns.analyse(data, lag=0), AllergenGroup.WHEAT)
        # Crude totals make wheat look strongly linked...
        exposed_rate = result.exposed_symptom_days / result.exposed_days
        unexposed_rate = result.unexposed_symptom_days / result.unexposed_days
        assert exposed_rate - unexposed_rate > 0.2
        # ...but within each four-week stretch it is not.
        assert result.status is not PatternStatus.FLAGGED

    def test_a_significant_but_small_difference_is_not_flagged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The size floor on its own: with the test forced to say "significant",
        a 5-point difference still is not flagged, and a 20-point one is."""
        monkeypatch.setattr(food_patterns.statistics, "shift_test", lambda _blocks: 1e-6)

        def symptom(rate_exposed: int, rate_other: int) -> Callable[[int], bool]:
            # Symptom days as a share out of 20, spread evenly through the log.
            return lambda o: (o // 2) % 20 < (rate_exposed if o % 2 == 0 else rate_other)

        eats = lambda o: {MILK} if o % 2 == 0 else set()  # noqa: E731
        small = history(28 * 10, eats=eats, symptom=symptom(3, 2))
        result = pattern(food_patterns.analyse(small, lag=0), MILK)
        assert result.risk_difference is not None
        assert 0 < result.risk_difference < food_patterns.FLOOR
        assert result.status is not PatternStatus.FLAGGED

        large = history(28 * 10, eats=eats, symptom=symptom(8, 4))
        assert pattern(food_patterns.analyse(large, lag=0), MILK).status is PatternStatus.FLAGGED

    def test_groups_sort_flagged_first(self) -> None:
        data = history(28 * 8, eats=milk_weekly, symptom=lagged_reaction(28 * 8))
        statuses = [p.status for p in food_patterns.analyse(data, lag=2).groups]
        assert statuses[0] is PatternStatus.FLAGGED
        assert statuses == sorted(statuses, key=food_patterns.STATUS_ORDER.index)


class TestSameDayNote:
    def test_it_fires_when_the_excess_sits_entirely_on_same_day_food(self) -> None:
        """Symptoms only on the day milk was eaten, never after: the pattern a
        soft-food choice on a bad day leaves behind."""
        data = history(food_patterns.HORIZON_DAYS, eats=milk_weekly, symptom=lambda o: o % 7 == 0)
        result = pattern(food_patterns.analyse(data, lag=2), MILK)
        assert result.status is PatternStatus.FLAGGED
        assert result.same_day_only is True

    def test_it_stays_silent_on_a_lagged_reaction(self) -> None:
        data = history(
            food_patterns.HORIZON_DAYS,
            eats=milk_weekly,
            symptom=lagged_reaction(food_patterns.HORIZON_DAYS),
        )
        assert pattern(food_patterns.analyse(data, lag=2), MILK).same_day_only is False

    def test_it_is_skipped_at_lag_0(self) -> None:
        data = history(food_patterns.HORIZON_DAYS, eats=milk_weekly, symptom=lambda o: o % 7 == 0)
        result = pattern(food_patterns.analyse(data, lag=0), MILK)
        assert result.status is PatternStatus.FLAGGED
        assert result.same_day_only is False


class TestCountsOnly:
    def test_ingredients_and_additives_carry_counts_and_no_verdict(self) -> None:
        data = history(
            60,
            eats=lambda _o: set(),
            symptom=lambda o: o % 2 == 0,
            ingredients=lambda o: {"en:oat"} | ({"en:e202"} if o % 3 == 0 else set()),
            additives=lambda o: {"preservative"} if o % 3 == 0 else set(),
        )
        report = food_patterns.analyse(data, lag=0)
        assert [p.key for p in report.ingredients] == ["en:oat", "en:e202"]
        assert all(
            p.status is PatternStatus.COUNTS_ONLY for p in report.ingredients + report.additives
        )
        assert all(p.q_value is None and p.risk_difference is None for p in report.ingredients)
        preservative = report.additives[0]
        assert (preservative.exposed_days, preservative.unexposed_days) == (20, 40)

    def test_rarely_eaten_ingredients_are_left_out(self) -> None:
        data = history(
            60,
            eats=lambda _o: set(),
            symptom=lambda _o: False,
            ingredients=lambda o: {"en:kiwi"} if o < 5 else set(),
        )
        assert food_patterns.analyse(data, lag=0).ingredients == []


def _days(rows: list[tuple[set[AllergenGroup], bool]]) -> list[food_patterns._Day]:
    """One block of analyzable days: (groups in the window, symptom day)."""
    return [
        food_patterns._Day(
            day=day(i),
            symptom=symptom,
            block=0,
            complete=True,
            exposure=DayFood(groups=frozenset(groups)),
            earlier=DayFood(),
        )
        for i, (groups, symptom) in enumerate(rows)
    ]


WHEAT = AllergenGroup.WHEAT
SOY = AllergenGroup.SOY


class TestCoExposure:
    def test_enrichment_qualifies_at_a_quarter_and_not_below(self) -> None:
        # X on 100 days, Y on 50 of them; Y on 25 of the 100 days without X.
        at_threshold = _days(
            [({MILK, EGG} if i < 50 else {MILK}, False) for i in range(100)]
            + [({EGG} if i < 25 else set(), False) for i in range(100)]
        )
        assert food_patterns._enrichment(at_threshold, MILK, EGG) == pytest.approx(0.25)
        assert food_patterns._co_exposure(at_threshold, MILK) != (None, None)

        below = _days(
            [({MILK, EGG} if i < 49 else {MILK}, False) for i in range(100)]
            + [({EGG} if i < 25 else set(), False) for i in range(100)]
        )
        assert food_patterns._enrichment(below, MILK, EGG) == pytest.approx(0.24)
        assert food_patterns._co_exposure(below, MILK) == (None, None)

    def test_an_exact_quarter_is_compared_exactly(self) -> None:
        """7 of 20 against 2 of 20 is exactly 0.25; in floating point it is
        0.2499..., which would slip under the threshold."""
        rows = [({MILK, EGG} if i < 7 else {MILK}, False) for i in range(20)]
        rows += [({EGG} if i < 2 else set(), False) for i in range(20)]
        days = _days(rows)
        assert food_patterns._enrichment(days, MILK, EGG) == Fraction(1, 4)
        assert food_patterns._co_exposure(days, MILK) != (None, None)

    def test_a_near_daily_group_with_little_enrichment_never_qualifies(self) -> None:
        """Wheat on 95% of days, and every wheat-free day is also egg-free. Asking
        the question the other way round would pin egg on wheat; how much of
        egg's excess wheat can account for is what matters, and that is small."""
        rows = [({EGG, WHEAT}, i % 3 == 0) for i in range(30)]
        rows += [({WHEAT}, False) for _ in range(65)]
        rows += [(set(), False) for _ in range(5)]
        days = _days(rows)
        assert food_patterns._enrichment(days, EGG, WHEAT) < 0.1
        assert food_patterns._co_exposure(days, EGG) == (None, None)

    def test_a_group_without_its_own_baseline_can_still_be_named(self) -> None:
        # Milk on 90% of days overall, and on every one of egg's days.
        rows = [({EGG, MILK}, True) for _ in range(60)]
        rows += [({MILK}, True) for _ in range(30)] + [(set(), False) for _ in range(10)]
        days = _days(rows)
        assert (
            sum(MILK in d.exposure.groups for d in days) / len(days)
            >= food_patterns.NO_BASELINE_SHARE
        )
        explained_by, often_with = food_patterns._co_exposure(days, EGG)
        assert MILK in (explained_by, often_with)

    def test_the_most_enriched_group_is_the_one_named(self) -> None:
        rows = [({MILK, EGG, SOY} if i < 30 else {MILK, EGG}, False) for i in range(60)]
        rows += [({SOY} if i < 18 else set(), False) for i in range(60)]
        days = _days(rows)
        # Egg: 1.0 against 0.0. Soy: 0.5 against 0.3.
        assert food_patterns._co_exposure(days, MILK) in ((EGG, None), (None, EGG))

    def test_no_excess_without_y_means_y_may_explain_it(self) -> None:
        # Symptom days come with egg; milk-only days have the same 10% background
        # rate as days with neither, over enough days to bound any difference.
        rows = [({MILK, EGG}, True) for _ in range(200)]
        rows += [({MILK}, i % 10 == 0) for i in range(200)]
        rows += [(set(), i % 10 == 5) for i in range(200)]
        assert food_patterns._co_exposure(_days(rows), MILK) == (EGG, None)

    @pytest.mark.parametrize("symptom", [False, True])
    def test_a_contrast_without_information_cannot_explain(self, symptom: bool) -> None:
        """Milk-only and neither days all clear (or all symptom days): the bound
        collapses to the estimate, so "explained" would rest on nothing."""
        rows = [({MILK, EGG}, True) for _ in range(40)]
        rows += [({MILK}, symptom) for _ in range(20)]
        rows += [(set(), symptom) for _ in range(20)]
        assert food_patterns._co_exposure(_days(rows), MILK) == (None, EGG)

    def test_too_few_days_without_y_means_the_log_cannot_tell_them_apart(self) -> None:
        rows = [({MILK, EGG}, True) for _ in range(40)]
        rows += [({MILK}, True) for _ in range(3)]
        rows += [(set(), False) for _ in range(40)]
        assert food_patterns._co_exposure(_days(rows), MILK) == (None, EGG)

    def test_an_unsettled_contrast_means_the_log_cannot_tell_them_apart(self) -> None:
        """Enough days on each side, but the comparison settles nothing either way:
        an excess too uncertain to count, and too large to rule out."""
        rows = [({MILK, EGG}, True) for _ in range(40)]
        milk_only = [({MILK}, i < 3) for i in range(10)]
        neither = [(set(), i < 1) for i in range(10)]
        rows += [day for pair in zip(milk_only, neither, strict=True) for day in pair]
        assert food_patterns._co_exposure(_days(rows), MILK) == (None, EGG)

    def test_a_clear_excess_without_y_needs_no_note(self) -> None:
        # Milk days are symptom days with or without egg; neither-days are clear.
        rows = [({MILK, EGG}, True) for _ in range(40)]
        rows += [({MILK}, i % 5 != 0) for i in range(40)]
        rows += [(set(), i % 10 == 0) for i in range(60)]
        # A realistic day order, so the shift test has something to shift.
        shuffled = [rows[(i * 37) % len(rows)] for i in range(len(rows))]
        assert food_patterns._co_exposure(_days(shuffled), MILK) == (None, None)


def _shifted(rows: list[tuple[bool, bool]]) -> list[food_patterns._Day]:
    """Days for the same-day check: (milk in the earlier window, symptom day)."""
    return [
        food_patterns._Day(
            day=day(i),
            symptom=symptom,
            block=0,
            complete=True,
            exposure=DayFood(groups=frozenset({MILK})),
            earlier=DayFood(groups=frozenset({MILK} if earlier else set())),
        )
        for i, (earlier, symptom) in enumerate(rows)
    ]


class TestSameDayEvidence:
    """The note weakens a real flag, so it needs as much evidence as a status."""

    def test_one_earlier_day_is_not_evidence(self) -> None:
        rows = [(i == 0, False) for i in range(20)] + [(False, i % 2 == 0) for i in range(20)]
        assert food_patterns._same_day_only(_shifted(rows), MILK, lag=2) is False

    def test_it_needs_eight_days_on_each_side(self) -> None:
        def rows(earlier_days: int) -> list[tuple[bool, bool]]:
            return [(True, False) for _ in range(earlier_days)] + [
                (False, i % 2 == 0) for i in range(30)
            ]

        assert food_patterns._same_day_only(_shifted(rows(7)), MILK, lag=2) is False
        assert food_patterns._same_day_only(_shifted(rows(8)), MILK, lag=2) is True

    def test_a_comparison_without_information_is_not_evidence(self) -> None:
        # No symptom days anywhere in the shifted comparison: the bound collapses.
        rows = [(True, False) for _ in range(10)] + [(False, False) for _ in range(10)]
        assert food_patterns._same_day_only(_shifted(rows), MILK, lag=2) is False
