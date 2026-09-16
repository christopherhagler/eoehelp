"""Authentication flows: magic-link issuance and verification, refresh rotation."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.config import Settings, get_settings
from eoehelp_api.core import security
from eoehelp_api.core.errors import InvalidTokenError
from eoehelp_api.db.session import session_scope
from eoehelp_api.models.auth import MagicLinkToken, RefreshToken
from eoehelp_api.models.enums import AuditOutcome, UserRole, UserStatus
from eoehelp_api.models.patient import Patient
from eoehelp_api.models.user import User
from eoehelp_api.observability import get_logger
from eoehelp_api.services import audit
from eoehelp_api.services.audit import AuditContext
from eoehelp_api.services.email import EmailSender

logger = get_logger(__name__)


class IssuedSession:
    def __init__(
        self,
        *,
        access_token: str,
        access_expires_at: datetime,
        refresh_token: str,
        refresh_expires_at: datetime,
        user: User,
        patient: Patient | None,
    ) -> None:
        self.access_token = access_token
        self.access_expires_at = access_expires_at
        self.refresh_token = refresh_token
        self.refresh_expires_at = refresh_expires_at
        self.user = user
        self.patient = patient


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        email_sender: EmailSender | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._email = email_sender or EmailSender(self._settings)

    async def request_magic_link(self, *, email: str, context: AuditContext | None = None) -> None:
        """Issue a sign-in link, creating the account on first request.

        Registration and login are the same action deliberately: it removes a
        separate signup form and the "account already exists" disclosure with it.
        """
        normalized = email.strip().lower()
        user = await self._get_user_by_email(normalized)

        if user is None:
            user = User(email=normalized, role=UserRole.PATIENT, status=UserStatus.ACTIVE)
            self._session.add(user)
            await self._session.flush()
            await audit.record(
                self._session,
                action="user.create",
                resource_type="user",
                resource_id=user.id,
                context=context,
            )
        elif user.status is not UserStatus.ACTIVE:
            # Say nothing to the caller; a suspended account must not be
            # distinguishable from an active one.
            await audit.record(
                self._session,
                action="auth.magic_link.request",
                resource_type="user",
                resource_id=user.id,
                outcome=AuditOutcome.DENIED,
                context=context,
                metadata={"reason": "account_not_active"},
            )
            return

        raw_token = security.generate_token()
        now = datetime.now(UTC)
        self._session.add(
            MagicLinkToken(
                user_id=user.id,
                token_hash=security.hash_token(raw_token),
                expires_at=now + timedelta(seconds=self._settings.magic_link_ttl_seconds),
                created_at=now,
                requested_ip=context.ip_address if context else None,
            )
        )
        await audit.record(
            self._session,
            action="auth.magic_link.request",
            resource_type="user",
            resource_id=user.id,
            context=context,
        )

        link = f"{self._settings.app_base_url.rstrip('/')}/verify?token={raw_token}"
        await self._email.send_magic_link(
            to=normalized,
            link=link,
            ttl_minutes=self._settings.magic_link_ttl_seconds // 60,
        )

    async def verify_magic_link(
        self, *, raw_token: str, context: AuditContext | None = None
    ) -> IssuedSession:
        token_hash = security.hash_token(raw_token)
        result = await self._session.execute(
            select(MagicLinkToken).where(MagicLinkToken.token_hash == token_hash)
        )
        token = result.scalar_one_or_none()
        now = datetime.now(UTC)

        if token is None or token.consumed_at is not None or token.expires_at <= now:
            await audit.record(
                self._session,
                action="auth.magic_link.verify",
                resource_type="magic_link_token",
                resource_id=token.id if token else None,
                outcome=AuditOutcome.DENIED,
                context=context,
                metadata={"reason": self._reject_reason(token, now)},
            )
            raise InvalidTokenError()

        token.consumed_at = now

        user = await self._session.get(User, token.user_id)
        if user is None or user.status is not UserStatus.ACTIVE:
            raise InvalidTokenError()

        # First successful sign-in doubles as email verification: possession of
        # the inbox is exactly what the link proves.
        if user.email_verified_at is None:
            user.email_verified_at = now

        patient = await self._get_patient_for_user(user.id)
        session = await self._issue_session(user=user, patient=patient, context=context)

        await audit.record(
            self._session,
            action="auth.magic_link.verify",
            resource_type="user",
            resource_id=user.id,
            patient_id=patient.id if patient else None,
            context=context,
        )
        return session

    @staticmethod
    def _reject_reason(token: MagicLinkToken | None, now: datetime) -> str:
        if token is None:
            return "unknown_token"
        if token.consumed_at is not None:
            return "already_consumed"
        if token.expires_at <= now:
            return "expired"
        return "unknown"

    async def refresh(
        self, *, raw_token: str, context: AuditContext | None = None
    ) -> IssuedSession:
        token_hash = security.hash_token(raw_token)
        result = await self._session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        stored = result.scalar_one_or_none()
        now = datetime.now(UTC)

        if stored is None:
            raise InvalidTokenError("Session expired. Please sign in again.")

        if stored.rotated_at is not None or stored.revoked_at is not None:
            # A rotated token presented again means the cookie was captured.
            # Revoke the whole family: the legitimate holder re-authenticates,
            # and the attacker's stolen token dies with it.
            #
            # Committed out of band because this request is about to fail. The
            # request transaction rolls back on the raise below, which would
            # otherwise discard the revocation and leave the stolen family live.
            await self._revoke_family_out_of_band(
                stored.family_id, token_id=stored.id, context=context
            )
            raise InvalidTokenError("Session expired. Please sign in again.")

        if stored.expires_at <= now:
            raise InvalidTokenError("Session expired. Please sign in again.")

        user = await self._session.get(User, stored.user_id)
        if user is None or user.status is not UserStatus.ACTIVE:
            raise InvalidTokenError("Session expired. Please sign in again.")

        stored.rotated_at = now
        patient = await self._get_patient_for_user(user.id)
        return await self._issue_session(
            user=user, patient=patient, context=context, family_id=stored.family_id
        )

    async def revoke_refresh_token(
        self, *, raw_token: str, context: AuditContext | None = None
    ) -> None:
        result = await self._session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == security.hash_token(raw_token))
        )
        stored = result.scalar_one_or_none()
        if stored is None:
            return
        await self._revoke_family(stored.family_id, reason="signed_out")
        await audit.record(
            self._session,
            action="auth.sign_out",
            resource_type="user",
            resource_id=stored.user_id,
            context=context,
        )

    async def _revoke_family(self, family_id: uuid.UUID, *, reason: str) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
        )

    async def _revoke_family_out_of_band(
        self,
        family_id: uuid.UUID,
        *,
        token_id: uuid.UUID,
        context: AuditContext | None,
    ) -> None:
        """Revoke a compromised token family in its own committed transaction.

        Deliberately not on the request session: the caller raises immediately
        after, and the request transaction's rollback would undo both the
        revocation and its audit entry.
        """
        async with session_scope() as session:
            await session.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.family_id == family_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC), revoked_reason="reuse_detected")
            )
            await audit.record(
                session,
                action="auth.refresh.reuse_detected",
                resource_type="refresh_token",
                resource_id=token_id,
                outcome=AuditOutcome.DENIED,
                context=context,
                metadata={"family_id": str(family_id)},
            )
        logger.warning("auth.refresh.reuse_detected", family_id=str(family_id))

    async def _issue_session(
        self,
        *,
        user: User,
        patient: Patient | None,
        context: AuditContext | None,
        family_id: uuid.UUID | None = None,
    ) -> IssuedSession:
        now = datetime.now(UTC)
        access_token, access_expires = security.create_access_token(
            user_id=user.id,
            patient_id=patient.id if patient else None,
            role=user.role.value,
        )
        raw_refresh = security.generate_token()
        refresh_expires = now + timedelta(seconds=self._settings.refresh_token_ttl_seconds)

        self._session.add(
            RefreshToken(
                user_id=user.id,
                token_hash=security.hash_token(raw_refresh),
                family_id=family_id or uuid.uuid4(),
                expires_at=refresh_expires,
                created_at=now,
                user_agent=context.user_agent if context else None,
                ip_address=context.ip_address if context else None,
            )
        )
        await self._session.flush()

        return IssuedSession(
            access_token=access_token,
            access_expires_at=access_expires,
            refresh_token=raw_refresh,
            refresh_expires_at=refresh_expires,
            user=user,
            patient=patient,
        )

    async def _get_user_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def _get_patient_for_user(self, user_id: uuid.UUID) -> Patient | None:
        result = await self._session.execute(select(Patient).where(Patient.user_id == user_id))
        return result.scalar_one_or_none()
