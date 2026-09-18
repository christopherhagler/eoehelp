"""Settings that protect production from development defaults."""

import pytest
from httpx import AsyncClient

from eoehelp_api.config import (
    DEV_FIELD_ENCRYPTION_KEY,
    DEV_JWT_SECRET,
    Settings,
    decode_field_key,
)
from eoehelp_api.core import ratelimit

STRONG = {
    "environment": "production",
    "jwt_secret": "x" * 48,
    # 32 bytes of zeros, urlsafe base64: valid, and not the development key.
    "field_encryption_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "usda_fdc_api_key": "real-key",
    "redis_url": "redis://redis:6379/0",
}


class TestFieldKey:
    def test_the_development_key_is_a_real_32_byte_key(self) -> None:
        assert len(decode_field_key(DEV_FIELD_ENCRYPTION_KEY)) == 32

    @pytest.mark.parametrize("raw", ["", "short", "ZGV2LW9ubHk=", "!!not base64!!"])
    def test_a_malformed_key_is_refused_at_startup(self, raw: str) -> None:
        """The first version hashed anything it could not decode, so a typo
        became a different key and old notes became unreadable, silently."""
        with pytest.raises(ValueError, match="field_encryption_key"):
            Settings(field_encryption_key=raw)


class TestProductionSafety:
    def test_a_fully_configured_production_starts(self) -> None:
        Settings(**STRONG).enforce_production_safety()

    @pytest.mark.parametrize(
        ("setting", "value"),
        [
            ("jwt_secret", DEV_JWT_SECRET),
            ("jwt_secret", "too-short"),
            # The regression: the old check searched this base64 text for
            # "dev-only", which it never contains.
            ("field_encryption_key", DEV_FIELD_ENCRYPTION_KEY),
            ("usda_fdc_api_key", "DEMO_KEY"),
            ("redis_url", None),
            ("rate_limits_enabled", False),
            ("debug", True),
        ],
    )
    def test_each_development_default_is_refused(self, setting: str, value: object) -> None:
        settings = Settings(**{**STRONG, setting: value})
        with pytest.raises(RuntimeError, match=setting):
            settings.enforce_production_safety()

    def test_local_development_is_not_affected(self) -> None:
        Settings(environment="local").enforce_production_safety()


class TestRateLimits:
    async def test_magic_link_requests_are_limited_per_address(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_send(self: object, *, to: str, link: str, ttl_minutes: int) -> None:
            return None

        monkeypatch.setattr("eoehelp_api.identity.email.EmailSender.send_magic_link", fake_send)

        limit = int(ratelimit.MAGIC_LINK_REQUEST.split("/")[0])
        statuses = [
            (
                await client.post("/api/v1/auth/magic-link", json={"email": f"p{i}@example.com"})
            ).status_code
            for i in range(limit + 1)
        ]
        assert statuses == [202] * limit + [429]

    async def test_a_limited_response_says_what_to_do_and_leaks_nothing(
        self, client: AsyncClient
    ) -> None:
        limit = int(ratelimit.MAGIC_LINK_VERIFY.split("/")[0])
        for _ in range(limit):
            await client.post("/api/v1/auth/magic-link/verify", json={"token": "x" * 20})
        limited = await client.post("/api/v1/auth/magic-link/verify", json={"token": "x" * 20})
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "60"
        assert limited.json() == {
            "detail": "Too many requests. Please wait a few minutes and try again."
        }
