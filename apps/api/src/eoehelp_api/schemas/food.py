"""Food and ingredient logging DTOs."""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from eoehelp_api.models.enums import AllergenGroup, EntryMethod, Meal

MAX_INGREDIENTS_PER_FOOD = 40
NAME_MAX_LENGTH = 120


def normalise_name(value: str) -> str:
    """Collapse internal whitespace and trim, keeping the patient's casing."""
    return " ".join(value.split())


def name_key(value: str) -> str:
    """The comparison form of a name: what makes "Hot sauce " and "hot sauce" one."""
    return normalise_name(value).casefold()


def _non_blank(value: str) -> str:
    cleaned = normalise_name(value)
    if not cleaned:
        raise ValueError("must not be blank")
    return cleaned


FoodName = Annotated[str, Field(max_length=NAME_MAX_LENGTH), AfterValidator(_non_blank)]


class IngredientRef(BaseModel):
    """One ingredient of a food, in exactly one of three forms.

    - `code`: a catalog ingredient the patient picked.
    - `custom_ingredient_id`: one of the patient's own ingredients.
    - `name`: typed text. The server matches it against the catalog (names and
      aliases) and the patient's own ingredients, and creates a new one of the
      patient's only if nothing matches — so a typed "flour" still counts as wheat.

    `allergen_groups` applies only when a typed name creates a new ingredient.
    Catalog groups are authoritative, and an existing ingredient's groups are
    changed through its own endpoint rather than as a side effect of logging.
    """

    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, max_length=64)
    custom_ingredient_id: uuid.UUID | None = None
    name: FoodName | None = None
    allergen_groups: list[AllergenGroup] | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "IngredientRef":
        given = [self.code, self.custom_ingredient_id, self.name]
        if sum(value is not None for value in given) != 1:
            raise ValueError("Give exactly one of code, custom_ingredient_id, or name.")
        if self.allergen_groups is not None and self.name is None:
            raise ValueError(
                "allergen_groups can only be set when adding a new ingredient by name."
            )
        return self


class FoodItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eaten_on: date
    meal: Meal
    name: FoodName
    ingredients: list[IngredientRef] = Field(
        default_factory=list, max_length=MAX_INGREDIENTS_PER_FOOD
    )


class IngredientRead(BaseModel):
    """An ingredient as the patient sees it, from whichever table it lives in."""

    code: str | None
    custom_ingredient_id: uuid.UUID | None
    name: str
    allergen_groups: list[AllergenGroup]


class FoodItemRead(BaseModel):
    id: uuid.UUID
    eaten_on: date
    meal: Meal
    name: str
    entry_method: EntryMethod
    ingredients: list[IngredientRead]
    created_at: datetime
    updated_at: datetime


class FoodItemList(BaseModel):
    range_start: date
    range_end: date
    items: list[FoodItemRead]


class RecentFood(BaseModel):
    """A food the patient has logged before, ready to log again in one tap.

    The ingredients are those of the most recent time it was logged, which is the
    best guess at how the patient makes it now.
    """

    name: str
    meal: Meal
    ingredients: list[IngredientRead]
    times_logged: int
    last_eaten_on: date


class CatalogIngredientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    allergen_groups: list[AllergenGroup]
    aliases: list[str]


class CustomIngredientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    allergen_groups: list[AllergenGroup]


class CustomIngredientUpdate(BaseModel):
    """Rename an ingredient or tag its allergen groups.

    Retagging applies to every past day it was eaten, deliberately: the tag
    describes what the ingredient is, and "hot sauce turned out to contain soy"
    is a correction to history, not a change from now on.
    """

    model_config = ConfigDict(extra="forbid")

    name: FoodName | None = None
    allergen_groups: list[AllergenGroup] | None = None
