"""Persisting synthetic histories.

Separate from the generator so the planning logic stays pure and testable, and so
the one dangerous part of this feature — writing to a database — is small enough
to read in one sitting.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.config import Settings, get_settings
from eoehelp_api.core.documents import CURRENT_VERSIONS, REQUIRED_AT_ONBOARDING
from eoehelp_api.core.security import FieldCipher
from eoehelp_api.db.session import apply_rls_scope, session_scope
from eoehelp_api.models.clinical import SymptomEntry
from eoehelp_api.models.consent import Consent
from eoehelp_api.models.enums import UserRole, UserStatus
from eoehelp_api.models.medication import Medication, MedicationDose
from eoehelp_api.models.patient import Patient
from eoehelp_api.models.user import User
from eoehelp_api.services import scoring
from eoehelp_api.services.schedules import rrule_for
from eoehelp_api.synthetic.plans import HistoryPlan


class SyntheticDataRefusedError(RuntimeError):
    """Raised rather than writing fabricated records where real ones live."""


@dataclass(frozen=True)
class WrittenHistory:
    patient_id: uuid.UUID
    email: str
    timezone: str
    symptom_entries: int
    medications: int
    doses: int
    first_day: str
    last_day: str
    epochs: list[str]


def assert_writable(settings: Settings | None = None, *, allow_staging: bool = False) -> None:
    """Refuse to fabricate patient records in an environment that holds real ones.

    A data generator with a path to production is a liability, not a convenience:
    invented symptom entries mixed into real ones are indistinguishable afterwards
    and would corrupt both the patient's record and any research export drawn from
    it. Staging is gated separately because it is the one place someone might
    legitimately want a seed, and should still have to say so.
    """
    current = settings or get_settings()
    if current.is_production:
        raise SyntheticDataRefusedError("Refusing to write synthetic patient data in production.")
    if current.environment == "staging" and not allow_staging:
        raise SyntheticDataRefusedError(
            "Writing synthetic data to staging needs allow_staging=True "
            "(or --allow-staging), so that it is a deliberate act."
        )


class SyntheticWriter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._cipher = FieldCipher.from_settings()

    async def write(self, plan: HistoryPlan) -> WrittenHistory:
        zone = ZoneInfo(plan.profile.timezone)

        user = User(
            email=plan.email,
            role=UserRole.PATIENT,
            status=UserStatus.ACTIVE,
            email_verified_at=datetime.now(UTC),
        )
        self._session.add(user)
        await self._session.flush()

        # Same pattern as real onboarding: the id is minted first so the
        # row-level-security scope can be set before the insert, because the
        # policy on `patients` governs INSERT as well as SELECT.
        patient_id = uuid.uuid4()
        await apply_rls_scope(self._session, patient_id)

        patient = Patient(
            id=patient_id,
            user_id=user.id,
            display_name=plan.profile.display_name,
            birth_year=plan.profile.birth_year,
            sex_at_birth=plan.profile.sex_at_birth,
            diagnosis_month=plan.profile.diagnosis_month,
            timezone=plan.profile.timezone,
        )
        self._session.add(patient)
        await self._session.flush()

        self._session.add_all(
            Consent(
                patient_id=patient_id,
                consent_type=consent_type,
                document_version=CURRENT_VERSIONS[consent_type],
                granted=True,
            )
            for consent_type in REQUIRED_AT_ONBOARDING
        )

        for day in plan.days:
            entry_id = uuid.uuid4()
            self._session.add(
                SymptomEntry(
                    id=entry_id,
                    patient_id=patient_id,
                    entry_date=day.entry_date,
                    ate_solid_food=day.ate_solid_food,
                    dysphagia_occurred=day.dysphagia_occurred,
                    dysphagia_severity=day.dysphagia_severity,
                    odynophagia=day.odynophagia,
                    odynophagia_severity=day.odynophagia_severity,
                    food_impaction_er_visit=day.food_impaction_er_visit,
                    coping_actions=day.coping_actions,
                    avoided_foods_today=day.avoided_foods_today,
                    modified_foods_today=day.modified_foods_today,
                    ate_unusually_slowly=day.ate_unusually_slowly,
                    notes_encrypted=self._cipher.encrypt(day.notes, aad=str(entry_id)),
                    entry_method=day.entry_method,
                    instrument_code=scoring.DSQ_CODE,
                    instrument_version=scoring.DSQ_VERSION,
                )
            )

        dose_count = 0
        for medication_plan in plan.medications:
            medication_id = uuid.uuid4()
            self._session.add(
                Medication(
                    id=medication_id,
                    patient_id=patient_id,
                    medication_code=medication_plan.code,
                    dose_amount=medication_plan.dose_amount,
                    dose_unit=medication_plan.dose_unit,
                    schedule_rrule=rrule_for(medication_plan.frequency),
                    started_on=medication_plan.started_on,
                    ended_on=medication_plan.ended_on,
                    stop_reason=medication_plan.stop_reason,
                    prescriber_note_encrypted=self._cipher.encrypt(
                        medication_plan.prescriber_note, aad=str(medication_id)
                    ),
                )
            )
            for dose in medication_plan.doses:
                # The plan carries nominal wall-clock times; they become instants
                # here in the patient's own zone. Interpreting 9pm as UTC would put
                # a Los Angeles dose on the following local day — the exact mistake
                # the adherence filter made.
                self._session.add(
                    MedicationDose(
                        patient_id=patient_id,
                        medication_id=medication_id,
                        taken_at=dose.taken_at.replace(tzinfo=zone),
                        status=dose.status,
                    )
                )
                dose_count += 1

        await self._session.flush()

        # No audit rows. The audit log records who touched a real record and when;
        # fabricating entries would make the one artifact that has to be
        # trustworthy into a mixture of fact and fiction.
        return WrittenHistory(
            patient_id=patient_id,
            email=plan.email,
            timezone=plan.profile.timezone,
            symptom_entries=len(plan.days),
            medications=len(plan.medications),
            doses=dose_count,
            first_day=plan.days[0].entry_date.isoformat() if plan.days else "-",
            last_day=plan.days[-1].entry_date.isoformat() if plan.days else "-",
            epochs=[f"{e.label} ({e.started_on} to {e.ended_on})" for e in plan.epochs],
        )


async def write_history(plan: HistoryPlan, *, allow_staging: bool = False) -> WrittenHistory:
    """Write one history in its own transaction."""
    assert_writable(allow_staging=allow_staging)
    async with session_scope() as session:
        return await SyntheticWriter(session).write(plan)
