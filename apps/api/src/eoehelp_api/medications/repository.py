"""Access to the patient's medications and dose events, and the medication catalog."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.core.errors import NotFoundError
from eoehelp_api.medications.models import Medication, MedicationCatalogEntry, MedicationDose


async def catalog_entries(session: AsyncSession) -> list[MedicationCatalogEntry]:
    """The medication catalog, grouped by drug class. Reference data: no patient scope."""
    result = await session.execute(
        select(MedicationCatalogEntry).order_by(
            MedicationCatalogEntry.drug_class, MedicationCatalogEntry.generic_name
        )
    )
    return list(result.scalars())


class MedicationRepository:
    """Every statement is filtered by the patient id from the verified token.

    Same contract as SymptomEntryRepository: the scope arrives through the
    constructor, never from a path or body, so there is no code path in which the
    filter can be omitted.
    """

    def __init__(self, session: AsyncSession, patient_id: uuid.UUID) -> None:
        self._session = session
        self._patient_id = patient_id

    async def list_medications(self, *, include_ended: bool = True) -> list[Medication]:
        statement = select(Medication).where(Medication.patient_id == self._patient_id)
        if not include_ended:
            statement = statement.where(Medication.ended_on.is_(None))
        # Active first, then most recently started: the list is read to answer
        # "what am I on now", not to browse history.
        result = await self._session.execute(
            statement.order_by(Medication.ended_on.is_(None).desc(), Medication.started_on.desc())
        )
        return list(result.unique().scalars().all())

    async def require_medication(self, medication_id: uuid.UUID) -> Medication:
        result = await self._session.execute(
            select(Medication).where(
                Medication.id == medication_id,
                Medication.patient_id == self._patient_id,
            )
        )
        medication = result.unique().scalar_one_or_none()
        if medication is None:
            # 404 rather than 403: confirming the row exists would disclose that
            # someone else is taking something.
            raise NotFoundError("No such medication.")
        return medication

    def add_medication(self, medication: Medication) -> None:
        if medication.patient_id != self._patient_id:
            raise ValueError("Refusing to write a row belonging to another patient.")
        self._session.add(medication)

    async def delete_medication(self, medication: Medication) -> None:
        await self._session.delete(medication)

    async def count_doses(self, medication_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(MedicationDose.id).where(
                MedicationDose.patient_id == self._patient_id,
                MedicationDose.medication_id == medication_id,
            )
        )
        return len(result.scalars().all())

    async def list_doses_between(self, start: datetime, end: datetime) -> list[MedicationDose]:
        result = await self._session.execute(
            select(MedicationDose)
            .where(
                MedicationDose.patient_id == self._patient_id,
                MedicationDose.taken_at >= start,
                MedicationDose.taken_at <= end,
            )
            .order_by(MedicationDose.taken_at)
        )
        return list(result.scalars().all())

    def add_dose(self, dose: MedicationDose) -> None:
        if dose.patient_id != self._patient_id:
            raise ValueError("Refusing to write a row belonging to another patient.")
        self._session.add(dose)

    async def require_dose(self, dose_id: uuid.UUID) -> MedicationDose:
        result = await self._session.execute(
            select(MedicationDose).where(
                MedicationDose.id == dose_id,
                MedicationDose.patient_id == self._patient_id,
            )
        )
        dose = result.scalar_one_or_none()
        if dose is None:
            raise NotFoundError("No such dose.")
        return dose

    async def delete_dose(self, dose: MedicationDose) -> None:
        await self._session.delete(dose)
