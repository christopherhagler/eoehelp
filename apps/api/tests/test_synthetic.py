"""The synthetic data generator.

Mostly pure tests, because the point of splitting planning from writing was to
make the properties that matter assertable without a database.
"""

import statistics
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.config import Settings
from eoehelp_api.models.enums import AllergenGroup, DoseStatus, EntryMethod
from eoehelp_api.schemas.auth import MagicLinkRequest
from eoehelp_api.schemas.food import FoodItemInput, IngredientRef
from eoehelp_api.schemas.symptoms import SymptomEntryInput
from eoehelp_api.services import scoring
from eoehelp_api.synthetic import HistoryGenerator, SyntheticDataRefusedError, assert_writable
from eoehelp_api.synthetic.generator import (
    INGREDIENT_GROUPS,
    MENU,
    TRIGGER_LAG_DAYS,
    groups_of,
)
from eoehelp_api.synthetic.plans import DayPlan, HistoryPlan
from eoehelp_api.synthetic.writer import SyntheticPatientExistsError, SyntheticWriter

TODAY = date(2026, 9, 16)


def plan(seed: int = 7, months: int = 18) -> HistoryPlan:
    return HistoryGenerator(seed=seed, today=TODAY).generate(months=months)


class TestDeterminism:
    def test_the_same_seed_gives_the_same_history(self) -> None:
        """Golden-file report tests are worthless without this, and a bug found in
        a demo has to be reproducible."""
        first, second = plan(seed=99), plan(seed=99)
        assert first == second

    def test_different_seeds_give_different_histories(self) -> None:
        assert plan(seed=1) != plan(seed=2)


class TestGeneratedDaysAreValid:
    def test_every_day_passes_the_api_validator(self) -> None:
        """The most valuable test here: generated data has to be data the product
        would actually accept.

        Run through SymptomEntryInput rather than a copy of its rules, so the
        generator cannot drift away from the instrument's coherence constraints —
        a fixture set the API would reject is useless for load tests and
        misleading for golden files.
        """
        for seed in range(12):
            for day in plan(seed=seed).days:
                SymptomEntryInput(
                    ate_solid_food=day.ate_solid_food,
                    dysphagia_occurred=day.dysphagia_occurred,
                    dysphagia_severity=day.dysphagia_severity,
                    odynophagia=day.odynophagia,
                    odynophagia_severity=day.odynophagia_severity,
                    coping_actions=day.coping_actions,
                    food_impaction_er_visit=day.food_impaction_er_visit,
                    avoided_foods_today=day.avoided_foods_today,
                    modified_foods_today=day.modified_foods_today,
                    ate_unusually_slowly=day.ate_unusually_slowly,
                    notes=day.notes,
                )

    def test_the_generated_address_can_actually_sign_in(self) -> None:
        """Seeded accounts have to work through the real magic-link flow.

        The first version used an @example.invalid address, which EmailStr refuses
        as a special-use domain — so every seeded patient was unreachable, which is
        most of what a demo seed is for. Checked against MagicLinkRequest rather
        than a regex, for the same reason the day plans are checked against
        SymptomEntryInput.
        """
        for seed in range(8):
            MagicLinkRequest(email=plan(seed=seed).email)

    def test_no_day_is_in_the_future(self) -> None:
        for seed in range(6):
            history = plan(seed=seed)
            assert all(day.entry_date <= TODAY for day in history.days)

    def test_days_are_unique_and_ordered(self) -> None:
        # One entry per patient per day is a database constraint, so a generator
        # that emitted a date twice would fail the insert rather than the test.
        for seed in range(6):
            dates = [day.entry_date for day in plan(seed=seed).days]
            assert dates == sorted(dates)
            assert len(dates) == len(set(dates))

    def test_the_record_is_incomplete_the_way_real_ones_are(self) -> None:
        """Gaps are the point: engagement decays, and the scoring code refuses to
        score a sparsely logged window. A complete record would never exercise it.
        """
        history = plan()
        span = (TODAY - history.days[0].entry_date).days + 1
        assert len(history.days) < span
        assert len(history.days) > span * 0.4


class TestClinicalShape:
    def test_treatment_visibly_helps(self) -> None:
        """A chart of uniform noise cannot show whether the chart works.

        Averaged over seeds rather than asserted per patient, because a quarter of
        generated patients are the ones for whom the steroid did not work — which
        is itself the realism being tested.
        """
        before: list[float] = []
        after: list[float] = []

        for seed in range(25):
            history = plan(seed=seed)
            first_epoch = history.epochs[0]
            last_epoch = history.epochs[-1]
            by_date = {day.entry_date: day for day in history.days}

            early = [
                _score(day)
                for day_date, day in by_date.items()
                if first_epoch.started_on <= day_date <= first_epoch.ended_on
            ]
            late = [
                _score(day)
                for day_date, day in by_date.items()
                if last_epoch.started_on <= day_date <= last_epoch.ended_on
            ]
            if early:
                before.append(statistics.fmean(early))
            if late:
                after.append(statistics.fmean(late))

        assert statistics.fmean(after) < statistics.fmean(before)

    def test_a_ppi_that_failed_is_recorded_as_having_failed(self) -> None:
        """The clinically interesting part of an EoE history is what did not work."""
        reasons = set()
        for seed in range(20):
            for medication in plan(seed=seed).medications:
                if medication.ended_on is not None:
                    assert medication.stop_reason is not None
                    reasons.add(medication.stop_reason.value)
                else:
                    # The check constraint refuses half a stop in either direction.
                    assert medication.stop_reason is None
        assert "ineffective" in reasons

    def test_adherence_decays_over_a_course(self) -> None:
        # Real adherence falls away, especially once symptoms are controlled, and
        # a report that never shows that is not showing anything a clinician
        # recognises.
        early_rates: list[float] = []
        late_rates: list[float] = []

        for seed in range(20):
            for medication in plan(seed=seed).medications:
                taken = [d for d in medication.doses if d.status is not DoseStatus.SKIPPED]
                if len(taken) < 40:
                    continue
                last = medication.ended_on or TODAY
                span = max((last - medication.started_on).days, 1)
                midpoint = medication.started_on + timedelta(days=span // 2)
                early = sum(1 for d in taken if d.taken_at.date() <= midpoint)
                late = len(taken) - early
                early_rates.append(early)
                late_rates.append(late)

        assert early_rates, "no course long enough to measure"
        assert statistics.fmean(late_rates) < statistics.fmean(early_rates)

    def test_some_days_are_unscorable_rather_than_zero(self) -> None:
        """Days without solid food exist, so the null-not-zero path gets exercised."""
        history = plan()
        assert any(not day.ate_solid_food for day in history.days)

    def test_both_entry_methods_appear(self) -> None:
        methods = {day.entry_method for day in plan().days}
        assert methods == {EntryMethod.SAME_DAY, EntryMethod.BACKFILL}


class TestTimezoneSpread:
    def test_patients_are_not_all_in_utc(self) -> None:
        """The blind spot that hid a real bug.

        Every dose a Los Angeles patient logged fell outside the adherence window,
        and the whole suite missed it because every fixture patient was in UTC.
        """
        zones = {plan(seed=seed).profile.timezone for seed in range(20)}
        assert len(zones) > 3
        assert zones - {"UTC"}, "generated patients must not all be in UTC"

    def test_zones_span_both_sides_of_utc(self) -> None:
        zones = {plan(seed=seed).profile.timezone for seed in range(40)}
        assert any(zone.startswith("America/") for zone in zones)
        assert any(zone.startswith(("Asia/", "Australia/", "Pacific/")) for zone in zones)

    def test_history_ends_on_the_patients_today_not_utcs(self) -> None:
        """At 01:00 UTC it is still yesterday evening in the Americas. A history
        ending on the UTC date would contain a day the API refuses as future."""
        now = datetime(2026, 9, 17, 1, 0, tzinfo=UTC)
        checked = set()
        for seed in range(60):
            history = HistoryGenerator(seed=seed, now=now).generate(months=2)
            zone = ZoneInfo(history.profile.timezone)
            local_now = now.astimezone(zone)
            checked.add(local_now.date())
            assert all(day.entry_date <= local_now.date() for day in history.days)
            assert all(food.eaten_on <= local_now.date() for food in history.foods)
            for medication in history.medications:
                assert medication.ended_on is None or medication.ended_on <= local_now.date()
                for dose in medication.doses:
                    # Doses carry local wall-clock time; see writer.py.
                    assert dose.taken_at.replace(tzinfo=zone) <= local_now
        # Both sides of the date line were exercised, or this proved nothing.
        assert checked == {date(2026, 9, 16), date(2026, 9, 17)}


class TestProductionGuard:
    def test_production_is_refused(self) -> None:
        """A generator with a path to production is a liability.

        Invented entries mixed into real ones are indistinguishable afterwards,
        and would corrupt both the record and any research export drawn from it.
        """
        with pytest.raises(SyntheticDataRefusedError, match="production"):
            assert_writable(Settings(environment="production", debug=False))

    def test_staging_needs_an_explicit_flag(self) -> None:
        staging = Settings(environment="staging")
        with pytest.raises(SyntheticDataRefusedError, match="allow_staging"):
            assert_writable(staging)
        assert_writable(staging, allow_staging=True)

    def test_local_is_allowed(self) -> None:
        assert_writable(Settings(environment="local"))


def _dysphagia_rates(history: HistoryPlan, group: AllergenGroup) -> tuple[list[bool], list[bool]]:
    """Symptom days split by logged exposure to one group, as an analysis would see them.

    Built from the logged foods only, not the hidden full diet, because the log is
    all a real analysis will ever have.
    """
    exposed: set[date] = set()
    for food in history.foods:
        if group in groups_of(food.ingredient_codes):
            exposed.update(
                food.eaten_on + timedelta(days=lag) for lag in range(TRIGGER_LAG_DAYS + 1)
            )
    food_days = {food.eaten_on for food in history.foods}
    after, otherwise = [], []
    for day in history.days:
        if day.ate_solid_food and day.entry_date in food_days:
            bucket = after if day.entry_date in exposed else otherwise
            bucket.append(bool(day.dysphagia_occurred))
    return after, otherwise


class TestFood:
    def test_every_food_passes_the_api_validator(self) -> None:
        for seed in range(12):
            for food in plan(seed=seed).foods:
                FoodItemInput(
                    eaten_on=food.eaten_on,
                    meal=food.meal,
                    name=food.name,
                    ingredients=[IngredientRef(code=code) for code in food.ingredient_codes],
                )

    def test_food_is_logged_only_on_logged_days_with_solid_food(self) -> None:
        history = plan()
        solid_days = {day.entry_date: day for day in history.days if day.ate_solid_food}
        assert history.foods
        for food in history.foods:
            day = solid_days[food.eaten_on]
            assert food.entry_method is day.entry_method

    def test_the_menu_uses_only_ingredients_with_known_groups(self) -> None:
        codes = {code for options in MENU.values() for _, recipe in options for code in recipe}
        assert codes == set(INGREDIENT_GROUPS)

    def test_the_menu_leaves_a_baseline_for_every_group(self) -> None:
        """A group present in every meal could never be compared with its absence."""
        for group in AllergenGroup:
            meals = [recipe for options in MENU.values() for _, recipe in options]
            assert any(group in groups_of(recipe) for recipe in meals), group
            assert any(group not in groups_of(recipe) for recipe in meals), group

    def test_some_patients_have_no_trigger_at_all(self) -> None:
        """They are the false-alarm check for any future food analysis."""
        counts = [len(plan(seed=seed).hidden_triggers) for seed in range(40)]
        assert 0 in counts
        assert sum(1 for c in counts if c > 0) > len(counts) / 2

    def test_planted_triggers_stand_out_from_noise_in_the_log(self) -> None:
        """The fixture is only useful for validating an analysis if its answer is
        recoverable from the logged data at all.

        Averaged across patients: a single patient's signal is weak and can be
        swamped by a co-eaten group (milk and wheat share mac and cheese), which is
        realistic and is exactly what the eventual analysis must cope with.
        """
        trigger_gaps, other_gaps = [], []
        for seed in range(40):
            history = plan(seed=seed)
            for group in AllergenGroup:
                after, otherwise = _dysphagia_rates(history, group)
                if len(after) < 20 or len(otherwise) < 20:
                    continue
                gap = statistics.fmean(after) - statistics.fmean(otherwise)
                (trigger_gaps if group in history.hidden_triggers else other_gaps).append(gap)

        assert len(trigger_gaps) >= 20
        assert statistics.fmean(trigger_gaps) > statistics.fmean(other_gaps) + 0.07

    def test_hidden_triggers_never_reach_the_database_model(self) -> None:
        """Ground truth is for tests. Nothing in the written schema can hold it."""
        from eoehelp_api.db.base import Base

        columns = {
            column.name for table in Base.metadata.tables.values() for column in table.columns
        }
        assert not any("trigger" in name for name in columns)


class TestWriting:
    async def test_a_generated_history_persists_and_scores(self, session: AsyncSession) -> None:
        """End of the loop: plan, write, and score what came back.

        Uses the real scoring service on the written rows, so this also proves the
        generator produces windows the instrument can actually score.
        """
        history = plan(seed=3, months=6)
        written = await SyntheticWriter(session).write(history)
        await session.commit()

        assert written.symptom_entries == len(history.days)
        assert written.doses == history.dose_count
        assert written.foods == len(history.foods) > 0

        ingredient_rows = (
            await session.execute(
                text("SELECT count(*) FROM food_log_item_ingredients WHERE patient_id = :pid"),
                {"pid": written.patient_id},
            )
        ).scalar_one()
        assert ingredient_rows == sum(len(food.ingredient_codes) for food in history.foods)

        entries = (
            await session.execute(
                text("SELECT count(*) FROM symptom_entries WHERE patient_id = :pid"),
                {"pid": written.patient_id},
            )
        ).scalar_one()
        assert entries == len(history.days)

        # The notes that exist are unreadable at rest.
        readable = (
            await session.execute(
                text(
                    "SELECT count(*) FROM symptom_entries "
                    "WHERE patient_id = :pid AND notes_encrypted::text LIKE '%stuck%'"
                ),
                {"pid": written.patient_id},
            )
        ).scalar_one()
        assert readable == 0

    async def test_writing_the_same_seed_twice_is_reported_not_crashed(
        self, session: AsyncSession
    ) -> None:
        """Seeds are repeatable by design, so a second run names the same patient."""
        history = plan(seed=5, months=1)
        await SyntheticWriter(session).write(history)
        await session.commit()
        with pytest.raises(SyntheticPatientExistsError, match=history.email):
            await SyntheticWriter(session).write(history)

    async def test_no_audit_rows_are_fabricated(self, session: AsyncSession) -> None:
        """The audit log records who touched a real record.

        Inventing entries would turn the one artifact that has to be trustworthy
        into a mixture of fact and fiction.
        """
        written = await SyntheticWriter(session).write(plan(seed=4, months=3))
        await session.commit()

        rows = (
            await session.execute(
                text("SELECT count(*) FROM audit_log WHERE patient_id = :pid"),
                {"pid": written.patient_id},
            )
        ).scalar_one()
        assert rows == 0


async def test_the_generators_allergen_groups_match_the_catalog(session: AsyncSession) -> None:
    """The generator keeps its own copy of part of the catalog, since it never
    reads the database. This is what stops the copy drifting."""
    rows = (
        await session.execute(
            text(
                "SELECT code, allergen_groups::text[] FROM ingredient_catalog WHERE code = ANY(:c)"
            ),
            {"c": sorted(INGREDIENT_GROUPS)},
        )
    ).all()
    catalog = {code: frozenset(AllergenGroup(g) for g in groups) for code, groups in rows}
    assert catalog == INGREDIENT_GROUPS


def _score(day: DayPlan) -> int:
    """Daily DSQ score for a plan, mirroring services.scoring for unscored days."""
    if not day.ate_solid_food:
        return 0
    points = (
        scoring.DYSPHAGIA_POINTS[day.dysphagia_severity]
        if day.dysphagia_severity is not None
        else 0
    )
    return min(points + (day.odynophagia_severity or 0), scoring.DSQ_MAX_DAILY_SCORE)
