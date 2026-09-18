"""Daily symptom tracking: the DSQ-shaped entry table and its instrument registry.

Hand-written, like 0001. Autogenerate cannot express row-level security policies
or role grants, and grants are not retroactive — a new table is invisible to
app_runtime until it is granted explicitly, so every migration adding a table
must re-run them.

Revision ID: 0002_symptom_entries
Revises: 0001_initial
Create Date: 2026-09-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_symptom_entries"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Patient-owned, therefore row-level-security protected. Every new clinical table
# joins this list; clinical_instruments is reference data and stays out of it.
RLS_TABLES = ("symptom_entries",)


def upgrade() -> None:
    # DSQ question 3: what the patient had to do, at the worst episode of the day,
    # to make food go down or get relief. Single choice, ordered as the
    # instrument scores it (0-4); see symptoms/scoring.py.
    dysphagia_relief = postgresql.ENUM(
        "cleared_on_its_own",
        "drank_liquid",
        "coughed_or_gagged",
        "vomited",
        "sought_medical_attention",
        name="dysphagia_relief",
        create_type=False,
    )
    entry_method = postgresql.ENUM("same_day", "backfill", name="entry_method", create_type=False)

    for enum in (dysphagia_relief, entry_method):
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "clinical_instruments",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("scoring_algorithm", sa.String(length=64), nullable=False),
        sa.Column("attribution", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code", name="pk_clinical_instruments"),
    )

    # Seeded here rather than at application startup so the foreign key below can
    # never dangle, and so the attribution the licence requires ships with the
    # schema instead of depending on a seed script someone forgets to run.
    op.execute(
        """
        INSERT INTO clinical_instruments
            (code, version, display_name, scoring_algorithm, attribution)
        VALUES (
            'DSQ',
            'v4.0',
            'Dysphagia Symptom Questionnaire',
            'dsq_v4_14day',
            'Dysphagia Symptom Questionnaire (DSQ) v4.0, Dellon ES et al., Aliment '
            || 'Pharmacol Ther 2013. Licence terms not yet confirmed: they must be '
            || 'obtained in writing before launch; see the launch gate.'
        )
        """
    )

    op.create_table(
        "symptom_entries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        # The day described, kept separate from created_at: only this column is
        # date-shifted for research, while created_at is system metadata.
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("ate_solid_food", sa.Boolean(), nullable=False),
        sa.Column("dysphagia_occurred", sa.Boolean(), nullable=True),
        sa.Column("dysphagia_relief", dysphagia_relief, nullable=True),
        sa.Column("odynophagia", sa.Boolean(), nullable=True),
        sa.Column("odynophagia_severity", sa.SmallInteger(), nullable=True),
        sa.Column(
            "food_impaction_er_visit",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("avoided_foods_today", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("modified_foods_today", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("ate_unusually_slowly", sa.Boolean(), server_default=sa.false(), nullable=False),
        # Application-layer AES-GCM with the key outside the database.
        sa.Column("notes_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("entry_method", entry_method, nullable=False),
        sa.Column("instrument_code", sa.String(length=32), nullable=False),
        sa.Column("instrument_version", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_symptom_entries"),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name="fk_symptom_entries_patient_id_patients",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_code"],
            ["clinical_instruments.code"],
            name="fk_symptom_entries_instrument_code_clinical_instruments",
        ),
        # One row per patient per day. An edit updates; it never adds a second
        # row, because two answers for one day cannot both be true and the
        # 14-day score needs exactly one input per day.
        sa.UniqueConstraint(
            "patient_id", "entry_date", name="uq_symptom_entries_patient_id_entry_date"
        ),
        # A day with no solid food has no dysphagia answer to give. Inventing a
        # "no" for those days would flatter the score of someone who lived on
        # shakes, which is the opposite of the truth.
        sa.CheckConstraint(
            "ate_solid_food OR (dysphagia_occurred IS NULL AND dysphagia_relief IS NULL)",
            name=op.f("ck_symptom_entries_dysphagia_requires_solid_food"),
        ),
        # A day with solid food answers question 2; without it the diary day is
        # not valid, and the score would silently count it as symptom-free.
        sa.CheckConstraint(
            "NOT ate_solid_food OR dysphagia_occurred IS NOT NULL",
            name=op.f("ck_symptom_entries_solid_food_day_answers_dysphagia"),
        ),
        # Question 3 is asked exactly when question 2 was yes.
        sa.CheckConstraint(
            "(dysphagia_occurred IS TRUE) = (dysphagia_relief IS NOT NULL)",
            name=op.f("ck_symptom_entries_relief_answers_dysphagia"),
        ),
        # An emergency visit for impacted food is medical attention, so the two
        # answers cannot contradict each other on the report.
        sa.CheckConstraint(
            "NOT food_impaction_er_visit OR dysphagia_relief = 'sought_medical_attention'",
            name=op.f("ck_symptom_entries_er_visit_is_medical_attention"),
        ),
        sa.CheckConstraint(
            "odynophagia_severity IS NULL OR odynophagia_severity BETWEEN 0 AND 3",
            name=op.f("ck_symptom_entries_odynophagia_severity_range"),
        ),
    )
    op.create_index(
        "ix_symptom_entries_patient_id_entry_date",
        "symptom_entries",
        ["patient_id", "entry_date"],
    )

    _apply_row_level_security()
    _apply_runtime_grants()


def _apply_row_level_security() -> None:
    """Enable RLS as the backstop behind the scoped-repository pattern.

    NULLIF guards the unset case: an unscoped session yields NULL, which matches
    no row, so a forgotten filter returns nothing rather than another patient's
    record. With no separate WITH CHECK clause the same expression governs
    INSERT, which is why the application sets the scope before writing a row.

    Statements are issued one at a time because asyncpg prepares each one and
    rejects multi-command strings.
    """
    scope = "NULLIF(current_setting('app.current_patient_id', true), '')::uuid"
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY patient_isolation ON {table} USING (patient_id = {scope})")


def _apply_runtime_grants() -> None:
    """Re-grant, because grants do not extend to tables created after them.

    The application role still owns nothing — owners bypass row-level security,
    which would make the policies above inert.
    """
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON symptom_entries TO app_runtime;
                -- Reference data: readable, never writable by the application.
                GRANT SELECT ON clinical_instruments TO app_runtime;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_table("symptom_entries")
    op.drop_table("clinical_instruments")

    for enum_name in ("entry_method", "dysphagia_relief"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
