"""Value types describing a synthetic patient history.

Plain dataclasses rather than ORM objects, because planning a history and writing
one are separate problems. The plan is pure and deterministic, so the properties
that matter — that treatment visibly helps, that adherence decays, that no day
violates the API's own validation rules — are testable without a database.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from eoehelp_api.models.enums import (
    CopingAction,
    DoseStatus,
    DysphagiaSeverity,
    EntryMethod,
    MedicationStopReason,
    SexAtBirth,
)
from eoehelp_api.services.schedules import DoseFrequency


@dataclass(frozen=True)
class ProfilePlan:
    display_name: str
    birth_year: int
    sex_at_birth: SexAtBirth
    diagnosis_month: date
    timezone: str


@dataclass(frozen=True)
class DayPlan:
    """One symptom entry, already satisfying the instrument's coherence rules."""

    entry_date: date
    ate_solid_food: bool
    dysphagia_occurred: bool | None
    dysphagia_severity: DysphagiaSeverity | None
    odynophagia: bool | None
    odynophagia_severity: int | None
    coping_actions: list[CopingAction]
    food_impaction_er_visit: bool
    avoided_foods_today: bool
    modified_foods_today: bool
    ate_unusually_slowly: bool
    notes: str | None
    entry_method: EntryMethod


@dataclass(frozen=True)
class DosePlan:
    taken_at: datetime
    status: DoseStatus


@dataclass(frozen=True)
class MedicationPlan:
    code: str
    frequency: DoseFrequency
    dose_amount: Decimal | None
    dose_unit: str | None
    started_on: date
    ended_on: date | None
    stop_reason: MedicationStopReason | None
    prescriber_note: str | None
    doses: list[DosePlan] = field(default_factory=list)


@dataclass(frozen=True)
class EpochPlan:
    """A stretch of time under one treatment approach.

    Carried through to the summary so a demo or a test fixture can be described
    in a sentence — "PPI for 10 weeks, stopped as ineffective, then budesonide" —
    rather than only as a row count.
    """

    label: str
    started_on: date
    ended_on: date
    severity_level: int


@dataclass(frozen=True)
class HistoryPlan:
    email: str
    profile: ProfilePlan
    days: list[DayPlan]
    medications: list[MedicationPlan]
    epochs: list[EpochPlan]

    @property
    def dose_count(self) -> int:
        return sum(len(m.doses) for m in self.medications)
