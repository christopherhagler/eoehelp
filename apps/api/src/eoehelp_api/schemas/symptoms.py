"""Daily symptom log DTOs.

The coherence rules here duplicate the check constraints in migration 0002 on
purpose. The database constraint is the guarantee; this layer exists so a client
that gets it wrong receives a 422 naming the field rather than a 500 from a
constraint violation.
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eoehelp_api.models.enums import DysphagiaRelief, EntryMethod


class SymptomEntryInput(BaseModel):
    """One day, as the patient answers it.

    entry_date is absent deliberately: it comes from the URL, so a body and a
    path cannot disagree about which day is being written.
    """

    model_config = ConfigDict(extra="forbid")

    # DSQ question 1.
    ate_solid_food: bool

    # DSQ question 2, required on a day with solid food.
    dysphagia_occurred: bool | None = None
    # DSQ question 3, required exactly when question 2 is yes.
    dysphagia_relief: DysphagiaRelief | None = None

    # Pain on swallowing, 1-3 when present. Scored separately from the DSQ total.
    odynophagia: bool | None = None
    odynophagia_severity: int | None = Field(default=None, ge=0, le=3)

    food_impaction_er_visit: bool = False

    avoided_foods_today: bool = False
    modified_foods_today: bool = False
    ate_unusually_slowly: bool = False

    # Encrypted at rest with the record id as additional authenticated data.
    # Never required, and never included in research export.
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _coherent(self) -> "SymptomEntryInput":
        if not self.ate_solid_food and (
            self.dysphagia_occurred is not None or self.dysphagia_relief is not None
        ):
            raise ValueError(
                "A day without solid food has no dysphagia answer: the instrument asks "
                "about swallowing food."
            )
        if self.ate_solid_food and self.dysphagia_occurred is None:
            raise ValueError(
                "dysphagia_occurred is required on a day with solid food: without it the "
                "day cannot be scored."
            )
        if bool(self.dysphagia_occurred) != (self.dysphagia_relief is not None):
            raise ValueError(
                "dysphagia_relief is answered exactly when food went down slowly or stuck."
            )
        if self.odynophagia is False and self.odynophagia_severity not in (None, 0):
            raise ValueError("odynophagia_severity must be absent or 0 when there was no pain.")
        if self.odynophagia and not self.odynophagia_severity:
            raise ValueError("odynophagia_severity is required when swallowing was painful.")
        if (
            self.food_impaction_er_visit
            and self.dysphagia_relief is not DysphagiaRelief.SOUGHT_MEDICAL_ATTENTION
        ):
            raise ValueError(
                "An emergency visit for stuck food means dysphagia_relief is "
                "'sought_medical_attention'."
            )
        return self


class SymptomEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entry_date: date
    ate_solid_food: bool
    dysphagia_occurred: bool | None
    dysphagia_relief: DysphagiaRelief | None
    odynophagia: bool | None
    odynophagia_severity: int | None
    food_impaction_er_visit: bool
    avoided_foods_today: bool
    modified_foods_today: bool
    ate_unusually_slowly: bool
    notes: str | None

    # Derived server-side from the patient's own timezone, never accepted from
    # the client: research weights same-day entries above recalled ones.
    entry_method: EntryMethod
    instrument_code: str
    instrument_version: str

    # The DSQ points for the day, 0-6 (question 2 yes = 2, plus question 3's
    # 0-4), or null for a day the instrument cannot score. Returned so the UI
    # never has to reimplement it.
    daily_score: int | None = None

    created_at: datetime
    updated_at: datetime


class SymptomEntryList(BaseModel):
    entries: list[SymptomEntryRead]
    range_start: date
    range_end: date


class SymptomBurdenRead(BaseModel):
    """A scored window, or an explicit null score with the reason in components.

    `score` is null rather than zero when too few days were logged. Dividing three
    answered days across a fourteen-day window would render a badly-tracked
    fortnight as remission, which is the most damaging thing this endpoint could
    get wrong.
    """

    period_start: date
    period_end: date
    instrument_code: str
    instrument_version: str
    days_in_window: int
    days_logged: int
    days_scorable: int
    max_score: int
    score: float | None
    components: dict[str, Any]


class SymptomBurdenTrend(BaseModel):
    points: list[SymptomBurdenRead]
