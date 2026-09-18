"""Endoscopies, their biopsy results, and dilations.

These are the credibility tables: a symptom diary is the patient's account, and
these carry what the scope and the pathologist found. Two rules a reviewer
should not "simplify" away, both from the plan:

- **No stored EREFS total.** A stored composite becomes meaningless across a
  change of grading. Totals are computed per version in procedures/erefs.py.
- **No stored remission flag.** The <15 eos/hpf threshold is a convention that
  interacts with field area and may be refined, so it is applied when read.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    LargeBinary,
    Numeric,
    SmallInteger,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eoehelp_api.db.base import Base, Timestamps, UUIDPrimaryKey, pg_enum
from eoehelp_api.procedures.enums import (
    BiopsyLocation,
    DilationComplication,
    DilatorType,
    EndoscopyIndication,
    EosComparator,
    ErefsVersion,
)


def _within(feature: str, classic_max: int, graded_max: int) -> CheckConstraint:
    # Mirrors procedures/erefs.py. The service gives a readable 422; this makes an
    # impossible score unstorable even if the service were bypassed.
    return CheckConstraint(
        f"erefs_{feature} IS NULL OR erefs_{feature} BETWEEN 0 AND "
        f"CASE erefs_version WHEN 'classic' THEN {classic_max} ELSE {graded_max} END",
        name=f"erefs_{feature}_in_range",
    )


class Endoscopy(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "endoscopies"
    __table_args__ = (
        Index("ix_endoscopies_patient_id_performed_on", "patient_id", "performed_on"),
        # A version with no scores says nothing; scores with no version cannot be
        # read. Either both are present or neither is.
        CheckConstraint(
            "(erefs_version IS NULL) = (erefs_edema IS NULL AND erefs_rings IS NULL "
            "AND erefs_exudates IS NULL AND erefs_furrows IS NULL "
            "AND erefs_stricture IS NULL)",
            name="erefs_version_matches_scores",
        ),
        _within("edema", 1, 2),
        _within("rings", 3, 3),
        _within("exudates", 2, 2),
        _within("furrows", 1, 2),
        _within("stricture", 1, 1),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
    )
    performed_on: Mapped[date] = mapped_column(Date, nullable=False)
    indication: Mapped[EndoscopyIndication] = mapped_column(
        pg_enum(EndoscopyIndication, "endoscopy_indication"), nullable=False
    )

    # Free text, so encrypted, with a distinct associated-data label for each so
    # the two ciphertexts cannot be swapped between columns undetected.
    facility_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    notes_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)

    # All nullable: many reports do not state EREFS, and a missing feature is
    # not a zero.
    erefs_version: Mapped[ErefsVersion | None] = mapped_column(
        pg_enum(ErefsVersion, "erefs_version")
    )
    erefs_edema: Mapped[int | None] = mapped_column(SmallInteger)
    erefs_rings: Mapped[int | None] = mapped_column(SmallInteger)
    erefs_exudates: Mapped[int | None] = mapped_column(SmallInteger)
    erefs_furrows: Mapped[int | None] = mapped_column(SmallInteger)
    erefs_stricture: Mapped[int | None] = mapped_column(SmallInteger)

    biopsies: Mapped[list["Biopsy"]] = relationship(
        back_populates="endoscopy",
        cascade="all, delete-orphan",
        order_by="Biopsy.position",
        lazy="selectin",
    )
    dilation: Mapped["Dilation | None"] = relationship(
        back_populates="endoscopy",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )

    @property
    def erefs_scores(self) -> dict[str, int | None]:
        return {
            "edema": self.erefs_edema,
            "rings": self.erefs_rings,
            "exudates": self.erefs_exudates,
            "furrows": self.erefs_furrows,
            "stricture": self.erefs_stricture,
        }


class Biopsy(UUIDPrimaryKey, Base):
    """The peak eosinophil count at one esophageal site, as the report states it."""

    __tablename__ = "biopsies"
    __table_args__ = (
        # A pathology report gives one peak per site. Two rows for "distal" would
        # leave the procedure's peak ambiguous.
        UniqueConstraint("endoscopy_id", "location", name="uq_biopsies_endoscopy_id_location"),
        CheckConstraint("peak_eos_per_hpf BETWEEN 0 AND 1000", name="peak_eos_in_range"),
        Index("ix_biopsies_patient_id", "patient_id"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
    )
    endoscopy_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("endoscopies.id", ondelete="CASCADE"),
        nullable=False,
    )
    location: Mapped[BiopsyLocation] = mapped_column(
        pg_enum(BiopsyLocation, "biopsy_location"), nullable=False
    )
    peak_eos_per_hpf: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    peak_eos_comparator: Mapped[EosComparator] = mapped_column(
        pg_enum(EosComparator, "eos_comparator"), nullable=False
    )
    # Tri-state: most reports do not comment, and "not stated" is not "absent".
    basal_zone_hyperplasia: Mapped[bool | None] = mapped_column()
    lamina_propria_fibrosis: Mapped[bool | None] = mapped_column()
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    endoscopy: Mapped[Endoscopy] = relationship(back_populates="biopsies")


class Dilation(UUIDPrimaryKey, Base):
    """A dilation performed during an endoscopy.

    Always attached to one. Esophageal dilation is done under endoscopic guidance
    in practice, and a free-standing row would be a date with no findings around
    it. At most one per procedure.
    """

    __tablename__ = "dilations"
    __table_args__ = (
        UniqueConstraint("endoscopy_id", name="uq_dilations_endoscopy_id"),
        CheckConstraint(
            "pre_diameter_mm IS NULL OR pre_diameter_mm BETWEEN 5 AND 25",
            name="pre_diameter_in_range",
        ),
        CheckConstraint(
            "final_diameter_mm IS NULL OR final_diameter_mm BETWEEN 5 AND 25",
            name="final_diameter_in_range",
        ),
        CheckConstraint(
            "pre_diameter_mm IS NULL OR final_diameter_mm IS NULL "
            "OR final_diameter_mm >= pre_diameter_mm",
            name="dilation_does_not_narrow",
        ),
        Index("ix_dilations_patient_id", "patient_id"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
    )
    endoscopy_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("endoscopies.id", ondelete="CASCADE"),
        nullable=False,
    )
    dilator_type: Mapped[DilatorType] = mapped_column(
        pg_enum(DilatorType, "dilator_type"), nullable=False
    )
    pre_diameter_mm: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    final_diameter_mm: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    complication: Mapped[DilationComplication | None] = mapped_column(
        pg_enum(DilationComplication, "dilation_complication")
    )

    endoscopy: Mapped[Endoscopy] = relationship(back_populates="dilation")
