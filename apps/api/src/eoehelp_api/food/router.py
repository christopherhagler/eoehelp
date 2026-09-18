"""Food and ingredient logging.

Same split as medications: the ingredient catalog is reference data behind plain
authentication, and everything patient-owned sits under /me.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.audit.service import AuditContext
from eoehelp_api.core import ratelimit
from eoehelp_api.core.deps import (
    Principal,
    get_authenticated_audit_context,
    get_current_patient,
    get_patient_session,
    get_principal,
    get_session,
)
from eoehelp_api.core.errors import NotFoundError, ServiceUnavailableError
from eoehelp_api.core.ratelimit import limiter
from eoehelp_api.food.enums import FoodDataSource
from eoehelp_api.food.models import CatalogIngredient
from eoehelp_api.food.products.provider import FoodData, FoodDataUnavailableError, get_food_data
from eoehelp_api.food.schemas import (
    CatalogIngredientRead,
    CustomIngredientRead,
    CustomIngredientUpdate,
    FoodItemInput,
    FoodItemList,
    FoodItemRead,
    ProductRead,
    ProductSummaryRead,
    RecentFood,
)
from eoehelp_api.food.service import MAX_RECENT_FOODS, FoodService, product_read
from eoehelp_api.identity.patient import Patient

UNAVAILABLE = "Product lookup is unavailable right now. You can add the food by name."

catalog_router = APIRouter(prefix="/foods", tags=["food"])
router = APIRouter(prefix="/me/foods", tags=["food"])


@catalog_router.get("/ingredients", response_model=list[CatalogIngredientRead])
async def list_catalog(
    _principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> list[CatalogIngredientRead]:
    """Every catalog ingredient, with its allergen groups and search aliases.

    Around a hundred rows, sent whole so the client can search as the patient
    types without a request per keystroke.
    """
    result = await session.execute(select(CatalogIngredient).order_by(CatalogIngredient.name))
    return [CatalogIngredientRead.model_validate(row) for row in result.scalars()]


# --- products -----------------------------------------------------------------
#
# Lookups against Open Food Facts and USDA, made by this server so that neither
# learns who is asking. Nothing is stored until a product is logged. The query
# text is never logged: what someone searches for is what they are eating.


@catalog_router.get("/products/search", response_model=list[ProductSummaryRead])
@limiter.limit(ratelimit.PRODUCT_LOOKUP)
async def search_products(
    request: Request,
    q: str = Query(min_length=2, max_length=100),
    limit: int = Query(default=20, ge=1, le=40),
    _principal: Principal = Depends(get_principal),
    food_data: FoodData = Depends(get_food_data),
) -> list[ProductSummaryRead]:
    try:
        found = await food_data.search(q.strip(), limit)
    except FoodDataUnavailableError as error:
        raise ServiceUnavailableError(UNAVAILABLE) from error
    return [
        ProductSummaryRead(
            source=hit.source,
            source_id=hit.source_id,
            barcode=hit.barcode,
            name=hit.name,
            brand=hit.brand,
        )
        for hit in found
    ]


@catalog_router.get("/products/barcode/{barcode}", response_model=ProductRead)
@limiter.limit(ratelimit.PRODUCT_LOOKUP)
async def product_by_barcode(
    request: Request,
    barcode: str = Path(pattern=r"^\d{8,14}$"),
    _principal: Principal = Depends(get_principal),
    food_data: FoodData = Depends(get_food_data),
) -> ProductRead:
    try:
        record = await food_data.by_barcode(barcode)
    except FoodDataUnavailableError as error:
        raise ServiceUnavailableError(UNAVAILABLE) from error
    if record is None:
        raise NotFoundError("No product with that barcode was found.")
    return product_read(record)


@catalog_router.get("/products/{source}/{source_id}", response_model=ProductRead)
@limiter.limit(ratelimit.PRODUCT_LOOKUP)
async def product_detail(
    request: Request,
    source: FoodDataSource,
    source_id: str = Path(max_length=64, pattern=r"^[0-9A-Za-z_-]+$"),
    _principal: Principal = Depends(get_principal),
    food_data: FoodData = Depends(get_food_data),
) -> ProductRead:
    try:
        record = await food_data.product(source, source_id)
    except FoodDataUnavailableError as error:
        raise ServiceUnavailableError(UNAVAILABLE) from error
    if record is None:
        raise NotFoundError("No such product.")
    return product_read(record)


# --- the patient's food log -----------------------------------------------------


@router.get("", response_model=FoodItemList)
async def list_foods(
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
    range_start: date | None = Query(default=None, alias="from"),
    range_end: date | None = Query(default=None, alias="to"),
) -> FoodItemList:
    """Logged food between two days, inclusive. Both default to the patient's today."""
    service = FoodService(session, patient)
    end = range_end or service.today
    start = range_start or end
    items = await service.list_range(start=start, end=end, context=context)
    return FoodItemList(range_start=start, range_end=end, items=items)


@router.post("", response_model=FoodItemRead, status_code=status.HTTP_201_CREATED)
async def log_food(
    payload: FoodItemInput,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
    food_data: FoodData = Depends(get_food_data),
) -> FoodItemRead:
    return await FoodService(session, patient, food_data).create(payload=payload, context=context)


# Literal paths are declared before /{item_id} so they are not captured as ids.
@router.get("/recent", response_model=list[RecentFood])
async def recent_foods(
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
    limit: int = Query(default=20, ge=1, le=MAX_RECENT_FOODS),
) -> list[RecentFood]:
    return await FoodService(session, patient).recent(limit=limit, context=context)


@router.get("/ingredients", response_model=list[CustomIngredientRead])
async def list_custom_ingredients(
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> list[CustomIngredientRead]:
    """The ingredients this patient has added that the catalog does not have."""
    return await FoodService(session, patient).list_custom_ingredients(context=context)


@router.patch("/ingredients/{ingredient_id}", response_model=CustomIngredientRead)
async def update_custom_ingredient(
    ingredient_id: uuid.UUID,
    payload: CustomIngredientUpdate,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> CustomIngredientRead:
    return await FoodService(session, patient).update_custom_ingredient(
        ingredient_id=ingredient_id, payload=payload, context=context
    )


@router.put("/{item_id}", response_model=FoodItemRead)
async def update_food(
    item_id: uuid.UUID,
    payload: FoodItemInput,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
    food_data: FoodData = Depends(get_food_data),
) -> FoodItemRead:
    """Replace a logged food, ingredients included."""
    return await FoodService(session, patient, food_data).update(
        item_id=item_id, payload=payload, context=context
    )


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_food(
    item_id: uuid.UUID,
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> Response:
    await FoodService(session, patient).delete(item_id=item_id, context=context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
