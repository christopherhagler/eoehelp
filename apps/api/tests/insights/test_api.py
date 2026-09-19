"""The food-pattern endpoint: shape, validation, audit, limits, and isolation."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.audit.models import AuditLog
from eoehelp_api.core import ratelimit
from eoehelp_api.identity.patient import Patient
from eoehelp_api.insights import food_patterns
from eoehelp_api.insights.service import InsightsService
from eoehelp_api.synthetic.generator import HistoryGenerator
from eoehelp_api.synthetic.writer import SyntheticWriter
from helpers import auth, days_ago, food_item, synthetic_pattern_input

PATTERNS = "/api/v1/me/insights/food-patterns"
SYMPTOMS = "/api/v1/me/symptoms"
FOODS = "/api/v1/me/foods"


async def log_day(client: AsyncClient, access: str, offset: int, **food: object) -> None:
    day = days_ago(offset)
    answered = await client.put(
        f"{SYMPTOMS}/{day}",
        json={"ate_solid_food": True, "dysphagia_occurred": False},
        headers=auth(access),
    )
    assert answered.status_code == 200, answered.text
    logged = await client.post(FOODS, json=food_item(eaten_on=day, **food), headers=auth(access))
    assert logged.status_code == 201, logged.text


class TestEndpoint:
    async def test_the_report_names_every_group_and_its_counts(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        for offset in range(3):
            await log_day(client, access, offset)

        response = await client.get(PATTERNS, headers=auth(access))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["method_version"] == food_patterns.METHOD_VERSION
        assert body["lag_days"] == food_patterns.DEFAULT_LAG_DAYS
        assert body["logged_days"] == 3
        assert len(body["groups"]) == 9
        # Bread, cheese, and butter every day: wheat and milk have no days without them.
        by_key = {g["key"]: g for g in body["groups"]}
        assert by_key["milk"]["status"] == "no_baseline"
        assert by_key["milk"]["label"] == "Milk"
        assert all(i["status"] == "counts_only" for i in body["ingredients"] + body["additives"])

    @pytest.mark.parametrize("lag", [-1, 4, "two"])
    async def test_a_lag_outside_0_to_3_is_refused(self, client: AsyncClient, onboard, lag) -> None:
        access, _ = await onboard()
        response = await client.get(PATTERNS, params={"lag_days": lag}, headers=auth(access))
        assert response.status_code == 422

    async def test_the_window_ends_on_the_patients_own_today(
        self, client: AsyncClient, onboard
    ) -> None:
        zone = "Pacific/Kiritimati"  # UTC+14: most often a different date from UTC
        access, _ = await onboard(timezone=zone)
        body = (await client.get(PATTERNS, headers=auth(access))).json()
        assert body["window_end"] == datetime.now(ZoneInfo(zone)).date().isoformat()

    async def test_a_catalog_dish_counts_toward_its_usual_groups(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        await log_day(client, access, 0, ingredients=[{"code": "mayonnaise"}])
        body = (await client.get(PATTERNS, params={"lag_days": 0}, headers=auth(access))).json()
        egg = next(g for g in body["groups"] if g["key"] == "egg")
        assert egg["exposed_days"] == 1

    async def test_the_audit_trail_records_counts_never_foods(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        access, _ = await onboard()
        await log_day(client, access, 0)
        await client.get(PATTERNS, headers=auth(access))

        rows = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "insights.food_patterns.read")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert set(rows[0].metadata_) == {"lag_days", "flagged", "assessed"}
        assert "milk" not in str(rows[0].metadata_)

    async def test_requests_are_rate_limited(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        limit = int(ratelimit.INSIGHTS.split("/")[0])
        statuses = [
            (await client.get(PATTERNS, headers=auth(access))).status_code for _ in range(limit + 1)
        ]
        assert statuses == [200] * limit + [429]


class TestIsolation:
    async def test_another_patients_log_is_never_counted(
        self, client: AsyncClient, onboard
    ) -> None:
        alice, _ = await onboard("alice@example.com")
        for offset in range(5):
            await log_day(client, alice, offset)
        bob, _ = await onboard("bob@example.com")

        body = (await client.get(PATTERNS, headers=auth(bob))).json()
        assert body["logged_days"] == 0
        assert body["analyzable_days"] == 0
        assert all(g["exposed_days"] == 0 for g in body["groups"])


async def test_the_database_path_matches_the_pure_analysis(session: AsyncSession) -> None:
    """A synthetic history written through the real tables and read back through
    the service gives the same group results as the pure analysis of its plan,
    so the validation of the pure code speaks for what patients see."""
    plan = HistoryGenerator(seed=5003).generate(months=6)
    written = await SyntheticWriter(session).write(plan)
    await session.commit()
    patient = await session.get(Patient, written.patient_id)
    assert patient is not None

    served = await InsightsService(session, patient).food_patterns(lag_days=2)
    expected = food_patterns.analyse(synthetic_pattern_input(plan, served.window_end), lag=2)

    assert served.analyzable_days == expected.analyzable_days
    assert [
        (g.key, g.status, g.exposed_days, g.exposed_symptom_days, g.unexposed_days)
        for g in served.groups
    ] == [
        (g.key, g.status, g.exposed_days, g.exposed_symptom_days, g.unexposed_days)
        for g in expected.groups
    ]
