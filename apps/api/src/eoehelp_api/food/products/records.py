"""What a product lookup produces, independent of which database answered."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from eoehelp_api.food.enums import AllergenGroup, FoodDataSource
from eoehelp_api.food.products import labels, vocabulary


@dataclass(frozen=True)
class ProductIngredient:
    """One ingredient of a label, flattened in reading order.

    ``depth`` keeps the nesting ("WATER" inside "MUSTARD (WATER, ...)") without a
    tree, which is what both the screen and an exposure analysis want.
    """

    key: str
    name: str
    depth: int
    recognized: bool
    note: str | None = None

    def as_json(self) -> dict[str, object]:
        return {
            "key": self.key,
            "name": self.name,
            "depth": self.depth,
            "recognized": self.recognized,
            "note": self.note,
        }


@dataclass(frozen=True)
class ProductSummary:
    source: FoodDataSource
    source_id: str
    barcode: str | None
    name: str
    brand: str | None


@dataclass(frozen=True)
class ProductRecord:
    source: FoodDataSource
    source_id: str
    barcode: str | None
    name: str
    brand: str | None
    ingredients_text: str | None
    ingredients: tuple[ProductIngredient, ...]
    # The manufacturer's "Contains:" statement.
    declared_allergens: frozenset[AllergenGroup]
    # "May contain" and shared-facility statements.
    may_contain: frozenset[AllergenGroup]
    source_updated_at: datetime | None

    @property
    def inferred_allergens(self) -> frozenset[AllergenGroup]:
        """Groups the ingredient list itself indicates.

        Kept apart from the declaration: a label whose "Contains:" line is missing
        or garbled still names its ingredients, and a disagreement between the two
        is itself worth showing.
        """
        return vocabulary.allergen_groups(
            *(part for i in self.ingredients for part in (i.key, i.name))
        )

    @property
    def additives(self) -> list[str]:
        seen: dict[str, None] = {}
        for ingredient in self.ingredients:
            if vocabulary.additive(ingredient.key):
                seen.setdefault(ingredient.key, None)
        return list(seen)

    @property
    def ingredients_complete(self) -> bool:
        return bool(self.ingredients) and all(i.recognized for i in self.ingredients)

    def content_hash(self) -> str:
        """Identity of what the label says, so a changed label is a new snapshot."""
        payload = {
            "name": self.name,
            "brand": self.brand,
            "text": self.ingredients_text,
            "ingredients": [i.as_json() for i in self.ingredients],
            "declared": sorted(self.declared_allergens),
            "may_contain": sorted(self.may_contain),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def flatten(items: tuple[labels.LabelIngredient, ...], depth: int = 0) -> list[ProductIngredient]:
    """Our own parse of a label, identified through the vocabulary."""
    flat: list[ProductIngredient] = []
    for item in items:
        identity = vocabulary.identify(item.name)
        flat.append(
            ProductIngredient(
                key=identity.key,
                name=item.name,
                depth=depth,
                recognized=identity.recognized,
                note=item.note,
            )
        )
        flat.extend(flatten(item.children, depth + 1))
    return flat


def classify_words(words: tuple[str, ...]) -> frozenset[AllergenGroup]:
    """Allergen groups named in a statement; anything else in it is dropped."""
    return vocabulary.allergen_groups(*words)


def display_case(text: str) -> str:
    """USDA stores names in capitals; show them the way a package reads."""
    if text.isupper():
        return " ".join(word.capitalize() for word in text.split())
    return text


def normalise_barcode(raw: str | None) -> str | None:
    """Digits only, as a 13-digit GTIN where shorter.

    Open Food Facts stores a UPC-A as 13 digits with a leading zero; USDA stores it
    as printed, sometimes without the leading zero. Padding both makes them match.
    """
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if not 8 <= len(digits) <= 14:
        return None
    if len(digits) == 14 and digits.startswith("0"):
        digits = digits[1:]
    return digits.zfill(13) if len(digits) < 13 else digits
