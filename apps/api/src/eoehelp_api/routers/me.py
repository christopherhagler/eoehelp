"""The patient's own record: onboarding, profile, and deletion.

Every route here is /me. There is no /patients/{id} anywhere in the API, which is
what makes an insecure-direct-object-reference bug impossible to write rather
than something to remember to guard against.
"""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.config import Settings, get_settings
from eoehelp_api.core.deps import (
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
    PatientPrincipal,
    Principal,
    get_authenticated_audit_context,
    get_current_patient,
    get_patient_principal,
    get_patient_role_principal,
    get_patient_session,
    get_session,
)
from eoehelp_api.core.errors import UnauthenticatedError
from eoehelp_api.models.patient import Patient
from eoehelp_api.models.user import User
from eoehelp_api.schemas.patient import (
    ConsentRecord,
    OnboardingRequest,
    OnboardingResponse,
    PatientProfile,
    PatientProfileUpdate,
)
from eoehelp_api.services.audit import AuditContext
from eoehelp_api.services.onboarding import OnboardingService

router = APIRouter(prefix="/me", tags=["patient"])


@router.post("/onboarding", response_model=OnboardingResponse, status_code=status.HTTP_201_CREATED)
async def complete_onboarding(
    payload: OnboardingRequest,
    principal: Principal = Depends(get_patient_role_principal),
    # Unscoped: the patient row does not exist yet, so there is nothing to scope
    # to. The service sets the scope itself once it has minted the id.
    session: AsyncSession = Depends(get_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> OnboardingResponse:
    user = await session.get(User, principal.user_id)
    if user is None:
        raise UnauthenticatedError()

    result = await OnboardingService(session).complete(user=user, payload=payload, context=context)
    return OnboardingResponse(
        patient=PatientProfile.model_validate(result.patient),
        consents=[ConsentRecord.model_validate(c) for c in result.consents],
        access_token=result.access_token,
        expires_at=result.access_expires_at,
    )


@router.get("/profile", response_model=PatientProfile)
async def read_profile(patient: Patient = Depends(get_current_patient)) -> PatientProfile:
    return PatientProfile.model_validate(patient)


@router.patch("/profile", response_model=PatientProfile)
async def update_profile(
    payload: PatientProfileUpdate,
    principal: PatientPrincipal = Depends(get_patient_principal),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> PatientProfile:
    patient = await OnboardingService(session).update_profile(
        patient_id=principal.patient_id, payload=payload, context=context
    )
    return PatientProfile.model_validate(patient)


@router.get("/consents", response_model=list[ConsentRecord])
async def read_consents(
    principal: PatientPrincipal = Depends(get_patient_principal),
    session: AsyncSession = Depends(get_patient_session),
) -> list[ConsentRecord]:
    consents = await OnboardingService(session).current_consents(principal.patient_id)
    return [ConsentRecord.model_validate(c) for c in consents]


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    response: Response,
    principal: PatientPrincipal = Depends(get_patient_principal),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Erase the record. Not reversible, and not a flag.

    Washington's My Health My Data Act gives a working deletion right, and the
    product promises the deletion is real. The audit trail of the access and of
    the deletion survives by design; it holds field names rather than values.
    """
    await OnboardingService(session).delete_account(
        user_id=principal.user_id, patient_id=principal.patient_id, context=context
    )
    # The session died with the account, so the cookie goes too rather than
    # sitting in the browser pointing at nothing.
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        secure=settings.environment != "local",
        samesite="strict",
        path=REFRESH_COOKIE_PATH,
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
