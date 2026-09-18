"""Logging packaged products, through the API, with recorded label data."""

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from eoehelp_api.audit.models import AuditLog
from eoehelp_api.food.enums import FoodDataSource
from eoehelp_api.food.products import openfoodfacts, usda
from eoehelp_api.food.products.provider import FoodDataUnavailableError, get_food_data
from eoehelp_api.food.products.records import ProductRecord, ProductSummary
from helpers import app_role_url, auth, food_item

FOODS = "/api/v1/me/foods"
PRODUCTS = "/api/v1/foods/products"
FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


class RecordedFoodData:
    """Answers from captured responses. Counts calls, so caching can be checked."""

    def __init__(self) -> None:
        self.hellmanns = openfoodfacts.to_record(load("off_product_hellmanns.json")["product"])
        self.vegan = usda.to_record(load("fdc_search_vegan_mayo.json")["foods"][0])
        self.lookups = 0
        self.down = False

    def _check(self) -> None:
        if self.down:
            raise FoodDataUnavailableError()

    async def search(self, query: str, limit: int) -> list[ProductSummary]:
        self._check()
        return [
            ProductSummary(r.source, r.source_id, r.barcode, r.name, r.brand)
            for r in (self.hellmanns, self.vegan)
            if query.lower() in r.name.lower()
        ][:limit]

    async def by_barcode(self, barcode: str) -> ProductRecord | None:
        self._check()
        return next(
            (r for r in (self.hellmanns, self.vegan) if r.barcode == barcode.zfill(13)), None
        )

    async def product(self, source: FoodDataSource, source_id: str) -> ProductRecord | None:
        self._check()
        self.lookups += 1
        return next(
            (
                r
                for r in (self.hellmanns, self.vegan)
                if r.source is source and r.source_id == source_id
            ),
            None,
        )


@pytest.fixture
def recorded(app: Any) -> RecordedFoodData:
    data = RecordedFoodData()
    app.dependency_overrides[get_food_data] = lambda: data
    return data


def hellmanns_ref() -> dict[str, str]:
    return {"source": "open_food_facts", "source_id": "0048001213487"}


class TestLookup:
    async def test_search_and_barcode(
        self, client: AsyncClient, sign_in, recorded: RecordedFoodData
    ) -> None:
        access = await sign_in()
        found = (
            await client.get(f"{PRODUCTS}/search", params={"q": "mayo"}, headers=auth(access))
        ).json()
        assert [hit["source"] for hit in found] == ["open_food_facts", "usda_fdc"]

        product = (
            await client.get(f"{PRODUCTS}/barcode/048001213487", headers=auth(access))
        ).json()
        assert product["brand"] == "Hellmann's"
        assert product["declared_allergens"] == ["egg", "soy"]
        assert product["may_contain"] == []
        assert "Open Food Facts" in product["attribution"]
        edta = next(i for i in product["ingredients"] if i["key"] == "en:e385")
        assert edta["additive_class"] == "preservative"
        soy_oil = next(i for i in product["ingredients"] if i["key"] == "en:soya-oil")
        assert soy_oil["allergen_groups"] == ["soy"]

    async def test_detail_and_not_found(
        self, client: AsyncClient, sign_in, recorded: RecordedFoodData
    ) -> None:
        access = await sign_in()
        detail = await client.get(f"{PRODUCTS}/usda_fdc/2655306", headers=auth(access))
        assert detail.status_code == 200
        assert "egg" not in detail.json()["inferred_allergens"]
        assert "public domain" in detail.json()["attribution"]

        missing = await client.get(f"{PRODUCTS}/barcode/00000000", headers=auth(access))
        assert missing.status_code == 404
        assert (
            await client.get(f"{PRODUCTS}/usda_fdc/nope", headers=auth(access))
        ).status_code == 404

    async def test_an_outage_is_a_503_that_points_to_the_alternative(
        self, client: AsyncClient, sign_in, recorded: RecordedFoodData
    ) -> None:
        recorded.down = True
        access = await sign_in()
        for path in ("/search?q=mayo", "/barcode/0048001213487", "/usda_fdc/2655306"):
            response = await client.get(f"{PRODUCTS}{path}", headers=auth(access))
            assert response.status_code == 503, path
            assert "by name" in response.json()["detail"]

    async def test_lookups_need_a_session_and_sane_input(
        self, client: AsyncClient, sign_in, recorded: RecordedFoodData
    ) -> None:
        assert (await client.get(f"{PRODUCTS}/search", params={"q": "mayo"})).status_code == 401
        access = await sign_in()
        for path in ("/search?q=m", "/barcode/12ab", "/barcode/123", "/usda_fdc/a%20b"):
            response = await client.get(f"{PRODUCTS}{path}", headers=auth(access))
            assert response.status_code == 422, path


class TestLoggingAProduct:
    async def test_the_label_becomes_the_ingredients(
        self, client: AsyncClient, onboard, recorded: RecordedFoodData
    ) -> None:
        access, _ = await onboard()
        response = await client.post(
            FOODS,
            json=food_item(
                name="Hellmann's on toast",
                product=hellmanns_ref(),
                ingredients=[{"code": "bread"}],
            ),
            headers=auth(access),
        )
        assert response.status_code == 201, response.text
        item = response.json()

        assert item["product"]["brand"] == "Hellmann's"
        assert item["product"]["declared_allergens"] == ["egg", "soy"]
        label = [i for i in item["ingredients"] if i["provenance"] == "label"]
        mine = [i for i in item["ingredients"] if i["provenance"] == "patient"]
        assert [i["canonical_key"] for i in label][:3] == [
            "en:soya-oil",
            "en:water",
            "en:whole-egg",
        ]
        assert all(i["code"] is None and i["custom_ingredient_id"] is None for i in label)
        assert [i["code"] for i in mine] == ["bread"]
        assert mine[0]["typical"] is True, "bread is a dish; its groups are the usual recipe"
        assert any(i["additive_class"] == "preservative" for i in label)

    async def test_the_client_cannot_supply_label_data(
        self, client: AsyncClient, onboard, recorded: RecordedFoodData
    ) -> None:
        access, _ = await onboard()
        response = await client.post(
            FOODS,
            json=food_item(product={**hellmanns_ref(), "ingredients": [{"key": "en:water"}]}),
            headers=auth(access),
        )
        assert response.status_code == 422

    async def test_the_same_label_is_one_snapshot(
        self, client: AsyncClient, onboard, recorded: RecordedFoodData, session: AsyncSession
    ) -> None:
        alice, _ = await onboard("alice@example.com")
        bob, _ = await onboard("bob@example.com")
        for access in (alice, bob, alice):
            await client.post(FOODS, json=food_item(product=hellmanns_ref()), headers=auth(access))
        count = (await session.execute(text("SELECT count(*) FROM food_products"))).scalar_one()
        assert count == 1

    async def test_a_recent_product_is_relogged_from_its_snapshot_without_a_lookup(
        self, client: AsyncClient, onboard, recorded: RecordedFoodData
    ) -> None:
        access, _ = await onboard()
        await client.post(
            FOODS,
            json=food_item(name="Mayo", product=hellmanns_ref(), ingredients=[{"name": "Pickles"}]),
            headers=auth(access),
        )
        lookups = recorded.lookups
        [recent] = (await client.get(f"{FOODS}/recent", headers=auth(access))).json()
        # Only the patient's own additions: the label comes from the snapshot.
        assert [i["name"] for i in recent["ingredients"]] == ["Pickles"]

        recorded.down = True  # a re-log must not depend on the sources being up
        again = await client.post(
            FOODS,
            json=food_item(
                name=recent["name"],
                product={"snapshot_id": recent["product"]["snapshot_id"]},
                ingredients=[
                    {"custom_ingredient_id": i["custom_ingredient_id"]}
                    for i in recent["ingredients"]
                ],
            ),
            headers=auth(access),
        )
        assert again.status_code == 201, again.text
        assert recorded.lookups == lookups
        assert again.json()["product"]["snapshot_id"] == recent["product"]["snapshot_id"]
        assert sum(i["provenance"] == "label" for i in again.json()["ingredients"]) == 10

    async def test_an_outage_blocks_only_new_products(
        self, client: AsyncClient, onboard, recorded: RecordedFoodData
    ) -> None:
        recorded.down = True
        access, _ = await onboard()
        blocked = await client.post(
            FOODS, json=food_item(product=hellmanns_ref()), headers=auth(access)
        )
        assert blocked.status_code == 503
        by_name = await client.post(FOODS, json=food_item(), headers=auth(access))
        assert by_name.status_code == 201

    async def test_unknown_products_and_snapshots_are_refused(
        self, client: AsyncClient, onboard, recorded: RecordedFoodData
    ) -> None:
        access, _ = await onboard()
        for product in (
            {"source": "usda_fdc", "source_id": "999"},
            {"snapshot_id": "00000000-0000-0000-0000-000000000000"},
        ):
            response = await client.post(
                FOODS, json=food_item(product=product), headers=auth(access)
            )
            assert response.status_code == 400, product
        for product in (
            {"source": "usda_fdc"},
            {**hellmanns_ref(), "snapshot_id": "00000000-0000-0000-0000-000000000000"},
            {},
        ):
            response = await client.post(
                FOODS, json=food_item(product=product), headers=auth(access)
            )
            assert response.status_code == 422, product

    async def test_editing_can_remove_the_product(
        self, client: AsyncClient, onboard, recorded: RecordedFoodData
    ) -> None:
        access, _ = await onboard()
        item = (
            await client.post(FOODS, json=food_item(product=hellmanns_ref()), headers=auth(access))
        ).json()
        edited = await client.put(f"{FOODS}/{item['id']}", json=food_item(), headers=auth(access))
        assert edited.status_code == 200, edited.text
        assert edited.json()["product"] is None
        assert all(i["provenance"] == "patient" for i in edited.json()["ingredients"])

    async def test_the_trail_names_the_source_not_the_product(
        self, client: AsyncClient, onboard, recorded: RecordedFoodData, session: AsyncSession
    ) -> None:
        access, _ = await onboard()
        await client.post(FOODS, json=food_item(product=hellmanns_ref()), headers=auth(access))
        row = (
            await session.execute(select(AuditLog).where(AuditLog.action == "food_log_item.create"))
        ).scalar_one()
        assert row.metadata_ is not None
        assert row.metadata_["product_source"] == "open_food_facts"
        assert row.metadata_["label_ingredient_count"] == 10
        assert "Hellmann" not in json.dumps(row.metadata_)
        assert "0048001213487" not in json.dumps(row.metadata_)


class TestTypedNames:
    async def test_a_known_additive_typed_by_name_gets_its_standard_identity(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        item = (
            await client.post(
                FOODS,
                json=food_item(ingredients=[{"name": "Sodium Benzoate"}, {"name": "cashew cream"}]),
                headers=auth(access),
            )
        ).json()
        benzoate, cream = item["ingredients"]
        assert benzoate["canonical_key"] == "en:e211"
        assert benzoate["additive_class"] == "preservative"
        # Tagged from its name even though the patient chose no groups.
        assert cream["allergen_groups"] == ["tree_nut"]


class TestSnapshotsAreEvidence:
    async def test_the_application_can_add_snapshots_but_never_change_them(
        self, client: AsyncClient, onboard, recorded: RecordedFoodData, test_database_url: str
    ) -> None:
        access, _ = await onboard()
        await client.post(FOODS, json=food_item(product=hellmanns_ref()), headers=auth(access))

        engine = create_async_engine(app_role_url(test_database_url))
        try:
            async with engine.connect() as conn:
                count = await conn.execute(text("SELECT count(*) FROM food_products"))
                assert count.scalar_one() == 1
            for statement in (
                "UPDATE food_products SET name = 'Altered'",
                "DELETE FROM food_products",
            ):
                with pytest.raises(ProgrammingError, match="permission denied"):
                    async with engine.connect() as conn, conn.begin():
                        await conn.execute(text(statement))
        finally:
            await engine.dispose()


async def test_catalog_keys_agree_with_the_vocabulary(client: AsyncClient, sign_in) -> None:
    """A catalog "Egg" and a label's "EGGS" must be the same ingredient to an
    analysis, and a non-dish's groups must be what its name says."""
    from eoehelp_api.food.products import vocabulary

    access = await sign_in()
    rows = (await client.get("/api/v1/foods/ingredients", headers=auth(access))).json()
    assert rows

    mismatched_keys = []
    mismatched_groups = []
    for row in rows:
        identity = vocabulary.identify(row["name"])
        catalog_key = row["canonical_key"]
        if identity.recognized and identity.key != catalog_key:
            mismatched_keys.append((row["code"], identity.key, catalog_key))
        if not row["is_composite"]:
            groups = vocabulary.allergen_groups(row["name"])
            inferred = [g.value for g in vocabulary.ordered(groups)]
            if inferred != row["allergen_groups"]:
                mismatched_groups.append((row["code"], inferred, row["allergen_groups"]))
    assert mismatched_keys == []
    assert mismatched_groups == []
