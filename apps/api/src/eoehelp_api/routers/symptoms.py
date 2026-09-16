"""The daily symptom log.

Entries are addressed by date, not by id: /me/symptoms/2026-09-16. A patient has
exactly one entry per day, so the date *is* the identifier, and a client editing
this morning's answer does not need to have kept hold of a UUID. It also means
there is no opaque id to enumerate.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.core.deps import (
    get_authenticated_audit_context,
    get_current_patient,
    get_patient_session,
)
from eoehelp_api.models.patient import Patient
from eoehelp_api.schemas.symptoms import (
    SymptomBurdenRead,
    SymptomBurdenTrend,
    SymptomEntryInput,
    SymptomEntryList,
    SymptomEntryRead,
)
from eoehelp_api.services import scoring
from eoehelp_api.services.audit import AuditContext
from eoehelp_api.services.scoring import SymptomBurden
from eoehelp_api.services.symptoms import SymptomService

router = APIRouter(prefix="/me/symptoms", tags=["symptoms"])

DEFAULT_RANGE_DAYS = 30
DEFAULT_TREND_POINTS = 30


def _burden_response(burden: SymptomBurden) -> SymptomBurdenRead:
    return SymptomBurdenRead(
        period_start=burden.period_start,
        period_end=burden.period_end,
        instrument_code=burden.instrument_code,
        instrument_version=burden.instrument_version,
        days_in_window=burden.days_in_window,
        days_logged=burden.days_logged,
        days_scorable=burden.days_scorable,
        max_score=scoring.DSQ_MAX_SCORE,
        score=burden.score,
        components=burden.components,
    )


@router.get("", response_model=SymptomEntryList)
async def list_entries(
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
    range_start: date | None = Query(default=None, alias="from"),
    range_end: date | None = Query(default=None, alias="to"),
) -> SymptomEntryList:
    service = SymptomService(session, patient)
    end = range_end or service.today
    start = range_start or end - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    entries = await service.list_range(start=start, end=end, context=context)
    return SymptomEntryList(entries=entries, range_start=start, range_end=end)


@router.get("/burden", response_model=SymptomBurdenRead)
async def read_burden(
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    as_of: date | None = Query(default=None),
) -> SymptomBurdenRead:
    """The 14-day symptom burden score ending on `as_of`, or today.

    Computed server-side so the screen, the PDF, and any future export cannot
    disagree about the same patient's score.
    """
    burden = await SymptomService(session, patient).burden(as_of=as_of)
    return _burden_response(burden)


@router.get("/burden/trend", response_model=SymptomBurdenTrend)
async def read_burden_trend(
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    as_of: date | None = Query(default=None),
    points: int = Query(default=DEFAULT_TREND_POINTS, ge=2, le=365),
) -> SymptomBurdenTrend:
    trend = await SymptomService(session, patient).burden_trend(as_of=as_of, points=points)
    return SymptomBurdenTrend(points=[_burden_response(b) for b in trend])


@router.get("/{entry_date}", response_model=SymptomEntryRead)
async def read_entry(
    entry_date: date,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> SymptomEntryRead:
    return await SymptomService(session, patient).get(entry_date=entry_date, context=context)


@router.put("/{entry_date}", response_model=SymptomEntryRead)
async def upsert_entry(
    entry_date: date,
    payload: SymptomEntryInput,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> SymptomEntryRead:
    """Write the entry for one day, creating or replacing it.

    PUT rather than POST: the day is the identifier, the operation is idempotent,
    and an offline client replaying a queued submission must not produce a second
    entry for the same date.
    """
    return await SymptomService(session, patient).upsert(
        entry_date=entry_date, payload=payload, context=context
    )


@router.delete("/{entry_date}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_date: date,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> Response:
    await SymptomService(session, patient).delete(entry_date=entry_date, context=context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
