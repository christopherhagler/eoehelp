"""Validation failures: diagnosable on the server, and silent about their inputs.

Both halves were added after a real onboarding failure that took a manual
reproduction to diagnose, because a 422 left no server-side trace of which field
had failed.
"""

from datetime import UTC, datetime

from httpx import AsyncClient

from helpers import auth, onboarding_payload

ME = "/api/v1/me"
SYMPTOMS = "/api/v1/me/symptoms"
REFERENCE = "/api/v1/reference"


class TestValidationResponses:
    async def test_the_response_names_the_field_that_failed(
        self, client: AsyncClient, sign_in
    ) -> None:
        """What lets the UI say "When you were diagnosed: ..." rather than "an
        error occurred", which leaves a patient stuck on a form."""
        access = await sign_in()
        response = await client.post(
            f"{ME}/onboarding",
            json=onboarding_payload(diagnosis_month="2019-06"),
            headers=auth(access),
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail[0]["loc"] == ["body", "diagnosis_month"]
        assert detail[0]["msg"]

    async def test_the_response_does_not_echo_the_submitted_value(
        self, client: AsyncClient, onboard
    ) -> None:
        """FastAPI's default 422 includes the rejected input.

        On this codebase that input is health data: a malformed note comes back in
        the error body, and from there into whatever logs or error tracking the
        client has. The handler strips it, and this asserts the stripping.
        """
        access, _ = await onboard()
        secret = "stuck on chicken at the Pine Street place with Dr Alvarez"
        today = datetime.now(UTC).date().isoformat()

        response = await client.put(
            f"{SYMPTOMS}/{today}",
            json={
                "ate_solid_food": True,
                "dysphagia_occurred": False,
                # Over the 4000-character limit, so the field is rejected and the
                # whole value would otherwise be reflected back.
                "notes": secret + ("x" * 4100),
            },
            headers=auth(access),
        )
        assert response.status_code == 422
        assert secret not in response.text
        assert "input" not in response.text

    async def test_a_model_level_rule_still_reports_usefully(
        self, client: AsyncClient, sign_in
    ) -> None:
        access = await sign_in()
        response = await client.post(
            f"{ME}/onboarding",
            json=onboarding_payload(birth_year=datetime.now(UTC).year - 5),
            headers=auth(access),
        )
        assert response.status_code == 422
        assert "18" in response.text


class TestTimezoneReference:
    async def test_the_server_serves_the_zones_it_will_accept(
        self, client: AsyncClient, sign_in
    ) -> None:
        """The browser's ICU data and the server's tz database move independently.

        Offering a zone the server does not know would leave a patient unable to
        complete onboarding at all, so the list comes from the validator's own
        source.
        """
        access = await sign_in()
        response = await client.get(f"{REFERENCE}/timezones", headers=auth(access))
        assert response.status_code == 200

        zones: list[str] = response.json()
        assert len(zones) > 100
        assert "UTC" in zones
        assert "America/Los_Angeles" in zones
        assert zones == sorted(zones)

    async def test_every_offered_zone_is_actually_accepted(
        self, client: AsyncClient, sign_in
    ) -> None:
        """The property that matters: the list and the validator cannot disagree."""
        access = await sign_in()
        zones: list[str] = (await client.get(f"{REFERENCE}/timezones", headers=auth(access))).json()

        import zoneinfo

        for zone in zones:
            zoneinfo.ZoneInfo(zone)

    async def test_it_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get(f"{REFERENCE}/timezones")).status_code == 401
