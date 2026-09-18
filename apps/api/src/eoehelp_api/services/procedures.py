"""Endoscopy records.

Unlike the daily logs there is no backfill window: these are entered from
reports, often years after the procedure, and the report is the source rather
than the patient's memory. The date still has to be plausible — not in the
future, and not before the patient was born.
"""

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.core.errors import BadRequestError
from eoehelp_api.core.security import FieldCipher
from eoehelp_api.models.enums import EosComparator
from eoehelp_api.models.patient import Patient
from eoehelp_api.models.procedures import Biopsy, Dilation, Endoscopy
from eoehelp_api.repositories.procedures import EndoscopyRepository
from eoehelp_api.schemas.procedures import (
    BiopsyRead,
    DilationRead,
    EndoscopyInput,
    EndoscopyRead,
    ErefsRead,
    PeakCount,
)
from eoehelp_api.services import audit, erefs
from eoehelp_api.services.audit import AuditContext

# Before this, no patient on this platform had an endoscopy worth recording, and a
# year like 0202 is a typo rather than history.
EARLIEST_PROCEDURE = date(1950, 1, 1)

# When two sites report the same number, ">50" says more than "50", which says
# more than "<50".
_COMPARATOR_RANK = {
    EosComparator.LESS_THAN: 0,
    EosComparator.EXACT: 1,
    EosComparator.GREATER_THAN: 2,
}


def _facility_aad(endoscopy_id: uuid.UUID) -> str:
    return f"{endoscopy_id}:facility"


def _notes_aad(endoscopy_id: uuid.UUID) -> str:
    return f"{endoscopy_id}:notes"


class EndoscopyService:
    def __init__(self, session: AsyncSession, patient: Patient) -> None:
        self._session = session
        self._patient = patient
        self._repo = EndoscopyRepository(session, patient.id)
        self._cipher = FieldCipher.from_settings()

    @property
    def today(self) -> date:
        return datetime.now(ZoneInfo(self._patient.timezone)).date()

    def _validate_date(self, performed_on: date) -> None:
        if performed_on > self.today:
            raise BadRequestError("That date has not happened yet in your timezone.")
        earliest = EARLIEST_PROCEDURE
        if self._patient.birth_year is not None:
            earliest = max(earliest, date(self._patient.birth_year, 1, 1))
        if performed_on < earliest:
            raise BadRequestError("That date is before you were born.")

    # --- writes ---------------------------------------------------------------

    async def create(
        self, *, payload: EndoscopyInput, context: AuditContext | None = None
    ) -> EndoscopyRead:
        self._validate_date(payload.performed_on)
        endoscopy = Endoscopy(id=uuid.uuid4(), patient_id=self._patient.id)
        self._apply(endoscopy, payload)
        self._repo.add(endoscopy)
        await self._session.flush()
        await self._session.refresh(endoscopy)
        await self._audit("endoscopy.create", endoscopy, payload, context)
        return self.to_read(endoscopy)

    async def update(
        self,
        *,
        endoscopy_id: uuid.UUID,
        payload: EndoscopyInput,
        context: AuditContext | None = None,
    ) -> EndoscopyRead:
        endoscopy = await self._repo.require(endoscopy_id)
        self._validate_date(payload.performed_on)

        # Remove the old findings and flush before adding the new ones: the unit
        # of work inserts before it deletes, and the per-site and per-procedure
        # unique constraints would otherwise see both at once.
        endoscopy.biopsies.clear()
        endoscopy.dilation = None
        await self._session.flush()

        self._apply(endoscopy, payload)
        await self._session.flush()
        await self._session.refresh(endoscopy)
        await self._audit("endoscopy.update", endoscopy, payload, context)
        return self.to_read(endoscopy)

    async def delete(self, *, endoscopy_id: uuid.UUID, context: AuditContext | None = None) -> None:
        endoscopy = await self._repo.require(endoscopy_id)
        await self._repo.delete(endoscopy)
        await self._session.flush()
        await audit.record(
            self._session,
            action="endoscopy.delete",
            resource_type="endoscopy",
            resource_id=endoscopy_id,
            patient_id=self._patient.id,
            context=context,
        )

    def _apply(self, endoscopy: Endoscopy, payload: EndoscopyInput) -> None:
        endoscopy.performed_on = payload.performed_on
        endoscopy.indication = payload.indication
        endoscopy.facility_encrypted = self._cipher.encrypt(
            payload.facility, aad=_facility_aad(endoscopy.id)
        )
        endoscopy.notes_encrypted = self._cipher.encrypt(
            payload.notes, aad=_notes_aad(endoscopy.id)
        )

        scores = payload.erefs
        endoscopy.erefs_version = scores.version if scores else None
        endoscopy.erefs_edema = scores.edema if scores else None
        endoscopy.erefs_rings = scores.rings if scores else None
        endoscopy.erefs_exudates = scores.exudates if scores else None
        endoscopy.erefs_furrows = scores.furrows if scores else None
        endoscopy.erefs_stricture = scores.stricture if scores else None

        endoscopy.biopsies = [
            Biopsy(
                patient_id=self._patient.id,
                location=biopsy.location,
                peak_eos_per_hpf=biopsy.peak_eos_per_hpf,
                peak_eos_comparator=biopsy.peak_eos_comparator,
                basal_zone_hyperplasia=biopsy.basal_zone_hyperplasia,
                lamina_propria_fibrosis=biopsy.lamina_propria_fibrosis,
                position=position,
            )
            for position, biopsy in enumerate(payload.biopsies)
        ]
        dilation = payload.dilation
        endoscopy.dilation = (
            Dilation(
                patient_id=self._patient.id,
                dilator_type=dilation.dilator_type,
                pre_diameter_mm=dilation.pre_diameter_mm,
                final_diameter_mm=dilation.final_diameter_mm,
                complication=dilation.complication,
            )
            if dilation
            else None
        )

    async def _audit(
        self,
        action: str,
        endoscopy: Endoscopy,
        payload: EndoscopyInput,
        context: AuditContext | None,
    ) -> None:
        await audit.record(
            self._session,
            action=action,
            resource_type="endoscopy",
            resource_id=endoscopy.id,
            patient_id=self._patient.id,
            context=context,
            metadata={
                # Which parts of the report were recorded, never what they said.
                "has_erefs": payload.erefs is not None,
                "biopsy_sites": len(payload.biopsies),
                "has_dilation": payload.dilation is not None,
                "has_facility": payload.facility is not None,
                "has_notes": payload.notes is not None,
            },
        )

    # --- reads ----------------------------------------------------------------

    async def list_all(self, *, context: AuditContext | None = None) -> list[EndoscopyRead]:
        rows = await self._repo.list_all()
        await audit.record(
            self._session,
            action="endoscopy.list",
            resource_type="endoscopy",
            patient_id=self._patient.id,
            context=context,
            metadata={"returned": len(rows)},
        )
        return [self.to_read(row) for row in rows]

    async def get(
        self, *, endoscopy_id: uuid.UUID, context: AuditContext | None = None
    ) -> EndoscopyRead:
        endoscopy = await self._repo.require(endoscopy_id)
        await audit.record(
            self._session,
            action="endoscopy.read",
            resource_type="endoscopy",
            resource_id=endoscopy.id,
            patient_id=self._patient.id,
            context=context,
        )
        return self.to_read(endoscopy)

    def to_read(self, endoscopy: Endoscopy) -> EndoscopyRead:
        biopsies = [
            BiopsyRead(
                location=b.location,
                peak_eos_per_hpf=b.peak_eos_per_hpf,
                peak_eos_comparator=b.peak_eos_comparator,
                basal_zone_hyperplasia=b.basal_zone_hyperplasia,
                lamina_propria_fibrosis=b.lamina_propria_fibrosis,
                histology=erefs.classify_count(b.peak_eos_per_hpf, b.peak_eos_comparator),
                deep_histology=erefs.classify_deep(b.peak_eos_per_hpf, b.peak_eos_comparator),
            )
            for b in endoscopy.biopsies
        ]
        peak_biopsy = max(
            endoscopy.biopsies,
            key=lambda b: (b.peak_eos_per_hpf, _COMPARATOR_RANK[b.peak_eos_comparator]),
            default=None,
        )

        erefs_read: ErefsRead | None = None
        if endoscopy.erefs_version is not None:
            scores = endoscopy.erefs_scores
            erefs_read = ErefsRead(
                version=endoscopy.erefs_version,
                edema=scores["edema"],
                rings=scores["rings"],
                exudates=scores["exudates"],
                furrows=scores["furrows"],
                stricture=scores["stricture"],
                total=erefs.total(scores),
                max_total=erefs.SCALES[endoscopy.erefs_version].max_total,
            )

        dilation = endoscopy.dilation
        return EndoscopyRead(
            id=endoscopy.id,
            performed_on=endoscopy.performed_on,
            indication=endoscopy.indication,
            facility=self._cipher.decrypt(
                endoscopy.facility_encrypted, aad=_facility_aad(endoscopy.id)
            ),
            notes=self._cipher.decrypt(endoscopy.notes_encrypted, aad=_notes_aad(endoscopy.id)),
            erefs=erefs_read,
            biopsies=biopsies,
            dilation=(
                DilationRead(
                    dilator_type=dilation.dilator_type,
                    pre_diameter_mm=dilation.pre_diameter_mm,
                    final_diameter_mm=dilation.final_diameter_mm,
                    complication=dilation.complication,
                )
                if dilation
                else None
            ),
            peak=(
                PeakCount(
                    value=peak_biopsy.peak_eos_per_hpf,
                    comparator=peak_biopsy.peak_eos_comparator,
                    location=peak_biopsy.location,
                )
                if peak_biopsy
                else None
            ),
            histology=erefs.classify_procedure(b.histology for b in biopsies),
            deep_histology=erefs.classify_procedure(b.deep_histology for b in biopsies),
            remission_threshold_eos_per_hpf=erefs.REMISSION_THRESHOLD_EOS_PER_HPF,
            deep_remission_max_eos_per_hpf=erefs.DEEP_REMISSION_MAX_EOS_PER_HPF,
            created_at=endoscopy.created_at,
            updated_at=endoscopy.updated_at,
        )
