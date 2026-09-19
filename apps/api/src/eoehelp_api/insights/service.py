"""Assembles a patient's food-pattern report from their own symptom and food logs.

Reads go through the symptom and food domains' own patient-scoped repositories;
this package adds no query of its own. The analysis is `food_patterns.analyse`,
the same code the validation tests run against planted synthetic triggers.
"""

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api import audit
from eoehelp_api.audit.service import AuditContext
from eoehelp_api.core import entry_dates
from eoehelp_api.core.errors import BadRequestError
from eoehelp_api.food.enums import AllergenGroup
from eoehelp_api.food.exposure import exposures
from eoehelp_api.food.repository import FoodRepository
from eoehelp_api.identity.patient import Patient
from eoehelp_api.insights import food_patterns
from eoehelp_api.insights.food_patterns import DayFood, FoodPattern, PatternInput, PatternStatus
from eoehelp_api.insights.schemas import FoodPatternRead, FoodPatternReport
from eoehelp_api.symptoms import scoring
from eoehelp_api.symptoms.repository import SymptomEntryRepository


def _pattern_read(pattern: FoodPattern, labels: dict[str, str]) -> FoodPatternRead:
    return FoodPatternRead(
        key=pattern.key,
        label=labels.get(pattern.key, pattern.key.replace("_", " ")),
        status=pattern.status,
        exposed_days=pattern.exposed_days,
        exposed_symptom_days=pattern.exposed_symptom_days,
        unexposed_days=pattern.unexposed_days,
        unexposed_symptom_days=pattern.unexposed_symptom_days,
        explained_by=pattern.explained_by,
        often_with=pattern.often_with,
        same_day_only=pattern.same_day_only,
        risk_difference=pattern.risk_difference,
        q_value=pattern.q_value,
    )


class InsightsService:
    def __init__(self, session: AsyncSession, patient: Patient) -> None:
        self._session = session
        self._patient = patient

    async def food_patterns(
        self, *, lag_days: int, context: AuditContext | None = None
    ) -> FoodPatternReport:
        if not 0 <= lag_days <= food_patterns.MAX_LAG_DAYS:
            raise BadRequestError(f"lag_days must be between 0 and {food_patterns.MAX_LAG_DAYS}.")

        today = entry_dates.patient_today(self._patient.timezone)
        start = today - timedelta(days=food_patterns.HORIZON_DAYS - 1)
        # Food from before the window still feeds the lag of its first days.
        food_start = start - timedelta(days=lag_days)

        entries = await SymptomEntryRepository(self._session, self._patient.id).list_between(
            start, today
        )
        items = await FoodRepository(self._session, self._patient.id).list_items_between(
            food_start, today
        )

        outcomes: dict[date, bool] = {}
        for entry in entries:
            score = scoring.daily_score(entry)
            if score is not None:
                outcomes[entry.entry_date] = score > 0

        by_day: dict[date, list[DayFood]] = defaultdict(list)
        names: dict[str, str] = {}
        for item in items:
            exposure = exposures(item)
            by_day[item.eaten_on].append(
                DayFood(exposure.groups, exposure.ingredient_keys, exposure.additive_classes)
            )
            for key, name in exposure.names.items():
                names.setdefault(key, name)
        foods = {
            day: DayFood(
                groups=frozenset().union(*(f.groups for f in day_foods)),
                ingredients=frozenset().union(*(f.ingredients for f in day_foods)),
                additives=frozenset().union(*(f.additives for f in day_foods)),
            )
            for day, day_foods in by_day.items()
        }

        report = food_patterns.analyse(
            PatternInput(
                window_end=today, outcomes=outcomes, foods=foods, logged_days=len(entries)
            ),
            lag=lag_days,
        )

        group_labels = {g.value: g.value.replace("_", " ").capitalize() for g in AllergenGroup}
        flagged = sum(p.status is PatternStatus.FLAGGED for p in report.groups)
        assessed = sum(
            p.status in (PatternStatus.FLAGGED, PatternStatus.NO_PATTERN) for p in report.groups
        )
        # Counts only: which foods were flagged is itself health information.
        await audit.record(
            self._session,
            action="insights.food_patterns.read",
            resource_type="insights",
            patient_id=self._patient.id,
            context=context,
            metadata={"lag_days": lag_days, "flagged": flagged, "assessed": assessed},
        )

        return FoodPatternReport(
            method_version=food_patterns.METHOD_VERSION,
            window_start=report.window_start,
            window_end=report.window_end,
            lag_days=report.lag_days,
            analyzable_days=report.analyzable_days,
            symptom_days=report.symptom_days,
            logged_days=report.logged_days,
            complete_window_share=report.complete_window_share,
            logging_gap=report.logging_gap,
            groups=[_pattern_read(p, group_labels) for p in report.groups],
            ingredients=[_pattern_read(p, names) for p in report.ingredients],
            additives=[_pattern_read(p, {}) for p in report.additives],
        )
