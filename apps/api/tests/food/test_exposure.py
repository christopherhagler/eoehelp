"""What a logged food exposes the patient to: one definition for display and analysis."""

from eoehelp_api.food.enums import AllergenGroup
from eoehelp_api.food.exposure import additive_class, exposures, row_groups, row_name
from eoehelp_api.food.models import (
    CatalogIngredient,
    CustomIngredient,
    FoodLogItem,
    FoodLogItemIngredient,
    FoodProduct,
)

MILK, EGG, SOY = AllergenGroup.MILK, AllergenGroup.EGG, AllergenGroup.SOY


def catalog_row() -> FoodLogItemIngredient:
    return FoodLogItemIngredient(
        canonical_key="en:mayonnaise",
        display_name="Mayonnaise",
        catalog=CatalogIngredient(
            code="mayonnaise",
            name="Mayonnaise",
            allergen_groups=[EGG],
            canonical_key="en:mayonnaise",
            is_composite=True,
        ),
    )


def custom_row() -> FoodLogItemIngredient:
    return FoodLogItemIngredient(
        canonical_key="patient:relish",
        display_name="relish",
        custom=CustomIngredient(
            name="Relish", canonical_key="patient:relish", allergen_groups=[SOY]
        ),
    )


def label_row(key: str, name: str) -> FoodLogItemIngredient:
    return FoodLogItemIngredient(canonical_key=key, display_name=name)


class TestRows:
    def test_a_catalog_row_carries_the_catalogs_groups(self) -> None:
        assert row_groups(catalog_row()) == [EGG]
        assert row_name(catalog_row()) == "Mayonnaise"

    def test_a_patients_own_ingredient_carries_its_tags(self) -> None:
        assert row_groups(custom_row()) == [SOY]
        assert row_name(custom_row()) == "Relish"

    def test_a_label_row_is_classified_when_read(self) -> None:
        assert row_groups(label_row("en:soya-oil", "soybean oil")) == [SOY]
        assert row_name(label_row("en:soya-oil", "soybean oil")) == "soybean oil"

    def test_additives_are_named_by_class(self) -> None:
        assert additive_class("en:e385") == "preservative"
        assert additive_class("en:water") is None


class TestItems:
    def test_every_row_and_the_declaration_count(self) -> None:
        item = FoodLogItem(
            name="Sandwich",
            ingredients=[
                catalog_row(),
                custom_row(),
                label_row("en:e385", "calcium disodium edta"),
            ],
            product=FoodProduct(name="Real Mayonnaise", declared_allergens=[MILK]),
        )
        exposure = exposures(item)
        # Milk comes only from the "Contains" declaration: it was eaten either way.
        assert exposure.groups == {EGG, SOY, MILK}
        assert exposure.ingredient_keys == {"en:mayonnaise", "patient:relish", "en:e385"}
        assert exposure.additive_classes == {"preservative"}
        assert exposure.names["patient:relish"] == "Relish"

    def test_a_food_without_a_product_has_only_its_rows(self) -> None:
        item = FoodLogItem(name="Toast", ingredients=[label_row("en:water", "water")], product=None)
        exposure = exposures(item)
        assert exposure.groups == frozenset()
        assert exposure.additive_classes == frozenset()
