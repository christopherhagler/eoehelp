"""Endoscopies, biopsy results, and dilations.

Hand-written like its predecessors. The EREFS range checks depend on the grading
version, which autogenerate has no way to express, and grants must be re-run for
new tables.

Revision ID: 0005_procedures
Revises: 0004_food_logging
Create Date: 2026-09-17

"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_procedures"
down_revision: str | None = "0004_food_logging"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES = ("endoscopies", "biopsies", "dilations")

ENUMS = {
    "endoscopy_indication": (
        "diagnosis",
        "treatment_response",
        "food_impaction",
        "surveillance",
        "other",
    ),
    "erefs_version": ("classic", "graded"),
    "biopsy_location": ("proximal", "mid", "distal", "unspecified"),
    "eos_comparator": ("exact", "greater_than", "less_than"),
    "dilator_type": ("balloon", "bougie", "unknown"),
    "dilation_complication": ("none", "chest_pain", "bleeding", "perforation", "other"),
}

# (feature, classic maximum, graded maximum). Mirrors procedures/erefs.py, which is
# checked against this table by the test suite.
EREFS_MAXIMA = (
    ("edema", 1, 2),
    ("rings", 3, 3),
    ("exudates", 2, 2),
    ("furrows", 1, 2),
    ("stricture", 1, 1),
)


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def _uuid(name: str, **kwargs: Any) -> sa.Column[Any]:
    return sa.Column(name, postgresql.UUID(as_uuid=True), **kwargs)


def upgrade() -> None:
    for name in ENUMS:
        _enum(name).create(op.get_bind(), checkfirst=True)

    op.create_table(
        "endoscopies",
        _uuid("id", server_default=sa.text("gen_random_uuid()"), nullable=False),
        _uuid("patient_id", nullable=False),
        sa.Column("performed_on", sa.Date(), nullable=False),
        sa.Column("indication", _enum("endoscopy_indication"), nullable=False),
        sa.Column("facility_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("notes_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("erefs_version", _enum("erefs_version"), nullable=True),
        *(sa.Column(f"erefs_{f}", sa.SmallInteger(), nullable=True) for f, _, _ in EREFS_MAXIMA),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_endoscopies"),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name="fk_endoscopies_patient_id_patients",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "(erefs_version IS NULL) = (erefs_edema IS NULL AND erefs_rings IS NULL "
            "AND erefs_exudates IS NULL AND erefs_furrows IS NULL "
            "AND erefs_stricture IS NULL)",
            name=op.f("ck_endoscopies_erefs_version_matches_scores"),
        ),
        *(
            sa.CheckConstraint(
                f"erefs_{feature} IS NULL OR erefs_{feature} BETWEEN 0 AND "
                f"CASE erefs_version WHEN 'classic' THEN {classic} ELSE {graded} END",
                name=op.f(f"ck_endoscopies_erefs_{feature}_in_range"),
            )
            for feature, classic, graded in EREFS_MAXIMA
        ),
    )
    op.create_index(
        "ix_endoscopies_patient_id_performed_on", "endoscopies", ["patient_id", "performed_on"]
    )

    op.create_table(
        "biopsies",
        _uuid("id", server_default=sa.text("gen_random_uuid()"), nullable=False),
        _uuid("patient_id", nullable=False),
        _uuid("endoscopy_id", nullable=False),
        sa.Column("location", _enum("biopsy_location"), nullable=False),
        sa.Column("peak_eos_per_hpf", sa.SmallInteger(), nullable=False),
        sa.Column("peak_eos_comparator", _enum("eos_comparator"), nullable=False),
        sa.Column("basal_zone_hyperplasia", sa.Boolean(), nullable=True),
        sa.Column("lamina_propria_fibrosis", sa.Boolean(), nullable=True),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_biopsies"),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name="fk_biopsies_patient_id_patients",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["endoscopy_id"],
            ["endoscopies.id"],
            name="fk_biopsies_endoscopy_id_endoscopies",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("endoscopy_id", "location", name="uq_biopsies_endoscopy_id_location"),
        sa.CheckConstraint(
            "peak_eos_per_hpf BETWEEN 0 AND 1000", name=op.f("ck_biopsies_peak_eos_in_range")
        ),
    )
    op.create_index("ix_biopsies_patient_id", "biopsies", ["patient_id"])

    op.create_table(
        "dilations",
        _uuid("id", server_default=sa.text("gen_random_uuid()"), nullable=False),
        _uuid("patient_id", nullable=False),
        _uuid("endoscopy_id", nullable=False),
        sa.Column("dilator_type", _enum("dilator_type"), nullable=False),
        sa.Column("pre_diameter_mm", sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column("final_diameter_mm", sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column("complication", _enum("dilation_complication"), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_dilations"),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name="fk_dilations_patient_id_patients",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["endoscopy_id"],
            ["endoscopies.id"],
            name="fk_dilations_endoscopy_id_endoscopies",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("endoscopy_id", name="uq_dilations_endoscopy_id"),
        sa.CheckConstraint(
            "pre_diameter_mm IS NULL OR pre_diameter_mm BETWEEN 5 AND 25",
            name=op.f("ck_dilations_pre_diameter_in_range"),
        ),
        sa.CheckConstraint(
            "final_diameter_mm IS NULL OR final_diameter_mm BETWEEN 5 AND 25",
            name=op.f("ck_dilations_final_diameter_in_range"),
        ),
        sa.CheckConstraint(
            "pre_diameter_mm IS NULL OR final_diameter_mm IS NULL "
            "OR final_diameter_mm >= pre_diameter_mm",
            name=op.f("ck_dilations_dilation_does_not_narrow"),
        ),
    )
    op.create_index("ix_dilations_patient_id", "dilations", ["patient_id"])

    scope = "NULLIF(current_setting('app.current_patient_id', true), '')::uuid"
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY patient_isolation ON {table} USING (patient_id = {scope})")

    grants = "\n".join(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO app_runtime;" for table in RLS_TABLES
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
                {grants}
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_table("dilations")
    op.drop_table("biopsies")
    op.drop_table("endoscopies")
    for name in reversed(list(ENUMS)):
        op.execute(f"DROP TYPE IF EXISTS {name}")
