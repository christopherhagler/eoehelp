"""Patient-scoped access to endoscopies and their findings."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.core.errors import NotFoundError
from eoehelp_api.models.procedures import Endoscopy


class EndoscopyRepository:
    """Same contract as the other repositories: the scope comes from the token."""

    def __init__(self, session: AsyncSession, patient_id: uuid.UUID) -> None:
        self._session = session
        self._patient_id = patient_id

    async def list_all(self) -> list[Endoscopy]:
        # Newest first: the question is "what did the last scope show".
        result = await self._session.execute(
            select(Endoscopy)
            .where(Endoscopy.patient_id == self._patient_id)
            .order_by(Endoscopy.performed_on.desc(), Endoscopy.created_at.desc())
        )
        return list(result.scalars().all())

    async def require(self, endoscopy_id: uuid.UUID) -> Endoscopy:
        result = await self._session.execute(
            select(Endoscopy).where(
                Endoscopy.id == endoscopy_id,
                Endoscopy.patient_id == self._patient_id,
            )
        )
        endoscopy = result.scalar_one_or_none()
        if endoscopy is None:
            raise NotFoundError("No such endoscopy.")
        return endoscopy

    def add(self, endoscopy: Endoscopy) -> None:
        if endoscopy.patient_id != self._patient_id:
            raise ValueError("Refusing to write a row belonging to another patient.")
        self._session.add(endoscopy)

    async def delete(self, endoscopy: Endoscopy) -> None:
        await self._session.delete(endoscopy)
