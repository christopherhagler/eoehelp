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

from eoehelp_api.core.entry_dates import EntryMethod
from eoehelp_api.db.base import Base, Timestamps, UUIDPrimaryKey, pg_enum
from eoehelp_api.symptoms.enums import DysphagiaRelief


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

    # Key into the scoring registry in symptoms/scoring.py. Scoring lives in
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

    Questions 1-3 are the Dysphagia Symptom Questionnaire's, asked and scored as
    the instrument defines them. A bespoke severity slider produces a number no
    gastroenterologist trusts and no journal accepts; the DSQ is the endpoint of
    the budesonide oral suspension registration trials, so a score here can be
    read against theirs.
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
            "ate_solid_food OR (dysphagia_occurred IS NULL AND dysphagia_relief IS NULL)",
            name="dysphagia_requires_solid_food",
        ),
        CheckConstraint(
            "NOT ate_solid_food OR dysphagia_occurred IS NOT NULL",
            name="solid_food_day_answers_dysphagia",
        ),
        CheckConstraint(
            "(dysphagia_occurred IS TRUE) = (dysphagia_relief IS NOT NULL)",
            name="relief_answers_dysphagia",
        ),
        CheckConstraint(
            "NOT food_impaction_er_visit OR dysphagia_relief = 'sought_medical_attention'",
            name="er_visit_is_medical_attention",
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

    # DSQ question 1: "Since you woke up this morning, did you eat solid food?"
    ate_solid_food: Mapped[bool] = mapped_column(nullable=False)
    # DSQ question 2: did food go down slowly or get stuck.
    dysphagia_occurred: Mapped[bool | None] = mapped_column()
    # DSQ question 3, asked only when question 2 was yes: what it took to get
    # relief at the worst episode. Scored 0-4 in symptoms/scoring.py.
    dysphagia_relief: Mapped[DysphagiaRelief | None] = mapped_column(
        pg_enum(DysphagiaRelief, "dysphagia_relief")
    )

    # Pain on swallowing. Recorded and reported, but deliberately not part of the
    # 0-84 DSQ total: the instrument scores pain separately.
    odynophagia: Mapped[bool | None] = mapped_column()
    odynophagia_severity: Mapped[int | None] = mapped_column(SmallInteger)

    # A food impaction needing emergency care. It is always also "sought medical
    # attention" for question 3, but it is a distinct clinical event that the
    # report flags on its own.
    food_impaction_er_visit: Mapped[bool] = mapped_column(nullable=False, default=False)

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
        pg_enum(EntryMethod, "entry_method"), nullable=False
    )

    instrument_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("clinical_instruments.code"), nullable=False, default="DSQ"
    )
    instrument_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v4.0")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SymptomEntry id={self.id} date={self.entry_date}>"
