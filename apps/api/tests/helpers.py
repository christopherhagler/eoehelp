"""Shared test helpers.

A plain module rather than fixtures, because these are values and one-liners
that read better inline than injected. pytest puts this directory on sys.path,
so both conftest and the test modules can import it.
"""

import os
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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
