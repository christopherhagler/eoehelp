"""Endoscopies, with their biopsy results and any dilation, under /me."""

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.audit.service import AuditContext
from eoehelp_api.deps import (
    get_authenticated_audit_context,
    get_current_patient,
    get_patient_session,
)
from eoehelp_api.identity.patient import Patient
from eoehelp_api.procedures.schemas import EndoscopyInput, EndoscopyRead
from eoehelp_api.procedures.service import EndoscopyService

router = APIRouter(prefix="/me/endoscopies", tags=["procedures"])


@router.get("", response_model=list[EndoscopyRead])
async def list_endoscopies(
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> list[EndoscopyRead]:
    """Every recorded endoscopy, newest first."""
    return await EndoscopyService(session, patient).list_all(context=context)


@router.post("", response_model=EndoscopyRead, status_code=status.HTTP_201_CREATED)
async def add_endoscopy(
    payload: EndoscopyInput,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> EndoscopyRead:
    return await EndoscopyService(session, patient).create(payload=payload, context=context)


@router.get("/{endoscopy_id}", response_model=EndoscopyRead)
async def read_endoscopy(
    endoscopy_id: uuid.UUID,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> EndoscopyRead:
    return await EndoscopyService(session, patient).get(endoscopy_id=endoscopy_id, context=context)


@router.put("/{endoscopy_id}", response_model=EndoscopyRead)
async def replace_endoscopy(
    endoscopy_id: uuid.UUID,
    payload: EndoscopyInput,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> EndoscopyRead:
    """Replace the whole record, findings included.

    Biopsy results usually arrive a week after the scope, so adding them is an
    edit of the same document rather than a separate resource.
    """
    return await EndoscopyService(session, patient).update(
        endoscopy_id=endoscopy_id, payload=payload, context=context
    )


@router.delete("/{endoscopy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endoscopy(
    endoscopy_id: uuid.UUID,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> Response:
    await EndoscopyService(session, patient).delete(endoscopy_id=endoscopy_id, context=context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
