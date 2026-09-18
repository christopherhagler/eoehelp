"""Medications and dose logging.

The dose-taking path is the one a patient touches daily, so it is deliberately
the cheapest call in the API: a POST with no body records "took it, now". Every
other operation here is occasional.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api import audit
from eoehelp_api.audit.service import AuditContext
from eoehelp_api.core import entry_dates
from eoehelp_api.core.errors import BadRequestError, ConflictError, NotFoundError
from eoehelp_api.core.security import FieldCipher
from eoehelp_api.identity.patient import Patient
from eoehelp_api.medications import adherence, schedules
from eoehelp_api.medications.adherence import MedicationAdherence
from eoehelp_api.medications.enums import DoseStatus
from eoehelp_api.medications.models import Medication, MedicationCatalogEntry, MedicationDose
from eoehelp_api.medications.repository import MedicationRepository
from eoehelp_api.medications.schedules import DoseFrequency
from eoehelp_api.medications.schemas import (
    DoseCreate,
    DoseRead,
    MedicationCreate,
    MedicationRead,
    MedicationStop,
    MedicationTodayItem,
)

# A dose cannot be logged further back than this. Same reasoning as the symptom
# backfill window: beyond a week it is recall, and a gap is more honest than a
# guess that adherence arithmetic will then treat as fact.
MAX_DOSE_BACKFILL_DAYS = 7

# Long enough for a course of swallowed steroids and any realistic history, short
# enough that a typo of 20026 is caught rather than stored.
MAX_MEDICATION_HISTORY_DAYS = 365 * 30


@dataclass(frozen=True)
class AdherenceRow:
    """Adherence joined to what the patient would recognise it as."""

    medication: Medication
    result: MedicationAdherence


class MedicationService:
    def __init__(self, session: AsyncSession, patient: Patient) -> None:
        self._session = session
        self._patient = patient
        self._repo = MedicationRepository(session, patient.id)
        self._cipher = FieldCipher.from_settings()
        self._zone = ZoneInfo(patient.timezone)

    @property
    def today(self) -> date:
        return entry_dates.patient_today(self._patient.timezone)

    def _day_bounds(self, day: date) -> tuple[datetime, datetime]:
        """The patient's calendar day as an absolute instant range.

        Computed in their timezone, not the server's: otherwise a dose taken at
        9pm in Los Angeles counts toward the following day, and both the daily
        view and the adherence denominator drift by one.
        """
        start = datetime.combine(day, time.min, tzinfo=self._zone)
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=self._zone)
        return start, end - timedelta(microseconds=1)

    async def add(
        self, *, payload: MedicationCreate, context: AuditContext | None = None
    ) -> MedicationRead:
        catalog = await self._session.get(MedicationCatalogEntry, payload.medication_code)
        if catalog is None:
            raise NotFoundError("Unknown medication.")

        today = self.today
        if payload.started_on > today:
            raise BadRequestError("A medication cannot start in the future.")
        if payload.started_on < today - timedelta(days=MAX_MEDICATION_HISTORY_DAYS):
            raise BadRequestError("That start date looks like a typo.")

        # Minted before the insert: it is the additional authenticated data for the
        # prescriber note's ciphertext, so it has to exist first.
        medication = Medication(
            id=uuid.uuid4(),
            patient_id=self._patient.id,
            medication_code=payload.medication_code,
            dose_amount=payload.dose_amount,
            dose_unit=payload.dose_unit or catalog.default_unit,
            schedule_rrule=schedules.rrule_for(payload.frequency),
            started_on=payload.started_on,
        )
        medication.prescriber_note_encrypted = self._cipher.encrypt(
            payload.prescriber_note, aad=str(medication.id)
        )
        self._repo.add_medication(medication)
        await self._session.flush()

        await audit.record(
            self._session,
            action="medication.create",
            resource_type="medication",
            resource_id=medication.id,
            patient_id=self._patient.id,
            context=context,
            metadata={
                # The medication name is clinical but not identifying, and knowing
                # which drug a change concerned is the point of the trail.
                "medication_code": payload.medication_code,
                "frequency": payload.frequency.value,
                "has_prescriber_note": payload.prescriber_note is not None,
            },
        )
        return self.to_read(medication, catalog)

    async def stop(
        self,
        *,
        medication_id: uuid.UUID,
        payload: MedicationStop,
        context: AuditContext | None = None,
    ) -> MedicationRead:
        medication = await self._repo.require_medication(medication_id)
        if medication.ended_on is not None:
            raise ConflictError("That medication has already been stopped.")
        if payload.ended_on < medication.started_on:
            raise BadRequestError("A medication cannot end before it started.")
        if payload.ended_on > self.today:
            raise BadRequestError("An end date cannot be in the future.")

        medication.ended_on = payload.ended_on
        medication.stop_reason = payload.stop_reason
        await self._session.flush()

        await audit.record(
            self._session,
            action="medication.stop",
            resource_type="medication",
            resource_id=medication.id,
            patient_id=self._patient.id,
            context=context,
            metadata={
                "medication_code": medication.medication_code,
                "stop_reason": payload.stop_reason.value,
            },
        )
        return self.to_read(medication)

    async def remove(
        self, *, medication_id: uuid.UUID, context: AuditContext | None = None
    ) -> None:
        """Delete a course entered by mistake.

        Refused once doses exist, because at that point it is history rather than a
        typo, and deleting it would silently remove the treatment a symptom trend
        was recorded against. Stopping it is the correct action, and the error says
        so.
        """
        medication = await self._repo.require_medication(medication_id)
        if await self._repo.count_doses(medication_id) > 0:
            raise ConflictError(
                "Doses have been logged against this medication, so it is part of "
                "your history. Stop it instead of deleting it."
            )

        await self._repo.delete_medication(medication)
        await self._session.flush()
        await audit.record(
            self._session,
            action="medication.delete",
            resource_type="medication",
            resource_id=medication_id,
            patient_id=self._patient.id,
            context=context,
            metadata={"medication_code": medication.medication_code},
        )

    # Named list_medications, not list: a method called `list` shadows the builtin
    # for the rest of the class body, so a later annotation like
    # `list[MedicationTodayItem]` resolves to the method and fails at import.
    async def list_medications(
        self, *, include_ended: bool = True, context: AuditContext | None = None
    ) -> list[MedicationRead]:
        medications = await self._repo.list_medications(include_ended=include_ended)
        await audit.record(
            self._session,
            action="medication.list",
            resource_type="medication",
            patient_id=self._patient.id,
            context=context,
            metadata={"returned": len(medications), "include_ended": include_ended},
        )
        return [self.to_read(m) for m in medications]

    async def log_dose(
        self,
        *,
        medication_id: uuid.UUID,
        payload: DoseCreate,
        context: AuditContext | None = None,
    ) -> DoseRead:
        medication = await self._repo.require_medication(medication_id)
        taken_at = payload.taken_at or datetime.now(UTC)
        if taken_at.tzinfo is None:
            # A naive timestamp is ambiguous, and guessing UTC would silently shift
            # the dose by up to a day. Read it as the patient's own wall clock.
            taken_at = taken_at.replace(tzinfo=self._zone)

        day = taken_at.astimezone(self._zone).date()
        if day > self.today:
            raise BadRequestError("A dose cannot be logged for the future.")
        if day < self.today - timedelta(days=MAX_DOSE_BACKFILL_DAYS):
            raise BadRequestError(f"Doses can be logged up to {MAX_DOSE_BACKFILL_DAYS} days late.")
        if day < medication.started_on:
            raise BadRequestError("That is before this medication started.")
        if medication.ended_on is not None and day > medication.ended_on:
            raise BadRequestError("That is after this medication was stopped.")

        dose = MedicationDose(
            id=uuid.uuid4(),
            patient_id=self._patient.id,
            medication_id=medication.id,
            taken_at=taken_at,
            status=payload.status,
        )
        self._repo.add_dose(dose)
        await self._session.flush()

        await audit.record(
            self._session,
            action="medication_dose.create",
            resource_type="medication_dose",
            resource_id=dose.id,
            patient_id=self._patient.id,
            context=context,
            metadata={
                "medication_code": medication.medication_code,
                "status": payload.status.value,
                "on_date": day.isoformat(),
            },
        )
        return DoseRead.model_validate(dose)

    async def undo_dose(self, *, dose_id: uuid.UUID, context: AuditContext | None = None) -> None:
        """Remove a dose event.

        The antidote to a mistaken tap. Deleting rather than flagging, because a
        dose that was never taken is not history — but the audit row recording the
        deletion is.
        """
        dose = await self._repo.require_dose(dose_id)
        medication_id = dose.medication_id
        await self._repo.delete_dose(dose)
        await self._session.flush()
        await audit.record(
            self._session,
            action="medication_dose.delete",
            resource_type="medication_dose",
            resource_id=dose_id,
            patient_id=self._patient.id,
            context=context,
            metadata={"medication_id": str(medication_id)},
        )

    async def today_view(
        self, *, on_date: date | None = None
    ) -> tuple[date, list[MedicationTodayItem]]:
        """Active medications with what today expects and what has been logged.

        Drives the chips on the daily log, so it answers both halves in one call:
        a patient needs to see that the evening dose is still outstanding, and
        needs the dose ids to undo a mistaken tap.
        """
        day = on_date or self.today
        medications = await self._repo.list_medications(include_ended=False)
        start, end = self._day_bounds(day)
        doses = await self._repo.list_doses_between(start, end)

        items = [
            MedicationTodayItem(
                medication_id=medication.id,
                medication_code=medication.medication_code,
                generic_name=medication.catalog.generic_name,
                dose_label=self._dose_label(medication),
                frequency=schedules.frequency_of(medication.schedule_rrule),
                expected_today=schedules.expected_doses(
                    rrule=medication.schedule_rrule,
                    started_on=medication.started_on,
                    ended_on=medication.ended_on,
                    window_start=day,
                    window_end=day,
                ),
                doses_today=[
                    DoseRead.model_validate(d) for d in doses if d.medication_id == medication.id
                ],
            )
            for medication in medications
            # A course that starts tomorrow is not actionable today.
            if medication.started_on <= day
        ]
        return day, items

    async def adherence(
        self, *, window_start: date, window_end: date, include_ended: bool = True
    ) -> list[AdherenceRow]:
        if window_end < window_start:
            raise BadRequestError("The range ends before it starts.")
        medications = await self._repo.list_medications(include_ended=include_ended)
        start, _ = self._day_bounds(window_start)
        _, end = self._day_bounds(window_end)
        doses = await self._repo.list_doses_between(start, end)

        results = adherence.adherence_summary(
            medications,
            doses,
            window_start=window_start,
            window_end=window_end,
            # The window is a range of the patient's calendar days, so the doses
            # have to be bucketed in their timezone too.
            tz=self._zone,
        )
        return [
            AdherenceRow(medication=medication, result=result)
            for medication, result in zip(medications, results, strict=True)
        ]

    @staticmethod
    def _dose_label(medication: Medication) -> str | None:
        if medication.dose_amount is None:
            return None
        amount = medication.dose_amount.normalize()
        if medication.dose_unit:
            return f"{amount:f} {medication.dose_unit}"
        return f"{amount:f}"

    def to_read(
        self, medication: Medication, catalog: MedicationCatalogEntry | None = None
    ) -> MedicationRead:
        entry = catalog or medication.catalog
        return MedicationRead(
            id=medication.id,
            medication_code=medication.medication_code,
            generic_name=entry.generic_name,
            drug_class=entry.drug_class,
            dose_amount=medication.dose_amount,
            dose_unit=medication.dose_unit,
            frequency=schedules.frequency_of(medication.schedule_rrule),
            started_on=medication.started_on,
            ended_on=medication.ended_on,
            stop_reason=medication.stop_reason,
            prescriber_note=self._cipher.decrypt(
                medication.prescriber_note_encrypted, aad=str(medication.id)
            ),
            is_active=medication.is_active,
        )


__all__ = ["AdherenceRow", "DoseFrequency", "DoseStatus", "MedicationService"]
