from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, LargeBinary, String
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eoehelp_api.db.base import Base, Timestamps, UUIDPrimaryKey, pg_enum
from eoehelp_api.identity.enums import UserRole, UserStatus

if TYPE_CHECKING:
    from eoehelp_api.identity.patient import Patient


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Nullable: magic link is the primary path and most accounts never set one.
    password_hash: Mapped[str | None] = mapped_column(String(255))

    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role"),
        nullable=False,
        default=UserRole.PATIENT,
    )
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus, "user_status"),
        nullable=False,
        default=UserStatus.ACTIVE,
    )

    # Shipped in the first migration so enabling TOTP later needs no migration
    # against a live users table.
    mfa_enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    mfa_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)

    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    patient: Mapped["Patient | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        # Deliberately omits email: repr() reaches logs and tracebacks.
        return f"<User id={self.id} role={self.role.value}>"
