"""One interface over both databases, with caching and graceful failure.

Search asks both sources at once and merges them, preferring Open Food Facts
when the same barcode appears in both, because its ingredients arrive already
parsed. Barcode lookup tries OFF first and falls back to USDA.

Either source being down is normal, not exceptional: food logging by name must
keep working, so a failure here becomes a clear 503 on the lookup endpoints
and nothing else.
"""

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Protocol, TypeVar

import httpx

from eoehelp_api import __version__
from eoehelp_api.config import get_settings
from eoehelp_api.food.enums import FoodDataSource
from eoehelp_api.food.products.openfoodfacts import OpenFoodFactsClient
from eoehelp_api.food.products.records import ProductRecord, ProductSummary, normalise_barcode
from eoehelp_api.food.products.usda import UsdaClient
from eoehelp_api.observability import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

CACHE_SECONDS = 600
CACHE_ENTRIES = 512


class FoodDataUnavailableError(Exception):
    """Every source that could answer failed."""


class FoodData(Protocol):
    async def search(self, query: str, limit: int) -> list[ProductSummary]: ...

    async def by_barcode(self, barcode: str) -> ProductRecord | None: ...

    async def product(self, source: FoodDataSource, source_id: str) -> ProductRecord | None: ...


class _TtlCache:
    """Small in-process cache. Label data changes on the scale of months."""

    def __init__(self) -> None:
        self._entries: OrderedDict[str, tuple[float, object]] = OrderedDict()

    async def get_or_load(self, key: str, load: Callable[[], Awaitable[T]]) -> T:
        now = time.monotonic()
        hit = self._entries.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            self._entries.move_to_end(key)
            return hit[1]  # type: ignore[return-value]
        value = await load()
        self._entries[key] = (now, value)
        self._entries.move_to_end(key)
        while len(self._entries) > CACHE_ENTRIES:
            self._entries.popitem(last=False)
        return value


class HttpFoodData:
    def __init__(self, http: httpx.AsyncClient, off: OpenFoodFactsClient, usda: UsdaClient):
        self._http = http
        self._off = off
        self._usda = usda
        self._cache = _TtlCache()

    @classmethod
    def from_settings(cls) -> "HttpFoodData":
        settings = get_settings()
        http = httpx.AsyncClient(
            timeout=settings.food_data_timeout_seconds,
            headers={"User-Agent": settings.food_data_user_agent.format(version=__version__)},
            follow_redirects=True,
        )
        return cls(
            http,
            OpenFoodFactsClient(
                http,
                base_url=settings.openfoodfacts_url,
                search_url=settings.openfoodfacts_search_url,
                country=settings.food_data_country,
            ),
            UsdaClient(
                http,
                base_url=settings.usda_fdc_url,
                api_key=settings.usda_fdc_api_key.get_secret_value(),
            ),
        )

    async def search(self, query: str, limit: int) -> list[ProductSummary]:
        return await self._cache.get_or_load(
            f"search:{limit}:{query.casefold()}", lambda: self._search(query, limit)
        )

    async def _search(self, query: str, limit: int) -> list[ProductSummary]:
        results = await asyncio.gather(
            self._off.search(query, limit), self._usda.search(query, limit), return_exceptions=True
        )
        answered: list[list[ProductSummary]] = []
        for source, result in zip(("open_food_facts", "usda_fdc"), results, strict=True):
            if isinstance(result, BaseException):
                # The query itself is never logged: what someone searched for is
                # what they are eating.
                logger.warning("fooddata.search_failed", source=source, error=type(result).__name__)
            else:
                answered.append(result)
        if not answered:
            raise FoodDataUnavailableError()

        merged: list[ProductSummary] = []
        seen: set[str] = set()
        # Interleave, so neither source crowds the other off the first screen.
        for index in range(max(len(r) for r in answered)):
            for source_results in answered:
                if index >= len(source_results):
                    continue
                hit = source_results[index]
                identity = hit.barcode or f"{hit.source}:{hit.source_id}"
                if identity in seen:
                    continue
                seen.add(identity)
                merged.append(hit)
        # A result with a brand is one a patient can match to the package in their
        # hand; unbranded community entries follow. The sort is stable, so the
        # interleaving holds within each group.
        merged.sort(key=lambda hit: hit.brand is None)
        return merged[:limit]

    async def by_barcode(self, barcode: str) -> ProductRecord | None:
        code = normalise_barcode(barcode)
        if code is None:
            return None
        return await self._cache.get_or_load(f"barcode:{code}", lambda: self._by_barcode(code))

    async def _by_barcode(self, code: str) -> ProductRecord | None:
        failures = 0
        without_ingredients: ProductRecord | None = None
        for lookup in (self._off.product, self._usda.by_barcode):
            try:
                found = await lookup(code)
            except httpx.HTTPError as error:
                failures += 1
                logger.warning("fooddata.lookup_failed", error=type(error).__name__)
                continue
            if found is not None and found.ingredients:
                return found
            # A known product with no ingredient list is still worth naming, but
            # the other source may have the list, so keep looking first.
            without_ingredients = without_ingredients or found
        if failures == 2:
            raise FoodDataUnavailableError()
        return without_ingredients

    async def product(self, source: FoodDataSource, source_id: str) -> ProductRecord | None:
        async def load() -> ProductRecord | None:
            client = self._off if source is FoodDataSource.OPEN_FOOD_FACTS else self._usda
            try:
                return await client.product(source_id)
            except httpx.HTTPError as error:
                logger.warning("fooddata.lookup_failed", error=type(error).__name__)
                raise FoodDataUnavailableError() from error

        return await self._cache.get_or_load(f"product:{source}:{source_id}", load)


@lru_cache
def get_food_data() -> FoodData:
    """The shared client. A dependency, so tests replace it with recorded data."""
    return HttpFoodData.from_settings()
