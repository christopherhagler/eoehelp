"""Pin each consent to the exact text that was agreed to.

Revision ID: 0006_consent_document_digest
Revises: 0005_procedures

The version label names a document; it does not prove which words were on the
screen. A digest does, and it is what makes a consent record hold up once a
document has been superseded. It also catches the one failure the registry
cannot: a published file edited together with its recorded digest, which would
otherwise re-point every old consent row at new wording.

Self-contained by design (ADR 0010): the digests below are literals, which
doubles as a record of what the three documents contained at publication.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_consent_document_digest"
down_revision: str | None = "0005_procedures"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# sha256 of each document's bytes at publication. See
# eoehelp_api/identity/documents.py, which verifies these at startup.
DIGESTS: dict[str, str] = {
    "tos-2026-09": "450b7d1254ec252dcd2d11023ec6a4cc3b6312e0c05f5eb8fd5b3f6b9d9fbd34",
    "privacy-2026-09": "6eb6642accabc882a2373c72ec44091983c4ba5abde130e7490940529430f41e",
    "chd-2026-09": "188a1cc1575cab899b2b9cec222a030592ebacf9d10015d1bf3a3be9cb648a9c",
}


def upgrade() -> None:
    op.add_column("consents", sa.Column("document_sha256", sa.String(length=64), nullable=True))

    for version, digest in DIGESTS.items():
        op.execute(
            sa.text(
                "UPDATE consents SET document_sha256 = :digest WHERE document_version = :version"
            ).bindparams(digest=digest, version=version)
        )

    # Fails loudly on a row this migration did not cover, rather than inventing
    # a digest for wording nobody can reproduce.
    op.alter_column("consents", "document_sha256", nullable=False)
    op.create_check_constraint(
        op.f("ck_consents_document_sha256_is_hex"),
        "consents",
        "document_sha256 ~ '^[0-9a-f]{64}$'",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_consents_document_sha256_is_hex"), "consents", type_="check")
    op.drop_column("consents", "document_sha256")
