"""Medication, schedule, dose, and adherence DTOs."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eoehelp_api.models.enums import DoseStatus, DrugClass, MedicationStopReason
from eoehelp_api.services.schedules import DoseFrequency


class MedicationCatalogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    generic_name: str
    drug_class: DrugClass
    default_route: str | None
    default_unit: str | None
    # Brand names, because a prescription label rarely says "budesonide oral
    # suspension" and a patient should be able to find what they were handed.
    also_known_as: str | None


class MedicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medication_code: str = Field(max_length=64)
    dose_amount: Decimal | None = Field(default=None, gt=0, le=100000, decimal_places=2)
    dose_unit: str | None = Field(default=None, max_length=32)

    # A frequency from a fixed list, never an RRULE. The rule is built server-side
    # — see services/schedules.py for why accepting one would be a mistake.
    frequency: DoseFrequency

    started_on: date
    prescriber_note: str | None = Field(default=None, max_length=2000)


class MedicationStop(BaseModel):
    """Stopping records both when and why.

    The reason is required rather than optional, because "stopped because it did
    not work" and "stopped because insurance refused it" lead a clinician to
    opposite next steps, and an unexplained end date loses that distinction
    permanently.
    """

    model_config = ConfigDict(extra="forbid")

    ended_on: date
    stop_reason: MedicationStopReason


class MedicationRead(BaseModel):
    id: uuid.UUID
    medication_code: str
    generic_name: str
    drug_class: DrugClass
    dose_amount: Decimal | None
    dose_unit: str | None
    frequency: DoseFrequency | None
    started_on: date
    ended_on: date | None
    stop_reason: MedicationStopReason | None
    prescriber_note: str | None
    is_active: bool


class DoseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Optional so the common case — tapping "took it" — needs no body at all. When
    # absent the server timestamps it, which is also the only trustworthy version.
    taken_at: datetime | None = None
    status: DoseStatus = DoseStatus.TAKEN


class DoseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    medication_id: uuid.UUID
    taken_at: datetime
    status: DoseStatus


class MedicationTodayItem(BaseModel):
    """One active medication, as the daily log needs to show it."""

    medication_id: uuid.UUID
    medication_code: str
    generic_name: str
    dose_label: str | None
    frequency: DoseFrequency | None
    expected_today: int | None
    doses_today: list[DoseRead]


class MedicationToday(BaseModel):
    on_date: date
    items: list[MedicationTodayItem]


class AdherenceRead(BaseModel):
    """Adherence, or an explicit admission that it cannot be measured.

    `percentage` is null for an as-needed medication and for a window outside the
    course. Null is not zero: rendering "unknown" as 0% would show a patient
    ignoring their treatment when in fact there was no expectation to meet.
    """

    medication_id: uuid.UUID
    medication_code: str
    generic_name: str
    frequency: DoseFrequency | None
    window_start: date
    window_end: date
    expected_doses: int | None
    taken_doses: int
    skipped_doses: int
    percentage: float | None


class AdherenceSummary(BaseModel):
    window_start: date
    window_end: date
    medications: list[AdherenceRead]

    @model_validator(mode="after")
    def _window_is_ordered(self) -> "AdherenceSummary":
        if self.window_end < self.window_start:
            raise ValueError("window_end precedes window_start")
        return self
