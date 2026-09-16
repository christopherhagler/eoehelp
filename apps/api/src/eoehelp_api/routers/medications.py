"""Medications, dose logging, and adherence.

Two routers: the catalog is reference data behind plain authentication, while
everything patient-owned sits under /me with the patient taken from the token.
"""

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.core.deps import (
    Principal,
    get_authenticated_audit_context,
    get_current_patient,
    get_patient_session,
    get_principal,
    get_session,
)
from eoehelp_api.models.medication import MedicationCatalogEntry
from eoehelp_api.models.patient import Patient
from eoehelp_api.schemas.medications import (
    AdherenceRead,
    AdherenceSummary,
    DoseCreate,
    DoseRead,
    MedicationCatalogItem,
    MedicationCreate,
    MedicationRead,
    MedicationStop,
    MedicationToday,
)
from eoehelp_api.services import schedules
from eoehelp_api.services.audit import AuditContext
from eoehelp_api.services.medications import AdherenceRow, MedicationService

catalog_router = APIRouter(prefix="/medications", tags=["medications"])
router = APIRouter(prefix="/me/medications", tags=["medications"])

DEFAULT_ADHERENCE_DAYS = 30


@catalog_router.get("/catalog", response_model=list[MedicationCatalogItem])
async def list_catalog(
    _principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> list[MedicationCatalogItem]:
    """The medications this product knows about.

    Reference data, so it is not under /me and writes no audit row — reading the
    list discloses nothing about the reader.
    """
    result = await session.execute(
        select(MedicationCatalogEntry).order_by(
            MedicationCatalogEntry.drug_class, MedicationCatalogEntry.generic_name
        )
    )
    return [MedicationCatalogItem.model_validate(row) for row in result.scalars()]


def _adherence_response(row: AdherenceRow) -> AdherenceRead:
    return AdherenceRead(
        medication_id=row.medication.id,
        medication_code=row.medication.medication_code,
        generic_name=row.medication.catalog.generic_name,
        frequency=schedules.frequency_of(row.medication.schedule_rrule),
        window_start=row.result.window_start,
        window_end=row.result.window_end,
        expected_doses=row.result.expected_doses,
        taken_doses=row.result.taken_doses,
        skipped_doses=row.result.skipped_doses,
        percentage=row.result.percentage,
    )


@router.get("", response_model=list[MedicationRead])
async def list_medications(
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
    include_ended: bool = Query(default=True),
) -> list[MedicationRead]:
    return await MedicationService(session, patient).list_medications(
        include_ended=include_ended, context=context
    )


@router.post("", response_model=MedicationRead, status_code=status.HTTP_201_CREATED)
async def add_medication(
    payload: MedicationCreate,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> MedicationRead:
    return await MedicationService(session, patient).add(payload=payload, context=context)


# Declared before /{medication_id} so these literal paths are not captured as ids.
@router.get("/today", response_model=MedicationToday)
async def medications_today(
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    on_date: date | None = Query(default=None, alias="on"),
) -> MedicationToday:
    """What is due today and what has been logged, in one call.

    The daily log needs both halves: whether the evening dose is still
    outstanding, and the dose ids required to undo a mistaken tap.
    """
    day, items = await MedicationService(session, patient).today_view(on_date=on_date)
    return MedicationToday(on_date=day, items=items)


@router.get("/adherence", response_model=AdherenceSummary)
async def read_adherence(
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    window_start: date | None = Query(default=None, alias="from"),
    window_end: date | None = Query(default=None, alias="to"),
    include_ended: bool = Query(default=True),
) -> AdherenceSummary:
    service = MedicationService(session, patient)
    end = window_end or service.today
    start = window_start or end - timedelta(days=DEFAULT_ADHERENCE_DAYS - 1)
    rows = await service.adherence(window_start=start, window_end=end, include_ended=include_ended)
    return AdherenceSummary(
        window_start=start,
        window_end=end,
        medications=[_adherence_response(row) for row in rows],
    )


@router.delete("/doses/{dose_id}", status_code=status.HTTP_204_NO_CONTENT)
async def undo_dose(
    dose_id: uuid.UUID,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> Response:
    await MedicationService(session, patient).undo_dose(dose_id=dose_id, context=context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{medication_id}/doses", response_model=DoseRead, status_code=status.HTTP_201_CREATED)
async def log_dose(
    medication_id: uuid.UUID,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
    payload: DoseCreate | None = None,
) -> DoseRead:
    """Record a dose.

    The body is optional: tapping "took it" sends none at all, and the server
    timestamps it — which is the only version worth trusting anyway.
    """
    return await MedicationService(session, patient).log_dose(
        medication_id=medication_id, payload=payload or DoseCreate(), context=context
    )


@router.post("/{medication_id}/stop", response_model=MedicationRead)
async def stop_medication(
    medication_id: uuid.UUID,
    payload: MedicationStop,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> MedicationRead:
    return await MedicationService(session, patient).stop(
        medication_id=medication_id, payload=payload, context=context
    )


@router.delete("/{medication_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_medication(
    medication_id: uuid.UUID,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> Response:
    """For a course entered by mistake. Refused once doses exist — see the service."""
    await MedicationService(session, patient).remove(medication_id=medication_id, context=context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
