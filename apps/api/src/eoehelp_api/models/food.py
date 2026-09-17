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
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eoehelp_api.db.base import Base, Timestamps, UUIDPrimaryKey
from eoehelp_api.models.enums import (
    AllergenGroup,
    EntryMethod,
    FoodDataSource,
    IngredientProvenance,
    Meal,
)


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
    # The same identity a label ingredient gets (fooddata/vocabulary.py), so
    # "egg" picked from this list and "EGGS" read off a label are one thing.
    canonical_key: Mapped[str] = mapped_column(String(160), nullable=False)
    # A dish rather than an ingredient: mayonnaise, bread, soy sauce. Its groups
    # are what the usual recipe contains, not a fact about what was eaten, and
    # the screen says so and suggests scanning the actual product.
    is_composite: Mapped[bool] = mapped_column(nullable=False, default=False)


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
    # Fixed at creation. A recognized name ("sodium benzoate") gets its standard
    # key, so it lines up with the same ingredient read off a label.
    canonical_key: Mapped[str] = mapped_column(String(160), nullable=False)
    allergen_groups: Mapped[list[AllergenGroup]] = mapped_column(
        _allergen_array(), nullable=False, default=list
    )


class FoodProduct(UUIDPrimaryKey, Base):
    """A snapshot of one product's label, as a source reported it.

    Public data, so not patient-scoped: the link between a patient and a product
    lives only in their own log rows. Snapshots are immutable — the application
    role may insert and read, never update or delete — because a logged meal
    must keep pointing at the label as it was. A changed label is a new row.
    """

    __tablename__ = "food_products"
    __table_args__ = (
        UniqueConstraint(
            "source", "source_id", "content_hash", name="uq_food_products_source_version"
        ),
        Index("ix_food_products_barcode", "barcode"),
    )

    source: Mapped[FoodDataSource] = mapped_column(
        _pg_enum(FoodDataSource, "food_data_source"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(14))
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(200))
    ingredients_text: Mapped[str | None] = mapped_column(Text)
    # Flattened, in reading order: [{key, name, depth, recognized, note}].
    ingredients: Mapped[list[dict[str, Any]]] = mapped_column(
        postgresql.JSONB, nullable=False, default=list
    )
    ingredients_complete: Mapped[bool] = mapped_column(nullable=False)
    declared_allergens: Mapped[list[AllergenGroup]] = mapped_column(
        _allergen_array(), nullable=False, default=list
    )
    may_contain: Mapped[list[AllergenGroup]] = mapped_column(
        _allergen_array(), nullable=False, default=list
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
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

    # The exact label snapshot, when the food was a scanned or searched product.
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("food_products.id")
    )
    product: Mapped[FoodProduct | None] = relationship(lazy="joined")

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
        # A patient's ingredient points at the catalog or at their own list; a
        # label ingredient points at neither, and is identified by its key.
        CheckConstraint(
            "CASE provenance WHEN 'label' "
            "THEN ingredient_code IS NULL AND custom_ingredient_id IS NULL "
            "ELSE (ingredient_code IS NULL) <> (custom_ingredient_id IS NULL) END",
            name="ingredient_matches_provenance",
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

    # Snapshotted for every row, so exposure queries need no joins and a label
    # ingredient, which has no row elsewhere, has an identity at all.
    canonical_key: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(String(300), nullable=False)
    provenance: Mapped[IngredientProvenance] = mapped_column(
        _pg_enum(IngredientProvenance, "ingredient_provenance"), nullable=False
    )
    # Nesting within a label: "WATER" inside "MUSTARD (WATER, ...)" is depth 1.
    depth: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0")
    )
    # False when a label ingredient could not be matched to a standard identity.
    recognized: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default=text("true")
    )
    # A label's stated purpose: "to protect freshness", "sweetener".
    note: Mapped[str | None] = mapped_column(String(200))

    item: Mapped[FoodLogItem] = relationship(back_populates="ingredients")
    catalog: Mapped[CatalogIngredient | None] = relationship(lazy="joined")
    custom: Mapped[CustomIngredient | None] = relationship(lazy="joined")
