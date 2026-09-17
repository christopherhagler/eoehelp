"""What a patient ate, down to the ingredient.

Food is logged per day and per meal, with the ingredients of each food stored on
the log item itself. Two decisions shape the tables:

**Ingredients are a snapshot, not a reference to a recipe.** How a patient makes
"my usual pizza" changes, and if the log pointed at a mutable recipe, editing it
would silently rewrite every past day — including days a trigger analysis has
already read. Each item copies its ingredient list at the moment it is logged.

**Catalog and patient ingredients are separate tables.** A single table with a
nullable owner looks simpler, but puts reference rows inside the blast radius of
`TRUNCATE patients CASCADE` and needs split row-level-security policies so the
application can read catalog rows without being able to delete them. Two tables
make both problems impossible instead of carefully avoided, at the price of one
"exactly one of" constraint on the join table.
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eoehelp_api.db.base import Base, Timestamps, UUIDPrimaryKey
from eoehelp_api.models.enums import AllergenGroup, EntryMethod, Meal


def _pg_enum(enum_type: type, name: str) -> Enum:
    return Enum(enum_type, name=name, values_callable=lambda e: [m.value for m in e])


def _allergen_array() -> postgresql.ARRAY[Any]:
    return postgresql.ARRAY(_pg_enum(AllergenGroup, "allergen_group"))


class CatalogIngredient(Base):
    """Reference ingredients, tagged with the allergen groups they belong to.

    Keyed on a slug like the medication catalog, for the same reasons: it is not
    patient data, the seed stays idempotent, and a stable key lets synthetic
    histories and golden files name ingredients without looking up a UUID. Not
    patient-scoped, so no row-level security.
    """

    __tablename__ = "ingredient_catalog"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    allergen_groups: Mapped[list[AllergenGroup]] = mapped_column(
        _allergen_array(), nullable=False, default=list
    )
    # Lower-case alternative names matched when a patient types rather than picks,
    # so "flour" finds wheat flour instead of becoming an untagged custom entry
    # that no allergen-group analysis would ever count.
    aliases: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(String(120)), nullable=False, default=list
    )


class CustomIngredient(UUIDPrimaryKey, Base):
    """An ingredient the catalog does not have, owned by one patient.

    Created implicitly when a typed name matches nothing, so logging is never
    blocked on the catalog being complete. The patient can tag allergen groups
    afterwards; until then it counts in ingredient-level analysis only.
    """

    __tablename__ = "custom_ingredients"
    __table_args__ = (
        # One row per name per patient, compared case- and space-insensitively.
        # Without it "Hot sauce" and "hot sauce " would be two ingredients, and an
        # exposure analysis would halve the evidence for each.
        UniqueConstraint(
            "patient_id", "name_key", name="uq_custom_ingredients_patient_id_name_key"
        ),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Free text the patient typed. Under row-level security like everything
    # patient-owned, and excluded from research export: a name can say anything.
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_key: Mapped[str] = mapped_column(String(120), nullable=False)
    allergen_groups: Mapped[list[AllergenGroup]] = mapped_column(
        _allergen_array(), nullable=False, default=list
    )


class FoodLogItem(UUIDPrimaryKey, Timestamps, Base):
    """One food eaten on one day.

    Not tied to the symptom entry by a foreign key. A patient may log breakfast
    before deciding how the day went, or log food on a day they never rate, and
    the day is the join key either way.
    """

    __tablename__ = "food_log_items"
    __table_args__ = (Index("ix_food_log_items_patient_id_eaten_on", "patient_id", "eaten_on"),)

    patient_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
    )
    eaten_on: Mapped[date] = mapped_column(Date, nullable=False)
    meal: Mapped[Meal] = mapped_column(_pg_enum(Meal, "meal"), nullable=False)

    # What the patient calls it: "turkey sandwich". Free text, so excluded from
    # research export; the ingredients are the analysable part.
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_key: Mapped[str] = mapped_column(String(120), nullable=False)

    # Derived like the symptom entry's, so research can weigh recalled meals —
    # arguably more prone to recall error than symptoms are.
    entry_method: Mapped[EntryMethod] = mapped_column(
        _pg_enum(EntryMethod, "entry_method"), nullable=False
    )

    ingredients: Mapped[list["FoodLogItemIngredient"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="FoodLogItemIngredient.position",
        lazy="selectin",
    )


class FoodLogItemIngredient(UUIDPrimaryKey, Base):
    """One ingredient of one logged food, frozen at the time it was logged."""

    __tablename__ = "food_log_item_ingredients"
    __table_args__ = (
        CheckConstraint(
            "(ingredient_code IS NULL) <> (custom_ingredient_id IS NULL)",
            name="exactly_one_ingredient",
        ),
        UniqueConstraint(
            "item_id", "ingredient_code", name="uq_food_log_item_ingredients_item_id_code"
        ),
        UniqueConstraint(
            "item_id",
            "custom_ingredient_id",
            name="uq_food_log_item_ingredients_item_id_custom",
        ),
        Index("ix_food_log_item_ingredients_patient_id", "patient_id"),
    )

    # Carried on the join row too, so row-level security can bind here directly
    # rather than depending on a join back to the parent item.
    patient_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("food_log_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    ingredient_code: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("ingredient_catalog.code", name="fk_food_log_item_ingredients_ingredient_code"),
    )
    custom_ingredient_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        # NO ACTION rather than RESTRICT: both are refused for a lone delete, but
        # NO ACTION is checked at the end of the statement, so deleting a patient
        # can cascade through this table and custom_ingredients in either order.
        ForeignKey(
            "custom_ingredients.id", name="fk_food_log_item_ingredients_custom_ingredient_id"
        ),
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    item: Mapped[FoodLogItem] = relationship(back_populates="ingredients")
    catalog: Mapped[CatalogIngredient | None] = relationship(lazy="joined")
    custom: Mapped[CustomIngredient | None] = relationship(lazy="joined")
