"""Food logging.

What this module guarantees, in order of how easy each is to get wrong:

**A typed name finds the catalog first.** "flour" resolves to wheat flour, not to
a new untagged ingredient that allergen-group analysis would never count. A new
ingredient of the patient's own is created only when nothing matches.

**Ingredients are frozen per item.** Editing a food replaces that item's list;
it never reaches into other days.

**The audit trail records shape, not content.** A food name is free text, and
"what someone ate" is exactly the kind of detail a health-data trail must not
hold. Rows carry the day, the meal, and counts.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.core.errors import BadRequestError
from eoehelp_api.models.enums import AllergenGroup
from eoehelp_api.models.food import (
    CatalogIngredient,
    CustomIngredient,
    FoodLogItem,
    FoodLogItemIngredient,
)
from eoehelp_api.models.patient import Patient
from eoehelp_api.repositories.food import FoodRepository
from eoehelp_api.schemas.food import (
    CustomIngredientRead,
    CustomIngredientUpdate,
    FoodItemInput,
    FoodItemRead,
    IngredientRead,
    IngredientRef,
    RecentFood,
    name_key,
)
from eoehelp_api.services import audit, entry_dates
from eoehelp_api.services.audit import AuditContext

MAX_RANGE_DAYS = 400

# How far back "recent" reaches. Long enough to include the rotation of meals a
# person actually cooks, short enough that a food abandoned months ago stops
# crowding the list.
RECENT_LOOKBACK_DAYS = 90
MAX_RECENT_FOODS = 50


@dataclass
class _Resolved:
    """The ingredient rows an item will point at, deduplicated and in order."""

    order: list[tuple[str, CatalogIngredient | CustomIngredient]] = field(default_factory=list)
    created: int = 0


def ingredient_read(row: FoodLogItemIngredient) -> IngredientRead:
    if row.catalog is not None:
        return IngredientRead(
            code=row.catalog.code,
            custom_ingredient_id=None,
            name=row.catalog.name,
            allergen_groups=list(row.catalog.allergen_groups),
        )
    if row.custom is None:  # pragma: no cover - the check constraint forbids it
        raise RuntimeError("Logged ingredient has neither a catalog nor a custom reference.")
    return IngredientRead(
        code=None,
        custom_ingredient_id=row.custom.id,
        name=row.custom.name,
        allergen_groups=list(row.custom.allergen_groups),
    )


def item_read(item: FoodLogItem) -> FoodItemRead:
    return FoodItemRead(
        id=item.id,
        eaten_on=item.eaten_on,
        meal=item.meal,
        name=item.name,
        entry_method=item.entry_method,
        ingredients=[ingredient_read(row) for row in item.ingredients],
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


class FoodService:
    def __init__(self, session: AsyncSession, patient: Patient) -> None:
        self._session = session
        self._patient = patient
        self._repo = FoodRepository(session, patient.id)

    @property
    def today(self) -> date:
        return datetime.now(ZoneInfo(self._patient.timezone)).date()

    # --- writes ---------------------------------------------------------------

    async def create(
        self, *, payload: FoodItemInput, context: AuditContext | None = None
    ) -> FoodItemRead:
        entry_method = entry_dates.classify(payload.eaten_on, today=self.today)
        resolved = await self._resolve(payload.ingredients)

        item = FoodLogItem(
            id=uuid.uuid4(),
            patient_id=self._patient.id,
            eaten_on=payload.eaten_on,
            meal=payload.meal,
            name=payload.name,
            name_key=name_key(payload.name),
            entry_method=entry_method,
        )
        item.ingredients = self._rows(resolved)
        self._repo.add_item(item)
        await self._session.flush()
        await self._session.refresh(item)

        await self._audit("food_log_item.create", item, resolved, context=context)
        return item_read(item)

    async def update(
        self,
        *,
        item_id: uuid.UUID,
        payload: FoodItemInput,
        context: AuditContext | None = None,
    ) -> FoodItemRead:
        item = await self._repo.require_item(item_id)
        # Both days must still be writable: moving a food onto last month is a
        # backfill by another route, and so is editing last month's food.
        today = self.today
        entry_dates.classify(item.eaten_on, today=today)
        entry_dates.classify(payload.eaten_on, today=today)

        resolved = await self._resolve(payload.ingredients)

        # Clear and flush before adding the replacement rows. The unit of work
        # issues inserts before deletes, so swapping in one step would briefly
        # hold the same ingredient twice and trip the per-item unique constraint.
        item.ingredients.clear()
        await self._session.flush()

        item.eaten_on = payload.eaten_on
        item.meal = payload.meal
        item.name = payload.name
        item.name_key = name_key(payload.name)
        # entry_method is not recomputed, as with symptom entries: correcting a
        # same-day record later does not make it recalled.
        item.ingredients.extend(self._rows(resolved))
        await self._session.flush()
        await self._session.refresh(item)

        await self._audit("food_log_item.update", item, resolved, context=context)
        return item_read(item)

    async def delete(self, *, item_id: uuid.UUID, context: AuditContext | None = None) -> None:
        # Deliberately not limited to the backfill window: removing a mistaken
        # entry is always allowed, and a gap is better than a wrong record.
        item = await self._repo.require_item(item_id)
        eaten_on = item.eaten_on
        await self._repo.delete_item(item)
        await self._session.flush()
        await audit.record(
            self._session,
            action="food_log_item.delete",
            resource_type="food_log_item",
            resource_id=item_id,
            patient_id=self._patient.id,
            context=context,
            metadata={"eaten_on": eaten_on.isoformat()},
        )

    async def update_custom_ingredient(
        self,
        *,
        ingredient_id: uuid.UUID,
        payload: CustomIngredientUpdate,
        context: AuditContext | None = None,
    ) -> CustomIngredientRead:
        ingredient = await self._repo.require_custom(ingredient_id)
        changed: list[str] = []

        if payload.name is not None:
            key = name_key(payload.name)
            if key != ingredient.name_key:
                clash = await self._repo.custom_by_name_key(key)
                if clash is not None:
                    raise BadRequestError("You already have an ingredient with that name.")
            ingredient.name = payload.name
            ingredient.name_key = key
            changed.append("name")

        if payload.allergen_groups is not None:
            ingredient.allergen_groups = _unique_groups(payload.allergen_groups)
            changed.append("allergen_groups")

        await self._session.flush()
        await audit.record(
            self._session,
            action="custom_ingredient.update",
            resource_type="custom_ingredient",
            resource_id=ingredient.id,
            patient_id=self._patient.id,
            context=context,
            metadata={"fields": changed},
        )
        return CustomIngredientRead.model_validate(ingredient)

    # --- reads ----------------------------------------------------------------

    async def list_range(
        self, *, start: date, end: date, context: AuditContext | None = None
    ) -> list[FoodItemRead]:
        if end < start:
            raise BadRequestError("The range ends before it starts.")
        if (end - start).days + 1 > MAX_RANGE_DAYS:
            raise BadRequestError(f"Ranges are limited to {MAX_RANGE_DAYS} days.")

        items = await self._repo.list_items_between(start, end)
        await audit.record(
            self._session,
            action="food_log_item.list",
            resource_type="food_log_item",
            patient_id=self._patient.id,
            context=context,
            metadata={
                "range_start": start.isoformat(),
                "range_end": end.isoformat(),
                "returned": len(items),
            },
        )
        return [item_read(item) for item in items]

    async def recent(
        self, *, limit: int = 20, context: AuditContext | None = None
    ) -> list[RecentFood]:
        """Foods logged lately, most often logged first.

        Derived from history rather than kept as saved recipes. There is nothing
        to manage, the list tracks what the patient actually eats, and a food's
        ingredients are the ones it had most recently — which is also what the
        patient would expect to see.
        """
        since = self.today - timedelta(days=RECENT_LOOKBACK_DAYS)
        items = await self._repo.list_items_since(since)

        latest: dict[str, FoodLogItem] = {}
        counts: dict[str, int] = {}
        for item in items:  # newest first, so the first sighting is the latest
            latest.setdefault(item.name_key, item)
            counts[item.name_key] = counts.get(item.name_key, 0) + 1

        ranked = sorted(
            latest.values(),
            key=lambda item: (-counts[item.name_key], -item.eaten_on.toordinal(), item.name_key),
        )[: min(limit, MAX_RECENT_FOODS)]

        await audit.record(
            self._session,
            action="food_log_item.recent",
            resource_type="food_log_item",
            patient_id=self._patient.id,
            context=context,
            metadata={"returned": len(ranked)},
        )
        return [
            RecentFood(
                name=item.name,
                meal=item.meal,
                ingredients=[ingredient_read(row) for row in item.ingredients],
                times_logged=counts[item.name_key],
                last_eaten_on=item.eaten_on,
            )
            for item in ranked
        ]

    async def list_custom_ingredients(
        self, *, context: AuditContext | None = None
    ) -> list[CustomIngredientRead]:
        rows = await self._repo.list_custom()
        await audit.record(
            self._session,
            action="custom_ingredient.list",
            resource_type="custom_ingredient",
            patient_id=self._patient.id,
            context=context,
            metadata={"returned": len(rows)},
        )
        return [CustomIngredientRead.model_validate(row) for row in rows]

    # --- internals ------------------------------------------------------------

    async def _resolve(self, refs: list[IngredientRef]) -> _Resolved:
        codes = {ref.code for ref in refs if ref.code is not None}
        custom_ids = {ref.custom_ingredient_id for ref in refs if ref.custom_ingredient_id}

        catalog = await self._repo.catalog_by_codes(codes)
        missing_codes = codes - catalog.keys()
        if missing_codes:
            raise BadRequestError("One or more ingredients are not in the catalog.")

        custom = await self._repo.custom_by_ids(custom_ids)
        if custom_ids - custom.keys():
            # Another patient's id reads exactly like a nonexistent one.
            raise BadRequestError("One or more ingredients were not found.")

        resolved = _Resolved()
        seen: set[str] = set()

        def keep(row: CatalogIngredient | CustomIngredient) -> None:
            key = (
                f"catalog:{row.code}" if isinstance(row, CatalogIngredient) else f"custom:{row.id}"
            )
            if key in seen:
                return
            seen.add(key)
            resolved.order.append((key, row))

        for ref in refs:
            if ref.code is not None:
                keep(catalog[ref.code])
            elif ref.custom_ingredient_id is not None:
                keep(custom[ref.custom_ingredient_id])
            else:
                assert ref.name is not None  # guaranteed by IngredientRef
                key = name_key(ref.name)
                match = await self._repo.catalog_by_name_key(key)
                if match is not None:
                    keep(match)
                    continue
                own, created = await self._repo.get_or_create_custom(
                    name=ref.name,
                    key=key,
                    allergen_groups=_unique_groups(ref.allergen_groups or []),
                )
                resolved.created += int(created)
                keep(own)

        return resolved

    def _rows(self, resolved: _Resolved) -> list[FoodLogItemIngredient]:
        rows: list[FoodLogItemIngredient] = []
        for position, (_, row) in enumerate(resolved.order):
            # The relationship objects are set, not just the foreign keys, so the
            # response can be built without a lazy load the async session forbids.
            if isinstance(row, CatalogIngredient):
                rows.append(
                    FoodLogItemIngredient(
                        patient_id=self._patient.id, catalog=row, position=position
                    )
                )
            else:
                rows.append(
                    FoodLogItemIngredient(
                        patient_id=self._patient.id, custom=row, position=position
                    )
                )
        return rows

    async def _audit(
        self,
        action: str,
        item: FoodLogItem,
        resolved: _Resolved,
        *,
        context: AuditContext | None = None,
    ) -> None:
        await audit.record(
            self._session,
            action=action,
            resource_type="food_log_item",
            resource_id=item.id,
            patient_id=self._patient.id,
            context=context,
            metadata={
                "eaten_on": item.eaten_on.isoformat(),
                "meal": item.meal.value,
                "entry_method": item.entry_method.value,
                # Counts only. What someone ate is the content, not the shape.
                "ingredient_count": len(resolved.order),
                "custom_ingredients_created": resolved.created,
            },
        )


def _unique_groups(groups: list[AllergenGroup]) -> list[AllergenGroup]:
    # Declaration order, so the stored array is stable whatever order was sent.
    return [group for group in AllergenGroup if group in set(groups)]
