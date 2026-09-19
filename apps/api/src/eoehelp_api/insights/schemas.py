"""Food-pattern response models."""

from datetime import date

from pydantic import BaseModel

from eoehelp_api.food.enums import AllergenGroup
from eoehelp_api.insights.food_patterns import PatternStatus


class FoodPatternRead(BaseModel):
    """One allergen group, ingredient, or additive class, and what the log shows for it.

    Allergen groups carry a tested status. Ingredients and additive classes are
    `counts_only` in v1: what happened on the days they were eaten, with no
    verdict attached.
    """

    key: str
    # Display name: the group, the ingredient as logged, or the additive class.
    label: str
    status: PatternStatus
    exposed_days: int
    exposed_symptom_days: int
    unexposed_days: int
    unexposed_symptom_days: int
    explained_by: AllergenGroup | None
    often_with: AllergenGroup | None
    same_day_only: bool
    # For the doctor report and for review. The patient screen never shows them.
    risk_difference: float | None
    q_value: float | None


class FoodPatternReport(BaseModel):
    method_version: str
    # The analysis window: the 540 days ending on the patient's today, whether or
    # not the log reaches back that far. analyzable_days says how much had data.
    window_start: date
    window_end: date
    lag_days: int
    # Days meeting the logging rule, and how many of them were symptom days.
    analyzable_days: int
    symptom_days: int
    # Symptom entries in the window, for context.
    logged_days: int
    # Diagnostics for the logging-gap review; not shown to the patient.
    complete_window_share: float | None
    logging_gap: float | None
    groups: list[FoodPatternRead]
    ingredients: list[FoodPatternRead]
    additives: list[FoodPatternRead]
