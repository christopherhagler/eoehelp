"""The ledger of published legal document revisions, and the check against it.

`consents.document_sha256` exists so the exact wording a patient agreed to can
be produced years later. A digest pinned in the source tree cannot promise that
on its own: the file and the digest travel in the same commit, so editing both
together passes every check and silently re-points existing consent rows at new
wording. That is not hypothetical — it happened in this repository's first week,
to 27 rows, and the superseded bytes were never committed.

This table is the second witness. A revision is published when a migration
inserts it here, and `consents` carries a composite foreign key to it, so the
database refuses a consent row naming bytes it has no record of. The rows
outlive any later commit, which is the property the source tree cannot have.

It holds digests of public text and no patient data: reference data, readable
by the application role and written only by migrations, like the ingredient and
medication catalogues.

Only the table lives here, and it imports nothing above the foundation. The
check that reconciles it with the registry is in `legal_ledger.py`, because
`identity/consent.py` imports this module for its registration side effect —
the composite foreign key cannot be mapped without it — and that import should
not drag the document registry and the markdown parser in with it.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from eoehelp_api.db.base import Base, pg_enum
from eoehelp_api.identity.enums import ConsentType


class PublishedLegalDocument(Base):
    """One published revision: the bytes, and which document they belong to.

    Deliberately not stored here: title, slug, effective date and review status.
    Each already lives in the registry, nothing in the database reads them, and
    a duplicated column is a drift surface — which is the class of defect this
    table exists to remove. Review status in particular changes without the
    bytes changing, so a stored copy would be stale exactly when it mattered.
    """

    __tablename__ = "legal_documents"
    __table_args__ = (
        PrimaryKeyConstraint("version", "content_sha256", name="pk_legal_documents"),
        # The target of the foreign key from consents. The consent type is in it
        # so a privacy-policy consent cannot name the terms of service's digest.
        UniqueConstraint(
            "consent_type",
            "version",
            "content_sha256",
            name="uq_legal_documents_consent_type_version_content_sha256",
        ),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_is_hex"),
        # A version id is a path segment in /legal/{id}; the route restricts the
        # shape already, and the database should agree rather than trust it.
        CheckConstraint("version ~ '^[a-z0-9-]{3,64}$'", name="version_is_a_url_id"),
    )

    version: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    consent_type: Mapped[ConsentType] = mapped_column(
        pg_enum(ConsentType, "consent_type"), nullable=False
    )
    # When the migration inserted it: provenance the registry cannot hold.
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
