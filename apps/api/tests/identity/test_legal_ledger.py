"""The registry and the database must agree about what was published.

This is the test that would have caught the original defect. The registry pins
each file's digest, but the file and the pin travel in the same commit, so
editing both together passes every check inside the build. The ledger rows were
written by a migration that has already run; they do not move when a later
commit moves. Comparing the two is the only check with a second witness.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.identity import documents
from eoehelp_api.identity.documents import Revision
from eoehelp_api.identity.enums import ConsentType, ReviewStatus
from eoehelp_api.identity.legal_ledger import verify_published_revisions


class TestTheLedgerMatchesTheRegistry:
    async def test_every_published_revision_is_recorded_exactly_once(
        self, session: AsyncSession
    ) -> None:
        rows = (
            await session.execute(
                text("SELECT consent_type, version, content_sha256 FROM legal_documents")
            )
        ).all()
        in_database = sorted(
            (consent_type, version, digest) for consent_type, version, digest in rows
        )
        in_registry = sorted(
            (consent_type.value, version, digest)
            for consent_type, version, digest in documents.published_revisions()
        )
        assert in_database == in_registry, (
            "the database and this build disagree about what was published; if a "
            "document's text changed, publish a new revision with a migration"
        )

    async def test_the_startup_check_passes_against_the_migrated_database(
        self, session: AsyncSession
    ) -> None:
        await verify_published_revisions(session)


class TestTheStartupCheckFails:
    """Both directions, because they are different failures.

    A ledger row this build cannot serve means bytes a patient may have agreed
    to are gone. A registry entry the ledger does not have means text is about
    to be served that was never published.
    """

    async def test_when_the_build_cannot_produce_published_bytes(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The registry forgets the terms entirely: the ledger still has them.
        remaining = tuple(
            document
            for document in documents.DOCUMENTS
            if document.consent_type is not ConsentType.TERMS_OF_SERVICE
        )
        monkeypatch.setattr(documents, "DOCUMENTS", remaining)

        with pytest.raises(RuntimeError, match="cannot produce") as failure:
            await verify_published_revisions(session)
        assert documents.TERMS_OF_SERVICE_VERSION in str(failure.value)

    async def test_when_a_revision_was_never_published(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        terms = documents.current_for(ConsentType.TERMS_OF_SERVICE)
        unpublished = "f" * 64
        with_extra = tuple(
            document
            if document.consent_type is not ConsentType.TERMS_OF_SERVICE
            else type(document)(
                consent_type=document.consent_type,
                version=document.version,
                slug=document.slug,
                title=document.title,
                effective_on=document.effective_on,
                revisions=(
                    *document.revisions,
                    Revision(sha256=unpublished, review_status=ReviewStatus.DRAFT),
                ),
            )
            for document in documents.DOCUMENTS
        )
        monkeypatch.setattr(documents, "DOCUMENTS", with_extra)

        with pytest.raises(RuntimeError, match="never published") as failure:
            await verify_published_revisions(session)
        assert unpublished in str(failure.value)
        assert terms.version in str(failure.value)


class TestTheLedgerCannotBeUnpublished:
    """Publishing rule 4, as a fact rather than a promise.

    "A draft revision's file may be retired only when no consent references it"
    is a claim the ADR amendment makes about the foreign key. This is the test
    that makes it true: even as the owner, with a consent pointing at a
    revision, the ledger row cannot be deleted.
    """

    async def test_a_referenced_revision_cannot_be_deleted(self, session: AsyncSession) -> None:
        terms = documents.current_for(ConsentType.TERMS_OF_SERVICE)
        user_id = (
            await session.execute(
                text(
                    "INSERT INTO users (email, role, status) "
                    "VALUES ('retire@example.com', 'patient', 'active') RETURNING id"
                )
            )
        ).scalar_one()
        patient_id = (
            await session.execute(
                text("INSERT INTO patients (user_id) VALUES (:uid) RETURNING id"),
                {"uid": user_id},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO consents "
                "(patient_id, consent_type, document_version, document_sha256, granted) "
                "VALUES (:pid, 'terms_of_service', :version, :digest, true)"
            ),
            {"pid": patient_id, "version": terms.version, "digest": terms.sha256},
        )
        await session.commit()

        delete = text("DELETE FROM legal_documents WHERE content_sha256 = :digest")
        with pytest.raises(IntegrityError):
            await session.execute(delete, {"digest": terms.sha256})
        await session.rollback()

    async def test_deleting_a_patient_takes_the_consent_and_its_scopes(
        self, session: AsyncSession
    ) -> None:
        """The other half, and the one a privacy policy promises.

        Deletion must leave no consent row behind even though the application
        role holds no DELETE on `consents` or `research_consent_scopes` —
        referential actions run as the constraint owner and ignore both grants
        and row-level security. Asserted rather than left in a migration
        comment, because the day it stops being true is the day an account
        deletion leaves clinical rows behind.
        """
        terms = documents.current_for(ConsentType.TERMS_OF_SERVICE)
        user_id = (
            await session.execute(
                text(
                    "INSERT INTO users (email, role, status) "
                    "VALUES ('cascade@example.com', 'patient', 'active') RETURNING id"
                )
            )
        ).scalar_one()
        patient_id = (
            await session.execute(
                text("INSERT INTO patients (user_id) VALUES (:uid) RETURNING id"),
                {"uid": user_id},
            )
        ).scalar_one()
        consent_id = (
            await session.execute(
                text(
                    "INSERT INTO consents "
                    "(patient_id, consent_type, document_version, document_sha256, granted) "
                    "VALUES (:pid, 'terms_of_service', :version, :digest, true) RETURNING id"
                ),
                {"pid": patient_id, "version": terms.version, "digest": terms.sha256},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO research_consent_scopes (consent_id, patient_id, scope) "
                "VALUES (:cid, :pid, 'symptoms')"
            ),
            {"cid": consent_id, "pid": patient_id},
        )
        await session.commit()

        await session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
        await session.commit()

        for table in ("consents", "research_consent_scopes"):
            remaining = (
                await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE patient_id = :pid"),
                    {"pid": patient_id},
                )
            ).scalar_one()
            assert remaining == 0, f"{table} survived the patient it belongs to"

        # And the ledger row is untouched: it is reference data, not the
        # patient's.
        assert (
            await session.execute(
                text("SELECT count(*) FROM legal_documents WHERE content_sha256 = :digest"),
                {"digest": terms.sha256},
            )
        ).scalar_one() == 1
