"""Adherence arithmetic, against hand-counted expectations.

Pure unit tests. The denominator is the whole difficulty here: without it a
fortnightly injection and a twice-daily pill are indistinguishable, and a report
that conflated them would send a clinician the wrong way.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from eoehelp_api.models.enums import DoseStatus
from eoehelp_api.models.medication import Medication, MedicationDose
from eoehelp_api.services import adherence, schedules
from eoehelp_api.services.schedules import DoseFrequency

START = date(2026, 9, 1)
WINDOW_END = date(2026, 9, 14)  # a 14-day window, 1st to 14th inclusive


def medication(
    frequency: DoseFrequency,
    *,
    started_on: date = START,
    ended_on: date | None = None,
) -> Medication:
    return Medication(
        id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        medication_code="omeprazole",
        schedule_rrule=schedules.rrule_for(frequency),
        started_on=started_on,
        ended_on=ended_on,
    )


def doses(
    med: Medication, days: list[int], *, status: DoseStatus = DoseStatus.TAKEN
) -> list[MedicationDose]:
    """One dose on each offset from START, at midday to stay clear of boundaries."""
    return [
        MedicationDose(
            id=uuid.uuid4(),
            patient_id=med.patient_id,
            medication_id=med.id,
            taken_at=datetime.combine(START + timedelta(days=d), time(12, 0), tzinfo=UTC),
            status=status,
        )
        for d in days
    ]


class TestExpectedDoses:
    @pytest.mark.parametrize(
        ("frequency", "expected"),
        [
            (DoseFrequency.ONCE_DAILY, 14),
            (DoseFrequency.TWICE_DAILY, 28),
            (DoseFrequency.THREE_TIMES_DAILY, 42),
            # 1st, 3rd, 5th, 7th, 9th, 11th, 13th — the 15th is outside.
            (DoseFrequency.EVERY_OTHER_DAY, 7),
            (DoseFrequency.WEEKLY, 2),  # 1st and 8th
            (DoseFrequency.EVERY_TWO_WEEKS, 1),  # 1st only; the next is the 15th
            (DoseFrequency.EVERY_FOUR_WEEKS, 1),
        ],
    )
    def test_each_frequency_counts_correctly_over_a_fortnight(
        self, frequency: DoseFrequency, expected: int
    ) -> None:
        assert (
            schedules.expected_doses(
                rrule=schedules.rrule_for(frequency),
                started_on=START,
                ended_on=None,
                window_start=START,
                window_end=WINDOW_END,
            )
            == expected
        )

    def test_as_needed_has_no_expectation(self) -> None:
        assert schedules.rrule_for(DoseFrequency.AS_NEEDED) is None
        assert (
            schedules.expected_doses(
                rrule=None,
                started_on=START,
                ended_on=None,
                window_start=START,
                window_end=WINDOW_END,
            )
            is None
        )

    def test_the_expectation_starts_when_the_medication_does(self) -> None:
        """A drug started on the 8th is not owed doses from the 1st."""
        assert (
            schedules.expected_doses(
                rrule=schedules.rrule_for(DoseFrequency.ONCE_DAILY),
                started_on=date(2026, 9, 8),
                ended_on=None,
                window_start=START,
                window_end=WINDOW_END,
            )
            == 7
        )

    def test_a_stopped_medication_stops_accruing_missed_doses(self) -> None:
        assert (
            schedules.expected_doses(
                rrule=schedules.rrule_for(DoseFrequency.ONCE_DAILY),
                started_on=START,
                ended_on=date(2026, 9, 5),
                window_start=START,
                window_end=WINDOW_END,
            )
            == 5
        )

    def test_a_window_before_the_course_expects_nothing(self) -> None:
        assert (
            schedules.expected_doses(
                rrule=schedules.rrule_for(DoseFrequency.ONCE_DAILY),
                started_on=date(2026, 10, 1),
                ended_on=None,
                window_start=START,
                window_end=WINDOW_END,
            )
            == 0
        )

    def test_every_other_day_is_phased_from_the_start_not_the_window(self) -> None:
        """The recurrence has to be anchored to the course.

        Phased from the window instead, an alternate-day rule lands on the wrong
        days and the count silently shifts.
        """
        count = schedules.expected_doses(
            rrule=schedules.rrule_for(DoseFrequency.EVERY_OTHER_DAY),
            started_on=date(2026, 8, 31),  # odd phase relative to September
            ended_on=None,
            window_start=START,
            window_end=WINDOW_END,
        )
        # 31 Aug, then 2nd, 4th, 6th, 8th, 10th, 12th, 14th inside the window.
        assert count == 7

    def test_frequency_round_trips_through_the_stored_rule(self) -> None:
        for frequency in DoseFrequency:
            assert schedules.frequency_of(schedules.rrule_for(frequency)) is frequency

    def test_an_unrecognised_rule_is_not_mislabelled(self) -> None:
        """A future custom schedule degrades to "cannot name this" rather than
        being reported as a frequency it is not."""
        assert schedules.frequency_of("FREQ=MONTHLY;BYMONTHDAY=1") is None


class TestAdherence:
    def test_a_fortnightly_injection_is_not_judged_like_a_twice_daily_pill(self) -> None:
        """The failure this whole module exists to prevent.

        Two logged doses is complete adherence for dupilumab and almost nothing
        for a PPI. Counting doses alone cannot tell them apart.
        """
        injection = medication(DoseFrequency.EVERY_TWO_WEEKS)
        pill = medication(DoseFrequency.TWICE_DAILY)

        injection_result = adherence.adherence_for(
            injection, doses(injection, [0]), window_start=START, window_end=WINDOW_END, tz=UTC
        )
        pill_result = adherence.adherence_for(
            pill, doses(pill, [0]), window_start=START, window_end=WINDOW_END, tz=UTC
        )

        assert injection_result.expected_doses == 1
        assert injection_result.percentage == 100.0
        assert pill_result.expected_doses == 28
        assert pill_result.percentage == 3.6  # 1/28

    def test_partial_adherence_is_a_plain_ratio(self) -> None:
        med = medication(DoseFrequency.ONCE_DAILY)
        result = adherence.adherence_for(
            med, doses(med, list(range(7))), window_start=START, window_end=WINDOW_END, tz=UTC
        )
        assert result.expected_doses == 14
        assert result.taken_doses == 7
        assert result.percentage == 50.0

    def test_a_delayed_dose_still_counts_as_taken(self) -> None:
        """Punishing honesty would teach patients to stop recording detail."""
        med = medication(DoseFrequency.ONCE_DAILY)
        late = doses(med, list(range(14)), status=DoseStatus.DELAYED)
        result = adherence.adherence_for(
            med, late, window_start=START, window_end=WINDOW_END, tz=UTC
        )
        assert result.percentage == 100.0

    def test_a_skipped_dose_is_counted_separately_not_as_taken(self) -> None:
        med = medication(DoseFrequency.ONCE_DAILY)
        mixed = doses(med, list(range(7))) + doses(
            med, list(range(7, 14)), status=DoseStatus.SKIPPED
        )
        result = adherence.adherence_for(
            med, mixed, window_start=START, window_end=WINDOW_END, tz=UTC
        )
        assert result.taken_doses == 7
        assert result.skipped_doses == 7
        assert result.percentage == 50.0

    def test_as_needed_reports_unknown_rather_than_perfect(self) -> None:
        """Null, not 100%: there was no expectation to meet, and claiming full
        adherence would be an invented fact about a patient's treatment."""
        med = medication(DoseFrequency.AS_NEEDED)
        result = adherence.adherence_for(
            med, doses(med, [0, 3]), window_start=START, window_end=WINDOW_END, tz=UTC
        )
        assert result.expected_doses is None
        assert result.percentage is None
        assert result.is_measurable is False
        assert result.taken_doses == 2

    def test_extra_doses_do_not_exceed_one_hundred_percent(self) -> None:
        # 130% adherence is a number no clinician can act on; the extra dose is a
        # logging artifact.
        med = medication(DoseFrequency.WEEKLY)
        result = adherence.adherence_for(
            med, doses(med, [0, 1, 2, 3]), window_start=START, window_end=WINDOW_END, tz=UTC
        )
        assert result.expected_doses == 2
        assert result.percentage == 100.0

    def test_doses_outside_the_window_are_ignored(self) -> None:
        med = medication(DoseFrequency.ONCE_DAILY)
        result = adherence.adherence_for(
            med, doses(med, [20, 21]), window_start=START, window_end=WINDOW_END, tz=UTC
        )
        assert result.taken_doses == 0

    def test_another_medications_doses_are_not_counted(self) -> None:
        ppi = medication(DoseFrequency.ONCE_DAILY)
        steroid = medication(DoseFrequency.ONCE_DAILY)
        result = adherence.adherence_for(
            ppi, doses(steroid, list(range(14))), window_start=START, window_end=WINDOW_END, tz=UTC
        )
        assert result.taken_doses == 0


class TestTimezoneBucketing:
    """A dose belongs to the day it was taken *where the patient is*.

    Found by running the flow end to end as a Los Angeles patient rather than the
    UTC one every test used: every dose was logged and adherence reported 0%,
    because an evening in Los Angeles is already tomorrow in UTC and the filter
    read the timestamp in UTC. Both directions are pinned here.
    """

    LA = ZoneInfo("America/Los_Angeles")
    AUCKLAND = ZoneInfo("Pacific/Auckland")

    def test_an_evening_dose_west_of_utc_counts_on_the_local_day(self) -> None:
        # 03:30 UTC on the 2nd is 20:30 on the 1st in Los Angeles.
        med = medication(DoseFrequency.ONCE_DAILY, started_on=date(2026, 9, 1))
        dose = MedicationDose(
            id=uuid.uuid4(),
            patient_id=med.patient_id,
            medication_id=med.id,
            taken_at=datetime(2026, 9, 2, 3, 30, tzinfo=UTC),
            status=DoseStatus.TAKEN,
        )

        local = adherence.adherence_for(
            med,
            [dose],
            window_start=date(2026, 9, 1),
            window_end=date(2026, 9, 1),
            tz=self.LA,
        )
        assert local.taken_doses == 1
        assert local.percentage == 100.0

        # Read in UTC the same dose falls outside the window entirely — which is
        # exactly the bug, preserved here so it cannot come back unnoticed.
        in_utc = adherence.adherence_for(
            med,
            [dose],
            window_start=date(2026, 9, 1),
            window_end=date(2026, 9, 1),
            tz=UTC,
        )
        assert in_utc.taken_doses == 0

    def test_a_morning_dose_east_of_utc_counts_on_the_local_day(self) -> None:
        # 22:00 UTC on the 1st is 10:00 on the 2nd in Auckland.
        med = medication(DoseFrequency.ONCE_DAILY, started_on=date(2026, 9, 1))
        dose = MedicationDose(
            id=uuid.uuid4(),
            patient_id=med.patient_id,
            medication_id=med.id,
            taken_at=datetime(2026, 9, 1, 22, 0, tzinfo=UTC),
            status=DoseStatus.TAKEN,
        )

        result = adherence.adherence_for(
            med,
            [dose],
            window_start=date(2026, 9, 2),
            window_end=date(2026, 9, 2),
            tz=self.AUCKLAND,
        )
        assert result.taken_doses == 1
