"""The daily symptom log.

Two things in here are load-bearing and easy to get wrong.

**"Today" is the patient's today.** The date a log entry describes is computed in
the patient's own timezone, not the server's. Scored against UTC, an entry made
at 8pm in Seattle lands on tomorrow's date and is then recorded as a backfill of
a day that has not happened — which corrupts both the calendar and the
same-day/recalled distinction research depends on.

**entry_method is derived, never accepted.** A client could otherwise claim
same-day entry for a month of recalled data, and recall bias is exactly what the
flag exists to let researchers weigh.
"""

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.core.errors import BadRequestError
from eoehelp_api.core.security import FieldCipher
from eoehelp_api.models.clinical import SymptomEntry
from eoehelp_api.models.enums import EntryMethod
from eoehelp_api.models.patient import Patient
from eoehelp_api.repositories.symptoms import SymptomEntryRepository
from eoehelp_api.schemas.symptoms import SymptomEntryInput, SymptomEntryRead
from eoehelp_api.services import audit, scoring
from eoehelp_api.services.audit import AuditContext
from eoehelp_api.services.scoring import SymptomBurden

# A week of catch-up covers a holiday or a flare that made logging impossible,
# while keeping entries close enough to the day to be worth something. Anything
# older is recall, and the plan would rather have a gap than fiction.
MAX_BACKFILL_DAYS = 7

# The longest span a single list request will return. A year of daily entries is
# well within one response, and the cap exists so an unbounded range cannot turn
# into an unbounded query.
MAX_RANGE_DAYS = 400


class SymptomService:
    def __init__(self, session: AsyncSession, patient: Patient) -> None:
        self._session = session
        self._patient = patient
        self._repo = SymptomEntryRepository(session, patient.id)
        self._cipher = FieldCipher.from_settings()

    @property
    def today(self) -> date:
        return datetime.now(ZoneInfo(self._patient.timezone)).date()

    def _validate_entry_date(self, entry_date: date) -> EntryMethod:
        today = self.today
        if entry_date > today:
            raise BadRequestError("That day has not happened yet in your timezone.")
        if entry_date < today - timedelta(days=MAX_BACKFILL_DAYS):
            raise BadRequestError(
                f"Entries can be added up to {MAX_BACKFILL_DAYS} days late. "
                "Older days are left blank rather than recalled."
            )
        return EntryMethod.SAME_DAY if entry_date == today else EntryMethod.BACKFILL

    async def upsert(
        self,
        *,
        entry_date: date,
        payload: SymptomEntryInput,
        context: AuditContext | None = None,
    ) -> SymptomEntryRead:
        """Create or replace the entry for one day.

        Upsert rather than create-plus-update because the unique constraint on
        (patient_id, entry_date) makes a second row for a day impossible, and a
        patient correcting this morning's answer should not have to know whether
        they are creating or editing.
        """
        entry_method = self._validate_entry_date(entry_date)
        existing = await self._repo.get_by_date(entry_date)

        if existing is None:
            # The id is generated here rather than by the database default
            # because it is the additional authenticated data for the notes
            # ciphertext, so it has to exist before the row is written.
            entry = SymptomEntry(
                id=uuid.uuid4(),
                patient_id=self._patient.id,
                entry_date=entry_date,
                entry_method=entry_method,
                instrument_code=scoring.DSQ_CODE,
                instrument_version=scoring.DSQ_VERSION,
            )
            self._apply(entry, payload)
            self._repo.add(entry)
            action = "symptom_entry.create"
        else:
            entry = existing
            # An edit does not relabel how the original was captured: a same-day
            # entry corrected two days later is still a same-day observation.
            self._apply(entry, payload)
            action = "symptom_entry.update"

        await self._session.flush()
        # updated_at is maintained by a SQL expression, so after an UPDATE its
        # value is unknown to the session and the attribute is expired. Reading it
        # while building the response would then trigger lazy IO outside the async
        # context and fail with MissingGreenlet. Refresh explicitly instead.
        await self._session.refresh(entry)

        await audit.record(
            self._session,
            action=action,
            resource_type="symptom_entry",
            resource_id=entry.id,
            patient_id=self._patient.id,
            context=context,
            metadata={
                "entry_date": entry_date.isoformat(),
                "entry_method": entry.entry_method.value,
                # Field names, never the answers.
                "fields": sorted(payload.model_dump(exclude={"notes"}).keys()),
                "has_notes": payload.notes is not None,
            },
        )
        return self.to_read(entry)

    def _apply(self, entry: SymptomEntry, payload: SymptomEntryInput) -> None:
        entry.ate_solid_food = payload.ate_solid_food
        entry.dysphagia_occurred = payload.dysphagia_occurred
        entry.dysphagia_severity = payload.dysphagia_severity
        entry.odynophagia = payload.odynophagia
        entry.odynophagia_severity = payload.odynophagia_severity
        entry.food_impaction_er_visit = payload.food_impaction_er_visit
        entry.coping_actions = payload.deduplicated_coping_actions
        entry.avoided_foods_today = payload.avoided_foods_today
        entry.modified_foods_today = payload.modified_foods_today
        entry.ate_unusually_slowly = payload.ate_unusually_slowly
        entry.notes_encrypted = self._cipher.encrypt(payload.notes, aad=str(entry.id))

    async def get(
        self, *, entry_date: date, context: AuditContext | None = None
    ) -> SymptomEntryRead:
        entry = await self._repo.require_by_date(entry_date)
        # Reads of a single record are audited individually. "Did someone browse
        # my records" is a question a breach response has to be able to answer,
        # and it cannot be answered from write logs alone.
        await audit.record(
            self._session,
            action="symptom_entry.read",
            resource_type="symptom_entry",
            resource_id=entry.id,
            patient_id=self._patient.id,
            context=context,
        )
        return self.to_read(entry)

    async def list_range(
        self,
        *,
        start: date,
        end: date,
        context: AuditContext | None = None,
    ) -> list[SymptomEntryRead]:
        if end < start:
            raise BadRequestError("The range ends before it starts.")
        if (end - start).days + 1 > MAX_RANGE_DAYS:
            raise BadRequestError(f"Ranges are limited to {MAX_RANGE_DAYS} days.")

        entries = await self._repo.list_between(start, end)
        # One row per list request rather than per record: enough to reconstruct
        # what was accessed, without the trail dwarfing the data it describes.
        await audit.record(
            self._session,
            action="symptom_entry.list",
            resource_type="symptom_entry",
            patient_id=self._patient.id,
            context=context,
            metadata={
                "range_start": start.isoformat(),
                "range_end": end.isoformat(),
                "returned": len(entries),
            },
        )
        return [self.to_read(entry) for entry in entries]

    async def delete(self, *, entry_date: date, context: AuditContext | None = None) -> None:
        entry = await self._repo.require_by_date(entry_date)
        entry_id = entry.id
        await self._repo.delete(entry)
        await self._session.flush()
        await audit.record(
            self._session,
            action="symptom_entry.delete",
            resource_type="symptom_entry",
            resource_id=entry_id,
            patient_id=self._patient.id,
            context=context,
            metadata={"entry_date": entry_date.isoformat()},
        )

    async def burden(self, *, as_of: date | None = None) -> SymptomBurden:
        period_end = as_of or self.today
        entries = await self._repo.list_between(
            period_end - timedelta(days=scoring.DSQ_WINDOW_DAYS - 1), period_end
        )
        return scoring.score_window(entries, period_end=period_end)

    async def burden_trend(
        self, *, as_of: date | None = None, points: int = 30
    ) -> list[SymptomBurden]:
        period_end = as_of or self.today
        # Each point needs the full window behind it, so the fetch reaches back
        # further than the range being charted.
        earliest = period_end - timedelta(days=points + scoring.DSQ_WINDOW_DAYS - 2)
        entries = await self._repo.list_between(earliest, period_end)
        return scoring.score_trend(entries, period_end=period_end, points=points)

    def to_read(self, entry: SymptomEntry) -> SymptomEntryRead:
        return SymptomEntryRead(
            entry_date=entry.entry_date,
            ate_solid_food=entry.ate_solid_food,
            dysphagia_occurred=entry.dysphagia_occurred,
            dysphagia_severity=entry.dysphagia_severity,
            odynophagia=entry.odynophagia,
            odynophagia_severity=entry.odynophagia_severity,
            food_impaction_er_visit=entry.food_impaction_er_visit,
            coping_actions=list(entry.coping_actions),
            avoided_foods_today=entry.avoided_foods_today,
            modified_foods_today=entry.modified_foods_today,
            ate_unusually_slowly=entry.ate_unusually_slowly,
            notes=self._cipher.decrypt(entry.notes_encrypted, aad=str(entry.id)),
            entry_method=entry.entry_method,
            instrument_code=entry.instrument_code,
            instrument_version=entry.instrument_version,
            daily_score=scoring.daily_score(entry),
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )
