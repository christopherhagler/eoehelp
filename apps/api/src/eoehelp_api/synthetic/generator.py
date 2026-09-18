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

**Food causes symptoms, with a delay, for a hidden few.** Each patient may have
trigger groups, recorded on the plan and never in the database. Eating one raises
symptom severity for that day and the next two, which is the delayed shape EoE
reactions take. A food-symptom analysis can then be measured against a known
answer before any patient reads its output.
"""

import random
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from eoehelp_api.core.entry_dates import EntryMethod
from eoehelp_api.food.enums import AllergenGroup, Meal
from eoehelp_api.identity.enums import SexAtBirth
from eoehelp_api.medications.enums import DoseStatus, MedicationStopReason
from eoehelp_api.medications.schedules import DoseFrequency
from eoehelp_api.symptoms.enums import DysphagiaRelief
from eoehelp_api.synthetic.plans import (
    DayPlan,
    DosePlan,
    EpochPlan,
    FoodPlan,
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


# --- diet ---------------------------------------------------------------------

# The allergen groups of every catalog ingredient the menu uses. A copy of part of
# migration 0004's seed, because the generator is pure and never reads the
# database; test_synthetic checks it against the real catalog so the two cannot
# drift apart silently.
INGREDIENT_GROUPS: dict[str, frozenset[AllergenGroup]] = {
    code: frozenset(AllergenGroup(g) for g in groups)
    for code, groups in {
        "almond": ["tree_nut"],
        "apple": [],
        "avocado": [],
        "banana": [],
        "beans": [],
        "beef": [],
        "bell_pepper": [],
        "berries": [],
        "bread": ["wheat"],
        "broccoli": [],
        "butter": ["milk"],
        "carrot": [],
        "cashew": ["tree_nut"],
        "celery": [],
        "cheese": ["milk"],
        "chicken": [],
        "chili_pepper": [],
        "citrus": [],
        "corn_tortilla": [],
        "crackers": ["wheat"],
        "cucumber": [],
        "dark_chocolate": [],
        "egg": ["egg"],
        "garlic": [],
        "grapes": [],
        "honey": [],
        "hummus": ["sesame"],
        "ice_cream": ["milk"],
        "lentils": [],
        "lettuce": [],
        "mayonnaise": ["egg"],
        "melon": [],
        "milk": ["milk"],
        "oats": [],
        "olive_oil": [],
        "onion": [],
        "pasta": ["wheat"],
        "peanut_butter": ["peanut"],
        "peas": [],
        "pork": [],
        "potato": [],
        "rice": [],
        "salmon": ["fish"],
        "seeds": [],
        "shrimp": ["shellfish"],
        "soy_sauce": ["wheat", "soy"],
        "spinach": [],
        "sweet_potato": [],
        "tofu": ["soy"],
        "tomato": [],
        "tortilla_flour": ["wheat"],
        "tuna": ["fish"],
        "turkey": [],
        "yogurt": ["milk"],
    }.items()
}

# (name, ingredient codes), by meal. Ordinary food, with every elimination-diet
# group represented and a good share of meals free of all of them, so an
# unexposed baseline exists for every group.
MENU: dict[Meal, tuple[tuple[str, tuple[str, ...]], ...]] = {
    Meal.BREAKFAST: (
        ("Porridge", ("oats", "milk", "honey")),
        ("Eggs on toast", ("egg", "bread", "butter")),
        ("Yogurt and berries", ("yogurt", "berries")),
        ("Rice congee", ("rice", "chicken", "garlic")),
        ("Banana oat smoothie", ("banana", "oats", "seeds")),
        ("Tofu scramble", ("tofu", "spinach", "onion")),
    ),
    Meal.LUNCH: (
        ("Turkey sandwich", ("bread", "turkey", "lettuce", "mayonnaise")),
        ("Chicken rice bowl", ("rice", "chicken", "broccoli", "olive_oil")),
        ("Lentil soup", ("lentils", "carrot", "onion", "celery")),
        ("Tuna salad", ("tuna", "lettuce", "cucumber", "olive_oil")),
        ("Cheese quesadilla", ("tortilla_flour", "cheese", "bell_pepper")),
        ("Hummus plate", ("hummus", "cucumber", "carrot", "corn_tortilla")),
    ),
    Meal.DINNER: (
        ("Spaghetti bolognese", ("pasta", "beef", "tomato", "onion", "garlic")),
        ("Salmon with potatoes", ("salmon", "potato", "spinach", "olive_oil")),
        ("Chicken stir-fry", ("rice", "chicken", "soy_sauce", "bell_pepper", "broccoli")),
        ("Shrimp tacos", ("corn_tortilla", "shrimp", "avocado", "citrus")),
        ("Pork and sweet potato", ("pork", "sweet_potato", "peas")),
        ("Mac and cheese", ("pasta", "cheese", "milk", "butter")),
        ("Beef chili", ("beef", "beans", "tomato", "chili_pepper", "rice")),
    ),
    Meal.SNACK: (
        ("Apple and peanut butter", ("apple", "peanut_butter")),
        ("Trail mix", ("almond", "cashew", "seeds")),
        ("Crackers and cheese", ("crackers", "cheese")),
        ("Fruit", ("melon", "grapes")),
        ("Dark chocolate", ("dark_chocolate",)),
        ("Ice cream", ("ice_cream",)),
    ),
}

# How often each meal happens at all.
MEAL_PROBABILITY = {Meal.BREAKFAST: 0.85, Meal.LUNCH: 0.9, Meal.DINNER: 1.0, Meal.SNACK: 0.5}

# Weighted toward milk, then wheat, then egg and soy, which is the order these
# groups turn up as triggers in elimination-diet studies. Roughly, not precisely:
# this is a test fixture, not an epidemiological model.
TRIGGER_WEIGHTS = {
    AllergenGroup.MILK: 50,
    AllergenGroup.WHEAT: 25,
    AllergenGroup.EGG: 15,
    AllergenGroup.SOY: 10,
}

# A reaction on the day of exposure and the two days after it.
TRIGGER_LAG_DAYS = 2

# Patients partly avoid what hurts them, often without knowing why. Without this
# a common trigger like milk is eaten nearly every day and leaves no unexposed
# baseline to compare against.
TRIGGER_AVOIDANCE = 0.5

# Food is logged on most, not all, of the days symptoms are.
FOOD_LOGGED_PROBABILITY = 0.8


def groups_of(codes: tuple[str, ...]) -> frozenset[AllergenGroup]:
    return frozenset().union(*(INGREDIENT_GROUPS[code] for code in codes))


class HistoryGenerator:
    """Plans one patient's history. Pure: no database, no clock, no network."""

    def __init__(
        self, *, seed: int, today: date | None = None, now: datetime | None = None
    ) -> None:
        """`today` pins the patient's local date, for tests that need fixed
        calendars. Otherwise the history ends at `now` (default: the real clock)
        as seen from the patient's own timezone."""
        self._random = random.Random(seed)
        # The diet draws from its own stream, so what a patient eats does not
        # depend on which days they happened to log, and adding food to the
        # generator did not reshuffle everything else a seed produces.
        self._diet_random = random.Random(f"{seed}:diet")
        self._seed = seed
        # Chosen first, from its own stream, because "today" depends on it.
        self._timezone = random.Random(f"{seed}:timezone").choice(TIMEZONES)

        # The history must not run past the patient's present. Taking today in UTC
        # handed every patient west of Greenwich an entry for tomorrow each
        # evening — a day the API itself refuses to accept.
        self._local_now: datetime | None = None
        if today is None:
            self._local_now = (
                (now or datetime.now(UTC)).astimezone(ZoneInfo(self._timezone)).replace(tzinfo=None)
            )
            today = self._local_now.date()
        self._today = today

    def generate(self, *, months: int = 18) -> HistoryPlan:
        start = self._today - timedelta(days=round(months * 30.4))

        profile = self._profile(start)
        epochs, medications = self._treatment_course(start)
        triggers = self._triggers()
        eaten = self._diet(start, triggers)
        exposed = self._exposed_days(eaten, triggers)
        days = self._daily_entries(epochs, start, exposed)
        foods = self._logged_foods(days, eaten)
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
            foods=foods,
            hidden_triggers=triggers,
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
            timezone=self._timezone,
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
        # A short history can end mid-trial. Then the course is still open: an end
        # date and a stop reason in the future would be a decision not yet made,
        # and the API refuses to record one.
        ppi_ongoing = ppi_end >= self._today
        epochs.append(
            EpochPlan(
                label="Proton pump inhibitor",
                started_on=ppi_start,
                ended_on=min(ppi_end, self._today),
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
                ended_on=None if ppi_ongoing else ppi_end,
                stop_reason=(
                    None
                    if ppi_ongoing
                    else MedicationStopReason.REMISSION
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

    def _triggers(self) -> frozenset[AllergenGroup]:
        rng = self._diet_random
        # Some patients have no food trigger at all. They matter as much as the
        # rest: they are how a food analysis is checked for false alarms.
        count = rng.choices((0, 1, 2), weights=(20, 65, 15))[0]
        groups = list(TRIGGER_WEIGHTS)
        chosen: set[AllergenGroup] = set()
        while len(chosen) < count:
            chosen.add(rng.choices(groups, weights=[TRIGGER_WEIGHTS[g] for g in groups])[0])
        return frozenset(chosen)

    def _diet(
        self, start: date, triggers: frozenset[AllergenGroup]
    ) -> dict[date, list[tuple[Meal, str, tuple[str, ...]]]]:
        """What was eaten on every day of the record, logged or not.

        Every day, because exposure does not stop when logging does: a trigger
        eaten on an unlogged Tuesday still shapes Wednesday's symptoms.
        """
        rng = self._diet_random
        eaten: dict[date, list[tuple[Meal, str, tuple[str, ...]]]] = {}
        for offset in range((self._today - start).days + 1):
            day = start + timedelta(days=offset)
            meals: list[tuple[Meal, str, tuple[str, ...]]] = []
            for meal, options in MENU.items():
                if rng.random() > MEAL_PROBABILITY[meal]:
                    continue
                name, codes = rng.choice(options)
                if groups_of(codes) & triggers and rng.random() < TRIGGER_AVOIDANCE:
                    name, codes = rng.choice(options)
                meals.append((meal, name, codes))
            eaten[day] = meals
        return eaten

    def _exposed_days(
        self,
        eaten: dict[date, list[tuple[Meal, str, tuple[str, ...]]]],
        triggers: frozenset[AllergenGroup],
    ) -> set[date]:
        exposed: set[date] = set()
        for day, meals in eaten.items():
            if any(groups_of(codes) & triggers for _, _, codes in meals):
                exposed.update(day + timedelta(days=lag) for lag in range(TRIGGER_LAG_DAYS + 1))
        return exposed

    def _logged_foods(
        self,
        days: list[DayPlan],
        eaten: dict[date, list[tuple[Meal, str, tuple[str, ...]]]],
    ) -> list[FoodPlan]:
        rng = self._diet_random
        foods: list[FoodPlan] = []
        for day in days:
            if not day.ate_solid_food or rng.random() > FOOD_LOGGED_PROBABILITY:
                continue
            foods.extend(
                FoodPlan(
                    eaten_on=day.entry_date,
                    meal=meal,
                    name=name,
                    ingredient_codes=codes,
                    entry_method=day.entry_method,
                )
                for meal, name, codes in eaten[day.entry_date]
            )
        return foods

    def _daily_entries(
        self, epochs: list[EpochPlan], start: date, exposed: set[date]
    ) -> list[DayPlan]:
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
            # A trigger adds a level on top of whatever treatment has achieved,
            # which is why it stays visible even in someone doing well overall.
            if day in exposed:
                severity = min(severity + 1, 3)

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
                dysphagia_relief=None,
                odynophagia=False,
                odynophagia_severity=None,
                food_impaction_er_visit=False,
                avoided_foods_today=True,
                modified_foods_today=rng.random() < 0.5,
                ate_unusually_slowly=False,
                notes=None,
                entry_method=self._entry_method(),
            )

        dysphagia_chance = (0.08, 0.3, 0.6, 0.85)[severity]
        occurred = rng.random() < dysphagia_chance

        relief: DysphagiaRelief | None = None
        er_visit = False
        if occurred:
            # Most episodes clear on their own or with a drink; vomiting and
            # medical attention are the tail, and grow with severity.
            weights = (
                (70, 25, 4, 1, 0),
                (50, 38, 8, 3, 1),
                (30, 45, 14, 8, 3),
                (18, 44, 18, 14, 6),
            )[severity]
            relief = rng.choices(list(DysphagiaRelief), weights=weights)[0]
            # Most medical attention for stuck food is an emergency visit.
            er_visit = relief is DysphagiaRelief.SOUGHT_MEDICAL_ATTENTION and rng.random() < 0.7

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
            dysphagia_relief=relief,
            odynophagia=pain,
            odynophagia_severity=pain_severity,
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

        last_day = min(medication.ended_on or self._today, self._today)
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
                # This evening's dose has not happened yet if it is still
                # afternoon, and neither has a decision to skip it.
                nominal = datetime.combine(day, time(hour))
                if self._local_now is not None and nominal > self._local_now:
                    continue
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
                taken_at = nominal + timedelta(minutes=jitter)
                if self._local_now is not None and taken_at > self._local_now:
                    continue
                doses.append(DosePlan(taken_at=taken_at.replace(tzinfo=UTC), status=status))
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
