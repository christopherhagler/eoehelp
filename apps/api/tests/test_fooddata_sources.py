"""Mapping recorded Open Food Facts and USDA responses.

The fixtures in fixtures/fooddata are real responses captured on 2026-09-16,
trimmed. Open Food Facts data is © Open Food Facts contributors, ODbL.
"""

import json
from pathlib import Path
from typing import Any

from eoehelp_api.fooddata import openfoodfacts, usda
from eoehelp_api.models.enums import AllergenGroup as G
from eoehelp_api.models.enums import FoodDataSource

FIXTURES = Path(__file__).parent / "fixtures" / "fooddata"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


class TestOpenFoodFacts:
    def test_hellmanns_is_more_than_egg(self) -> None:
        """The case that started this: real mayonnaise carries soy and a preservative."""
        record = openfoodfacts.to_record(load("off_product_hellmanns.json")["product"])

        assert record.source is FoodDataSource.OPEN_FOOD_FACTS
        assert record.barcode == "0048001213487"
        assert record.brand == "Hellmann's"
        assert record.name == "Real Mayonnaise"
        assert record.declared_allergens == {G.EGG, G.SOY}
        assert record.inferred_allergens == {G.EGG, G.SOY}
        assert "en:e385" in record.additives
        assert record.ingredients_complete

        edta = next(i for i in record.ingredients if i.key == "en:e385")
        # OFF parsed "(used to protect quality)" as a child ingredient.
        assert edta.note == "used to protect quality"
        assert all(i.name != "used" for i in record.ingredients)

    def test_a_messy_label_is_kept_but_flagged(self) -> None:
        record = openfoodfacts.to_record(load("off_product_miracle_whip_light.json")["product"])

        assert not record.ingredients_complete
        keys = [i.key for i in record.ingredients]
        # Cleaned up where it can be...
        assert "en:natural-flavouring" in keys
        assert "en:e202" in keys
        # ...and flagged where it cannot, rather than silently dropped.
        unrecognized = [i.name for i in record.ingredients if not i.recognized]
        assert "ts modified food starch" in unrecognized
        assert record.declared_allergens >= {G.EGG, G.SOY}

    def test_search_hits(self) -> None:
        hits = openfoodfacts.to_summaries(load("off_search_mayonnaise.json"))
        assert hits
        assert all(hit.source is FoodDataSource.OPEN_FOOD_FACTS for hit in hits)
        assert all(hit.barcode for hit in hits)

    def test_gluten_alone_does_not_declare_wheat(self) -> None:
        """OFF's gluten tag covers barley and rye too."""
        product = {
            "code": "1",
            "product_name": "Barley rusk",
            "allergens_tags": ["en:gluten"],
            "ingredients_text_en": "barley flour, salt",
        }
        assert openfoodfacts.to_record(product).declared_allergens == frozenset()
        product["ingredients_text_en"] = "wheat flour, barley flour, salt"
        assert openfoodfacts.to_record(product).declared_allergens == {G.WHEAT}


class TestUsda:
    def test_a_vegan_mayo_has_no_egg(self) -> None:
        foods = load("fdc_search_vegan_mayo.json")["foods"]
        records = [usda.to_record(food) for food in foods]

        assert all(G.EGG not in r.inferred_allergens for r in records)
        wegmans = records[0]
        assert wegmans.source is FoodDataSource.USDA_FDC
        assert wegmans.name == "Vegan Mayo Spread, Vegan Mayo"
        assert wegmans.brand == "Wegmans"
        assert [(i.depth, i.name) for i in wegmans.ingredients[:4]] == [
            (0, "CANOLA OIL"),
            (0, "CHICKPEA BROTH"),
            (1, "WATER"),
            (1, "CHICKPEAS"),
        ]
        assert {"en:e415", "en:e330", "en:e234"} <= set(wegmans.additives)
        assert wegmans.source_updated_at is not None

    def test_both_date_formats(self) -> None:
        food = {"fdcId": 1, "description": "X", "modifiedDate": "9/13/2023"}
        assert usda.to_record(food).source_updated_at is not None

    def test_search_hits(self) -> None:
        hits = usda.to_summaries(load("fdc_search_vegan_mayo.json"))
        assert [hit.source_id for hit in hits][:1] == ["2655306"]


class TestContentHash:
    def test_a_changed_label_is_a_different_snapshot(self) -> None:
        product = load("off_product_hellmanns.json")["product"]
        first = openfoodfacts.to_record(product)
        assert first.content_hash() == openfoodfacts.to_record(product).content_hash()

        product = {**product, "ingredients_text_en": product["ingredients_text_en"] + ", paprika"}
        product.pop("ingredients")
        assert openfoodfacts.to_record(product).content_hash() != first.content_hash()
