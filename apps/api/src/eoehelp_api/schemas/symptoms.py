"""Daily symptom log DTOs.

The coherence rules here duplicate the check constraints in migration 0002 on
purpose. The database constraint is the guarantee; this layer exists so a client
that gets it wrong receives a 422 naming the field rather than a 500 from a
constraint violation.
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eoehelp_api.models.enums import CopingAction, DysphagiaSeverity, EntryMethod


class SymptomEntryInput(BaseModel):
    """One day, as the patient answers it.

    entry_date is absent deliberately: it comes from the URL, so a body and a
    path cannot disagree about which day is being written.
    """

    model_config = ConfigDict(extra="forbid")

    ate_solid_food: bool

    dysphagia_occurred: bool | None = None
    dysphagia_severity: DysphagiaSeverity | None = None

    odynophagia: bool | None = None
    odynophagia_severity: int | None = Field(default=None, ge=0, le=3)

    food_impaction_er_visit: bool = False
    coping_actions: list[CopingAction] = Field(default_factory=list)

    avoided_foods_today: bool = False
    modified_foods_today: bool = False
    ate_unusually_slowly: bool = False

    # Encrypted at rest with the record id as additional authenticated data.
    # Never required, and never included in research export.
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _coherent(self) -> "SymptomEntryInput":
        if not self.ate_solid_food and (
            self.dysphagia_occurred is not None or self.dysphagia_severity is not None
        ):
            raise ValueError(
                "A day without solid food has no dysphagia answer: the instrument asks "
                "about swallowing food."
            )
        if self.dysphagia_occurred and self.dysphagia_severity is None:
            raise ValueError("dysphagia_severity is required when food went down slowly or stuck.")
        if self.dysphagia_occurred is False and self.dysphagia_severity not in (
            None,
            DysphagiaSeverity.NONE,
        ):
            raise ValueError("dysphagia_severity must be absent or 'none' when nothing stuck.")
        if self.odynophagia is False and self.odynophagia_severity not in (None, 0):
            raise ValueError("odynophagia_severity must be absent or 0 when there was no pain.")
        if self.odynophagia and not self.odynophagia_severity:
            raise ValueError("odynophagia_severity is required when swallowing was painful.")
        # An ER visit is recorded on its own column as well as in coping_actions,
        # because the report flags it separately; keep them from contradicting.
        if CopingAction.ER_VISIT in self.coping_actions and not self.food_impaction_er_visit:
            raise ValueError(
                "food_impaction_er_visit must be true when 'er_visit' is a coping action."
            )
        return self

    @property
    def deduplicated_coping_actions(self) -> list[CopingAction]:
        """Order-preserving deduplication: a client repeating a chip is not an error."""
        return list(dict.fromkeys(self.coping_actions))


class SymptomEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entry_date: date
    ate_solid_food: bool
    dysphagia_occurred: bool | None
    dysphagia_severity: DysphagiaSeverity | None
    odynophagia: bool | None
    odynophagia_severity: int | None
    food_impaction_er_visit: bool
    coping_actions: list[CopingAction]
    avoided_foods_today: bool
    modified_foods_today: bool
    ate_unusually_slowly: bool
    notes: str | None

    # Derived server-side from the patient's own timezone, never accepted from
    # the client: research weights same-day entries above recalled ones.
    entry_method: EntryMethod
    instrument_code: str
    instrument_version: str

    # The score for the day this entry belongs to, 0-6, or null for a day the
    # instrument cannot score. Returned so the UI never has to reimplement it.
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
