"""Patient profile and onboarding DTOs."""

import uuid
import zoneinfo
from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eoehelp_api.identity.documents import MINIMUM_AGE_YEARS
from eoehelp_api.identity.enums import SexAtBirth


def _validate_timezone(value: str) -> str:
    try:
        zoneinfo.ZoneInfo(value)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Unrecognised timezone.") from exc
    return value


def check_diagnosis_month(diagnosis_month: date | None, *, birth_year: int | None) -> None:
    """A diagnosis cannot be in the future, or before the patient was born.

    Month precision, so "this month" is always allowed: a patient in a timezone
    ahead of the server may already be in next month's first day.
    """
    if diagnosis_month is None:
        return
    first_of_next_month = (date.today().replace(day=1) + timedelta(days=32)).replace(day=1)
    if diagnosis_month >= first_of_next_month:
        raise ValueError("The diagnosis month cannot be in the future.")
    if birth_year is not None and diagnosis_month.year < birth_year:
        raise ValueError("The diagnosis month cannot be before the year you were born.")


class ConsentAcceptance(BaseModel):
    """The three documents required to hold an account.

    Three separate booleans rather than one "I agree": Washington's My Health My
    Data Act requires specific consent to the consumer health data disclosure,
    and a single checkbox covering everything is exactly what it prohibits.
    Research participation is deliberately not here — it is a separate decision,
    made later, and never a condition of using the product.
    """

    model_config = ConfigDict(extra="forbid")

    terms_of_service: bool
    privacy_policy: bool
    consumer_health_data: bool

    @model_validator(mode="after")
    def _all_required(self) -> "ConsentAcceptance":
        missing = [
            name
            for name, given in (
                ("terms_of_service", self.terms_of_service),
                ("privacy_policy", self.privacy_policy),
                ("consumer_health_data", self.consumer_health_data),
            )
            if not given
        ]
        if missing:
            raise ValueError(f"These must be accepted to create a record: {', '.join(missing)}")
        return self


class OnboardingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Whatever the patient wants to be called, including on the report they hand
    # their doctor. Not required, and not verified against anything.
    display_name: str | None = Field(default=None, max_length=120)

    # Year, not date of birth. A full DOB is a direct HIPAA Safe Harbor identifier
    # with outsized re-identification value, and year is enough to enforce the
    # adults-only launch gate.
    birth_year: int = Field(ge=1900, le=2100)

    sex_at_birth: SexAtBirth | None = None

    # Month precision, stored as the first of that month. EoE diagnosis dates are
    # remembered as "around March" and the extra precision would be false.
    diagnosis_month: date | None = None

    # Load-bearing, not a display preference: "today" for a daily log has to be
    # the patient's today. Scored against UTC, an evening entry in Seattle lands
    # on tomorrow and silently becomes a backfill.
    timezone: str = Field(default="UTC", max_length=64)

    consents: ConsentAcceptance

    _check_timezone = field_validator("timezone")(_validate_timezone)

    @field_validator("diagnosis_month")
    @classmethod
    def _to_first_of_month(cls, value: date | None) -> date | None:
        return value.replace(day=1) if value is not None else None

    @model_validator(mode="after")
    def _must_be_an_adult(self) -> "OnboardingRequest":
        # Year arithmetic, so someone turning 18 this year passes. The precision
        # the gate deserves is bounded by the precision of what we store.
        if date.today().year - self.birth_year < MINIMUM_AGE_YEARS:
            raise ValueError(
                f"eoehelp is currently available to people aged {MINIMUM_AGE_YEARS} and over."
            )
        check_diagnosis_month(self.diagnosis_month, birth_year=self.birth_year)
        return self


class PatientProfileUpdate(BaseModel):
    """Every field optional: this is a PATCH, and an absent field is untouched.

    birth_year and sex_at_birth are absent on purpose. They gate eligibility and
    describe the research cohort, so changing them is a support action with an
    audit trail, not a profile edit.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=120)
    diagnosis_month: date | None = None
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str | None) -> str | None:
        return _validate_timezone(value) if value is not None else None

    @field_validator("diagnosis_month")
    @classmethod
    def _to_first_of_month(cls, value: date | None) -> date | None:
        return value.replace(day=1) if value is not None else None


class PatientProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # UUID rather than str so it round-trips from the ORM without hand-coercion,
    # and still serialises as a string over the wire.
    id: uuid.UUID
    display_name: str | None
    birth_year: int | None
    sex_at_birth: SexAtBirth | None
    diagnosis_month: date | None
    timezone: str
    created_at: datetime


class ConsentRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    consent_type: str
    document_version: str
    granted: bool
    granted_at: datetime


class OnboardingResponse(BaseModel):
    """Carries a fresh access token because the old one predates the patient row.

    The access token embeds the patient id, and every patient-scoped route reads
    it from there rather than from the request. Returning a new token here saves
    the client an immediate refresh round trip to become usable.
    """

    patient: PatientProfile
    consents: list[ConsentRecord]
    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime
