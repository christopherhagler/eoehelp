"""Endoscopy records through the API."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.exceptions import InvalidTag
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.models.audit import AuditLog
from helpers import auth

SCOPES = "/api/v1/me/endoscopies"


def days_ago(n: int) -> str:
    return (datetime.now(UTC).date() - timedelta(days=n)).isoformat()


def report(**overrides: Any) -> dict[str, Any]:
    return {
        "performed_on": days_ago(30),
        "indication": "treatment_response",
        "facility": "Riverside Digestive Health",
        "notes": "Dr Okafor: mucosa much improved",
        "erefs": {
            "version": "classic",
            "edema": 1,
            "rings": 1,
            "exudates": 0,
            "furrows": 1,
            "stricture": 0,
        },
        "biopsies": [
            {"location": "proximal", "peak_eos_per_hpf": 4},
            {"location": "distal", "peak_eos_per_hpf": 22, "basal_zone_hyperplasia": True},
        ],
        "dilation": None,
        **overrides,
    }


async def add(client: AsyncClient, access: str, **overrides: Any) -> dict[str, Any]:
    response = await client.post(SCOPES, json=report(**overrides), headers=auth(access))
    assert response.status_code == 201, response.text
    return dict(response.json())


class TestRecording:
    async def test_a_full_report_round_trips_with_derived_readings(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        scope = await add(client, access)

        assert scope["erefs"]["total"] == 3
        assert scope["erefs"]["max_total"] == 8
        assert [b["histology"] for b in scope["biopsies"]] == [
            "below_threshold",
            "at_or_above_threshold",
        ]
        assert scope["peak"] == {"value": 22, "comparator": "exact", "location": "distal"}
        assert scope["histology"] == "at_or_above_threshold"
        assert scope["deep_histology"] == "at_or_above_threshold"
        assert [b["deep_histology"] for b in scope["biopsies"]] == [
            "below_threshold",
            "at_or_above_threshold",
        ]
        assert scope["remission_threshold_eos_per_hpf"] == 15
        assert scope["deep_remission_max_eos_per_hpf"] == 6
        assert scope["facility"] == "Riverside Digestive Health"

    async def test_a_report_with_only_a_date_is_allowed(self, client: AsyncClient, onboard) -> None:
        """Patients often know only that a scope happened. That is still history."""
        access, _ = await onboard()
        scope = await add(client, access, erefs=None, biopsies=[], facility=None, notes=None)
        assert scope["erefs"] is None
        assert scope["peak"] is None
        assert scope["histology"] is None

    async def test_partial_erefs_has_no_total(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        scope = await add(client, access, erefs={"version": "graded", "rings": 2})
        assert scope["erefs"]["rings"] == 2
        assert scope["erefs"]["edema"] is None
        assert scope["erefs"]["total"] is None
        assert scope["erefs"]["max_total"] == 10

    async def test_a_stated_upper_bound_is_kept_and_read_honestly(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        scope = await add(
            client,
            access,
            biopsies=[
                {"location": "mid", "peak_eos_per_hpf": 50, "peak_eos_comparator": "greater_than"},
                {"location": "distal", "peak_eos_per_hpf": 50},
            ],
        )
        # Same number, but ">50" says more than "50".
        assert scope["peak"] == {"value": 50, "comparator": "greater_than", "location": "mid"}

        vague = await add(
            client,
            access,
            biopsies=[
                {"location": "distal", "peak_eos_per_hpf": 20, "peak_eos_comparator": "less_than"}
            ],
        )
        assert vague["histology"] == "indeterminate"

    async def test_a_dilation_is_recorded_with_the_scope(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        scope = await add(
            client,
            access,
            indication="food_impaction",
            dilation={
                "dilator_type": "balloon",
                "pre_diameter_mm": "12.0",
                "final_diameter_mm": "15.0",
                "complication": "none",
            },
        )
        assert scope["dilation"]["final_diameter_mm"] == "15.0"


class TestValidation:
    async def test_scores_outside_the_grading_are_refused(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        for erefs_payload in (
            {"version": "classic", "edema": 2},
            {"version": "graded", "rings": 4},
            {"version": "graded", "stricture": -1},
            {"version": "classic"},
        ):
            response = await client.post(
                SCOPES, json=report(erefs=erefs_payload), headers=auth(access)
            )
            assert response.status_code == 422, erefs_payload

    async def test_the_same_graded_score_is_accepted_under_its_own_grading(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard()
        await add(client, access, erefs={"version": "graded", "edema": 2, "furrows": 2})

    async def test_the_database_refuses_an_out_of_range_score_on_its_own(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        """The check constraint is the guarantee; the validator only explains."""
        access, _ = await onboard()
        scope = await add(client, access)
        with pytest.raises(IntegrityError, match="erefs_edema_in_range"):
            await session.execute(
                text("UPDATE endoscopies SET erefs_edema = 2 WHERE id = :id"),
                {"id": scope["id"]},
            )
        await session.rollback()

    async def test_one_count_per_site(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        response = await client.post(
            SCOPES,
            json=report(
                biopsies=[
                    {"location": "distal", "peak_eos_per_hpf": 3},
                    {"location": "distal", "peak_eos_per_hpf": 30},
                ]
            ),
            headers=auth(access),
        )
        assert response.status_code == 422

    async def test_a_dilation_cannot_narrow(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        response = await client.post(
            SCOPES,
            json=report(dilation={"pre_diameter_mm": "15.0", "final_diameter_mm": "12.0"}),
            headers=auth(access),
        )
        assert response.status_code == 422

    async def test_dates_must_be_possible(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard(birth_year=1990)
        future = await client.post(
            SCOPES, json=report(performed_on=days_ago(-2)), headers=auth(access)
        )
        assert future.status_code == 400
        before_birth = await client.post(
            SCOPES, json=report(performed_on="1989-06-01"), headers=auth(access)
        )
        assert before_birth.status_code == 400
        years_ago = await client.post(
            SCOPES, json=report(performed_on="2012-03-04"), headers=auth(access)
        )
        assert years_ago.status_code == 201, "old reports are the point; no backfill window"


class TestEditing:
    async def test_adding_results_later_replaces_the_findings(
        self, client: AsyncClient, onboard
    ) -> None:
        """The usual order: scope first, pathology a week later."""
        access, _ = await onboard()
        scope = await add(client, access, biopsies=[], dilation={"dilator_type": "bougie"})

        response = await client.put(
            f"{SCOPES}/{scope['id']}",
            json=report(
                biopsies=[
                    {"location": "distal", "peak_eos_per_hpf": 8},
                    {"location": "proximal", "peak_eos_per_hpf": 2},
                ],
                dilation={"dilator_type": "balloon", "final_diameter_mm": "16.5"},
            ),
            headers=auth(access),
        )
        assert response.status_code == 200, response.text
        edited = response.json()
        assert edited["histology"] == "below_threshold"
        assert edited["dilation"]["dilator_type"] == "balloon"

        again = await client.put(
            f"{SCOPES}/{scope['id']}", json=report(dilation=None), headers=auth(access)
        )
        assert again.status_code == 200, again.text
        assert again.json()["dilation"] is None
        assert [b["location"] for b in again.json()["biopsies"]] == ["proximal", "distal"]

    async def test_listing_is_newest_first_and_delete_cascades(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        access, _ = await onboard()
        older = await add(client, access, performed_on=days_ago(400))
        newer = await add(client, access, dilation={"dilator_type": "unknown"})

        listed = (await client.get(SCOPES, headers=auth(access))).json()
        assert [s["id"] for s in listed] == [newer["id"], older["id"]]

        assert (
            await client.delete(f"{SCOPES}/{newer['id']}", headers=auth(access))
        ).status_code == 204
        for table, expected in (("biopsies", 2), ("dilations", 0)):
            count = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            assert count == expected, table
        assert (
            await client.get(f"{SCOPES}/{newer['id']}", headers=auth(access))
        ).status_code == 404


class TestPrivacy:
    async def test_free_text_is_encrypted_at_rest(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        access, _ = await onboard()
        await add(client, access)
        leaked = (
            await session.execute(
                text(
                    "SELECT count(*) FROM endoscopies WHERE "
                    "encode(facility_encrypted, 'escape') LIKE '%Riverside%' "
                    "OR encode(notes_encrypted, 'escape') LIKE '%Okafor%'"
                )
            )
        ).scalar_one()
        assert leaked == 0

    async def test_facility_and_notes_ciphertexts_cannot_be_swapped(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        """Each column is bound to its own label, so moving one into the other
        fails to decrypt instead of showing a note as the facility."""
        access, _ = await onboard()
        scope = await add(client, access)
        await session.execute(
            text("UPDATE endoscopies SET facility_encrypted = notes_encrypted WHERE id = :id"),
            {"id": scope["id"]},
        )
        await session.commit()
        # The test transport re-raises server errors; in service this is a 500
        # from the unhandled-exception handler, which logs the type only.
        with pytest.raises(InvalidTag):
            await client.get(f"{SCOPES}/{scope['id']}", headers=auth(access))

    async def test_another_patients_scope_is_a_404(self, client: AsyncClient, onboard) -> None:
        alice, _ = await onboard("alice@example.com")
        bob, _ = await onboard("bob@example.com")
        scope = await add(client, alice)
        for method in ("GET", "PUT", "DELETE"):
            response = await client.request(
                method,
                f"{SCOPES}/{scope['id']}",
                json=report() if method == "PUT" else None,
                headers=auth(bob),
            )
            assert response.status_code == 404, method
        assert (await client.get(SCOPES, headers=auth(bob))).json() == []

    async def test_the_trail_records_what_was_recorded_not_what_it_said(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        access, _ = await onboard()
        scope = await add(client, access)
        await client.get(f"{SCOPES}/{scope['id']}", headers=auth(access))
        await client.get(SCOPES, headers=auth(access))
        await client.delete(f"{SCOPES}/{scope['id']}", headers=auth(access))

        rows = (
            (
                await session.execute(
                    select(AuditLog)
                    .where(AuditLog.resource_type == "endoscopy")
                    .order_by(AuditLog.id)
                )
            )
            .scalars()
            .all()
        )
        assert [r.action for r in rows] == [
            "endoscopy.create",
            "endoscopy.read",
            "endoscopy.list",
            "endoscopy.delete",
        ]
        assert rows[0].metadata_ == {
            "has_erefs": True,
            "biopsy_sites": 2,
            "has_dilation": False,
            "has_facility": True,
            "has_notes": True,
        }
        trail = " ".join(str(r.metadata_) for r in rows)
        for secret in ("Riverside", "Okafor", "22"):
            assert secret not in trail


async def test_the_erefs_reference_lists_both_gradings(client: AsyncClient, sign_in) -> None:
    access = await sign_in()
    scales = (await client.get("/api/v1/reference/erefs", headers=auth(access))).json()
    assert {s["version"]: s["max_total"] for s in scales} == {"classic": 8, "graded": 10}
