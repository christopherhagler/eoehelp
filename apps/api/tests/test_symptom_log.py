"""The daily symptom log, end to end through the API."""

from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.models.audit import AuditLog
from helpers import auth

SYMPTOMS = "/api/v1/me/symptoms"


def today() -> date:
    return datetime.now(UTC).date()


CLEAR_DAY = {"ate_solid_food": True, "dysphagia_occurred": False}
BAD_DAY = {
    "ate_solid_food": True,
    "dysphagia_occurred": True,
    "dysphagia_relief": "vomited",
    "odynophagia": True,
    "odynophagia_severity": 2,
}


class TestWritingADay:
    async def test_a_symptom_free_day_is_two_answers(self, client: AsyncClient, onboard) -> None:
        """The common case has to be trivial or patients stop logging, and every
        downstream feature loses its input."""
        access, _ = await onboard()
        response = await client.put(f"{SYMPTOMS}/{today()}", json=CLEAR_DAY, headers=auth(access))
        assert response.status_code == 200
        body = response.json()
        assert body["entry_date"] == today().isoformat()
        assert body["daily_score"] == 0
        assert body["entry_method"] == "same_day"
        assert body["instrument_code"] == "DSQ"

    async def test_writing_the_same_day_twice_updates_rather_than_duplicates(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        """PUT by date, so an offline client replaying a queued submission cannot
        produce a second entry for one day."""
        access, _ = await onboard()
        await client.put(f"{SYMPTOMS}/{today()}", json=CLEAR_DAY, headers=auth(access))
        second = await client.put(f"{SYMPTOMS}/{today()}", json=BAD_DAY, headers=auth(access))

        assert second.status_code == 200
        # 2 for question 2 and 3 for vomiting; pain is scored separately.
        assert second.json()["daily_score"] == 5

        count = (await session.execute(text("SELECT count(*) FROM symptom_entries"))).scalar_one()
        assert count == 1

    async def test_notes_are_encrypted_at_rest(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        """Free text is where identifiers leak: patients write their own and
        their doctor's name into notes."""
        access, _ = await onboard()
        secret = "Dr Alvarez said to call if it happens again"
        await client.put(
            f"{SYMPTOMS}/{today()}",
            json={**CLEAR_DAY, "notes": secret},
            headers=auth(access),
        )

        stored = (
            await session.execute(text("SELECT notes_encrypted FROM symptom_entries"))
        ).scalar_one()
        assert isinstance(stored, (bytes, memoryview))
        assert secret.encode() not in bytes(stored)

        # Still readable through the API, which is the point of encrypting rather
        # than dropping it.
        read_back = await client.get(f"{SYMPTOMS}/{today()}", headers=auth(access))
        assert read_back.json()["notes"] == secret

    async def test_a_day_without_solid_food_cannot_carry_a_dysphagia_answer(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        response = await client.put(
            f"{SYMPTOMS}/{today()}",
            json={"ate_solid_food": False, "dysphagia_occurred": False},
            headers=auth(access),
        )
        assert response.status_code == 422

    async def test_relief_is_required_when_something_stuck(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        response = await client.put(
            f"{SYMPTOMS}/{today()}",
            json={"ate_solid_food": True, "dysphagia_occurred": True},
            headers=auth(access),
        )
        assert response.status_code == 422

    async def test_a_solid_food_day_must_answer_whether_food_stuck(
        self, client: AsyncClient, onboard
    ) -> None:
        """Without question 2 the day is not a valid diary day, and silently
        treating it as clear would lower the score."""
        access, _ = await onboard()
        response = await client.put(
            f"{SYMPTOMS}/{today()}", json={"ate_solid_food": True}, headers=auth(access)
        )
        assert response.status_code == 422

    async def test_relief_cannot_be_given_when_nothing_stuck(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        response = await client.put(
            f"{SYMPTOMS}/{today()}",
            json={**CLEAR_DAY, "dysphagia_relief": "drank_liquid"},
            headers=auth(access),
        )
        assert response.status_code == 422

    async def test_an_er_visit_must_be_medical_attention(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        response = await client.put(
            f"{SYMPTOMS}/{today()}",
            json={
                "ate_solid_food": True,
                "dysphagia_occurred": True,
                "dysphagia_relief": "vomited",
                "food_impaction_er_visit": True,
            },
            headers=auth(access),
        )
        assert response.status_code == 422

    async def test_an_er_visit_scores_the_maximum_and_is_flagged(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        response = await client.put(
            f"{SYMPTOMS}/{today()}",
            json={
                "ate_solid_food": True,
                "dysphagia_occurred": True,
                "dysphagia_relief": "sought_medical_attention",
                "food_impaction_er_visit": True,
            },
            headers=auth(access),
        )
        assert response.status_code == 200
        assert response.json()["daily_score"] == 6
        assert response.json()["food_impaction_er_visit"] is True

    async def test_the_database_holds_the_rules_on_its_own(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        """The validator explains; the check constraint is the guarantee."""
        access, _ = await onboard()
        await client.put(f"{SYMPTOMS}/{today()}", json=CLEAR_DAY, headers=auth(access))
        with pytest.raises(IntegrityError, match="relief_answers_dysphagia"):
            await session.execute(text("UPDATE symptom_entries SET dysphagia_relief = 'vomited'"))
        await session.rollback()


class TestDateRules:
    async def test_a_future_day_is_refused(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        response = await client.put(
            f"{SYMPTOMS}/{today() + timedelta(days=1)}", json=CLEAR_DAY, headers=auth(access)
        )
        assert response.status_code == 400

    async def test_recent_backfill_is_allowed_and_flagged(
        self, client: AsyncClient, onboard
    ) -> None:
        """Flagged rather than hidden: research weights same-day entries above
        recalled ones, and the flag is derived here rather than trusted from the
        client."""
        access, _ = await onboard()
        response = await client.put(
            f"{SYMPTOMS}/{today() - timedelta(days=3)}", json=CLEAR_DAY, headers=auth(access)
        )
        assert response.status_code == 200
        assert response.json()["entry_method"] == "backfill"

    async def test_older_than_a_week_is_refused(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        response = await client.put(
            f"{SYMPTOMS}/{today() - timedelta(days=8)}", json=CLEAR_DAY, headers=auth(access)
        )
        assert response.status_code == 400

    async def test_today_follows_the_patients_timezone(self, client: AsyncClient, onboard) -> None:
        """A day that is still in the future in UTC can already be today in
        Auckland. Scored against UTC, that entry is rejected or silently recorded
        as a backfill of a day that has not happened."""
        access, _ = await onboard(timezone="Pacific/Auckland")
        from zoneinfo import ZoneInfo

        local_today = datetime.now(ZoneInfo("Pacific/Auckland")).date()
        response = await client.put(
            f"{SYMPTOMS}/{local_today}", json=CLEAR_DAY, headers=auth(access)
        )
        assert response.status_code == 200
        assert response.json()["entry_method"] == "same_day"


class TestReadingBack:
    async def test_range_listing_returns_days_in_order(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        for offset in (2, 0, 1):
            await client.put(
                f"{SYMPTOMS}/{today() - timedelta(days=offset)}",
                json=CLEAR_DAY,
                headers=auth(access),
            )

        response = await client.get(SYMPTOMS, headers=auth(access))
        assert response.status_code == 200
        dates = [e["entry_date"] for e in response.json()["entries"]]
        assert dates == sorted(dates)
        assert len(dates) == 3

    async def test_a_day_that_was_never_logged_is_a_404(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        response = await client.get(f"{SYMPTOMS}/{today()}", headers=auth(access))
        assert response.status_code == 404

    async def test_deleting_a_day_removes_it(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        await client.put(f"{SYMPTOMS}/{today()}", json=CLEAR_DAY, headers=auth(access))
        deleted = await client.delete(f"{SYMPTOMS}/{today()}", headers=auth(access))
        assert deleted.status_code == 204
        assert (await client.get(f"{SYMPTOMS}/{today()}", headers=auth(access))).status_code == 404


class TestIsolation:
    async def test_one_patient_cannot_read_anothers_day(self, client: AsyncClient, onboard) -> None:
        """404 rather than 403: confirming the record exists would itself be a
        disclosure. There is no id in the URL to tamper with either — only a
        date, and the patient comes from the token."""
        access_a, _ = await onboard("alice@example.com")
        access_b, _ = await onboard("bob@example.com")

        await client.put(f"{SYMPTOMS}/{today()}", json=BAD_DAY, headers=auth(access_a))

        as_bob = await client.get(f"{SYMPTOMS}/{today()}", headers=auth(access_b))
        assert as_bob.status_code == 404

        bobs_list = await client.get(SYMPTOMS, headers=auth(access_b))
        assert bobs_list.json()["entries"] == []

    async def test_writing_the_same_date_as_another_patient_is_a_separate_row(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        access_a, _ = await onboard("alice@example.com")
        access_b, _ = await onboard("bob@example.com")

        await client.put(f"{SYMPTOMS}/{today()}", json=CLEAR_DAY, headers=auth(access_a))
        response = await client.put(f"{SYMPTOMS}/{today()}", json=BAD_DAY, headers=auth(access_b))

        assert response.status_code == 200
        count = (await session.execute(text("SELECT count(*) FROM symptom_entries"))).scalar_one()
        assert count == 2


class TestSymptomBurden:
    async def test_a_sparse_fortnight_refuses_to_produce_a_score(
        self, client: AsyncClient, onboard
    ) -> None:
        """The failure mode this guards: three logged days divided across
        fourteen renders a badly-tracked fortnight as remission."""
        access, _ = await onboard()
        for offset in range(3):
            await client.put(
                f"{SYMPTOMS}/{today() - timedelta(days=offset)}",
                json=BAD_DAY,
                headers=auth(access),
            )

        response = await client.get(f"{SYMPTOMS}/burden", headers=auth(access))
        assert response.status_code == 200
        body = response.json()
        assert body["score"] is None
        assert body["days_scorable"] == 3
        assert body["components"]["unscorable_reason"] == "fewer_than_minimum_scorable_days"

    async def test_a_fully_logged_week_scores(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        # Seven days is the floor, and the backfill limit is also seven, so this
        # is exactly the earliest point a new patient can be scored.
        for offset in range(7):
            await client.put(
                f"{SYMPTOMS}/{today() - timedelta(days=offset)}",
                json=BAD_DAY,
                headers=auth(access),
            )

        body = (await client.get(f"{SYMPTOMS}/burden", headers=auth(access))).json()
        assert body["days_scorable"] == 7
        assert body["score"] == 70.0  # 5 points a day, normalised over 14 days
        assert body["max_score"] == 84
        assert body["components"]["dysphagia_days"] == 7

    async def test_the_trend_returns_one_point_per_day(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        await client.put(f"{SYMPTOMS}/{today()}", json=CLEAR_DAY, headers=auth(access))
        response = await client.get(f"{SYMPTOMS}/burden/trend?points=10", headers=auth(access))
        assert response.status_code == 200
        assert len(response.json()["points"]) == 10


class TestAuditTrail:
    async def test_writes_and_detail_reads_are_both_recorded(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        """Reads matter as much as writes: "did someone browse my records" is a
        question a breach response has to be able to answer."""
        access, _ = await onboard()
        await client.put(f"{SYMPTOMS}/{today()}", json=CLEAR_DAY, headers=auth(access))
        await client.put(f"{SYMPTOMS}/{today()}", json=BAD_DAY, headers=auth(access))
        await client.get(f"{SYMPTOMS}/{today()}", headers=auth(access))
        await client.get(SYMPTOMS, headers=auth(access))
        await client.delete(f"{SYMPTOMS}/{today()}", headers=auth(access))

        actions = [
            r.action
            for r in (await session.execute(select(AuditLog))).scalars().all()
            if r.action.startswith("symptom_entry")
        ]
        assert actions == [
            "symptom_entry.create",
            "symptom_entry.update",
            "symptom_entry.read",
            "symptom_entry.list",
            "symptom_entry.delete",
        ]

    async def test_the_trail_records_that_a_note_exists_not_what_it_says(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        access, _ = await onboard()
        await client.put(
            f"{SYMPTOMS}/{today()}",
            json={**CLEAR_DAY, "notes": "swallowed wrong at the Thai place on Pine"},
            headers=auth(access),
        )

        rows = (await session.execute(select(AuditLog))).scalars().all()
        serialised = str([r.metadata_ for r in rows])
        assert "Thai place" not in serialised
        assert "has_notes" in serialised
