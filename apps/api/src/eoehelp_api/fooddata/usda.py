"""USDA FoodData Central branded foods: search and lookup.

Public domain. Ingredients arrive as the printed statement only, so the label
parser and vocabulary do all the structuring.
"""

from datetime import UTC, datetime
from typing import Any

import httpx

from eoehelp_api.fooddata import labels
from eoehelp_api.fooddata.records import (
    ProductRecord,
    ProductSummary,
    classify_words,
    display_case,
    flatten,
    normalise_barcode,
)
from eoehelp_api.models.enums import FoodDataSource


def _date(raw: object) -> datetime | None:
    # Search returns ISO dates; the detail endpoint returns US-style ones.
    if not isinstance(raw, str) or not raw:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _brand(food: dict[str, Any]) -> str | None:
    brand = (food.get("brandName") or food.get("brandOwner") or "").strip()
    return display_case(brand) or None


def to_record(food: dict[str, Any]) -> ProductRecord:
    text = (food.get("ingredients") or "").strip() or None
    parsed = labels.parse(text)
    return ProductRecord(
        source=FoodDataSource.USDA_FDC,
        source_id=str(food["fdcId"]),
        barcode=normalise_barcode(food.get("gtinUpc")),
        name=display_case(str(food.get("description") or food["fdcId"]).strip()),
        brand=_brand(food),
        ingredients_text=text,
        ingredients=tuple(flatten(parsed.ingredients)),
        declared_allergens=classify_words(parsed.declared_allergens),
        may_contain=classify_words(parsed.may_contain),
        source_updated_at=_date(food.get("modifiedDate")) or _date(food.get("publishedDate")),
    )


def to_summaries(payload: dict[str, Any]) -> list[ProductSummary]:
    return [
        ProductSummary(
            source=FoodDataSource.USDA_FDC,
            source_id=str(food["fdcId"]),
            barcode=normalise_barcode(food.get("gtinUpc")),
            name=display_case(str(food.get("description") or food["fdcId"]).strip()),
            brand=_brand(food),
        )
        for food in payload.get("foods", [])
        if food.get("fdcId")
    ]


class UsdaClient:
    def __init__(self, http: httpx.AsyncClient, *, base_url: str, api_key: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def _search(self, query: str, limit: int) -> dict[str, Any]:
        response = await self._http.get(
            f"{self._base_url}/foods/search",
            params={
                "query": query,
                "dataType": "Branded",
                "pageSize": limit,
                "api_key": self._api_key,
            },
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return body

    async def search(self, query: str, limit: int) -> list[ProductSummary]:
        return to_summaries(await self._search(query, limit))

    async def product(self, fdc_id: str) -> ProductRecord | None:
        if not fdc_id.isdigit():
            return None
        response = await self._http.get(
            f"{self._base_url}/food/{fdc_id}", params={"api_key": self._api_key}
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return to_record(response.json())

    async def by_barcode(self, barcode: str) -> ProductRecord | None:
        body = await self._search(barcode, 10)
        for food in body.get("foods", []):
            if normalise_barcode(food.get("gtinUpc")) == barcode:
                return to_record(food)
        return None
