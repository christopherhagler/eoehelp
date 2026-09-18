"""Food logging.

What this module guarantees, in order of how easy each is to get wrong:

**A typed name finds the catalog first.** "flour" resolves to wheat flour, not to
a new untagged ingredient that allergen-group analysis would never count. A new
ingredient of the patient's own is created only when nothing matches.

**Ingredients are frozen per item.** Editing a food replaces that item's list;
it never reaches into other days.

**A product's ingredients come from its label, via the server.** When a food is
a scanned or searched product, the server fetches the label itself and stores
an immutable snapshot; the client cannot supply label ingredients. The
patient's own additions are kept, marked as theirs.

**The audit trail records shape, not content.** A food name is free text, and
"what someone ate" is exactly the kind of detail a health-data trail must not
hold. Rows carry the day, the meal, and counts.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api import audit
from eoehelp_api.audit.service import AuditContext
from eoehelp_api.core import entry_dates
from eoehelp_api.core.errors import BadRequestError, ServiceUnavailableError
from eoehelp_api.food.enums import AllergenGroup, FoodDataSource, IngredientProvenance
from eoehelp_api.food.models import (
    CatalogIngredient,
    CustomIngredient,
    FoodLogItem,
    FoodLogItemIngredient,
    FoodProduct,
)
from eoehelp_api.food.products import vocabulary
from eoehelp_api.food.products.provider import FoodData, FoodDataUnavailableError
from eoehelp_api.food.products.records import ProductRecord
from eoehelp_api.food.repository import FoodRepository
from eoehelp_api.food.schemas import (
    CustomIngredientRead,
    CustomIngredientUpdate,
    FoodItemInput,
    FoodItemRead,
    IngredientRead,
    IngredientRef,
    ProductIngredientRead,
    ProductRead,
    ProductRef,
    ProductSnapshotRead,
    RecentFood,
    name_key,
)
from eoehelp_api.identity.patient import Patient

MAX_RANGE_DAYS = 400

# How far back "recent" reaches. Long enough to include the rotation of meals a
# person actually cooks, short enough that a food abandoned months ago stops
# crowding the list.
RECENT_LOOKBACK_DAYS = 90
MAX_RECENT_FOODS = 50
# Each logging of a food counts for half as much every this many days, so the
# list reflects what someone eats now: a food eaten today outranks one eaten
# weekly and last had several days ago, while daily staples stay on top.
RECENT_HALF_LIFE_DAYS = 3


@dataclass
class _Resolved:
    """The ingredient rows an item will point at, deduplicated and in order."""

    order: list[tuple[str, CatalogIngredient | CustomIngredient]] = field(default_factory=list)
    created: int = 0


ATTRIBUTION = {
    FoodDataSource.OPEN_FOOD_FACTS: (
        "Product data from Open Food Facts, available under the Open Database License."
    ),
    FoodDataSource.USDA_FDC: "Product data from USDA FoodData Central (public domain).",
}


def _additive_class(key: str) -> str | None:
    found = vocabulary.additive(key)
    return found.additive_class.value if found else None


def ingredient_read(row: FoodLogItemIngredient) -> IngredientRead:
    common = {
        "canonical_key": row.canonical_key,
        "provenance": row.provenance,
        "recognized": row.recognized,
        "depth": row.depth,
        "note": row.note,
        "additive_class": _additive_class(row.canonical_key),
    }
    if row.catalog is not None:
        return IngredientRead(
            code=row.catalog.code,
            custom_ingredient_id=None,
            name=row.catalog.name,
            allergen_groups=list(row.catalog.allergen_groups),
            typical=row.catalog.is_composite,
            **common,
        )
    if row.custom is not None:
        return IngredientRead(
            code=None,
            custom_ingredient_id=row.custom.id,
            name=row.custom.name,
            allergen_groups=list(row.custom.allergen_groups),
            typical=False,
            **common,
        )
    # A label ingredient. Its groups are classified on read, so an improvement
    # to the classifier corrects past days too, as a retag does.
    return IngredientRead(
        code=None,
        custom_ingredient_id=None,
        name=row.display_name,
        allergen_groups=vocabulary.ordered(
            vocabulary.allergen_groups(row.canonical_key, row.display_name)
        ),
        typical=False,
        **common,
    )


def snapshot_read(product: FoodProduct) -> ProductSnapshotRead:
    return ProductSnapshotRead(
        snapshot_id=product.id,
        source=product.source,
        source_id=product.source_id,
        barcode=product.barcode,
        name=product.name,
        brand=product.brand,
        ingredients_complete=product.ingredients_complete,
        declared_allergens=list(product.declared_allergens),
        may_contain=list(product.may_contain),
        fetched_at=product.fetched_at,
        attribution=ATTRIBUTION[product.source],
    )


def product_read(record: ProductRecord) -> ProductRead:
    return ProductRead(
        source=record.source,
        source_id=record.source_id,
        barcode=record.barcode,
        name=record.name,
        brand=record.brand,
        ingredients_text=record.ingredients_text,
        ingredients=[
            ProductIngredientRead(
                key=i.key,
                name=i.name,
                depth=i.depth,
                recognized=i.recognized,
                note=i.note,
                allergen_groups=vocabulary.ordered(vocabulary.allergen_groups(i.key, i.name)),
                additive_class=_additive_class(i.key),
            )
            for i in record.ingredients
        ],
        ingredients_complete=record.ingredients_complete,
        declared_allergens=vocabulary.ordered(record.declared_allergens),
        may_contain=vocabulary.ordered(record.may_contain),
        inferred_allergens=vocabulary.ordered(record.inferred_allergens),
        source_updated_at=record.source_updated_at,
        attribution=ATTRIBUTION[record.source],
    )


def item_read(item: FoodLogItem) -> FoodItemRead:
    return FoodItemRead(
        id=item.id,
        eaten_on=item.eaten_on,
        meal=item.meal,
        name=item.name,
        entry_method=item.entry_method,
        product=snapshot_read(item.product) if item.product else None,
        ingredients=[ingredient_read(row) for row in item.ingredients],
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


class FoodService:
    def __init__(
        self, session: AsyncSession, patient: Patient, food_data: FoodData | None = None
    ) -> None:
        self._session = session
        self._patient = patient
        self._repo = FoodRepository(session, patient.id)
        # Only needed to log a product that has not been snapshotted yet.
        self._food_data = food_data

    @property
    def today(self) -> date:
        return datetime.now(ZoneInfo(self._patient.timezone)).date()

    # --- writes ---------------------------------------------------------------

    async def create(
        self, *, payload: FoodItemInput, context: AuditContext | None = None
    ) -> FoodItemRead:
        entry_method = entry_dates.classify(payload.eaten_on, today=self.today)
        product = await self._product(payload.product)
        resolved = await self._resolve(payload.ingredients)

        item = FoodLogItem(
            id=uuid.uuid4(),
            patient_id=self._patient.id,
            eaten_on=payload.eaten_on,
            meal=payload.meal,
            name=payload.name,
            name_key=name_key(payload.name),
            entry_method=entry_method,
            product=product,
        )
        item.ingredients = self._rows(product, resolved)
        self._repo.add_item(item)
        await self._session.flush()
        await self._session.refresh(item)

        await self._audit("food_log_item.create", item, product, resolved, context=context)
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

        product = await self._product(payload.product)
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
        item.product = product
        # entry_method is not recomputed, as with symptom entries: correcting a
        # same-day record later does not make it recalled.
        item.ingredients.extend(self._rows(product, resolved))
        await self._session.flush()
        await self._session.refresh(item)

        await self._audit("food_log_item.update", item, product, resolved, context=context)
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
        """Foods logged lately, ranked by how often and how recently.

        Derived from history rather than kept as saved recipes. There is nothing
        to manage, the list tracks what the patient actually eats, and a food's
        ingredients are the ones it had most recently — which is also what the
        patient would expect to see.
        """
        today = self.today
        items = await self._repo.list_items_since(today - timedelta(days=RECENT_LOOKBACK_DAYS))

        latest: dict[str, FoodLogItem] = {}
        counts: dict[str, int] = {}
        scores: dict[str, float] = {}
        for item in items:  # newest first, so the first sighting is the latest
            key = item.name_key
            latest.setdefault(key, item)
            counts[key] = counts.get(key, 0) + 1
            age = max((today - item.eaten_on).days, 0)
            scores[key] = scores.get(key, 0.0) + 0.5 ** (age / RECENT_HALF_LIFE_DAYS)

        ranked = sorted(
            latest.values(),
            key=lambda item: (-scores[item.name_key], item.name_key),
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
                product=snapshot_read(item.product) if item.product else None,
                ingredients=[
                    ingredient_read(row)
                    for row in item.ingredients
                    if row.provenance is IngredientProvenance.PATIENT
                ],
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

    async def _product(self, ref: ProductRef | None) -> FoodProduct | None:
        if ref is None:
            return None
        if ref.snapshot_id is not None:
            snapshot = await self._repo.product_snapshot(ref.snapshot_id)
            if snapshot is None:
                raise BadRequestError("That product could not be found.")
            return snapshot

        # ProductRef guarantees both are set when snapshot_id is not.
        assert ref.source is not None
        assert ref.source_id is not None
        if self._food_data is None:  # pragma: no cover - wiring error, not a request error
            raise RuntimeError("FoodService needs a FoodData provider to look up products.")
        try:
            record = await self._food_data.product(ref.source, ref.source_id)
        except FoodDataUnavailableError as error:
            raise ServiceUnavailableError(
                "Product lookup is unavailable right now. You can add the food by name."
            ) from error
        if record is None:
            raise BadRequestError("That product could not be found.")
        return await self._repo.snapshot_for(record)

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
                # Not in the catalog: it becomes the patient's own, but with the
                # standard identity when the name is a known one ("sodium
                # benzoate"), and with groups the name itself indicates, so a
                # typed "cashew cream" is never left untagged.
                identity = vocabulary.identify(ref.name)
                groups = set(ref.allergen_groups or []) | vocabulary.allergen_groups(ref.name)
                own, created = await self._repo.get_or_create_custom(
                    name=ref.name,
                    key=key,
                    canonical_key=identity.key,
                    allergen_groups=_unique_groups(list(groups)),
                )
                resolved.created += int(created)
                keep(own)

        return resolved

    def _rows(
        self, product: FoodProduct | None, resolved: _Resolved
    ) -> list[FoodLogItemIngredient]:
        rows: list[FoodLogItemIngredient] = []
        if product is not None:
            for entry in product.ingredients:
                rows.append(
                    FoodLogItemIngredient(
                        patient_id=self._patient.id,
                        provenance=IngredientProvenance.LABEL,
                        canonical_key=str(entry["key"]),
                        display_name=str(entry["name"])[:300],
                        depth=int(entry["depth"]),
                        recognized=bool(entry["recognized"]),
                        note=str(entry["note"])[:200] if entry.get("note") else None,
                        position=len(rows),
                    )
                )
        for _, row in resolved.order:
            # The relationship objects are set, not just the foreign keys, so the
            # response can be built without a lazy load the async session forbids.
            reference = {"catalog": row} if isinstance(row, CatalogIngredient) else {"custom": row}
            rows.append(
                FoodLogItemIngredient(
                    patient_id=self._patient.id,
                    provenance=IngredientProvenance.PATIENT,
                    canonical_key=row.canonical_key,
                    display_name=row.name,
                    position=len(rows),
                    **reference,
                )
            )
        return rows

    async def _audit(
        self,
        action: str,
        item: FoodLogItem,
        product: FoodProduct | None,
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
                "label_ingredient_count": len(product.ingredients) if product else 0,
                "product_source": product.source.value if product else None,
                "custom_ingredients_created": resolved.created,
            },
        )


def _unique_groups(groups: list[AllergenGroup]) -> list[AllergenGroup]:
    # Declaration order, so the stored array is stable whatever order was sent.
    return [group for group in AllergenGroup if group in set(groups)]
