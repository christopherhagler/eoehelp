"""The synthetic data generator.

Mostly pure tests, because the point of splitting planning from writing was to
make the properties that matter assertable without a database.
"""

import statistics
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.config import Settings
from eoehelp_api.models.enums import DoseStatus, EntryMethod
from eoehelp_api.schemas.auth import MagicLinkRequest
from eoehelp_api.schemas.symptoms import SymptomEntryInput
from eoehelp_api.services import scoring
from eoehelp_api.synthetic import HistoryGenerator, SyntheticDataRefusedError, assert_writable
from eoehelp_api.synthetic.plans import DayPlan, HistoryPlan
from eoehelp_api.synthetic.writer import SyntheticWriter

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
