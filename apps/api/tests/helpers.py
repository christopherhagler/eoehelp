"""Shared test helpers.

A plain module rather than fixtures, because these are values and one-liners
that read better inline than injected. pytest puts this directory on sys.path,
so both conftest and the test modules can import it.
"""

import os
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from eoehelp_api.food.enums import AllergenGroup
from eoehelp_api.insights.food_patterns import DayFood, PatternInput
from eoehelp_api.synthetic.generator import INGREDIENT_GROUPS
from eoehelp_api.synthetic.plans import HistoryPlan

DEFAULT_ONBOARDING: dict[str, Any] = {
    "display_name": "Test Patient",
    "birth_year": 1990,
    "sex_at_birth": "undisclosed",
    "timezone": "UTC",
    "consents": {
        "terms_of_service": True,
        "privacy_policy": True,
        "consumer_health_data": True,
    },
}


def auth(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def onboarding_payload(**overrides: Any) -> dict[str, Any]:
    return {**DEFAULT_ONBOARDING, **overrides}


def utc_today() -> date:
    """Today for the default test patient, whose timezone is UTC."""
    return datetime.now(UTC).date()


def days_ago(n: int) -> str:
    return (utc_today() - timedelta(days=n)).isoformat()


def food_item(**overrides: Any) -> dict[str, Any]:
    """A food as the daily log sends it: today's lunch, from catalog ingredients."""
    return {
        "eaten_on": days_ago(0),
        "meal": "lunch",
        "name": "Cheese toastie",
        "ingredients": [{"code": "bread"}, {"code": "cheese"}, {"code": "butter"}],
        **overrides,
    }


def app_role_url(database_url: str) -> str:
    """Rewrite the test database URL to connect as the unprivileged app role.

    Row-level security binds only this role, so a test that proves isolation has
    to connect as it rather than as the table owner.
    """
    override = os.environ.get("APP_RUNTIME_DATABASE_URL")
    if override:
        return override
    parts = urlsplit(database_url)
    password = os.environ.get("APP_RUNTIME_PASSWORD", "app_runtime_local_only")
    netloc = f"app_runtime:{password}@{parts.hostname}:{parts.port or 5432}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def synthetic_pattern_input(plan: HistoryPlan, window_end: date) -> PatternInput:
    """A generated history as the food-pattern analysis sees a real one.

    Lives in the tests, not the application: nothing outside `synthetic` may
    import the generator (tests/test_architecture.py). Ingredients are catalog
    codes here; the database path keys them by canonical key instead, so only
    group-level results are comparable between the two.
    """
    outcomes = {
        d.entry_date: bool(d.dysphagia_occurred)
        for d in plan.days
        if d.ate_solid_food and d.dysphagia_occurred is not None
    }
    groups: dict[date, set[AllergenGroup]] = defaultdict(set)
    ingredients: dict[date, set[str]] = defaultdict(set)
    for food in plan.foods:
        for code in food.ingredient_codes:
            groups[food.eaten_on] |= INGREDIENT_GROUPS[code]
            ingredients[food.eaten_on].add(code)
    foods = {
        day: DayFood(groups=frozenset(groups[day]), ingredients=frozenset(ingredients[day]))
        for day in {f.eaten_on for f in plan.foods}
    }
    return PatternInput(
        window_end=window_end, outcomes=outcomes, foods=foods, logged_days=len(plan.days)
    )
