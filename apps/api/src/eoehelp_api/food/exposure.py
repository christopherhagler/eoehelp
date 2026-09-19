"""What a logged food exposes the patient to.

One definition shared by the food log's display and the insights analysis, so
the screen that shows "contains milk" and the analysis that counts milk days
cannot disagree about what a food contained.

Allergen groups come from three places, by the kind of row:

- **Catalog rows** carry the catalog's groups. A composite dish ("mayonnaise")
  carries its usual recipe's groups; the food log shows those as "usually".
- **The patient's own ingredients** carry the groups the patient tagged.
- **Label rows** are classified when read, so an improvement to the classifier
  corrects past days too.

A packaged product's "Contains" declaration adds its groups on top, because a
declared allergen was eaten whether or not the parsed ingredient list shows it.
"""

from dataclasses import dataclass

from eoehelp_api.food.enums import AllergenGroup
from eoehelp_api.food.models import FoodLogItem, FoodLogItemIngredient
from eoehelp_api.food.products import vocabulary


def row_groups(row: FoodLogItemIngredient) -> list[AllergenGroup]:
    """The allergen groups one ingredient row belongs to, in declaration order."""
    if row.catalog is not None:
        return list(row.catalog.allergen_groups)
    if row.custom is not None:
        return list(row.custom.allergen_groups)
    return vocabulary.ordered(vocabulary.allergen_groups(row.canonical_key, row.display_name))


def row_name(row: FoodLogItemIngredient) -> str:
    if row.catalog is not None:
        return row.catalog.name
    if row.custom is not None:
        return row.custom.name
    return row.display_name


def additive_class(canonical_key: str) -> str | None:
    found = vocabulary.additive(canonical_key)
    return found.additive_class.value if found else None


@dataclass(frozen=True)
class ItemExposure:
    groups: frozenset[AllergenGroup]
    ingredient_keys: frozenset[str]
    additive_classes: frozenset[str]
    # Display names by canonical key, for labelling ingredient counts.
    names: dict[str, str]


def exposures(item: FoodLogItem) -> ItemExposure:
    groups: set[AllergenGroup] = set()
    keys: set[str] = set()
    additives: set[str] = set()
    names: dict[str, str] = {}
    for row in item.ingredients:
        groups.update(row_groups(row))
        keys.add(row.canonical_key)
        names.setdefault(row.canonical_key, row_name(row))
        found = additive_class(row.canonical_key)
        if found is not None:
            additives.add(found)
    if item.product is not None:
        groups.update(item.product.declared_allergens)
    return ItemExposure(
        groups=frozenset(groups),
        ingredient_keys=frozenset(keys),
        additive_classes=frozenset(additives),
        names=names,
    )
