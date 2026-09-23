"""Onboarding: the patient record, the consents that permit it, and deletion."""

import asyncio
from datetime import UTC, datetime

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.audit.models import AuditLog
from eoehelp_api.identity import documents
from eoehelp_api.identity.consent import Consent
from eoehelp_api.identity.documents import (
    CONSUMER_HEALTH_DATA_VERSION,
    PRIVACY_POLICY_VERSION,
    TERMS_OF_SERVICE_VERSION,
)
from eoehelp_api.identity.enums import ConsentType
from eoehelp_api.identity.patient import Patient
from eoehelp_api.identity.user import User
from helpers import auth, onboarding_payload

ME = "/api/v1/me"

_payload = onboarding_payload


class TestOnboarding:
    async def test_creates_the_patient_record_and_its_consents(
        self, client: AsyncClient, sign_in, session: AsyncSession
    ) -> None:
        access = await sign_in("new@example.com")
        response = await client.post(f"{ME}/onboarding", json=_payload(), headers=auth(access))

        assert response.status_code == 201
        body = response.json()
        assert body["patient"]["display_name"] == "Test Patient"
        assert body["patient"]["birth_year"] == 1990

        patient = (await session.execute(select(Patient))).scalar_one()
        assert str(patient.id) == body["patient"]["id"]

        consents = (await session.execute(select(Consent))).scalars().all()
        assert {c.consent_type.value for c in consents} == {
            "terms_of_service",
            "privacy_policy",
            "consumer_health_data",
        }
        # Which text was agreed to, not merely that something was.
        assert {c.document_version for c in consents} == {
            TERMS_OF_SERVICE_VERSION,
            PRIVACY_POLICY_VERSION,
            CONSUMER_HEALTH_DATA_VERSION,
        }
        assert all(c.granted for c in consents)

    async def test_returns_a_token_carrying_the_new_patient_id(
        self, client: AsyncClient, sign_in
    ) -> None:
        """The pre-onboarding token has no patient id, so it cannot reach /me/*.

        Returning a fresh one saves the client an immediate refresh just to
        become usable.
        """
        access = await sign_in()
        before = await client.get(f"{ME}/profile", headers=auth(access))
        assert before.status_code == 403

        response = await client.post(f"{ME}/onboarding", json=_payload(), headers=auth(access))
        new_access = response.json()["access_token"]
        claims = jwt.decode(new_access, options={"verify_signature": False})
        assert claims["pid"] == response.json()["patient"]["id"]

        after = await client.get(f"{ME}/profile", headers=auth(new_access))
        assert after.status_code == 200

    async def test_onboarding_twice_is_rejected(self, client: AsyncClient, sign_in) -> None:
        access = await sign_in()
        first = await client.post(f"{ME}/onboarding", json=_payload(), headers=auth(access))
        assert first.status_code == 201
        second = await client.post(f"{ME}/onboarding", json=_payload(), headers=auth(access))
        assert second.status_code == 409

    async def test_under_eighteen_is_refused(self, client: AsyncClient, sign_in) -> None:
        # v1 is adults-only: under-13 triggers COPPA and verifiable parental
        # consent, which is a milestone of its own rather than a checkbox.
        access = await sign_in()
        response = await client.post(
            f"{ME}/onboarding",
            json=_payload(birth_year=datetime.now(UTC).year - 12),
            headers=auth(access),
        )
        assert response.status_code == 422

    async def test_every_required_consent_must_be_given_individually(
        self, client: AsyncClient, sign_in
    ) -> None:
        """One blanket "I agree" is exactly what WA MHMD prohibits."""
        access = await sign_in()
        response = await client.post(
            f"{ME}/onboarding",
            json=_payload(
                consents={
                    "terms_of_service": True,
                    "privacy_policy": True,
                    "consumer_health_data": False,
                }
            ),
            headers=auth(access),
        )
        assert response.status_code == 422
        assert "consumer_health_data" in response.text

    async def test_unknown_timezone_is_refused(self, client: AsyncClient, sign_in) -> None:
        # The timezone decides which day an entry belongs to, so a bad one is a
        # data-correctness problem, not a display preference.
        access = await sign_in()
        response = await client.post(
            f"{ME}/onboarding", json=_payload(timezone="Mars/Olympus"), headers=auth(access)
        )
        assert response.status_code == 422

    async def test_diagnosis_date_is_reduced_to_month_precision(
        self, client: AsyncClient, sign_in
    ) -> None:
        access = await sign_in()
        response = await client.post(
            f"{ME}/onboarding", json=_payload(diagnosis_month="2021-03-17"), headers=auth(access)
        )
        assert response.json()["patient"]["diagnosis_month"] == "2021-03-01"

    async def test_a_diagnosis_must_be_possible(self, client: AsyncClient, sign_in) -> None:
        access = await sign_in()
        next_year = f"{datetime.now(UTC).year + 1}-01-01"
        for month in (next_year, "1985-06-01"):
            response = await client.post(
                f"{ME}/onboarding",
                json=_payload(birth_year=1990, diagnosis_month=month),
                headers=auth(access),
            )
            assert response.status_code == 422, month

    async def test_a_double_submitted_form_is_a_conflict_not_a_server_error(
        self, client: AsyncClient, sign_in
    ) -> None:
        """A double tap races the existence check; the loser must get 409."""
        access = await sign_in()
        results = await asyncio.gather(
            *(
                client.post(f"{ME}/onboarding", json=_payload(), headers=auth(access))
                for _ in range(3)
            )
        )
        assert sorted(r.status_code for r in results) == [201, 409, 409]

    async def test_the_profile_refuses_an_impossible_diagnosis(
        self, client: AsyncClient, onboard
    ) -> None:
        access, _ = await onboard(birth_year=1990)
        response = await client.patch(
            f"{ME}/profile", json={"diagnosis_month": "1980-01-01"}, headers=auth(access)
        )
        assert response.status_code == 400

    async def test_writes_an_audit_trail_of_field_names_not_values(
        self, client: AsyncClient, sign_in, session: AsyncSession
    ) -> None:
        access = await sign_in()
        await client.post(
            f"{ME}/onboarding", json=_payload(display_name="Jane Doe"), headers=auth(access)
        )

        rows = (await session.execute(select(AuditLog))).scalars().all()
        actions = [r.action for r in rows]
        assert "patient.create" in actions
        assert actions.count("consent.grant") == 3

        serialised = str([r.metadata_ for r in rows])
        assert "Jane Doe" not in serialised, "the audit trail must not carry PHI values"
        assert "display_name" in serialised

    async def test_consent_rows_carry_the_digest_of_the_document_in_force(
        self, client: AsyncClient, sign_in, session: AsyncSession
    ) -> None:
        """The version label names a document; only the digest identifies the
        words. Asserting the *correct* digest is the point: any 64-hex value
        satisfies the column and its constraint."""
        access = await sign_in()
        await client.post(f"{ME}/onboarding", json=_payload(), headers=auth(access))

        rows = (await session.execute(select(Consent))).scalars().all()
        stored = {row.consent_type: row.document_sha256 for row in rows}
        assert len(stored) == 3
        for consent_type, digest in stored.items():
            assert digest == documents.current_for(consent_type).sha256

    async def test_the_consent_audit_row_records_the_digest_and_nothing_else(
        self, client: AsyncClient, sign_in, session: AsyncSession
    ) -> None:
        """The consent row cascades away with the account; this one does not, so
        after a deletion it is the only surviving statement of what was agreed
        to. A version label alone does not identify wording."""
        access = await sign_in()
        await client.post(f"{ME}/onboarding", json=_payload(), headers=auth(access))

        rows = (await session.execute(select(AuditLog))).scalars().all()
        grants = [row for row in rows if row.action == "consent.grant"]
        assert len(grants) == 3

        published = {document.sha256 for document in documents.DOCUMENTS}
        for row in grants:
            assert set(row.metadata_) == {"consent_type", "document_version", "content_sha256"}
            assert row.metadata_["content_sha256"] in published

    async def test_a_malformed_digest_is_refused_by_the_database(
        self, session: AsyncSession
    ) -> None:
        """The check constraint, not the application, is what guarantees this:
        it holds against a repository written in a hurry and against psql."""
        user_id = (
            await session.execute(
                text(
                    "INSERT INTO users (email, role, status) "
                    "VALUES ('digest@example.com', 'patient', 'active') RETURNING id"
                )
            )
        ).scalar_one()
        patient_id = (
            await session.execute(
                text("INSERT INTO patients (user_id) VALUES (:uid) RETURNING id"),
                {"uid": user_id},
            )
        ).scalar_one()
        await session.commit()

        # "a" * 65 is refused by the varchar(64) type rather than by the check
        # constraint, which is why DBAPIError is accepted below: both layers are
        # exercised, and the regex alone would not catch an over-long value.
        for malformed in ("A" * 64, "a" * 63, "a" * 65, "g" * 64, "", " " + "a" * 63):
            with pytest.raises((IntegrityError, DBAPIError)):
                await session.execute(
                    text(
                        "INSERT INTO consents "
                        "(patient_id, consent_type, document_version, document_sha256, granted) "
                        "VALUES (:pid, 'terms_of_service', 'tos-2026-09', :digest, true)"
                    ),
                    {"pid": patient_id, "digest": malformed},
                )
            await session.rollback()

    async def test_a_consent_must_name_a_published_revision(self, session: AsyncSession) -> None:
        """The foreign key to legal_documents, which is what makes "the wording
        can be reproduced" a guarantee rather than a convention.

        The three rejected cases are the three ways a consent row can name
        evidence that does not exist: unpublished bytes, the right bytes under
        the wrong version, and a published pair under the wrong document.
        """
        user_id = (
            await session.execute(
                text(
                    "INSERT INTO users (email, role, status) "
                    "VALUES ('ledger@example.com', 'patient', 'active') RETURNING id"
                )
            )
        ).scalar_one()
        patient_id = (
            await session.execute(
                text("INSERT INTO patients (user_id) VALUES (:uid) RETURNING id"),
                {"uid": user_id},
            )
        ).scalar_one()
        await session.commit()

        terms = documents.current_for(ConsentType.TERMS_OF_SERVICE)
        privacy = documents.current_for(ConsentType.PRIVACY_POLICY)
        insert = text(
            "INSERT INTO consents "
            "(patient_id, consent_type, document_version, document_sha256, granted) "
            "VALUES (:pid, CAST(:type AS consent_type), :version, :digest, true)"
        )
        rejected = (
            # Never published: the failure that produced 27 unreadable rows.
            ("terms_of_service", terms.version, "b" * 64),
            # Real bytes, wrong version id.
            ("terms_of_service", "tos-2099-01", terms.sha256),
            # A published pair, attributed to the wrong document.
            ("privacy_policy", terms.version, terms.sha256),
        )
        for consent_type, version, digest in rejected:
            with pytest.raises(IntegrityError):
                await session.execute(
                    insert,
                    {"pid": patient_id, "type": consent_type, "version": version, "digest": digest},
                )
            await session.rollback()

        # And the positive case, so the test proves the constraint admits the
        # triple onboarding actually writes.
        await session.execute(
            insert,
            {
                "pid": patient_id,
                "type": "privacy_policy",
                "version": privacy.version,
                "digest": privacy.sha256,
            },
        )
        await session.commit()


class TestProfile:
    async def test_profile_can_be_read_and_updated(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()

        updated = await client.patch(
            f"{ME}/profile",
            json={"display_name": "Renamed", "timezone": "America/Los_Angeles"},
            headers=auth(access),
        )
        assert updated.status_code == 200
        assert updated.json()["display_name"] == "Renamed"
        assert updated.json()["timezone"] == "America/Los_Angeles"

        # Absent fields are untouched rather than nulled.
        assert updated.json()["birth_year"] == 1990

    async def test_birth_year_is_not_editable_through_the_profile(
        self, client: AsyncClient, onboard
    ) -> None:
        """It gates eligibility and describes the research cohort.

        Changing it is a support action with a trail, not a profile edit.
        """
        access, _ = await onboard()
        response = await client.patch(
            f"{ME}/profile", json={"birth_year": 2015}, headers=auth(access)
        )
        assert response.status_code == 422

    async def test_current_consents_are_listed(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        response = await client.get(f"{ME}/consents", headers=auth(access))
        assert response.status_code == 200
        assert len(response.json()) == 3


class TestAccountDeletion:
    async def test_deletion_removes_the_record_and_keeps_the_trail(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        """Two requirements that pull against each other, so both are asserted.

        WA MHMD gives a working deletion right and the product promises the
        deletion is real; the audit log has to outlive the record it describes
        because "was this account accessed before it was erased" is the question
        a breach response asks.
        """
        access, _patient = await onboard()
        today = datetime.now(UTC).date().isoformat()
        logged = await client.put(
            f"{ME}/symptoms/{today}", json={"ate_solid_food": False}, headers=auth(access)
        )
        assert logged.status_code == 200

        response = await client.delete(ME, headers=auth(access))
        assert response.status_code == 204

        assert (await session.execute(select(User))).scalars().all() == []
        assert (await session.execute(select(Patient))).scalars().all() == []
        assert (await session.execute(select(Consent))).scalars().all() == []
        remaining_entries = (
            await session.execute(text("SELECT count(*) FROM symptom_entries"))
        ).scalar_one()
        assert remaining_entries == 0

        actions = [r.action for r in (await session.execute(select(AuditLog))).scalars().all()]
        assert "account.delete" in actions
        assert "patient.create" in actions, "the trail of the erased account survives it"

    async def test_the_token_stops_working_afterwards(self, client: AsyncClient, onboard) -> None:
        access, _ = await onboard()
        await client.delete(ME, headers=auth(access))
        # The access token is still cryptographically valid until it expires, so
        # the patient row being gone is what must stop it.
        response = await client.get(f"{ME}/profile", headers=auth(access))
        assert response.status_code in (403, 404)

    async def test_deleting_is_only_possible_for_your_own_account(
        self, client: AsyncClient, onboard, session: AsyncSession
    ) -> None:
        access_a, _ = await onboard("alice@example.com")
        _access_b, patient_b = await onboard("bob@example.com")

        await client.delete(ME, headers=auth(access_a))

        # There is no id to pass, so the only thing deletion can act on is the
        # caller's own record. Bob is untouched.
        survivors = (await session.execute(select(Patient))).scalars().all()
        assert [str(p.id) for p in survivors] == [patient_b["id"]]
