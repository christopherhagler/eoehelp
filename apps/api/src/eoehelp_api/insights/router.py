"""Insights: what the patient's own logs show when read together."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.audit.service import AuditContext
from eoehelp_api.core import ratelimit
from eoehelp_api.deps import (
    get_authenticated_audit_context,
    get_current_patient,
    get_patient_session,
)
from eoehelp_api.identity.patient import Patient
from eoehelp_api.insights import food_patterns
from eoehelp_api.insights.schemas import FoodPatternReport
from eoehelp_api.insights.service import InsightsService

router = APIRouter(prefix="/me/insights", tags=["insights"])


@router.get("/food-patterns", response_model=FoodPatternReport)
@ratelimit.route_limit(ratelimit.INSIGHTS, "insights")
async def read_food_patterns(
    request: Request,
    lag_days: int = Query(
        default=food_patterns.DEFAULT_LAG_DAYS, ge=0, le=food_patterns.MAX_LAG_DAYS
    ),
    patient: Patient = Depends(get_current_patient),
    session: AsyncSession = Depends(get_patient_session),
    context: AuditContext = Depends(get_authenticated_audit_context),
) -> FoodPatternReport:
    """Which allergen groups the patient's log links to symptom days, and which it does not.

    Descriptive only: counts and one of a fixed set of statuses, never advice.
    Ingredients and additive classes are counts only. The method is described in
    docs/plans/2026-09-19-insights-food-patterns.md.
    """
    return await InsightsService(session, patient).food_patterns(lag_days=lag_days, context=context)
