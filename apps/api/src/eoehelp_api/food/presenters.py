"""How stored food records and fetched product labels are shown to a patient.

Shared by the service, which returns logged items, and the router, which
returns search and barcode results that are never stored.

Allergen groups for label ingredients are classified here, on every read, so an
improvement to the classifier corrects past days as well as new ones.
"""

from eoehelp_api.food.enums import FoodDataSource
from eoehelp_api.food.models import FoodLogItem, FoodLogItemIngredient, FoodProduct
from eoehelp_api.food.products import vocabulary
from eoehelp_api.food.products.records import ProductRecord
from eoehelp_api.food.schemas import (
    FoodItemRead,
    IngredientRead,
    ProductIngredientRead,
    ProductRead,
    ProductSnapshotRead,
)

ATTRIBUTION = {
    FoodDataSource.OPEN_FOOD_FACTS: (
        "Product data from Open Food Facts, available under the Open Database License."
    ),
    FoodDataSource.USDA_FDC: "Product data from USDA FoodData Central (public domain).",
}


def _additive_class(key: str) -> str | None:
    found = vocabulary.additive(key)
    return found.additive_class.value if found else None


def ingredient_read(row: FoodLogItemIngredient) -> IngredientRead:
    common = {
        "canonical_key": row.canonical_key,
        "provenance": row.provenance,
        "recognized": row.recognized,
        "depth": row.depth,
        "note": row.note,
        "additive_class": _additive_class(row.canonical_key),
    }
    if row.catalog is not None:
        return IngredientRead(
            code=row.catalog.code,
            custom_ingredient_id=None,
            name=row.catalog.name,
            allergen_groups=list(row.catalog.allergen_groups),
            typical=row.catalog.is_composite,
            **common,
        )
    if row.custom is not None:
        return IngredientRead(
            code=None,
            custom_ingredient_id=row.custom.id,
            name=row.custom.name,
            allergen_groups=list(row.custom.allergen_groups),
            typical=False,
            **common,
        )
    # A label ingredient. Its groups are classified on read, so an improvement
    # to the classifier corrects past days too, as a retag does.
    return IngredientRead(
        code=None,
        custom_ingredient_id=None,
        name=row.display_name,
        allergen_groups=vocabulary.ordered(
            vocabulary.allergen_groups(row.canonical_key, row.display_name)
        ),
        typical=False,
        **common,
    )


def snapshot_read(product: FoodProduct) -> ProductSnapshotRead:
    return ProductSnapshotRead(
        snapshot_id=product.id,
        source=product.source,
        source_id=product.source_id,
        barcode=product.barcode,
        name=product.name,
        brand=product.brand,
        ingredients_complete=product.ingredients_complete,
        declared_allergens=list(product.declared_allergens),
        may_contain=list(product.may_contain),
        fetched_at=product.fetched_at,
        attribution=ATTRIBUTION[product.source],
    )


def product_read(record: ProductRecord) -> ProductRead:
    return ProductRead(
        source=record.source,
        source_id=record.source_id,
        barcode=record.barcode,
        name=record.name,
        brand=record.brand,
        ingredients_text=record.ingredients_text,
        ingredients=[
            ProductIngredientRead(
                key=i.key,
                name=i.name,
                depth=i.depth,
                recognized=i.recognized,
                note=i.note,
                allergen_groups=vocabulary.ordered(vocabulary.allergen_groups(i.key, i.name)),
                additive_class=_additive_class(i.key),
            )
            for i in record.ingredients
        ],
        ingredients_complete=record.ingredients_complete,
        declared_allergens=vocabulary.ordered(record.declared_allergens),
        may_contain=vocabulary.ordered(record.may_contain),
        inferred_allergens=vocabulary.ordered(record.inferred_allergens),
        source_updated_at=record.source_updated_at,
        attribution=ATTRIBUTION[record.source],
    )


def item_read(item: FoodLogItem) -> FoodItemRead:
    return FoodItemRead(
        id=item.id,
        eaten_on=item.eaten_on,
        meal=item.meal,
        name=item.name,
        entry_method=item.entry_method,
        product=snapshot_read(item.product) if item.product else None,
        ingredients=[ingredient_read(row) for row in item.ingredients],
        created_at=item.created_at,
        updated_at=item.updated_at,
    )
