"""Shared test helpers.

A plain module rather than fixtures, because these are values and one-liners
that read better inline than injected. pytest puts this directory on sys.path,
so both conftest and the test modules can import it.
"""

from typing import Any

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
