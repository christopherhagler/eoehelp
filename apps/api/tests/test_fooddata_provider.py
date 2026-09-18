"""The HTTP clients and the combined provider, over a mock transport.

No network: httpx.MockTransport serves the recorded responses, so the request
shapes, the merge, the fallback, the cache, and outage handling are all real
code paths without a real server.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from eoehelp_api.food.enums import FoodDataSource
from eoehelp_api.food.products.openfoodfacts import OpenFoodFactsClient
from eoehelp_api.food.products.provider import FoodDataUnavailableError, HttpFoodData
from eoehelp_api.food.products.usda import UsdaClient

FIXTURES = Path(__file__).parent / "fixtures" / "fooddata"
OFF = "https://off.test"
OFF_SEARCH = "https://search.off.test"
USDA = "https://usda.test/fdc/v1"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


Handler = Callable[[httpx.Request], httpx.Response]


class Upstream:
    """Routes requests to handlers and remembers what was asked."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.off_search: Handler = lambda r: httpx.Response(
            200, json=load("off_search_mayonnaise.json")
        )
        self.off_product: Handler = lambda r: httpx.Response(
            200, json=load("off_product_hellmanns.json")
        )
        self.usda_search: Handler = lambda r: httpx.Response(
            200, json=load("fdc_search_vegan_mayo.json")
        )
        self.usda_food: Handler = lambda r: httpx.Response(
            200, json=load("fdc_search_vegan_mayo.json")["foods"][0]
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.startswith(OFF_SEARCH):
            return self.off_search(request)
        if url.startswith(f"{OFF}/api/v2/product/"):
            return self.off_product(request)
        if url.startswith(f"{USDA}/foods/search"):
            return self.usda_search(request)
        if url.startswith(f"{USDA}/food/"):
            return self.usda_food(request)
        return httpx.Response(418)


def down(_: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("unreachable")


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


@pytest.fixture
def provider(upstream: Upstream) -> HttpFoodData:
    http = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    return HttpFoodData(
        http,
        OpenFoodFactsClient(http, base_url=OFF, search_url=OFF_SEARCH, country="en:united-states"),
        UsdaClient(http, base_url=USDA, api_key="test-key"),
    )


class TestRequests:
    async def test_search_asks_both_sources_the_right_way(
        self, provider: HttpFoodData, upstream: Upstream
    ) -> None:
        await provider.search("mayo", 5)
        off, usda = sorted(upstream.requests, key=lambda r: str(r.url))
        assert off.url.params["q"] == 'mayo countries_tags:"en:united-states"'
        assert off.url.params["page_size"] == "5"
        assert usda.url.params["dataType"] == "Branded"
        assert usda.url.params["api_key"] == "test-key"

    async def test_a_non_numeric_usda_id_is_not_sent(
        self, provider: HttpFoodData, upstream: Upstream
    ) -> None:
        assert await provider.product(FoodDataSource.USDA_FDC, "abc") is None
        assert upstream.requests == []


class TestSearch:
    async def test_results_interleave_and_stop_at_the_limit(self, provider: HttpFoodData) -> None:
        hits = await provider.search("mayo", 4)
        assert [hit.source for hit in hits] == [
            FoodDataSource.OPEN_FOOD_FACTS,
            FoodDataSource.USDA_FDC,
            FoodDataSource.OPEN_FOOD_FACTS,
            FoodDataSource.USDA_FDC,
        ]

    async def test_the_same_barcode_appears_once_preferring_open_food_facts(
        self, provider: HttpFoodData, upstream: Upstream
    ) -> None:
        shared = load("fdc_search_vegan_mayo.json")
        code = str(shared["foods"][0]["gtinUpc"])
        upstream.off_search = lambda r: httpx.Response(
            200, json={"hits": [{"code": code.zfill(13), "product_name": "Vegan mayo"}]}
        )
        hits = await provider.search("vegan", 10)
        matching = [hit for hit in hits if hit.barcode == code.zfill(13)]
        assert [hit.source for hit in matching] == [FoodDataSource.OPEN_FOOD_FACTS]

    async def test_branded_results_come_first(
        self, provider: HttpFoodData, upstream: Upstream
    ) -> None:
        upstream.off_search = lambda r: httpx.Response(
            200,
            json={
                "hits": [
                    {"code": "0000000000017", "product_name": "Vegan mayo"},
                    {"code": "0000000000024", "product_name": "VEGAN MAYO", "brands": ["Vega"]},
                ]
            },
        )
        upstream.usda_search = lambda r: httpx.Response(200, json={"foods": []})
        hits = await provider.search("vegan", 10)
        assert [(hit.name, hit.brand) for hit in hits] == [
            ("Vegan Mayo", "Vega"),
            ("Vegan mayo", None),
        ]

    async def test_one_source_down_is_not_an_outage(
        self, provider: HttpFoodData, upstream: Upstream
    ) -> None:
        upstream.usda_search = down
        hits = await provider.search("mayo", 10)
        assert hits
        assert {hit.source for hit in hits} == {FoodDataSource.OPEN_FOOD_FACTS}

    async def test_both_down_is(self, provider: HttpFoodData, upstream: Upstream) -> None:
        upstream.usda_search = down
        upstream.off_search = lambda r: httpx.Response(503)
        with pytest.raises(FoodDataUnavailableError):
            await provider.search("mayo", 10)

    async def test_repeat_searches_are_cached(
        self, provider: HttpFoodData, upstream: Upstream
    ) -> None:
        await provider.search("Mayo", 5)
        await provider.search("mayo", 5)
        assert len(upstream.requests) == 2  # one per source, once


class TestBarcode:
    async def test_open_food_facts_first(self, provider: HttpFoodData, upstream: Upstream) -> None:
        record = await provider.by_barcode("048001213487")
        assert record is not None
        assert record.source is FoodDataSource.OPEN_FOOD_FACTS
        assert str(upstream.requests[0].url).startswith(f"{OFF}/api/v2/product/0048001213487")

    async def test_falls_back_to_usda_when_open_food_facts_has_nothing(
        self, provider: HttpFoodData, upstream: Upstream
    ) -> None:
        upstream.off_product = lambda r: httpx.Response(200, json={"status": 0})
        code = str(load("fdc_search_vegan_mayo.json")["foods"][0]["gtinUpc"])
        record = await provider.by_barcode(code)
        assert record is not None
        assert record.source is FoodDataSource.USDA_FDC

    async def test_a_product_without_ingredients_is_still_returned(
        self, provider: HttpFoodData, upstream: Upstream
    ) -> None:
        bare = {"status": 1, "product": {"code": "0000000000017", "product_name": "Mystery"}}
        upstream.off_product = lambda r: httpx.Response(200, json=bare)
        upstream.usda_search = lambda r: httpx.Response(200, json={"foods": []})
        record = await provider.by_barcode("17")
        assert record is None  # too short to be a barcode
        record = await provider.by_barcode("0000000000017")
        assert record is not None
        assert record.name == "Mystery"
        assert record.ingredients == ()

    async def test_unknown_everywhere_is_none(
        self, provider: HttpFoodData, upstream: Upstream
    ) -> None:
        upstream.off_product = lambda r: httpx.Response(404)
        upstream.usda_search = lambda r: httpx.Response(200, json={"foods": []})
        assert await provider.by_barcode("0000000000024") is None

    async def test_both_down_is_an_outage_not_a_miss(
        self, provider: HttpFoodData, upstream: Upstream
    ) -> None:
        upstream.off_product = down
        upstream.usda_search = down
        with pytest.raises(FoodDataUnavailableError):
            await provider.by_barcode("0048001213487")


class TestDetail:
    async def test_each_source(self, provider: HttpFoodData) -> None:
        off = await provider.product(FoodDataSource.OPEN_FOOD_FACTS, "0048001213487")
        usda = await provider.product(FoodDataSource.USDA_FDC, "2655306")
        assert off is not None
        assert usda is not None
        assert (off.brand, usda.brand) == ("Hellmann's", "Wegmans")

    async def test_missing_and_down(self, provider: HttpFoodData, upstream: Upstream) -> None:
        upstream.usda_food = lambda r: httpx.Response(404)
        assert await provider.product(FoodDataSource.USDA_FDC, "1") is None
        upstream.off_product = down
        with pytest.raises(FoodDataUnavailableError):
            await provider.product(FoodDataSource.OPEN_FOOD_FACTS, "0048001213487")


def test_the_default_provider_identifies_itself() -> None:
    """Open Food Facts throttles anonymous clients; the version is filled in."""
    provider = HttpFoodData.from_settings()
    agent = provider._http.headers["User-Agent"]
    assert agent.startswith("eoehelp/0.1.0 (")
    assert "{version}" not in agent
