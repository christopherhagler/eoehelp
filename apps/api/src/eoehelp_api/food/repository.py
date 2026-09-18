"""Access to logged food, the patient's own ingredients, and the ingredient catalog."""

import uuid
from collections.abc import Collection
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.core.errors import NotFoundError
from eoehelp_api.food.enums import AllergenGroup
from eoehelp_api.food.models import CatalogIngredient, CustomIngredient, FoodLogItem, FoodProduct
from eoehelp_api.food.products.records import ProductRecord
from eoehelp_api.food.products.vocabulary import ordered


async def catalog_ingredients(session: AsyncSession) -> list[CatalogIngredient]:
    """The whole ingredient catalog, by name. Reference data: no patient scope."""
    result = await session.execute(select(CatalogIngredient).order_by(CatalogIngredient.name))
    return list(result.scalars())


class FoodRepository:
    """Every patient-owned statement is filtered by the id from the verified token.

    Catalog lookups live here too, so the service has a single data-access
    dependency. They are the only unscoped statements, and they read reference
    data that has no owner.
    """

    def __init__(self, session: AsyncSession, patient_id: uuid.UUID) -> None:
        self._session = session
        self._patient_id = patient_id

    # --- catalog --------------------------------------------------------------

    async def catalog_by_codes(self, codes: Collection[str]) -> dict[str, CatalogIngredient]:
        if not codes:
            return {}
        result = await self._session.execute(
            select(CatalogIngredient).where(CatalogIngredient.code.in_(codes))
        )
        return {row.code: row for row in result.scalars()}

    async def catalog_by_name_key(self, key: str) -> CatalogIngredient | None:
        """A catalog ingredient whose name or alias matches, preferring the name.

        Aliases are stored lower-case, and keys are case-folded, so the comparison
        is exact on both sides.
        """
        result = await self._session.execute(
            select(CatalogIngredient)
            .where(
                or_(
                    func.lower(CatalogIngredient.name) == key,
                    CatalogIngredient.aliases.contains([key]),
                )
            )
            .order_by((func.lower(CatalogIngredient.name) == key).desc(), CatalogIngredient.code)
            .limit(1)
        )
        return result.scalar_one_or_none()

    # --- the patient's own ingredients -----------------------------------------

    async def list_custom(self) -> list[CustomIngredient]:
        result = await self._session.execute(
            select(CustomIngredient)
            .where(CustomIngredient.patient_id == self._patient_id)
            .order_by(CustomIngredient.name_key)
        )
        return list(result.scalars().all())

    async def custom_by_ids(self, ids: Collection[uuid.UUID]) -> dict[uuid.UUID, CustomIngredient]:
        if not ids:
            return {}
        result = await self._session.execute(
            select(CustomIngredient).where(
                CustomIngredient.patient_id == self._patient_id,
                CustomIngredient.id.in_(ids),
            )
        )
        return {row.id: row for row in result.scalars()}

    async def require_custom(self, ingredient_id: uuid.UUID) -> CustomIngredient:
        found = await self.custom_by_ids([ingredient_id])
        if ingredient_id not in found:
            raise NotFoundError("No such ingredient.")
        return found[ingredient_id]

    async def custom_by_name_key(self, key: str) -> CustomIngredient | None:
        result = await self._session.execute(
            select(CustomIngredient).where(
                CustomIngredient.patient_id == self._patient_id,
                CustomIngredient.name_key == key,
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create_custom(
        self,
        *,
        name: str,
        key: str,
        canonical_key: str,
        allergen_groups: list[AllergenGroup],
    ) -> tuple[CustomIngredient, bool]:
        """The patient's ingredient with this key, creating it if absent.

        INSERT … ON CONFLICT rather than select-then-insert: two quick taps on a
        slow connection would otherwise race to create the same ingredient, and
        the loser would fail on the unique constraint with a 500.
        """
        inserted = await self._session.execute(
            insert(CustomIngredient)
            .values(
                id=uuid.uuid4(),
                patient_id=self._patient_id,
                name=name,
                name_key=key,
                canonical_key=canonical_key,
                allergen_groups=allergen_groups,
            )
            .on_conflict_do_nothing(constraint="uq_custom_ingredients_patient_id_name_key")
            .returning(CustomIngredient.id)
        )
        created = inserted.scalar_one_or_none() is not None
        existing = await self.custom_by_name_key(key)
        if existing is None:  # pragma: no cover - the row was just written or already there
            raise RuntimeError("Custom ingredient vanished between insert and select.")
        return existing, created

    # --- product snapshots ----------------------------------------------------
    #
    # Public label data, so unscoped like the catalog. Which patient ate a
    # product is recorded only on their own log rows.

    async def product_snapshot(self, snapshot_id: uuid.UUID) -> FoodProduct | None:
        return await self._session.get(FoodProduct, snapshot_id)

    async def snapshot_for(self, record: ProductRecord) -> FoodProduct:
        """The stored snapshot matching this label exactly, writing it if new."""
        content_hash = record.content_hash()
        await self._session.execute(
            insert(FoodProduct)
            .values(
                id=uuid.uuid4(),
                source=record.source,
                source_id=record.source_id,
                barcode=record.barcode,
                name=record.name[:300],
                brand=record.brand[:200] if record.brand else None,
                ingredients_text=record.ingredients_text,
                ingredients=[i.as_json() for i in record.ingredients],
                ingredients_complete=record.ingredients_complete,
                declared_allergens=ordered(record.declared_allergens),
                may_contain=ordered(record.may_contain),
                content_hash=content_hash,
                source_updated_at=record.source_updated_at,
            )
            .on_conflict_do_nothing(constraint="uq_food_products_source_version")
        )
        stored = await self._session.execute(
            select(FoodProduct).where(
                FoodProduct.source == record.source,
                FoodProduct.source_id == record.source_id,
                FoodProduct.content_hash == content_hash,
            )
        )
        return stored.scalar_one()

    # --- logged food ----------------------------------------------------------

    async def list_items_between(self, start: date, end: date) -> list[FoodLogItem]:
        result = await self._session.execute(
            select(FoodLogItem)
            .where(
                FoodLogItem.patient_id == self._patient_id,
                FoodLogItem.eaten_on >= start,
                FoodLogItem.eaten_on <= end,
            )
            .order_by(FoodLogItem.eaten_on, FoodLogItem.meal, FoodLogItem.created_at)
        )
        return list(result.unique().scalars().all())

    async def list_items_since(self, start: date) -> list[FoodLogItem]:
        """Newest first, for building the recent-foods list."""
        result = await self._session.execute(
            select(FoodLogItem)
            .where(FoodLogItem.patient_id == self._patient_id, FoodLogItem.eaten_on >= start)
            .order_by(FoodLogItem.eaten_on.desc(), FoodLogItem.created_at.desc())
        )
        return list(result.unique().scalars().all())

    async def require_item(self, item_id: uuid.UUID) -> FoodLogItem:
        result = await self._session.execute(
            select(FoodLogItem).where(
                FoodLogItem.id == item_id,
                FoodLogItem.patient_id == self._patient_id,
            )
        )
        item = result.unique().scalar_one_or_none()
        if item is None:
            raise NotFoundError("No such food.")
        return item

    def add_item(self, item: FoodLogItem) -> None:
        if item.patient_id != self._patient_id:
            raise ValueError("Refusing to write a row belonging to another patient.")
        self._session.add(item)

    async def delete_item(self, item: FoodLogItem) -> None:
        await self._session.delete(item)
