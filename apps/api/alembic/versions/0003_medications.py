"""Medications: the catalog, per-patient courses, and dose events.

Hand-written like its predecessors. Autogenerate cannot express row-level
security or grants, and grants do not extend to tables created after them, so
every migration that adds a table re-runs them.

Revision ID: 0003_medications
Revises: 0002_symptom_entries
Create Date: 2026-09-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_medications"
down_revision: str | None = "0002_symptom_entries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES = ("medications", "medication_doses")

# Seeded here rather than by a script, so the foreign key from `medications` can
# never dangle and so a fresh database is immediately usable. Codes are stable
# slugs: a re-run inserts nothing new, and the API surface stays legible.
CATALOG = [
    ("omeprazole", "Omeprazole", "ppi", "oral", "mg", "Prilosec, Losec"),
    ("esomeprazole", "Esomeprazole", "ppi", "oral", "mg", "Nexium"),
    ("lansoprazole", "Lansoprazole", "ppi", "oral", "mg", "Prevacid"),
    ("pantoprazole", "Pantoprazole", "ppi", "oral", "mg", "Protonix, Pantoloc"),
    (
        "budesonide_oral_suspension",
        "Budesonide oral suspension",
        "swallowed_topical_corticosteroid",
        "swallowed",
        "mg",
        "Eohilia",
    ),
    (
        "budesonide_slurry",
        "Compounded budesonide slurry",
        "swallowed_topical_corticosteroid",
        "swallowed",
        "mg",
        "Mixed with sucralose by a compounding pharmacy",
    ),
    (
        "fluticasone_swallowed",
        "Swallowed fluticasone",
        "swallowed_topical_corticosteroid",
        "swallowed",
        "mcg",
        "Flovent, used without a spacer and swallowed",
    ),
    ("dupilumab", "Dupilumab", "biologic", "subcutaneous", "mg", "Dupixent"),
]


def upgrade() -> None:
    drug_class = postgresql.ENUM(
        "ppi",
        "swallowed_topical_corticosteroid",
        "biologic",
        "other",
        name="drug_class",
        create_type=False,
    )
    dose_status = postgresql.ENUM(
        "taken", "skipped", "delayed", name="dose_status", create_type=False
    )
    stop_reason = postgresql.ENUM(
        "remission",
        "ineffective",
        "side_effects",
        "cost",
        "insurance",
        "provider_directed",
        "other",
        name="medication_stop_reason",
        create_type=False,
    )
    for enum in (drug_class, dose_status, stop_reason):
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "medication_catalog",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("generic_name", sa.String(length=120), nullable=False),
        sa.Column("drug_class", drug_class, nullable=False),
        sa.Column("default_route", sa.String(length=32), nullable=True),
        sa.Column("default_unit", sa.String(length=32), nullable=True),
        sa.Column("also_known_as", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("code", name="pk_medication_catalog"),
    )
    op.bulk_insert(
        sa.table(
            "medication_catalog",
            sa.column("code", sa.String),
            sa.column("generic_name", sa.String),
            sa.column("drug_class", drug_class),
            sa.column("default_route", sa.String),
            sa.column("default_unit", sa.String),
            sa.column("also_known_as", sa.Text),
        ),
        [
            {
                "code": code,
                "generic_name": name,
                "drug_class": cls,
                "default_route": route,
                "default_unit": unit,
                "also_known_as": aka,
            }
            for code, name, cls, route, unit, aka in CATALOG
        ],
    )

    op.create_table(
        "medications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("medication_code", sa.String(length=64), nullable=False),
        sa.Column("dose_amount", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("dose_unit", sa.String(length=32), nullable=True),
        # An iCal RRULE and the adherence denominator. NULL means as-needed, which
        # is reported as unknown rather than as full adherence.
        sa.Column("schedule_rrule", sa.String(length=255), nullable=True),
        sa.Column("started_on", sa.Date(), nullable=False),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.Column("stop_reason", stop_reason, nullable=True),
        sa.Column("prescriber_note_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_medications"),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name="fk_medications_patient_id_patients",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["medication_code"],
            ["medication_catalog.code"],
            name="fk_medications_medication_code_medication_catalog",
        ),
        sa.CheckConstraint(
            "ended_on IS NULL OR ended_on >= started_on",
            name=op.f("ck_medications_medication_ends_after_it_starts"),
        ),
        # Half a stop — a date with no reason, or a reason with no date — reads as
        # missing data months later, when nobody remembers which it was.
        sa.CheckConstraint(
            "(ended_on IS NULL) = (stop_reason IS NULL)",
            name=op.f("ck_medications_medication_stop_is_complete"),
        ),
        sa.CheckConstraint(
            "dose_amount IS NULL OR dose_amount > 0",
            name=op.f("ck_medications_medication_dose_is_positive"),
        ),
    )
    op.create_index(
        "ix_medications_patient_id_started_on", "medications", ["patient_id", "started_on"]
    )

    op.create_table(
        "medication_doses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("medication_id", postgresql.UUID(as_uuid=True), nullable=False),
        # An event with a timestamp, not a daily checkbox: a twice-daily PPI has
        # two a day, and collapsing them would make adherence uncomputable for
        # exactly the regimens where it matters.
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", dose_status, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_medication_doses"),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name="fk_medication_doses_patient_id_patients",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["medication_id"],
            ["medications.id"],
            name="fk_medication_doses_medication_id_medications",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_medication_doses_patient_id_taken_at",
        "medication_doses",
        ["patient_id", "taken_at"],
    )

    _apply_row_level_security()
    _apply_runtime_grants()


def _apply_row_level_security() -> None:
    scope = "NULLIF(current_setting('app.current_patient_id', true), '')::uuid"
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY patient_isolation ON {table} USING (patient_id = {scope})")


def _apply_runtime_grants() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON medications TO app_runtime;
                GRANT SELECT, INSERT, UPDATE, DELETE ON medication_doses TO app_runtime;
                -- Reference data: readable, never writable by the application.
                GRANT SELECT ON medication_catalog TO app_runtime;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_table("medication_doses")
    op.drop_table("medications")
    op.drop_table("medication_catalog")

    for enum_name in ("medication_stop_reason", "dose_status", "drug_class"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
