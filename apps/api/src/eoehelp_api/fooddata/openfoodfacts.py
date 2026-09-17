"""Open Food Facts: search and product lookup.

Data is ODbL-licensed, which requires attribution wherever it is shown. The
share-alike terms need a lawyer's reading before launch; see ADR 0008.
"""

from datetime import UTC, datetime
from typing import Any

import httpx

from eoehelp_api.fooddata import labels, vocabulary
from eoehelp_api.fooddata.records import (
    ProductIngredient,
    ProductRecord,
    ProductSummary,
    classify_words,
    display_case,
    flatten,
    normalise_barcode,
)
from eoehelp_api.models.enums import AllergenGroup, FoodDataSource

PRODUCT_FIELDS = (
    "code,product_name,product_name_en,brands,allergens_tags,traces_tags,"
    "ingredients,ingredients_text_en,ingredients_text,last_modified_t"
)

# OFF's allergen tags, onto our groups. "en:gluten" is deliberately absent: it
# covers barley and rye as well as wheat, so wheat is taken from the ingredients.
_ALLERGEN_TAGS = {
    "en:milk": AllergenGroup.MILK,
    "en:eggs": AllergenGroup.EGG,
    "en:soybeans": AllergenGroup.SOY,
    "en:peanuts": AllergenGroup.PEANUT,
    "en:nuts": AllergenGroup.TREE_NUT,
    "en:fish": AllergenGroup.FISH,
    "en:crustaceans": AllergenGroup.SHELLFISH,
    "en:molluscs": AllergenGroup.SHELLFISH,
    "en:sesame-seeds": AllergenGroup.SESAME,
}


def _groups(tags: list[str] | None) -> frozenset[AllergenGroup]:
    return frozenset(_ALLERGEN_TAGS[tag] for tag in tags or () if tag in _ALLERGEN_TAGS)


def _text(node: dict[str, Any]) -> str:
    return str(node.get("text") or node.get("id") or "").strip()


def _ingredients(nodes: list[dict[str, Any]], depth: int = 0) -> list[ProductIngredient]:
    flat: list[ProductIngredient] = []
    for node in nodes:
        text = _text(node)
        # OFF's own parse can carry label phrasing into a node ("contains less
        # than 2% of natural flavor"); the same cleaning as for USDA text applies.
        parsed = labels.parse(text).ingredients
        name = parsed[0].name if parsed else text
        note = parsed[0].note if parsed else None

        # OFF sometimes turns a purpose ("used to protect quality") into a child
        # ingredient. Those become the parent's note instead.
        children = node.get("ingredients") or []
        notes = [_text(child) for child in children if labels.is_function_note(_text(child))]
        children = [child for child in children if not labels.is_function_note(_text(child))]
        note = note or (", ".join(notes) if notes else None)

        if node.get("is_in_taxonomy") and str(node.get("id", "")).startswith("en:"):
            key, recognized = str(node["id"]), True
        else:
            identity = vocabulary.identify(name)
            key, recognized = identity.key, identity.recognized
        if name:
            flat.append(
                ProductIngredient(key=key, name=name, depth=depth, recognized=recognized, note=note)
            )
        flat.extend(_ingredients(children, depth + 1))
    return flat


def to_record(product: dict[str, Any]) -> ProductRecord:
    text = product.get("ingredients_text_en") or product.get("ingredients_text") or None
    nodes = product.get("ingredients") or []
    parsed = labels.parse(text)
    ingredients = _ingredients(nodes) if nodes else flatten(parsed.ingredients)

    declared = _groups(product.get("allergens_tags"))
    if "en:gluten" in (product.get("allergens_tags") or []):
        declared |= vocabulary.allergen_groups(*(i.name for i in ingredients)) & {
            AllergenGroup.WHEAT
        }
    modified = product.get("last_modified_t")
    code = str(product.get("code") or "")
    return ProductRecord(
        source=FoodDataSource.OPEN_FOOD_FACTS,
        source_id=code,
        barcode=normalise_barcode(code),
        name=display_case(
            str(product.get("product_name_en") or product.get("product_name") or code).strip()
        ),
        brand=_first_brand(product.get("brands")),
        ingredients_text=text,
        ingredients=tuple(ingredients),
        # OFF's tags plus our reading of the label text, since OFF's tags miss a
        # statement it failed to parse.
        declared_allergens=declared | classify_words(parsed.declared_allergens),
        may_contain=_groups(product.get("traces_tags")) | classify_words(parsed.may_contain),
        source_updated_at=datetime.fromtimestamp(int(modified), UTC) if modified else None,
    )


def _first_brand(brands: object) -> str | None:
    if isinstance(brands, list):
        return str(brands[0]).strip() if brands else None
    if isinstance(brands, str) and brands.strip():
        return brands.split(",")[0].strip()
    return None


def to_summaries(payload: dict[str, Any]) -> list[ProductSummary]:
    return [
        ProductSummary(
            source=FoodDataSource.OPEN_FOOD_FACTS,
            source_id=str(hit["code"]),
            barcode=normalise_barcode(str(hit["code"])),
            name=display_case(str(hit.get("product_name") or hit["code"]).strip()),
            brand=_first_brand(hit.get("brands")),
        )
        for hit in payload.get("hits", [])
        if hit.get("code") and hit.get("product_name")
    ]


class OpenFoodFactsClient:
    def __init__(
        self, http: httpx.AsyncClient, *, base_url: str, search_url: str, country: str
    ) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._search_url = search_url.rstrip("/")
        self._country = country

    async def search(self, query: str, limit: int) -> list[ProductSummary]:
        response = await self._http.get(
            f"{self._search_url}/search",
            params={
                "q": f'{query} countries_tags:"{self._country}"',
                "page_size": limit,
                "fields": "code,product_name,brands",
            },
        )
        response.raise_for_status()
        return to_summaries(response.json())

    async def product(self, code: str) -> ProductRecord | None:
        response = await self._http.get(
            f"{self._base_url}/api/v2/product/{code}.json", params={"fields": PRODUCT_FIELDS}
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        body = response.json()
        if body.get("status") != 1 or not body.get("product"):
            return None
        return to_record(body["product"])
