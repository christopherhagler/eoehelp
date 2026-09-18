"""Patient-scoped access to daily symptom entries."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.core.errors import NotFoundError
from eoehelp_api.symptoms.models import SymptomEntry


class SymptomEntryRepository:
    """Every statement is filtered by one patient id.

    That id comes from the constructor, which the request layer populates from
    the verified access token — never from a path parameter or a request body.
    Patient routes are /me/*, so there is no "which patient" question available
    to answer wrongly.

    Written concrete rather than generic on purpose: this is the first clinical
    table, and a shared base class is worth extracting when the second and third
    arrive in M2, where the pattern will be visible rather than guessed at.
    """

    def __init__(self, session: AsyncSession, patient_id: uuid.UUID) -> None:
        self._session = session
        self._patient_id = patient_id

    async def get_by_date(self, entry_date: date) -> SymptomEntry | None:
        result = await self._session.execute(
            select(SymptomEntry).where(
                SymptomEntry.patient_id == self._patient_id,
                SymptomEntry.entry_date == entry_date,
            )
        )
        return result.scalar_one_or_none()

    async def require_by_date(self, entry_date: date) -> SymptomEntry:
        entry = await self.get_by_date(entry_date)
        if entry is None:
            # 404 rather than 403, always: a 403 on someone else's record would
            # confirm that the record exists, which is itself a disclosure.
            raise NotFoundError("No entry for that date.")
        return entry

    async def list_between(self, start: date, end: date) -> list[SymptomEntry]:
        result = await self._session.execute(
            select(SymptomEntry)
            .where(
                SymptomEntry.patient_id == self._patient_id,
                SymptomEntry.entry_date >= start,
                SymptomEntry.entry_date <= end,
            )
            .order_by(SymptomEntry.entry_date)
        )
        return list(result.scalars().all())

    def add(self, entry: SymptomEntry) -> None:
        if entry.patient_id != self._patient_id:
            # Unreachable through the API, and it stays that way by being an
            # error rather than a silent correction.
            raise ValueError("Refusing to write a row belonging to another patient.")
        self._session.add(entry)

    async def delete(self, entry: SymptomEntry) -> None:
        await self._session.delete(entry)
