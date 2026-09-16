"""Clinical observation tables.

Deliberately separate from the identity tables. Research export reads this side
keyed on a pseudonym and never joins to `patients`, which is what makes
de-identified export a query rather than a schema migration later.
"""

import uuid
from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from eoehelp_api.db.base import Base, Timestamps, UUIDPrimaryKey
from eoehelp_api.models.enums import CopingAction, DysphagiaSeverity, EntryMethod


def _pg_enum(enum_type: type, name: str) -> Enum:
    return Enum(enum_type, name=name, values_callable=lambda e: [m.value for m in e])


class ClinicalInstrument(Base):
    """Reference table of the validated instruments this product records.

    Versioned as data rather than baked into column names, because instruments
    get revised and a stored score computed under an older revision must stay
    interpretable. Not patient-scoped, so no row-level security.
    """

    __tablename__ = "clinical_instruments"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)

    # Key into the scoring registry in services/scoring.py. Scoring lives in
    # Python, not a database trigger: the algorithm needs to be unit-testable
    # against hand-computed fixtures and will be revised with clinical review.
    scoring_algorithm: Mapped[str] = mapped_column(String(64), nullable=False)

    # Licence and citation, carried in the database so the attribution the
    # licence requires cannot drift away from the data it applies to.
    attribution: Mapped[str] = mapped_column(Text, nullable=False)


class SymptomEntry(UUIDPrimaryKey, Timestamps, Base):
    """One patient-reported day, following the Dysphagia Symptom Questionnaire.

    One row per patient per day, enforced in the database. An edit updates the
    existing row rather than adding a second, because two entries for one day
    cannot both be true and the 14-day score has to have a single input per day.

    The question set is DSQ-shaped on purpose. A bespoke severity slider produces
    a number no gastroenterologist trusts and no journal accepts; these items are
    comparable to the endpoint used in the budesonide and dupilumab registration
    trials.
    """

    __tablename__ = "symptom_entries"
    __table_args__ = (
        UniqueConstraint(
            "patient_id", "entry_date", name="uq_symptom_entries_patient_id_entry_date"
        ),
        Index("ix_symptom_entries_patient_id_entry_date", "patient_id", "entry_date"),
        # A day with no solid food cannot have a dysphagia answer: the DSQ asks
        # about swallowing food, and inventing a "no" for those days would drag
        # the score down for someone who simply drank a shake.
        CheckConstraint(
            "ate_solid_food OR (dysphagia_occurred IS NULL AND dysphagia_severity IS NULL)",
            name="dysphagia_requires_solid_food",
        ),
        CheckConstraint(
            "dysphagia_occurred IS NOT TRUE OR dysphagia_severity IS NOT NULL",
            name="dysphagia_needs_severity",
        ),
        CheckConstraint(
            "odynophagia_severity IS NULL OR odynophagia_severity BETWEEN 0 AND 3",
            name="odynophagia_severity_range",
        ),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
    )

    # The day being described, separate from created_at. Only this one is
    # date-shifted for research; created_at is system metadata and is not exported.
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)

    ate_solid_food: Mapped[bool] = mapped_column(nullable=False)
    dysphagia_occurred: Mapped[bool | None] = mapped_column()
    dysphagia_severity: Mapped[DysphagiaSeverity | None] = mapped_column(
        _pg_enum(DysphagiaSeverity, "dysphagia_severity")
    )

    odynophagia: Mapped[bool | None] = mapped_column()
    odynophagia_severity: Mapped[int | None] = mapped_column(SmallInteger)

    # Separate from the coping actions because an impaction needing emergency
    # care is a distinct clinical event, and the report flags it on its own.
    food_impaction_er_visit: Mapped[bool] = mapped_column(nullable=False, default=False)

    coping_actions: Mapped[list[CopingAction]] = mapped_column(
        postgresql.ARRAY(_pg_enum(CopingAction, "coping_action")),
        nullable=False,
        default=list,
    )

    # Behavioural adaptation, in our own wording. EEsAI covers this ground but
    # its licensing is unconfirmed, so these are plain questions rather than its
    # scored items, and they are not summed into the DSQ score.
    avoided_foods_today: Mapped[bool] = mapped_column(nullable=False, default=False)
    modified_foods_today: Mapped[bool] = mapped_column(nullable=False, default=False)
    ate_unusually_slowly: Mapped[bool] = mapped_column(nullable=False, default=False)

    # Application-layer AES-GCM, key held outside the database. Free text is
    # where identifiers leak: patients write their own and their doctor's name
    # into notes. Excluded from research export entirely rather than scrubbed.
    notes_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)

    entry_method: Mapped[EntryMethod] = mapped_column(
        _pg_enum(EntryMethod, "entry_method"), nullable=False
    )

    instrument_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("clinical_instruments.code"), nullable=False, default="DSQ"
    )
    instrument_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v4.0")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SymptomEntry id={self.id} date={self.entry_date}>"
