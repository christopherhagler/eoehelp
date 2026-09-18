import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eoehelp_api.db.base import Base, UUIDPrimaryKey
from eoehelp_api.identity.enums import ConsentType, ResearchScope


class Consent(UUIDPrimaryKey, Base):
    """Append-only consent record. This is the legal artifact.

    Rows are never updated and never deleted: a revocation is a new row with
    granted=False. Current state is the most recent row per (patient, type).
    Mutating a consent row would destroy the evidence that consent was given.
    """

    __tablename__ = "consents"
    __table_args__ = (Index("ix_consents_current", "patient_id", "consent_type", "granted_at"),)

    patient_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    consent_type: Mapped[ConsentType] = mapped_column(
        Enum(ConsentType, name="consent_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    # Which version of the document was agreed to, e.g. "tos-2026-01". Required:
    # "they consented" is meaningless without knowing to what.
    document_version: Mapped[str] = mapped_column(String(64), nullable=False)

    granted: Mapped[bool] = mapped_column(nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(512))

    scopes: Mapped[list["ResearchConsentScope"]] = relationship(
        back_populates="consent", cascade="all, delete-orphan"
    )


class ResearchConsentScope(Base):
    """Per-scope grants attached to a research consent.

    Research participation is not one boolean: a patient may share symptom data
    while withholding endoscopy results.
    """

    __tablename__ = "research_consent_scopes"

    consent_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("consents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    scope: Mapped[ResearchScope] = mapped_column(
        Enum(ResearchScope, name="research_scope", values_callable=lambda e: [m.value for m in e]),
        primary_key=True,
    )

    consent: Mapped["Consent"] = relationship(back_populates="scopes")
