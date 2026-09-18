from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.audit.service import AuditContext
from eoehelp_api.config import Settings, get_settings
from eoehelp_api.core import ratelimit
from eoehelp_api.core.deps import (
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
    Principal,
    get_audit_context,
    get_principal,
    get_session,
)
from eoehelp_api.core.errors import InvalidTokenError
from eoehelp_api.core.ratelimit import limiter
from eoehelp_api.identity.auth_schemas import (
    AccessTokenResponse,
    MagicLinkRequest,
    MagicLinkRequestAccepted,
    MagicLinkVerify,
    SessionUser,
)
from eoehelp_api.identity.auth_service import AuthService, IssuedSession
from eoehelp_api.identity.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, session: IssuedSession, settings: Settings) -> None:
    """Store the refresh token in an httpOnly cookie.

    httpOnly so injected script cannot read it — for a health app, a token in
    localStorage turns any XSS into full account takeover. SameSite=strict is
    viable because this is a single first-party origin, and it removes the CSRF
    exposure the cookie would otherwise introduce.
    """
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=session.refresh_token,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=True,
        secure=settings.environment != "local",
        samesite="strict",
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        secure=settings.environment != "local",
        samesite="strict",
        path=REFRESH_COOKIE_PATH,
    )


@router.post(
    "/magic-link",
    response_model=MagicLinkRequestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(ratelimit.MAGIC_LINK_REQUEST)
async def request_magic_link(
    request: Request,
    payload: MagicLinkRequest,
    session: AsyncSession = Depends(get_session),
    context: AuditContext = Depends(get_audit_context),
) -> MagicLinkRequestAccepted:
    await AuthService(session).request_magic_link(email=payload.email, context=context)
    return MagicLinkRequestAccepted()


@router.post("/magic-link/verify", response_model=AccessTokenResponse)
@limiter.limit(ratelimit.MAGIC_LINK_VERIFY)
async def verify_magic_link(
    request: Request,
    payload: MagicLinkVerify,
    response: Response,
    session: AsyncSession = Depends(get_session),
    context: AuditContext = Depends(get_audit_context),
    settings: Settings = Depends(get_settings),
) -> AccessTokenResponse:
    issued = await AuthService(session).verify_magic_link(raw_token=payload.token, context=context)
    _set_refresh_cookie(response, issued, settings)
    return AccessTokenResponse(
        access_token=issued.access_token, expires_at=issued.access_expires_at
    )


@router.post("/refresh", response_model=AccessTokenResponse)
@limiter.limit(ratelimit.SESSION_REFRESH)
async def refresh_session(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    context: AuditContext = Depends(get_audit_context),
    settings: Settings = Depends(get_settings),
) -> AccessTokenResponse:
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_token:
        raise InvalidTokenError("Session expired. Please sign in again.")

    issued = await AuthService(session).refresh(raw_token=raw_token, context=context)
    _set_refresh_cookie(response, issued, settings)
    return AccessTokenResponse(
        access_token=issued.access_token, expires_at=issued.access_expires_at
    )


@router.post("/sign-out", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    context: AuditContext = Depends(get_audit_context),
    settings: Settings = Depends(get_settings),
) -> Response:
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if raw_token:
        await AuthService(session).revoke_refresh_token(raw_token=raw_token, context=context)
    _clear_refresh_cookie(response, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/session", response_model=SessionUser)
async def current_session(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> SessionUser:
    user = await session.get(User, principal.user_id)
    if user is None:
        raise InvalidTokenError("Session expired. Please sign in again.")

    return SessionUser(
        id=str(user.id),
        email=user.email,
        role=user.role.value,
        email_verified=user.email_verified_at is not None,
        patient_id=str(principal.patient_id) if principal.patient_id else None,
        onboarding_complete=principal.patient_id is not None,
    )
