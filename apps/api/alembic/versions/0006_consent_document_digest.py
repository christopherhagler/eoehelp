"""Pin each consent to the exact text that was agreed to.

Revision ID: 0006_consent_document_digest
Revises: 0005_procedures

The version label names a document; it does not prove which words were on the
screen. A digest does, and it is what makes a consent record hold up once a
document has been superseded. It also catches the one failure the registry
cannot: a published file edited together with its recorded digest, which would
otherwise re-point every old consent row at new wording.

It also creates `legal_documents`, the ledger of published revisions, and
points `consents` at it with a composite foreign key. The registry in the
source tree cannot be the only witness to what was published: a file and its
recorded digest travel in the same commit, so editing both together passes
every check in the build. These rows do not, which is the whole point.

Self-contained by design (ADR 0010): the revisions below are literals, which
doubles as a dated record of what was published and when.

This migration also revokes UPDATE and DELETE on consents from app_runtime.
The model has always called the table append-only; until now only a docstring
said so, while the role could rewrite the very column this migration adds.

**The backfill is only honest before deployment.** Step 4 gives every existing
consent row the current digest of the version it names. That is truthful here
because every such row is synthetic pre-deployment data. Against real consents
it would fabricate evidence — asserting that patients agreed to bytes nobody
has checked they ever saw. A later publication migration must never backfill;
it inserts its ledger row and stops.

**Editing this migration in place is a pre-deployment privilege.** Nothing is
deployed, so the ledger is still rewritable and the development database is
rebuilt instead of migrated. That window closes at the first deploy.

Downgrading destroys evidence. Dropping the column discards every recorded
digest, dropping `legal_documents` discards the record of what was ever
published, and re-upgrading reconstructs only the revisions listed in this
file — so a row written against a later document comes back NULL and the
re-upgrade fails at SET NOT NULL. Harmless while nothing is deployed; after the
first patient, `alembic downgrade 0006` is destruction of a legal record, not a
rollback.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_consent_document_digest"
down_revision: str | None = "0005_procedures"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every revision published by this migration: (consent_type, version, sha256 of
# the file's bytes). Declared once here and used for both the ledger and the
# backfill. See eoehelp_api/identity/documents.py, whose registry must agree
# with these rows or the API refuses to start.
# The publication date is a literal too, not now(): now() is transaction start
# time, so every environment would record the moment its database was built and
# two environments would disagree about when a document was published. This is
# provenance on a legal record; it has to be the same everywhere.
PUBLISHED_REVISIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "terms_of_service",
        "tos-2026-09",
        "450b7d1254ec252dcd2d11023ec6a4cc3b6312e0c05f5eb8fd5b3f6b9d9fbd34",
        "2026-09-19",
    ),
    (
        "privacy_policy",
        "privacy-2026-09",
        "6eb6642accabc882a2373c72ec44091983c4ba5abde130e7490940529430f41e",
        "2026-09-19",
    ),
    (
        "consumer_health_data",
        "chd-2026-09",
        "188a1cc1575cab899b2b9cec222a030592ebacf9d10015d1bf3a3be9cb648a9c",
        "2026-09-19",
    ),
)


def upgrade() -> None:
    op.create_table(
        "legal_documents",
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "consent_type",
            postgresql.ENUM(name="consent_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("version", "content_sha256", name="pk_legal_documents"),
        sa.UniqueConstraint(
            "consent_type",
            "version",
            "content_sha256",
            name="uq_legal_documents_consent_type_version_content_sha256",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_legal_documents_content_sha256_is_hex"),
        ),
        sa.CheckConstraint(
            "version ~ '^[a-z0-9-]{3,64}$'", name=op.f("ck_legal_documents_version_is_a_url_id")
        ),
    )

    for consent_type, version, digest, published_on in PUBLISHED_REVISIONS:
        op.execute(
            # Cast explicitly: a bound parameter arrives as varchar and the
            # column is a native enum, which Postgres will not coerce. Schema
            # qualified so it does not depend on search_path.
            sa.text(
                "INSERT INTO legal_documents "
                "(consent_type, version, content_sha256, published_at) "
                "VALUES (CAST(:consent_type AS public.consent_type), :version, :digest, "
                "CAST(:published_on AS timestamptz))"
            ).bindparams(
                consent_type=consent_type,
                version=version,
                digest=digest,
                published_on=published_on,
            )
        )

    op.add_column("consents", sa.Column("document_sha256", sa.String(length=64), nullable=True))

    # From the ledger rather than from per-version literals, so the digests are
    # declared once. Valid only because this migration publishes exactly one
    # revision per version; see the docstring on why a later publication
    # migration must not do this at all.
    op.execute(
        """
        UPDATE consents c
           SET document_sha256 = d.content_sha256
          FROM legal_documents d
         WHERE d.version = c.document_version
           AND d.consent_type = c.consent_type
           AND c.document_sha256 IS NULL
        """
    )

    # Fails loudly on a row this migration did not cover, rather than inventing
    # a digest for wording nobody can reproduce. Named explicitly, because
    # env.py runs the whole upgrade in one transaction: a bare "contains null
    # values" from SET NOT NULL rolls the run back without saying which version
    # was uncovered.
    uncovered = (
        op.get_bind()
        .execute(
            sa.text("SELECT DISTINCT document_version FROM consents WHERE document_sha256 IS NULL")
        )
        .scalars()
        .all()
    )
    if uncovered:
        raise RuntimeError(
            "No published digest for consent document version(s): "
            + ", ".join(sorted(uncovered))
            + ". Add the revision to PUBLISHED_REVISIONS in this migration, with the "
            "sha256 of the bytes those patients agreed to."
        )

    op.alter_column(
        "consents", "document_sha256", existing_type=sa.String(length=64), nullable=False
    )
    op.create_check_constraint(
        op.f("ck_consents_document_sha256_is_hex"),
        "consents",
        "document_sha256 ~ '^[0-9a-f]{64}$'",
    )

    # Read as the migration role, which owns consents and so bypasses RLS —
    # which is why this sees anything at all. Run as an unscoped app_runtime it
    # would return nothing and pass silently.
    #
    # Before the foreign key, so a stale row produces a readable instruction
    # rather than an opaque constraint violation. Versions and counts only: a
    # digest this migration cannot explain does not belong in an error message,
    # and a patient id never does.
    stale = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT c.consent_type::text, c.document_version, count(*) AS rows
                  FROM consents c
                  LEFT JOIN legal_documents d
                    ON d.consent_type = c.consent_type
                   AND d.version = c.document_version
                   AND d.content_sha256 = c.document_sha256
                 WHERE d.version IS NULL
                 GROUP BY c.consent_type, c.document_version
                 ORDER BY c.consent_type, c.document_version
                """
            )
        )
        .all()
    )
    if stale:
        raise RuntimeError(
            "Consent rows name document revisions that were never published: "
            + ", ".join(
                f"{consent_type}/{version} ({count} rows)" for consent_type, version, count in stale
            )
            + ". Before deployment, rebuild the development database "
            "(make clean && make up && make seed). After deployment, publish the "
            "missing revision's bytes and add them to a migration — deleting a "
            "consent row destroys a legal record."
        )

    op.create_foreign_key(
        "fk_consents_document_revision_legal_documents",
        "consents",
        "legal_documents",
        ["consent_type", "document_version", "document_sha256"],
        ["consent_type", "version", "content_sha256"],
    )

    # The same argument 0001 makes for audit_log, applied to the other table
    # that is legal evidence. The cascade from patients still deletes these
    # rows: it runs as the constraint owner and ignores both grants and RLS.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
                REVOKE UPDATE, DELETE ON consents FROM app_runtime;
                -- 0001 grants DML on ALL TABLES, which sweeps up Alembic's own
                -- bookkeeping: the application could move the migration head.
                -- It never reads it, so nothing is lost by taking it away.
                REVOKE ALL ON alembic_version FROM app_runtime;
                -- Reference data: readable, and written only by a migration.
                -- 0001's GRANT covered only the tables that existed then, so a
                -- new table starts with no grants at all.
                GRANT SELECT ON legal_documents TO app_runtime;
                -- Consent scopes are part of the same evidence as the consent.
                REVOKE UPDATE, DELETE ON research_consent_scopes FROM app_runtime;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
                GRANT UPDATE, DELETE ON consents TO app_runtime;
                GRANT UPDATE, DELETE ON research_consent_scopes TO app_runtime;
                -- alembic_version is deliberately not re-granted: the
                -- application never reads it, and restoring the ability to move
                -- the migration head is not part of rolling back this change.
            END IF;
        END
        $$
        """
    )
    op.drop_constraint(
        "fk_consents_document_revision_legal_documents", "consents", type_="foreignkey"
    )
    op.drop_constraint(op.f("ck_consents_document_sha256_is_hex"), "consents", type_="check")
    op.drop_column("consents", "document_sha256")
    op.drop_table("legal_documents")
