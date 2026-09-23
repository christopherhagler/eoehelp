import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eoehelp_api.db.base import Base, UUIDPrimaryKey, pg_enum
from eoehelp_api.identity.enums import ConsentType, ResearchScope

# The foreign key below targets this table's columns directly rather than by
# string, so the dependency is visible and typo-proof, and the import that makes
# the table resolvable is a real one rather than a side effect.
from eoehelp_api.identity.legal_document import PublishedLegalDocument


class Consent(UUIDPrimaryKey, Base):
    """Append-only consent record. This is the legal artifact.

    Rows are never updated and never deleted: a revocation is a new row with
    granted=False. Current state is the most recent row per (patient, type).
    Mutating a consent row would destroy the evidence that consent was given.
    """

    __tablename__ = "consents"
    __table_args__ = (
        Index("ix_consents_current", "patient_id", "consent_type", "granted_at"),
        # The target of research_consent_scopes' composite foreign key.
        UniqueConstraint("id", "patient_id", name="uq_consents_id_patient_id"),
        # Every consent names a revision the ledger records as published, so a
        # consent row can never point at bytes nothing can produce.
        ForeignKeyConstraint(
            ["consent_type", "document_version", "document_sha256"],
            [
                PublishedLegalDocument.__table__.c.consent_type,
                PublishedLegalDocument.__table__.c.version,
                PublishedLegalDocument.__table__.c.content_sha256,
            ],
            name="fk_consents_document_revision_legal_documents",
        ),
        CheckConstraint(
            "document_sha256 ~ '^[0-9a-f]{64}$'",
            name="document_sha256_is_hex",
        ),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    consent_type: Mapped[ConsentType] = mapped_column(
        pg_enum(ConsentType, "consent_type"),
        nullable=False,
    )

    # Which version of the document was agreed to, e.g. "tos-2026-01". Required:
    # "they consented" is meaningless without knowing to what.
    document_version: Mapped[str] = mapped_column(String(64), nullable=False)

    # The sha256 of that document's text. The version is a label; this is the
    # text itself. It is what answers "show me exactly what they agreed to"
    # after the document has been superseded, and it detects the one failure the
    # registry cannot: a published file edited together with its recorded digest.
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    granted: Mapped[bool] = mapped_column(nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(512))

    # Not "all, delete-orphan": deletion is the database's job through the
    # composite cascade below, and app_runtime no longer holds DELETE on this
    # table, so an ORM-issued delete would now fail rather than be merely
    # redundant.
    scopes: Mapped[list["ResearchConsentScope"]] = relationship(
        back_populates="consent", cascade="save-update, merge"
    )


class ResearchConsentScope(Base):
    """Per-scope grants attached to a research consent.

    Research participation is not one boolean: a patient may share symptom data
    while withholding endoscopy results.
    """

    __tablename__ = "research_consent_scopes"
    __table_args__ = (
        # Composite, so the denormalised patient_id cannot disagree with its
        # parent consent. A row claiming the wrong patient would be visible to
        # the wrong patient under the policy below, which would make the
        # denormalisation the leak it exists to prevent.
        ForeignKeyConstraint(
            ["consent_id", "patient_id"],
            ["consents.id", "consents.patient_id"],
            ondelete="CASCADE",
            name="fk_research_consent_scopes_consent_id_consents",
        ),
    )

    consent_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    # Carried so row-level security has a column to scope on. Every other
    # patient-owned table has one; this table's absence was why the catalogue
    # test passed it by omission rather than by coverage (ADR 0002).
    patient_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    scope: Mapped[ResearchScope] = mapped_column(
        pg_enum(ResearchScope, "research_scope"),
        primary_key=True,
    )

    consent: Mapped["Consent"] = relationship(back_populates="scopes")
