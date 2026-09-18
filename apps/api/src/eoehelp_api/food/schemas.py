"""Food and ingredient logging DTOs."""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from eoehelp_api.core.entry_dates import EntryMethod
from eoehelp_api.food.enums import AllergenGroup, FoodDataSource, IngredientProvenance, Meal

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


class ProductRef(BaseModel):
    """Which product was eaten.

    Either a source record, which the server fetches itself — label data is never
    accepted from the client, since the point of it is that it came from the
    label — or an existing snapshot, which is how a recent food is logged again.
    """

    model_config = ConfigDict(extra="forbid")

    source: FoodDataSource | None = None
    source_id: str | None = Field(default=None, min_length=1, max_length=64)
    snapshot_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_form(self) -> "ProductRef":
        by_source = self.source is not None and self.source_id is not None
        partial = (self.source is None) != (self.source_id is None)
        if partial or by_source == (self.snapshot_id is not None):
            raise ValueError("Give either source and source_id, or snapshot_id.")
        return self


class FoodItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eaten_on: date
    meal: Meal
    name: FoodName
    product: ProductRef | None = None
    # With a product these are additions to its label ("with added cheese").
    ingredients: list[IngredientRef] = Field(
        default_factory=list, max_length=MAX_INGREDIENTS_PER_FOOD
    )


class IngredientRead(BaseModel):
    """An ingredient as the patient sees it, from whichever source it came."""

    code: str | None
    custom_ingredient_id: uuid.UUID | None
    name: str
    canonical_key: str
    provenance: IngredientProvenance
    allergen_groups: list[AllergenGroup]
    # True for a dish from the catalog: its groups are the usual recipe's.
    typical: bool
    # False when a label ingredient could not be matched to a standard identity.
    recognized: bool
    depth: int
    note: str | None
    additive_class: str | None


class ProductIngredientRead(BaseModel):
    key: str
    name: str
    depth: int
    recognized: bool
    note: str | None
    allergen_groups: list[AllergenGroup]
    additive_class: str | None


class ProductSummaryRead(BaseModel):
    source: FoodDataSource
    source_id: str
    barcode: str | None
    name: str
    brand: str | None


class ProductRead(ProductSummaryRead):
    """A product's label, freshly looked up and not yet logged."""

    ingredients_text: str | None
    ingredients: list[ProductIngredientRead]
    ingredients_complete: bool
    declared_allergens: list[AllergenGroup]
    may_contain: list[AllergenGroup]
    # From the ingredient list itself; may add to or disagree with the label.
    inferred_allergens: list[AllergenGroup]
    source_updated_at: datetime | None
    attribution: str


class ProductSnapshotRead(ProductSummaryRead):
    """The label snapshot a logged food points at."""

    snapshot_id: uuid.UUID
    ingredients_complete: bool
    declared_allergens: list[AllergenGroup]
    may_contain: list[AllergenGroup]
    fetched_at: datetime
    attribution: str


class FoodItemRead(BaseModel):
    id: uuid.UUID
    eaten_on: date
    meal: Meal
    name: str
    entry_method: EntryMethod
    product: ProductSnapshotRead | None
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
    product: ProductSnapshotRead | None
    # The patient's own additions only when a product is set; its label
    # ingredients come from the snapshot.
    ingredients: list[IngredientRead]
    times_logged: int
    last_eaten_on: date


class CatalogIngredientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    allergen_groups: list[AllergenGroup]
    aliases: list[str]
    canonical_key: str
    is_composite: bool


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
