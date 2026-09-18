"""Adherence: doses taken against doses the schedule expected.

Percentage-of-logged-doses is meaningless without a denominator, and the
denominator is the whole difficulty. A patient on fortnightly dupilumab who
logged both injections in a month is perfectly adherent; a patient on a
twice-daily PPI who logged two doses in a month has taken 3% of them. Counting
doses alone cannot tell those apart, and a report that conflated them would
mislead a clinician into the wrong next step.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, tzinfo

from eoehelp_api.medications import schedules
from eoehelp_api.medications.enums import DoseStatus
from eoehelp_api.medications.models import Medication, MedicationDose


@dataclass(frozen=True)
class MedicationAdherence:
    """Adherence for one medication over one window.

    `percentage` is None when there is nothing to measure against — an as-needed
    medication, or a window entirely outside the course. None reads as "unknown"
    in the API and on the report; it is never rendered as zero, which would look
    like a patient ignoring their treatment.
    """

    medication_id: str
    window_start: date
    window_end: date
    expected_doses: int | None
    taken_doses: int
    skipped_doses: int
    percentage: float | None

    @property
    def is_measurable(self) -> bool:
        return self.percentage is not None


def adherence_for(
    medication: Medication,
    doses: Iterable[MedicationDose],
    *,
    window_start: date,
    window_end: date,
    tz: tzinfo,
) -> MedicationAdherence:
    """Adherence for one medication over a window of the patient's own days.

    `tz` is required rather than defaulting to UTC, because a default is how this
    silently breaks. Dose timestamps are stored as absolute instants, and the
    window is a range of *calendar days* — which day an instant belongs to depends
    entirely on the timezone it is read in. A dose taken at 8pm in Los Angeles is
    already tomorrow in UTC, so reading it in UTC drops it from today's window and
    reports 0% adherence for a patient who took everything.
    """
    relevant = [d for d in doses if d.medication_id == medication.id]
    in_window = [
        d for d in relevant if window_start <= d.taken_at.astimezone(tz).date() <= window_end
    ]

    taken = sum(1 for d in in_window if d.status is DoseStatus.TAKEN)
    # A delayed dose was taken, late. Counting it as a miss would punish honesty,
    # and patients who feel punished for detail stop recording it.
    taken += sum(1 for d in in_window if d.status is DoseStatus.DELAYED)
    skipped = sum(1 for d in in_window if d.status is DoseStatus.SKIPPED)

    expected = schedules.expected_doses(
        rrule=medication.schedule_rrule,
        started_on=medication.started_on,
        ended_on=medication.ended_on,
        window_start=window_start,
        window_end=window_end,
    )

    percentage: float | None = None
    if expected is not None and expected > 0:
        # Capped at 100: an extra logged dose is a logging artifact, and 130%
        # adherence is a number no clinician can act on.
        percentage = round(min(taken / expected, 1.0) * 100, 1)

    return MedicationAdherence(
        medication_id=str(medication.id),
        window_start=window_start,
        window_end=window_end,
        expected_doses=expected,
        taken_doses=taken,
        skipped_doses=skipped,
        percentage=percentage,
    )


def adherence_summary(
    medications: Sequence[Medication],
    doses: Sequence[MedicationDose],
    *,
    window_start: date,
    window_end: date,
    tz: tzinfo,
) -> list[MedicationAdherence]:
    return [
        adherence_for(m, doses, window_start=window_start, window_end=window_end, tz=tz)
        for m in medications
    ]
