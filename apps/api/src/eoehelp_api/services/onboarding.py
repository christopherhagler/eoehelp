"""Account onboarding: the patient record and the consents that permit it to exist."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.core import security
from eoehelp_api.core.documents import CURRENT_VERSIONS, REQUIRED_AT_ONBOARDING
from eoehelp_api.core.errors import BadRequestError, ConflictError, NotFoundError
from eoehelp_api.db.session import apply_rls_scope
from eoehelp_api.models.consent import Consent
from eoehelp_api.models.patient import Patient
from eoehelp_api.models.user import User
from eoehelp_api.schemas.patient import (
    OnboardingRequest,
    PatientProfileUpdate,
    check_diagnosis_month,
)
from eoehelp_api.services import audit
from eoehelp_api.services.audit import AuditContext


@dataclass(frozen=True)
class OnboardedPatient:
    patient: Patient
    consents: list[Consent]
    access_token: str
    access_expires_at: datetime


class OnboardingService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def complete(
        self,
        *,
        user: User,
        payload: OnboardingRequest,
        context: AuditContext | None = None,
    ) -> OnboardedPatient:
        """Create the patient record and its consent rows in one transaction.

        Either both land or neither does. A patient record without the consent
        that permitted it is data held without a lawful basis, and a consent row
        pointing at a patient that does not exist is unusable evidence.
        """
        existing = await self._session.execute(select(Patient).where(Patient.user_id == user.id))
        if existing.scalar_one_or_none() is not None:
            raise ConflictError("This account already has a patient record.")

        # The id is minted here, before the insert, so the row-level-security
        # scope can be set first. The policy on `patients` governs INSERT as well
        # as SELECT, so an unscoped session cannot create the very row it is
        # about to own. Setting the scope up front also keeps the invariant that
        # a transaction only ever touches one patient.
        patient_id = uuid.uuid4()
        await apply_rls_scope(self._session, patient_id)

        patient = Patient(
            id=patient_id,
            user_id=user.id,
            display_name=payload.display_name,
            birth_year=payload.birth_year,
            sex_at_birth=payload.sex_at_birth,
            diagnosis_month=payload.diagnosis_month,
            timezone=payload.timezone,
        )
        self._session.add(patient)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # A double-tapped submit races the check above; the unique constraint
            # on user_id catches the loser, which should read as a conflict, not
            # as a server error.
            raise ConflictError("This account already has a patient record.") from exc

        consents = [
            Consent(
                patient_id=patient.id,
                consent_type=consent_type,
                document_version=CURRENT_VERSIONS[consent_type],
                granted=True,
                ip_address=context.ip_address if context else None,
                user_agent=context.user_agent if context else None,
            )
            for consent_type in REQUIRED_AT_ONBOARDING
        ]
        self._session.add_all(consents)
        await self._session.flush()

        await audit.record(
            self._session,
            action="patient.create",
            resource_type="patient",
            resource_id=patient.id,
            patient_id=patient.id,
            context=context,
            # Field names and versions only. What the patient typed into
            # display_name is PHI and has no business in the audit trail.
            metadata={
                "fields": sorted(payload.model_dump(exclude={"consents"}).keys()),
                "timezone": payload.timezone,
            },
        )
        for consent in consents:
            await audit.record(
                self._session,
                action="consent.grant",
                resource_type="consent",
                resource_id=consent.id,
                patient_id=patient.id,
                context=context,
                metadata={
                    "consent_type": consent.consent_type.value,
                    "document_version": consent.document_version,
                },
            )

        access_token, expires_at = security.create_access_token(
            user_id=user.id, patient_id=patient.id, role=user.role.value
        )
        return OnboardedPatient(
            patient=patient,
            consents=consents,
            access_token=access_token,
            access_expires_at=expires_at,
        )

    async def get_profile(self, patient_id: uuid.UUID) -> Patient:
        patient = await self._session.get(Patient, patient_id)
        if patient is None:
            raise NotFoundError("No patient record.")
        return patient

    async def update_profile(
        self,
        *,
        patient_id: uuid.UUID,
        payload: PatientProfileUpdate,
        context: AuditContext | None = None,
    ) -> Patient:
        patient = await self.get_profile(patient_id)
        changes = payload.model_dump(exclude_unset=True)
        if "diagnosis_month" in changes:
            try:
                check_diagnosis_month(changes["diagnosis_month"], birth_year=patient.birth_year)
            except ValueError as exc:
                raise BadRequestError(str(exc)) from exc
        for field, value in changes.items():
            setattr(patient, field, value)
        await self._session.flush()

        await audit.record(
            self._session,
            action="patient.update",
            resource_type="patient",
            resource_id=patient.id,
            patient_id=patient.id,
            context=context,
            metadata={"fields": sorted(changes.keys())},
        )
        return patient

    async def current_consents(self, patient_id: uuid.UUID) -> list[Consent]:
        """The latest row per consent type.

        The table is append-only, so "current" is a question about ordering
        rather than about the newest write having overwritten anything.
        """
        result = await self._session.execute(
            select(Consent)
            .where(Consent.patient_id == patient_id)
            .order_by(Consent.consent_type, Consent.granted_at.desc())
        )
        latest: dict[str, Consent] = {}
        for consent in result.scalars():
            latest.setdefault(consent.consent_type.value, consent)
        return list(latest.values())

    async def delete_account(
        self,
        *,
        user_id: uuid.UUID,
        patient_id: uuid.UUID,
        context: AuditContext | None = None,
    ) -> None:
        """Erase the record, keeping the trail that it existed and was erased.

        Washington's My Health My Data Act gives a working deletion right, and
        the product promises the deletion is real — so this removes rows rather
        than setting a flag. Clinical data, consents, and tokens go with the user
        through ON DELETE CASCADE.

        The audit log deliberately survives. It carries no FK to users or
        patients precisely so that it can outlive them, and it holds field names
        rather than values, so what remains is evidence of access and erasure
        rather than a copy of the deleted record. Those two requirements pull
        against each other and both are tested.
        """
        user = await self._session.get(User, user_id)
        if user is None:
            raise NotFoundError("No account.")

        await audit.record(
            self._session,
            action="account.delete",
            resource_type="user",
            resource_id=user_id,
            patient_id=patient_id,
            context=context,
        )
        await self._session.delete(user)
        await self._session.flush()
