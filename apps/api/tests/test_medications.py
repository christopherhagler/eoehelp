"""Medications and dose logging through the API."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.models.audit import AuditLog
from helpers import auth

MEDS = "/api/v1/me/medications"
CATALOG = "/api/v1/medications/catalog"


def today() -> str:
    return datetime.now(UTC).date().isoformat()


def days_ago(n: int) -> str:
    return (datetime.now(UTC).date() - timedelta(days=n)).isoformat()


PPI = {
    "medication_code": "omeprazole",
    "dose_amount": "20.00",
    "dose_unit": "mg",
    "frequency": "twice_daily",
    "started_on": None,  # filled per test
}


async def add_ppi(client: AsyncClient, access: str, **overrides: object) -> dict:
    payload = {**PPI, "started_on": days_ago(6), **overrides}
    response = await client.post(MEDS, json=payload, headers=auth(access))
    assert response.status_code == 201, response.text
    return dict(response.json())


class TestCatalog:
    async def test_the_catalog_lists_the_drugs_eoe_actually_uses(
        self, client: AsyncClient, sign_in
    ) -> None:
        access = await sign_in()
        response = await client.get(CATALOG, headers=auth(access))
        assert response.status_code == 200
        codes = {row["code"] for row in response.json()}
        assert {
            "omeprazole",
            "esomeprazole",
            "lansoprazole",
            "pantoprazole",
            "rabeprazole",
            "dexlansoprazole",
            "budesonide_oral_suspension",
            "budesonide_orodispersible",
            "budesonide_slurry",
            "fluticasone_swallowed",
            "dupilumab",
        } == codes

        classes = {row["drug_class"] for row in response.json()}
        assert classes == {"ppi", "swallowed_topical_corticosteroid", "biologic"}

    async def test_the_catalog_needs_only_a_session_not_onboarding(
        self, client: AsyncClient, sign_in
    ) -> None:
        """Reference data discloses nothing about the reader, so it is not /me and
        does not require a patient record."""
        access = await sign_in()
        assert (await client.get(CATALOG, headers=auth(access))).status_code == 200

    async def test_the_catalog_still_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get(CATALOG)).status_code == 401


class TestAddingAMedication:
    async def test_a_frequency_becomes_a_stored_recurrence_rule(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        """Clients send a frequency; the RRULE is built server-side.

        An arbitrary rule is an expansion primitive, so the grammar a caller can
        reach is the enum rather than iCal.
        """
        access, _ = await onboard()
        body = await add_ppi(client, access)

        assert body["frequency"] == "twice_daily"
        assert body["generic_name"] == "Omeprazole"
        assert body["is_active"] is True

        stored = (
            await session.execute(text("SELECT schedule_rrule FROM medications"))
        ).scalar_one()
        assert stored == "FREQ=DAILY;BYHOUR=9,21;BYMINUTE=0;BYSECOND=0"

    async def test_an_rrule_cannot_be_injected_through_the_frequency_field(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        response = await client.post(
            MEDS,
            json={**PPI, "started_on": today(), "frequency": "FREQ=SECONDLY;COUNT=99999999"},
            headers=auth(access),
        )
        assert response.status_code == 422

    async def test_an_unknown_medication_is_refused(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        response = await client.post(
            MEDS,
            json={**PPI, "started_on": today(), "medication_code": "not_a_real_drug"},
            headers=auth(access),
        )
        assert response.status_code == 404

    async def test_a_future_start_is_refused(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
        response = await client.post(
            MEDS, json={**PPI, "started_on": tomorrow}, headers=auth(access)
        )
        assert response.status_code == 400

    async def test_a_negative_dose_is_refused(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        response = await client.post(
            MEDS,
            json={**PPI, "started_on": today(), "dose_amount": "-20.00"},
            headers=auth(access),
        )
        assert response.status_code == 422

    async def test_the_prescriber_note_is_encrypted_at_rest(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        access, _ = await onboard()
        secret = "Dr Alvarez wants a repeat scope in 8 weeks"
        await add_ppi(client, access, prescriber_note=secret)

        stored = (
            await session.execute(text("SELECT prescriber_note_encrypted FROM medications"))
        ).scalar_one()
        assert secret.encode() not in bytes(stored)

        listed = await client.get(MEDS, headers=auth(access))
        assert listed.json()[0]["prescriber_note"] == secret


class TestStoppingAndDeleting:
    async def test_stopping_records_when_and_why(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        medication = await add_ppi(client, access)

        response = await client.post(
            f"{MEDS}/{medication['id']}/stop",
            json={"ended_on": today(), "stop_reason": "ineffective"},
            headers=auth(access),
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is False
        assert response.json()["stop_reason"] == "ineffective"

    async def test_a_reason_is_required_to_stop(self, client: AsyncClient, onboard) -> None:
        """ "Stopped because it did not work" and "stopped because insurance refused"
        lead to opposite next steps, and an unexplained end date loses that."""
        access, _ = await onboard()
        medication = await add_ppi(client, access)
        response = await client.post(
            f"{MEDS}/{medication['id']}/stop",
            json={"ended_on": today()},
            headers=auth(access),
        )
        assert response.status_code == 422

    async def test_stopping_twice_is_a_conflict(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        medication = await add_ppi(client, access)
        body = {"ended_on": today(), "stop_reason": "remission"}
        await client.post(f"{MEDS}/{medication['id']}/stop", json=body, headers=auth(access))
        second = await client.post(
            f"{MEDS}/{medication['id']}/stop", json=body, headers=auth(access)
        )
        assert second.status_code == 409

    async def test_an_end_date_before_the_start_is_refused(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        medication = await add_ppi(client, access, started_on=days_ago(2))
        response = await client.post(
            f"{MEDS}/{medication['id']}/stop",
            json={"ended_on": days_ago(5), "stop_reason": "other"},
            headers=auth(access),
        )
        assert response.status_code == 400

    async def test_a_mistyped_entry_can_be_deleted(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        medication = await add_ppi(client, access)
        deleted = await client.delete(f"{MEDS}/{medication['id']}", headers=auth(access))
        assert deleted.status_code == 204
        assert (await client.get(MEDS, headers=auth(access))).json() == []

    async def test_deleting_is_refused_once_doses_exist(self, client: AsyncClient, onboard) -> None:
        """At that point it is history, not a typo: deleting it would remove the
        treatment a symptom trend was recorded against."""
        access, _ = await onboard()
        medication = await add_ppi(client, access)
        await client.post(f"{MEDS}/{medication['id']}/doses", headers=auth(access))

        response = await client.delete(f"{MEDS}/{medication['id']}", headers=auth(access))
        assert response.status_code == 409
        assert "Stop it instead" in response.text


class TestDoseLogging:
    async def test_logging_a_dose_needs_no_body(self, client: AsyncClient, onboard) -> None:
        """The daily action has to be the cheapest call in the API."""
        access, _ = await onboard()
        medication = await add_ppi(client, access)
        response = await client.post(f"{MEDS}/{medication['id']}/doses", headers=auth(access))
        assert response.status_code == 201
        assert response.json()["status"] == "taken"

    async def test_two_doses_in_one_day_are_two_events(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        """A twice-daily PPI has two, and collapsing them to a daily checkbox
        would make adherence uncomputable for exactly those regimens."""
        access, _ = await onboard()
        medication = await add_ppi(client, access)
        await client.post(f"{MEDS}/{medication['id']}/doses", headers=auth(access))
        await client.post(f"{MEDS}/{medication['id']}/doses", headers=auth(access))

        count = (await session.execute(text("SELECT count(*) FROM medication_doses"))).scalar_one()
        assert count == 2

    async def test_a_mistaken_tap_can_be_undone(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        medication = await add_ppi(client, access)
        dose = await client.post(f"{MEDS}/{medication['id']}/doses", headers=auth(access))
        dose_id = dose.json()["id"]

        undone = await client.delete(f"{MEDS}/doses/{dose_id}", headers=auth(access))
        assert undone.status_code == 204

        view = await client.get(f"{MEDS}/today", headers=auth(access))
        assert view.json()["items"][0]["doses_today"] == []

    async def test_a_skip_is_recorded_rather_than_inferred(
        self, client: AsyncClient, onboard
    ) -> None:
        """An absent dose is ambiguous; a deliberate skip is information."""
        access, _ = await onboard()
        medication = await add_ppi(client, access)
        response = await client.post(
            f"{MEDS}/{medication['id']}/doses",
            json={"status": "skipped"},
            headers=auth(access),
        )
        assert response.status_code == 201
        assert response.json()["status"] == "skipped"

    async def test_a_dose_before_the_medication_started_is_refused(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        medication = await add_ppi(client, access, started_on=days_ago(2))
        response = await client.post(
            f"{MEDS}/{medication['id']}/doses",
            json={"taken_at": f"{days_ago(5)}T12:00:00Z"},
            headers=auth(access),
        )
        assert response.status_code == 400

    async def test_a_dose_after_the_medication_stopped_is_refused(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        medication = await add_ppi(client, access, started_on=days_ago(6))
        await client.post(
            f"{MEDS}/{medication['id']}/stop",
            json={"ended_on": days_ago(3), "stop_reason": "side_effects"},
            headers=auth(access),
        )
        response = await client.post(
            f"{MEDS}/{medication['id']}/doses",
            json={"taken_at": f"{today()}T12:00:00Z"},
            headers=auth(access),
        )
        assert response.status_code == 400

    async def test_a_future_dose_is_refused(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        medication = await add_ppi(client, access)
        tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
        response = await client.post(
            f"{MEDS}/{medication['id']}/doses",
            json={"taken_at": f"{tomorrow}T12:00:00Z"},
            headers=auth(access),
        )
        assert response.status_code == 400


class TestTodayView:
    async def test_it_reports_what_is_due_and_what_is_logged(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        medication = await add_ppi(client, access)
        await client.post(f"{MEDS}/{medication['id']}/doses", headers=auth(access))

        response = await client.get(f"{MEDS}/today", headers=auth(access))
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["generic_name"] == "Omeprazole"
        assert item["dose_label"] == "20 mg"
        assert item["expected_today"] == 2
        assert len(item["doses_today"]) == 1

    async def test_a_stopped_medication_leaves_the_daily_view(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        medication = await add_ppi(client, access)
        await client.post(
            f"{MEDS}/{medication['id']}/stop",
            json={"ended_on": today(), "stop_reason": "remission"},
            headers=auth(access),
        )
        response = await client.get(f"{MEDS}/today", headers=auth(access))
        assert response.json()["items"] == []

    async def test_an_as_needed_medication_has_no_expectation(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        await add_ppi(client, access, frequency="as_needed")
        response = await client.get(f"{MEDS}/today", headers=auth(access))
        assert response.json()["items"][0]["expected_today"] is None


class TestAdherenceEndpoint:
    async def test_adherence_uses_the_schedule_as_the_denominator(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        # Started 6 days ago, twice daily: 7 days in the window including today,
        # so 14 expected doses. Log 7 of them.
        medication = await add_ppi(client, access, started_on=days_ago(6))
        for _ in range(7):
            await client.post(f"{MEDS}/{medication['id']}/doses", headers=auth(access))

        response = await client.get(
            f"{MEDS}/adherence", params={"from": days_ago(6), "to": today()}, headers=auth(access)
        )
        assert response.status_code == 200
        row = response.json()["medications"][0]
        assert row["expected_doses"] == 14
        assert row["taken_doses"] == 7
        assert row["percentage"] == 50.0
        assert row["frequency"] == "twice_daily"

    async def test_doses_are_bucketed_in_the_patients_timezone(
        self, client: AsyncClient, onboard
    ) -> None:
        """A dose logged now must count toward the patient's today, not UTC's.

        For a Los Angeles patient in the evening, UTC is already tomorrow. Reading
        the timestamp in UTC drops the dose out of the window and reports 0%
        adherence for someone who took everything.
        """
        access, _ = await onboard(timezone="America/Los_Angeles")
        medication = await add_ppi(client, access, started_on=days_ago(1))
        await client.post(f"{MEDS}/{medication['id']}/doses", headers=auth(access))

        response = await client.get(f"{MEDS}/adherence", headers=auth(access))
        row = response.json()["medications"][0]
        assert row["taken_doses"] == 1

    async def test_as_needed_reports_unknown_not_perfect(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        await add_ppi(client, access, frequency="as_needed")
        response = await client.get(f"{MEDS}/adherence", headers=auth(access))
        row = response.json()["medications"][0]
        assert row["expected_doses"] is None
        assert row["percentage"] is None


class TestIsolation:
    async def test_one_patient_cannot_see_or_touch_anothers_medication(
        self, client: AsyncClient, onboard
    ) -> None:
        access_a, _ = await onboard("alice@example.com")
        access_b, _ = await onboard("bob@example.com")
        medication = await add_ppi(client, access_a)

        assert (await client.get(MEDS, headers=auth(access_b))).json() == []

        # 404 rather than 403: confirming the row exists would disclose that
        # someone else is on a treatment.
        as_bob = await client.post(f"{MEDS}/{medication['id']}/doses", headers=auth(access_b))
        assert as_bob.status_code == 404

        stop_attempt = await client.post(
            f"{MEDS}/{medication['id']}/stop",
            json={"ended_on": today(), "stop_reason": "other"},
            headers=auth(access_b),
        )
        assert stop_attempt.status_code == 404

    async def test_one_patient_cannot_undo_anothers_dose(
        self, client: AsyncClient, onboard
    ) -> None:
        access_a, _ = await onboard("alice@example.com")
        access_b, _ = await onboard("bob@example.com")
        medication = await add_ppi(client, access_a)
        dose = await client.post(f"{MEDS}/{medication['id']}/doses", headers=auth(access_a))

        response = await client.delete(f"{MEDS}/doses/{dose.json()['id']}", headers=auth(access_b))
        assert response.status_code == 404


class TestAuditTrail:
    async def test_every_change_is_recorded_without_the_prescriber_note(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        access, _ = await onboard()
        medication = await add_ppi(
            client, access, prescriber_note="taper per Dr Alvarez at the Swedish clinic"
        )
        dose = await client.post(f"{MEDS}/{medication['id']}/doses", headers=auth(access))
        await client.delete(f"{MEDS}/doses/{dose.json()['id']}", headers=auth(access))
        await client.post(
            f"{MEDS}/{medication['id']}/stop",
            json={"ended_on": today(), "stop_reason": "cost"},
            headers=auth(access),
        )

        rows = (await session.execute(select(AuditLog))).scalars().all()
        actions = [r.action for r in rows if r.action.startswith("medication")]
        assert actions == [
            "medication.create",
            "medication_dose.create",
            "medication_dose.delete",
            "medication.stop",
        ]

        serialised = str([r.metadata_ for r in rows])
        assert "Swedish clinic" not in serialised
        assert "has_prescriber_note" in serialised
        # Which drug a change concerned is the point of the trail, and a drug name
        # is clinical without being identifying.
        assert "omeprazole" in serialised
