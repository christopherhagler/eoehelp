import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Index, String, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eoehelp_api.audit.enums import AuditOutcome
from eoehelp_api.db.base import Base


class AuditLog(Base):
    """Append-only access and change record.

    Three properties matter and are enforced elsewhere:
      - The app role holds INSERT only; UPDATE and DELETE are revoked in migration,
        so a compromised application cannot erase its own trail.
      - Rows are written in the same transaction as the change they describe, so a
        crash cannot commit data without its audit entry.
      - `metadata_` carries changed field *names* only, never PHI values.

    A sequential id is intentional here: gaps are evidence of tampering.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_patient_id_occurred_at", "patient_id", "occurred_at"),
        Index("ix_audit_log_action_occurred_at", "action", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Null for unauthenticated actors, notably share-link viewers.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(postgresql.UUID(as_uuid=True))
    actor_role: Mapped[str | None] = mapped_column(String(32))

    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(postgresql.UUID(as_uuid=True))

    # Whose data was touched, which differs from the actor for share-link access.
    patient_id: Mapped[uuid.UUID | None] = mapped_column(postgresql.UUID(as_uuid=True))

    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(512))

    outcome: Mapped[AuditOutcome] = mapped_column(
        Enum(AuditOutcome, name="audit_outcome", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    metadata_: Mapped[dict[str, object] | None] = mapped_column("metadata", JSONB)

    # No foreign keys to users or patients by design: the audit trail must outlive
    # account deletion. A cascade here would erase the record of the deletion itself.
