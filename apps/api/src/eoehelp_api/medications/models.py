"""Medications, their schedules, and the doses actually taken.

The schedule is what makes adherence honest. Without an expected-dose
denominator, a fortnightly injection and a twice-daily pill are
indistinguishable — 14 logged doses is perfect adherence for one and a quarter
of the expectation for the other.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eoehelp_api.db.base import Base, Timestamps, UUIDPrimaryKey, pg_enum
from eoehelp_api.medications.enums import DoseStatus, DrugClass, MedicationStopReason


class MedicationCatalogEntry(Base):
    """Reference list of EoE medications.

    Keyed on a stable slug rather than a UUID, like `clinical_instruments` and
    unlike every patient-owned table. The UUID rule exists so record ids in URLs
    and exports cannot be enumerated or counted; reference data is neither
    patient data nor secret, and a slug makes the seed idempotent and the API
    legible. Not patient-scoped, so no row-level security.
    """

    __tablename__ = "medication_catalog"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    generic_name: Mapped[str] = mapped_column(String(120), nullable=False)
    drug_class: Mapped[DrugClass] = mapped_column(pg_enum(DrugClass, "drug_class"), nullable=False)
    default_route: Mapped[str | None] = mapped_column(String(32))
    default_unit: Mapped[str | None] = mapped_column(String(32))

    # Shown next to the medication so a patient recognises what they were handed,
    # since prescriptions and pharmacy labels rarely use the generic name.
    also_known_as: Mapped[str | None] = mapped_column(Text)


class Medication(UUIDPrimaryKey, Timestamps, Base):
    """One course of one medication for one patient.

    A restart after a gap is a new row, not an edit: the dates and the stop
    reason of the first course are the clinical history, and overwriting them
    would erase the fact that it was tried and stopped.
    """

    __tablename__ = "medications"
    __table_args__ = (
        Index("ix_medications_patient_id_started_on", "patient_id", "started_on"),
        CheckConstraint(
            "ended_on IS NULL OR ended_on >= started_on",
            name="medication_ends_after_it_starts",
        ),
        # A stop reason without an end date, or an end date without a reason, is a
        # half-recorded event that reads as missing data later.
        CheckConstraint(
            "(ended_on IS NULL) = (stop_reason IS NULL)",
            name="medication_stop_is_complete",
        ),
        CheckConstraint(
            "dose_amount IS NULL OR dose_amount > 0",
            name="medication_dose_is_positive",
        ),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
    )
    medication_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("medication_catalog.code"), nullable=False
    )

    dose_amount: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    dose_unit: Mapped[str | None] = mapped_column(String(32))

    # An iCal RRULE, and the adherence denominator. NULL means as-needed, where
    # there is no expectation to measure against — reported as unknown rather
    # than as 100%.
    #
    # Never accepted from the client as free text: the API offers a fixed set of
    # frequencies and builds the rule here, because an arbitrary rule can be made
    # to enumerate effectively forever.
    schedule_rrule: Mapped[str | None] = mapped_column(String(255))

    started_on: Mapped[date] = mapped_column(Date, nullable=False)
    ended_on: Mapped[date | None] = mapped_column(Date)
    stop_reason: Mapped[MedicationStopReason | None] = mapped_column(
        pg_enum(MedicationStopReason, "medication_stop_reason")
    )

    prescriber_note_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)

    catalog: Mapped["MedicationCatalogEntry"] = relationship(lazy="joined")

    @property
    def is_active(self) -> bool:
        return self.ended_on is None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Medication id={self.id} code={self.medication_code}>"


class MedicationDose(UUIDPrimaryKey, Base):
    """A single dose event.

    An event with a timestamp rather than a daily checkbox, because a twice-daily
    PPI has two of them and collapsing them to one per day would make adherence
    uncomputable for exactly the regimens where it matters most.
    """

    __tablename__ = "medication_doses"
    __table_args__ = (Index("ix_medication_doses_patient_id_taken_at", "patient_id", "taken_at"),)

    patient_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
    )
    medication_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("medications.id", ondelete="CASCADE"),
        nullable=False,
    )

    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[DoseStatus] = mapped_column(pg_enum(DoseStatus, "dose_status"), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
