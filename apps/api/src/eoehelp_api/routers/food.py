"""Food and ingredient logging.

Same split as medications: the ingredient catalog is reference data behind plain
authentication, and everything patient-owned sits under /me.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.core.deps import (
    Principal,
    get_authenticated_audit_context,
    get_current_patient,
    get_patient_session,
    get_principal,
    get_session,
)
from eoehelp_api.models.food import CatalogIngredient
from eoehelp_api.models.patient import Patient
from eoehelp_api.schemas.food import (
    CatalogIngredientRead,
    CustomIngredientRead,
    CustomIngredientUpdate,
    FoodItemInput,
    FoodItemList,
    FoodItemRead,
    RecentFood,
)
from eoehelp_api.services.audit import AuditContext
from eoehelp_api.services.food import MAX_RECENT_FOODS, FoodService

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
) -> FoodItemRead:
    return await FoodService(session, patient).create(payload=payload, context=context)


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
) -> FoodItemRead:
    """Replace a logged food, ingredients included."""
    return await FoodService(session, patient).update(
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
