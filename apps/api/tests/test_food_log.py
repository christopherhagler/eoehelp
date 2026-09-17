"""Food and ingredient logging through the API."""

from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.models.audit import AuditLog
from helpers import auth

FOODS = "/api/v1/me/foods"
CATALOG = "/api/v1/foods/ingredients"


def days_ago(n: int) -> str:
    return (datetime.now(UTC).date() - timedelta(days=n)).isoformat()


def food(**overrides: Any) -> dict[str, Any]:
    return {
        "eaten_on": days_ago(0),
        "meal": "lunch",
        "name": "Cheese toastie",
        "ingredients": [{"code": "bread"}, {"code": "cheese"}, {"code": "butter"}],
        **overrides,
    }


async def log(client: AsyncClient, access: str, **overrides: Any) -> dict[str, Any]:
    response = await client.post(FOODS, json=food(**overrides), headers=auth(access))
    assert response.status_code == 201, response.text
    return dict(response.json())


class TestCatalog:
    async def test_the_catalog_tags_ingredients_with_allergen_groups(
        self, client: AsyncClient, sign_in
    ) -> None:
        access = await sign_in()
        response = await client.get(CATALOG, headers=auth(access))
        assert response.status_code == 200
        rows = {row["code"]: row for row in response.json()}

        assert rows["butter"]["allergen_groups"] == ["milk"]
        assert rows["soy_sauce"]["allergen_groups"] == ["wheat", "soy"]
        assert rows["rice"]["allergen_groups"] == []
        # Every elimination-diet group is represented by at least one ingredient,
        # or a group-level view would have a permanently empty row.
        groups = {g for row in rows.values() for g in row["allergen_groups"]}
        assert groups == {
            "milk",
            "wheat",
            "egg",
            "soy",
            "peanut",
            "tree_nut",
            "fish",
            "shellfish",
            "sesame",
        }

    async def test_no_name_or_alias_resolves_to_two_ingredients(
        self, client: AsyncClient, sign_in
    ) -> None:
        """A typed word must have one meaning. If "chips" were an alias of two
        ingredients, which one it became would depend on sort order."""
        access = await sign_in()
        rows = (await client.get(CATALOG, headers=auth(access))).json()
        owners: dict[str, set[str]] = {}
        for row in rows:
            owners.setdefault(row["name"].casefold(), set()).add(row["code"])
            for alias in row["aliases"]:
                assert alias == alias.casefold(), f"alias {alias!r} must be stored lower-case"
                owners.setdefault(alias, set()).add(row["code"])
        ambiguous = {word: codes for word, codes in owners.items() if len(codes) > 1}
        assert ambiguous == {}


class TestLogging:
    async def test_a_food_is_logged_with_its_ingredients_in_order(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        item = await log(client, access)

        assert item["name"] == "Cheese toastie"
        assert item["entry_method"] == "same_day"
        assert [i["code"] for i in item["ingredients"]] == ["bread", "cheese", "butter"]
        assert item["ingredients"][1]["allergen_groups"] == ["milk"]

    async def test_a_typed_name_finds_the_catalog_by_alias(
        self, client: AsyncClient, onboard
    ) -> None:
        """A typed "flour" must count as wheat, or group-level analysis silently misses it."""
        access, _ = await onboard()
        item = await log(client, access, ingredients=[{"name": "  Flour "}, {"name": "MAYO"}])
        assert [i["code"] for i in item["ingredients"]] == ["wheat_flour", "mayonnaise"]

        custom = await client.get(f"{FOODS}/ingredients", headers=auth(access))
        assert custom.json() == [], "a catalog match must not create a custom ingredient"

    async def test_an_unknown_name_becomes_the_patients_own_ingredient_once(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        first = await log(
            client,
            access,
            ingredients=[{"name": "Grandma's hot relish", "allergen_groups": ["soy", "soy"]}],
        )
        second = await log(client, access, ingredients=[{"name": "grandma's   HOT relish"}])

        [one] = first["ingredients"]
        [two] = second["ingredients"]
        assert one["code"] is None
        assert one["custom_ingredient_id"] == two["custom_ingredient_id"]
        assert one["name"] == "Grandma's hot relish"
        assert one["allergen_groups"] == ["soy"]

        custom = (await client.get(f"{FOODS}/ingredients", headers=auth(access))).json()
        assert len(custom) == 1

    async def test_the_same_ingredient_twice_is_stored_once(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        item = await log(
            client,
            access,
            ingredients=[{"code": "milk"}, {"name": "whole milk"}, {"code": "milk"}],
        )
        assert [i["code"] for i in item["ingredients"]] == ["milk"]

    async def test_a_food_with_no_ingredients_is_allowed(
        self, client: AsyncClient, onboard
    ) -> None:
        """Logging must never be blocked on detail. The item still records that a
        meal happened, which is worth more than nothing."""
        access, _ = await onboard()
        item = await log(client, access, ingredients=[])
        assert item["ingredients"] == []

    async def test_an_unknown_catalog_code_is_refused(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        response = await client.post(
            FOODS, json=food(ingredients=[{"code": "unobtainium"}]), headers=auth(access)
        )
        assert response.status_code == 400

    async def test_an_ingredient_reference_must_be_exactly_one_kind(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        for ref in ({}, {"code": "milk", "name": "milk"}, {"code": "milk", "allergen_groups": []}):
            response = await client.post(FOODS, json=food(ingredients=[ref]), headers=auth(access))
            assert response.status_code == 422, ref

    async def test_a_blank_name_is_refused(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        response = await client.post(FOODS, json=food(name="   "), headers=auth(access))
        assert response.status_code == 422


class TestDateRules:
    async def test_a_future_day_is_refused(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        response = await client.post(FOODS, json=food(eaten_on=days_ago(-2)), headers=auth(access))
        assert response.status_code == 400

    async def test_recent_backfill_is_allowed_and_flagged(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        item = await log(client, access, eaten_on=days_ago(3))
        assert item["entry_method"] == "backfill"

    async def test_the_backfill_window_matches_the_symptom_log(
        self, client: AsyncClient, onboard
    ) -> None:
        """A patient catching up after a flare fills in both halves of a day; one
        being accepted while the other is refused would be incoherent."""
        access, _ = await onboard()
        assert (
            await client.post(FOODS, json=food(eaten_on=days_ago(7)), headers=auth(access))
        ).status_code == 201
        assert (
            await client.post(FOODS, json=food(eaten_on=days_ago(8)), headers=auth(access))
        ).status_code == 400


class TestEditing:
    async def test_editing_replaces_the_ingredients_of_that_item_only(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        yesterday = await log(client, access, eaten_on=days_ago(1))
        today = await log(client, access)

        response = await client.put(
            f"{FOODS}/{today['id']}",
            json=food(
                name="Cheese toastie (vegan)",
                ingredients=[{"code": "bread"}, {"name": "cashew cheese"}, {"code": "bread"}],
            ),
            headers=auth(access),
        )
        assert response.status_code == 200, response.text
        edited = response.json()
        assert edited["name"] == "Cheese toastie (vegan)"
        assert [i["name"] for i in edited["ingredients"]] == ["Bread", "cashew cheese"]

        listed = (
            await client.get(
                FOODS, params={"from": days_ago(1), "to": days_ago(1)}, headers=auth(access)
            )
        ).json()
        [untouched] = listed["items"]
        assert untouched["id"] == yesterday["id"]
        assert [i["code"] for i in untouched["ingredients"]] == ["bread", "cheese", "butter"]

    async def test_re_saving_the_same_ingredients_does_not_trip_the_unique_constraint(
        self, client: AsyncClient, onboard
    ) -> None:
        """The unit of work inserts before it deletes; a naive swap would briefly
        hold "bread" twice on one item."""
        access, _ = await onboard()
        item = await log(client, access)
        response = await client.put(f"{FOODS}/{item['id']}", json=food(), headers=auth(access))
        assert response.status_code == 200, response.text
        assert [i["code"] for i in response.json()["ingredients"]] == ["bread", "cheese", "butter"]

    async def test_an_edit_keeps_the_original_entry_method(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        item = await log(client, access)
        response = await client.put(
            f"{FOODS}/{item['id']}", json=food(eaten_on=days_ago(2)), headers=auth(access)
        )
        assert response.json()["entry_method"] == "same_day"

    async def test_an_item_older_than_the_window_cannot_be_edited_but_can_be_deleted(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        access, _ = await onboard()
        item = await log(client, access)
        await session.execute(
            text("UPDATE food_log_items SET eaten_on = CURRENT_DATE - 30 WHERE id = :id"),
            {"id": item["id"]},
        )
        await session.commit()

        edit = await client.put(f"{FOODS}/{item['id']}", json=food(), headers=auth(access))
        assert edit.status_code == 400

        delete = await client.delete(f"{FOODS}/{item['id']}", headers=auth(access))
        assert delete.status_code == 204

    async def test_deleting_removes_the_item_and_its_ingredients(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        access, _ = await onboard()
        item = await log(client, access)
        assert (
            await client.delete(f"{FOODS}/{item['id']}", headers=auth(access))
        ).status_code == 204
        remaining = (
            await session.execute(text("SELECT count(*) FROM food_log_item_ingredients"))
        ).scalar_one()
        assert remaining == 0
        again = await client.delete(f"{FOODS}/{item['id']}", headers=auth(access))
        assert again.status_code == 404


class TestReadingBack:
    async def test_the_default_range_is_today(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        await log(client, access, eaten_on=days_ago(1))
        mine = await log(client, access)
        listed = (await client.get(FOODS, headers=auth(access))).json()
        assert [i["id"] for i in listed["items"]] == [mine["id"]]

    async def test_items_come_back_in_day_then_meal_order(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        await log(client, access, meal="dinner", name="c")
        await log(client, access, meal="breakfast", name="b")
        await log(client, access, meal="snack", name="d", eaten_on=days_ago(1))
        listed = (
            await client.get(FOODS, params={"from": days_ago(1)}, headers=auth(access))
        ).json()
        assert [i["name"] for i in listed["items"]] == ["d", "b", "c"]

    async def test_a_reversed_range_is_refused(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        response = await client.get(
            FOODS, params={"from": days_ago(0), "to": days_ago(1)}, headers=auth(access)
        )
        assert response.status_code == 400


class TestRecentFoods:
    async def test_recent_foods_rank_by_frequency_with_the_latest_ingredients(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        await log(
            client, access, name="Porridge", eaten_on=days_ago(2), ingredients=[{"code": "oats"}]
        )
        await log(
            client,
            access,
            name="porridge",
            meal="breakfast",
            eaten_on=days_ago(1),
            ingredients=[{"code": "oats"}, {"code": "milk"}],
        )
        await log(client, access, name="Salad", ingredients=[{"code": "lettuce"}])

        recent = (await client.get(f"{FOODS}/recent", headers=auth(access))).json()
        assert [r["name"] for r in recent] == ["porridge", "Salad"]
        porridge = recent[0]
        assert porridge["times_logged"] == 2
        assert porridge["meal"] == "breakfast"
        assert [i["code"] for i in porridge["ingredients"]] == ["oats", "milk"]

    async def test_recent_foods_can_be_logged_again_as_they_are(
        self, client: AsyncClient, onboard
    ) -> None:
        """The client posts a recent food's ingredients straight back. Custom
        ingredients arrive by id, which must round-trip."""
        access, _ = await onboard()
        await log(client, access, name="Relish sandwich", ingredients=[{"name": "Relish"}])
        [recent] = (await client.get(f"{FOODS}/recent", headers=auth(access))).json()

        refs = [
            {"code": i["code"]}
            if i["code"]
            else {"custom_ingredient_id": i["custom_ingredient_id"]}
            for i in recent["ingredients"]
        ]
        again = await log(client, access, name=recent["name"], ingredients=refs)
        assert again["ingredients"] == recent["ingredients"]


class TestCustomIngredients:
    async def test_retagging_an_ingredient_applies_to_past_items(
        self, client: AsyncClient, onboard
    ) -> None:
        """The tag describes what the ingredient is, so finding out that the relish
        contains soy corrects history rather than starting from today."""
        access, _ = await onboard()
        item = await log(client, access, ingredients=[{"name": "Relish"}])
        ingredient_id = item["ingredients"][0]["custom_ingredient_id"]

        response = await client.patch(
            f"{FOODS}/ingredients/{ingredient_id}",
            json={"allergen_groups": ["wheat", "soy", "wheat"]},
            headers=auth(access),
        )
        assert response.status_code == 200
        assert response.json()["allergen_groups"] == ["wheat", "soy"]

        [listed] = (await client.get(FOODS, headers=auth(access))).json()["items"]
        assert listed["ingredients"][0]["allergen_groups"] == ["wheat", "soy"]

    async def test_renaming_onto_an_existing_name_is_refused(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        item = await log(client, access, ingredients=[{"name": "Relish"}, {"name": "Chutney"}])
        chutney = item["ingredients"][1]["custom_ingredient_id"]

        clash = await client.patch(
            f"{FOODS}/ingredients/{chutney}", json={"name": "relish"}, headers=auth(access)
        )
        assert clash.status_code == 400

        recase = await client.patch(
            f"{FOODS}/ingredients/{chutney}", json={"name": "CHUTNEY"}, headers=auth(access)
        )
        assert recase.status_code == 200
        assert recase.json()["name"] == "CHUTNEY"


class TestIsolation:
    async def test_another_patients_food_is_a_404(self, client: AsyncClient, onboard) -> None:
        alice, _ = await onboard("alice@example.com")
        bob, _ = await onboard("bob@example.com")
        item = await log(client, alice)

        assert (
            await client.put(f"{FOODS}/{item['id']}", json=food(), headers=auth(bob))
        ).status_code == 404
        assert (await client.delete(f"{FOODS}/{item['id']}", headers=auth(bob))).status_code == 404
        assert (await client.get(FOODS, headers=auth(bob))).json()["items"] == []
        assert (await client.get(f"{FOODS}/recent", headers=auth(bob))).json() == []

    async def test_another_patients_ingredient_cannot_be_used_or_edited(
        self, client: AsyncClient, onboard
    ) -> None:
        alice, _ = await onboard("alice@example.com")
        bob, _ = await onboard("bob@example.com")
        item = await log(client, alice, ingredients=[{"name": "Secret sauce"}])
        alice_ingredient = item["ingredients"][0]["custom_ingredient_id"]

        borrowed = await client.post(
            FOODS,
            json=food(ingredients=[{"custom_ingredient_id": alice_ingredient}]),
            headers=auth(bob),
        )
        assert borrowed.status_code == 400

        edited = await client.patch(
            f"{FOODS}/ingredients/{alice_ingredient}",
            json={"name": "Not so secret"},
            headers=auth(bob),
        )
        assert edited.status_code == 404
        assert (await client.get(f"{FOODS}/ingredients", headers=auth(bob))).json() == []

    async def test_the_same_typed_name_makes_separate_ingredients_per_patient(
        self, client: AsyncClient, onboard
    ) -> None:
        alice, _ = await onboard("alice@example.com")
        bob, _ = await onboard("bob@example.com")
        a = await log(client, alice, ingredients=[{"name": "Relish"}])
        b = await log(client, bob, ingredients=[{"name": "Relish"}])
        assert (
            a["ingredients"][0]["custom_ingredient_id"]
            != b["ingredients"][0]["custom_ingredient_id"]
        )

    async def test_deleting_the_account_removes_food_and_custom_ingredients(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        access, _ = await onboard()
        await log(client, access, ingredients=[{"name": "Relish"}, {"code": "bread"}])
        assert (await client.delete("/api/v1/me", headers=auth(access))).status_code == 204

        for table in ("food_log_items", "food_log_item_ingredients", "custom_ingredients"):
            count = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            assert count == 0, table
        catalog = (
            await session.execute(text("SELECT count(*) FROM ingredient_catalog"))
        ).scalar_one()
        assert catalog > 100, "reference data must survive a patient's deletion"


class TestAuditTrail:
    async def test_the_trail_records_the_shape_of_a_meal_never_its_content(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        access, _ = await onboard()
        item = await log(
            client,
            access,
            name="Birthday cake at Dr Okafor's",
            ingredients=[{"code": "egg"}, {"name": "Aunt Mae's frosting"}],
        )
        await client.put(f"{FOODS}/{item['id']}", json=food(), headers=auth(access))
        await client.get(FOODS, headers=auth(access))
        await client.get(f"{FOODS}/recent", headers=auth(access))
        await client.get(f"{FOODS}/ingredients", headers=auth(access))
        await client.delete(f"{FOODS}/{item['id']}", headers=auth(access))

        rows = (
            (
                await session.execute(
                    select(AuditLog)
                    .where(AuditLog.resource_type.in_(["food_log_item", "custom_ingredient"]))
                    .order_by(AuditLog.id)
                )
            )
            .scalars()
            .all()
        )
        assert [row.action for row in rows] == [
            "food_log_item.create",
            "food_log_item.update",
            "food_log_item.list",
            "food_log_item.recent",
            "custom_ingredient.list",
            "food_log_item.delete",
        ]
        created = rows[0].metadata_
        assert created is not None
        assert created["ingredient_count"] == 2
        assert created["custom_ingredients_created"] == 1

        trail = " ".join(str(row.metadata_) for row in rows)
        for secret in ("Birthday", "Okafor", "Aunt Mae", "frosting", "toastie", "egg"):
            assert secret not in trail
