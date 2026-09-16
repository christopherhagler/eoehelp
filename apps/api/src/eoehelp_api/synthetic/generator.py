"""Deterministic synthetic EoE histories.

Needed for four things the plan depends on: load tests, golden-file report tests,
staging seeds, and demos. Real patient data can never serve any of them.

Three properties are deliberate, and each exists because its absence has already
cost something or plainly would.

**Correlated, not random.** A chart of uniform noise tells you nothing about
whether the chart works. These histories have a shape: an untreated stretch, a PPI
that usually fails, a swallowed steroid that usually helps, adherence decaying
with time, and flares that follow the decay. That is what makes a report worth
reviewing with a clinician.

**Timezones vary, and most are not UTC.** A UTC-only fixture set hid a real bug in
which every logged dose fell outside the adherence window for anyone west of
Greenwich. Generated patients are spread across zones so that class of error
surfaces here rather than in front of a patient.

**Deterministic.** Same seed, same history, down to the notes. Golden-file tests
are worthless otherwise, and a bug found in a demo has to be reproducible.
"""

import random
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from eoehelp_api.models.enums import (
    CopingAction,
    DoseStatus,
    DysphagiaSeverity,
    EntryMethod,
    MedicationStopReason,
    SexAtBirth,
)
from eoehelp_api.services.schedules import DoseFrequency
from eoehelp_api.synthetic.plans import (
    DayPlan,
    DosePlan,
    EpochPlan,
    HistoryPlan,
    MedicationPlan,
    ProfilePlan,
)

# Deliberately weighted away from UTC. See the module docstring.
TIMEZONES = (
    "America/Los_Angeles",
    "America/Denver",
    "America/Chicago",
    "America/New_York",
    "Europe/London",
    "Europe/Berlin",
    "Asia/Kolkata",
    "Australia/Sydney",
    "Pacific/Auckland",
    "UTC",
)

FIRST_NAMES = (
    "Avery",
    "Rowan",
    "Marta",
    "Devin",
    "Priya",
    "Lena",
    "Caleb",
    "Nadia",
    "Theo",
    "Imani",
    "Jonas",
    "Sofia",
    "Ellis",
    "Reza",
    "Maeve",
    "Kofi",
)

# Free-text notes, so the encrypted column and the "notes are excluded from
# research export" path have something realistic to carry. None of it is real.
FLARE_NOTES = (
    "bread stuck again, had to leave the table",
    "chicken went down badly, drank most of a glass of water",
    "needed to bring it back up, worst in a while",
    "steak was a mistake",
    "took twenty minutes to finish a sandwich",
)
CALM_NOTES = (
    "good day, ate normally",
    "no trouble at all",
    "ate out and it was fine",
    "first easy week in a while",
)


class HistoryGenerator:
    """Plans one patient's history. Pure: no database, no clock, no network."""

    def __init__(self, *, seed: int, today: date | None = None) -> None:
        self._random = random.Random(seed)
        self._seed = seed
        self._today = today or datetime.now(UTC).date()

    def generate(self, *, months: int = 18) -> HistoryPlan:
        start = self._today - timedelta(days=round(months * 30.4))

        profile = self._profile(start)
        epochs, medications = self._treatment_course(start)
        days = self._daily_entries(epochs, start)
        medications = [self._with_doses(m, epochs) for m in medications]

        return HistoryPlan(
            # example.com, not example.invalid: the .invalid TLD is a special-use
            # domain that the email validator behind EmailStr refuses, so a seeded
            # account could not sign in through the real magic-link flow — which
            # is most of what a demo seed is for. example.com is IANA-reserved and
            # cannot reach a real inbox either.
            email=f"synthetic.{profile.display_name.lower()}.{self._seed}@example.com",
            profile=profile,
            days=days,
            medications=medications,
            epochs=epochs,
        )

    def _profile(self, start: date) -> ProfilePlan:
        rng = self._random
        # 18+ only, matching the launch gate, and skewed young because EoE is.
        birth_year = self._today.year - rng.randint(19, 58)
        # Diagnosed before the record begins, sometimes years before.
        diagnosis = start - timedelta(days=rng.randint(30, 2200))
        return ProfilePlan(
            display_name=rng.choice(FIRST_NAMES),
            birth_year=birth_year,
            sex_at_birth=rng.choice(list(SexAtBirth)),
            diagnosis_month=diagnosis.replace(day=1),
            timezone=rng.choice(TIMEZONES),
        )

    def _treatment_course(self, start: date) -> tuple[list[EpochPlan], list[MedicationPlan]]:
        """An EoE course that looks like the real thing.

        Sequenced the way guidelines and practice actually run: a PPI trial first,
        which fails for most patients with EoE, then a swallowed topical steroid,
        which usually works. Severity levels drive the daily draw below, so the
        trajectory shows up in the symptom score rather than being asserted
        separately.
        """
        rng = self._random
        epochs: list[EpochPlan] = []
        medications: list[MedicationPlan] = []

        # 1. Untreated or newly diagnosed: symptoms at their worst.
        ppi_start = start + timedelta(days=rng.randint(7, 21))
        epochs.append(
            EpochPlan(
                label="Before treatment",
                started_on=start,
                ended_on=ppi_start - timedelta(days=1),
                severity_level=3,
            )
        )

        # 2. A PPI trial. Usually ineffective in EoE, which is the clinically
        #    interesting part: the record should show the thing that did not work.
        ppi_weeks = rng.randint(8, 16)
        ppi_end = ppi_start + timedelta(weeks=ppi_weeks)
        ppi_worked = rng.random() < 0.3
        epochs.append(
            EpochPlan(
                label="Proton pump inhibitor",
                started_on=ppi_start,
                ended_on=ppi_end,
                severity_level=2 if ppi_worked else 3,
            )
        )
        medications.append(
            MedicationPlan(
                code=rng.choice(("omeprazole", "esomeprazole", "pantoprazole")),
                frequency=DoseFrequency.TWICE_DAILY,
                dose_amount=Decimal(rng.choice(("20.00", "40.00"))),
                dose_unit="mg",
                started_on=ppi_start,
                ended_on=ppi_end,
                stop_reason=(
                    MedicationStopReason.REMISSION
                    if ppi_worked
                    else MedicationStopReason.INEFFECTIVE
                ),
                prescriber_note="8 week trial, repeat endoscopy after",
            )
        )

        # 3. A swallowed topical steroid, which mostly works.
        steroid_start = ppi_end + timedelta(days=rng.randint(3, 28))
        if steroid_start < self._today:
            steroid_works = rng.random() < 0.75
            epochs.append(
                EpochPlan(
                    label="Swallowed topical steroid",
                    started_on=steroid_start,
                    ended_on=self._today,
                    severity_level=0 if steroid_works else 2,
                )
            )
            medications.append(
                MedicationPlan(
                    code=rng.choice(
                        ("budesonide_oral_suspension", "budesonide_slurry", "fluticasone_swallowed")
                    ),
                    frequency=DoseFrequency.TWICE_DAILY,
                    dose_amount=Decimal("2.00"),
                    dose_unit="mg",
                    started_on=steroid_start,
                    ended_on=None,
                    stop_reason=None,
                    prescriber_note=None,
                )
            )

            # 4. A biologic for some of the patients the steroid did not fix.
            if not steroid_works and rng.random() < 0.6:
                biologic_start = steroid_start + timedelta(weeks=rng.randint(10, 20))
                if biologic_start < self._today:
                    medications.append(
                        MedicationPlan(
                            code="dupilumab",
                            frequency=DoseFrequency.WEEKLY,
                            dose_amount=Decimal("300.00"),
                            dose_unit="mg",
                            started_on=biologic_start,
                            ended_on=None,
                            stop_reason=None,
                            prescriber_note=None,
                        )
                    )
                    epochs.append(
                        EpochPlan(
                            label="Biologic added",
                            started_on=biologic_start,
                            ended_on=self._today,
                            severity_level=1,
                        )
                    )

        return epochs, medications

    def _severity_on(self, epochs: list[EpochPlan], day: date) -> int:
        # Later epochs win, so an overlapping "biologic added" stretch supersedes
        # the steroid epoch it sits inside.
        level = 3
        for epoch in epochs:
            if epoch.started_on <= day <= epoch.ended_on:
                level = epoch.severity_level
        return level

    def _daily_entries(self, epochs: list[EpochPlan], start: date) -> list[DayPlan]:
        rng = self._random
        days: list[DayPlan] = []
        total_days = (self._today - start).days

        # Flares: a handful of bad weeks scattered through the record, so the
        # trend line has structure a clinician would ask about.
        flare_starts = sorted(
            start + timedelta(days=rng.randint(0, max(total_days - 10, 1)))
            for _ in range(rng.randint(1, 4))
        )

        for offset in range(total_days + 1):
            day = start + timedelta(days=offset)
            severity = self._severity_on(epochs, day)
            in_flare = any(f <= day <= f + timedelta(days=rng.randint(5, 12)) for f in flare_starts)
            if in_flare:
                severity = min(severity + 2, 3)

            # Engagement decays. Patients log diligently for a few weeks and then
            # less, which is exactly why the scoring code refuses to score a
            # sparsely logged window.
            logged_probability = max(0.92 - (offset / max(total_days, 1)) * 0.35, 0.5)
            if severity >= 2:
                logged_probability += 0.12  # a bad day is more memorable
            if rng.random() > min(logged_probability, 0.97):
                continue

            days.append(self._day(day, severity))

        return days

    def _day(self, day: date, severity: int) -> DayPlan:
        """One day's answers, constructed to satisfy the instrument's own rules.

        The coherence constraints live in the API's schema and in check
        constraints; a generator that produced data those would reject would be
        useless for load tests and misleading for golden files, so they are
        respected here by construction and asserted in the tests.
        """
        rng = self._random

        # Roughly one day in fourteen without solid food, more often when bad.
        skipped_solids = rng.random() < (0.12 if severity >= 2 else 0.04)
        if skipped_solids:
            return DayPlan(
                entry_date=day,
                ate_solid_food=False,
                dysphagia_occurred=None,
                dysphagia_severity=None,
                odynophagia=False,
                odynophagia_severity=None,
                coping_actions=[],
                food_impaction_er_visit=False,
                avoided_foods_today=True,
                modified_foods_today=rng.random() < 0.5,
                ate_unusually_slowly=False,
                notes=None,
                entry_method=self._entry_method(),
            )

        dysphagia_chance = (0.08, 0.3, 0.6, 0.85)[severity]
        occurred = rng.random() < dysphagia_chance

        chosen_severity: DysphagiaSeverity | None = None
        coping: list[CopingAction] = []
        er_visit = False
        if occurred:
            weights = ((70, 25, 5), (55, 35, 10), (35, 45, 20), (20, 45, 35))[severity]
            chosen_severity = rng.choices(
                [
                    DysphagiaSeverity.MILD_SLOW,
                    DysphagiaSeverity.STUCK_SELF_RESOLVED,
                    DysphagiaSeverity.STUCK_INTERVENTION,
                ],
                weights=weights,
            )[0]

            if chosen_severity is DysphagiaSeverity.MILD_SLOW:
                coping = [CopingAction.EXTRA_CHEWING]
            elif chosen_severity is DysphagiaSeverity.STUCK_SELF_RESOLVED:
                coping = [CopingAction.DRANK_LIQUID]
            else:
                coping = [CopingAction.DRANK_LIQUID, CopingAction.LEFT_TABLE]
                if rng.random() < 0.3:
                    coping.append(CopingAction.INDUCED_VOMIT)
                # A food impaction needing emergency care is rare even when bad.
                if rng.random() < 0.04:
                    coping.append(CopingAction.ER_VISIT)
                    # The API requires these two to agree.
                    er_visit = True

        pain_chance = (0.05, 0.12, 0.25, 0.4)[severity]
        pain = rng.random() < pain_chance
        pain_severity = rng.randint(1, min(severity + 1, 3)) if pain else None

        note: str | None = None
        if rng.random() < 0.12:
            note = rng.choice(FLARE_NOTES if severity >= 2 else CALM_NOTES)

        return DayPlan(
            entry_date=day,
            ate_solid_food=True,
            dysphagia_occurred=occurred,
            dysphagia_severity=chosen_severity,
            odynophagia=pain,
            odynophagia_severity=pain_severity,
            coping_actions=coping,
            food_impaction_er_visit=er_visit,
            avoided_foods_today=rng.random() < (0.5 if severity >= 2 else 0.15),
            modified_foods_today=rng.random() < (0.45 if severity >= 2 else 0.12),
            ate_unusually_slowly=rng.random() < (0.55 if severity >= 2 else 0.18),
            notes=note,
            entry_method=self._entry_method(),
        )

    def _entry_method(self) -> EntryMethod:
        # Most days are logged the same day; some are caught up later. Research
        # weights these differently, so a generator that produced only same-day
        # entries would never exercise that distinction.
        return EntryMethod.BACKFILL if self._random.random() < 0.15 else EntryMethod.SAME_DAY

    def _with_doses(self, medication: MedicationPlan, epochs: list[EpochPlan]) -> MedicationPlan:
        """Dose events with adherence that decays, as real adherence does.

        Doses are placed at the nominal schedule hours in UTC. The patient's own
        timezone is applied when writing, so a dose logged in the evening in Los
        Angeles lands on the right local day — the thing the adherence bug got
        wrong.
        """
        rng = self._random
        hours = {
            DoseFrequency.ONCE_DAILY: (9,),
            DoseFrequency.TWICE_DAILY: (9, 21),
            DoseFrequency.THREE_TIMES_DAILY: (8, 14, 20),
        }.get(medication.frequency, (9,))

        last_day = medication.ended_on or self._today
        span = max((last_day - medication.started_on).days, 1)
        doses: list[DosePlan] = []

        day = medication.started_on
        while day <= last_day:
            offset = (day - medication.started_on).days
            # Weekly and fortnightly schedules only fire on their own days.
            if medication.frequency is DoseFrequency.WEEKLY and offset % 7 != 0:
                day += timedelta(days=1)
                continue
            if medication.frequency is DoseFrequency.EVERY_TWO_WEEKS and offset % 14 != 0:
                day += timedelta(days=1)
                continue

            # Starts high, decays, and decays faster once symptoms are under
            # control — which is the real reason people stop taking things.
            adherence = 0.95 - (offset / span) * 0.3
            if self._severity_on(epochs, day) == 0:
                adherence -= 0.1

            for hour in hours:
                roll = rng.random()
                if roll > max(adherence, 0.45):
                    # A minority of misses are recorded as deliberate skips rather
                    # than simply absent, because that is a different fact.
                    if rng.random() < 0.25:
                        doses.append(
                            DosePlan(
                                taken_at=datetime.combine(day, time(hour), tzinfo=UTC),
                                status=DoseStatus.SKIPPED,
                            )
                        )
                    continue

                status = DoseStatus.DELAYED if rng.random() < 0.08 else DoseStatus.TAKEN
                jitter = rng.randint(-45, 90)
                doses.append(
                    DosePlan(
                        taken_at=datetime.combine(day, time(hour), tzinfo=UTC)
                        + timedelta(minutes=jitter),
                        status=status,
                    )
                )
            day += timedelta(days=1)

        return MedicationPlan(
            code=medication.code,
            frequency=medication.frequency,
            dose_amount=medication.dose_amount,
            dose_unit=medication.dose_unit,
            started_on=medication.started_on,
            ended_on=medication.ended_on,
            stop_reason=medication.stop_reason,
            prescriber_note=medication.prescriber_note,
            doses=doses,
        )
