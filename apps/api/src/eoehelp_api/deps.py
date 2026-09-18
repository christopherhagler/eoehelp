"""FastAPI dependencies: request context, sessions, and the authenticated principal."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import jwt
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.audit.service import AuditContext
from eoehelp_api.core import security
from eoehelp_api.core.errors import ForbiddenError, UnauthenticatedError
from eoehelp_api.db.session import apply_rls_scope, get_session_factory
from eoehelp_api.identity.enums import UserRole
from eoehelp_api.identity.patient import Patient

API_V1_PREFIX = "/api/v1"

REFRESH_COOKIE_NAME = "eoehelp_refresh"

# Scoped to the auth routes so the refresh token is not attached to every API
# request. Derived from API_V1_PREFIX rather than written out: if the cookie path
# and the mounted route prefix drift apart, the browser silently stops sending
# the cookie and refresh fails for every user.
REFRESH_COOKIE_PATH = f"{API_V1_PREFIX}/auth"


@dataclass(frozen=True)
class Principal:
    """The authenticated caller, derived solely from the verified access token.

    `patient_id` never comes from a path or body parameter. Patient-facing routes
    are /me/*, so there is no "which patient" question to get wrong — which is
    what removes the IDOR bug class rather than merely guarding against it.
    """

    user_id: uuid.UUID
    role: UserRole
    patient_id: uuid.UUID | None

    @property
    def is_onboarded(self) -> bool:
        return self.patient_id is not None


def get_audit_context(request: Request) -> AuditContext:
    return AuditContext(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """Unscoped transactional session for routes that are not patient-specific.

    Row-level security still applies; the scope is set to an empty value so any
    policy-protected table returns zero rows rather than everything.
    """
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await apply_rls_scope(session, None)
        yield session


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise UnauthenticatedError()
    return token


def get_principal(request: Request) -> Principal:
    token = _bearer_token(request)
    try:
        claims = security.decode_access_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise UnauthenticatedError("Access token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthenticatedError() from exc

    try:
        user_id = uuid.UUID(str(claims["sub"]))
        role = UserRole(str(claims["role"]))
    except (KeyError, ValueError) as exc:
        raise UnauthenticatedError() from exc

    raw_patient_id = claims.get("pid")
    patient_id: uuid.UUID | None = None
    if raw_patient_id is not None:
        try:
            patient_id = uuid.UUID(str(raw_patient_id))
        except ValueError as exc:
            raise UnauthenticatedError() from exc

    return Principal(user_id=user_id, role=role, patient_id=patient_id)


def get_patient_role_principal(
    principal: Principal = Depends(get_principal),
) -> Principal:
    """A patient account, onboarded or not.

    Onboarding itself needs this: the caller is authenticated but has no patient
    record yet, so it cannot require one.
    """
    if principal.role is not UserRole.PATIENT:
        raise ForbiddenError("This endpoint is for patient accounts.")
    return principal


@dataclass(frozen=True)
class PatientPrincipal:
    """An onboarded patient, where `patient_id` is known to exist.

    A separate type rather than a checked field, so that every patient-scoped
    route is statically guaranteed a real patient id. The alternative — carrying
    `patient_id: UUID | None` everywhere — spreads either an assertion or an
    unchecked Optional into every handler, and one of those eventually gets it
    wrong.
    """

    user_id: uuid.UUID
    patient_id: uuid.UUID


def get_patient_principal(
    principal: Principal = Depends(get_patient_role_principal),
) -> PatientPrincipal:
    if principal.patient_id is None:
        raise ForbiddenError("Complete onboarding before using this endpoint.")
    return PatientPrincipal(user_id=principal.user_id, patient_id=principal.patient_id)


async def get_patient_session(
    principal: PatientPrincipal = Depends(get_patient_principal),
) -> AsyncIterator[AsyncSession]:
    """Session bound to the caller's patient row for the life of one transaction."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await apply_rls_scope(session, principal.patient_id)
        yield session


async def get_current_patient(
    principal: PatientPrincipal = Depends(get_patient_principal),
    session: AsyncSession = Depends(get_patient_session),
) -> Patient:
    """The caller's own patient row, loaded inside the scoped transaction.

    Fetched rather than reconstructed from the token because the timezone lives
    here, and the daily log is wrong in a way nobody notices if it is guessed:
    "today" has to be the patient's today.

    The lookup goes through the row-level-security scope set by
    get_patient_session, so it can only ever return the caller's own row — if the
    scope and the token disagreed, this would return nothing rather than someone
    else's record.
    """
    patient = await session.get(Patient, principal.patient_id)
    if patient is None:
        raise ForbiddenError("Complete onboarding before using this endpoint.")
    return patient


def get_authenticated_audit_context(
    request: Request,
    principal: Principal = Depends(get_principal),
) -> AuditContext:
    return AuditContext(
        actor_user_id=principal.user_id,
        actor_role=principal.role.value,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
