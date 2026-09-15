import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, SmallInteger, String
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eoehelp_api.db.base import Base, Timestamps, UUIDPrimaryKey
from eoehelp_api.models.enums import SexAtBirth

if TYPE_CHECKING:
    from eoehelp_api.models.user import User


class Patient(UUIDPrimaryKey, Timestamps, Base):
    """Identifying patient attributes, deliberately separated from clinical tables.

    Research export reads the clinical side keyed on a pseudonym and never joins
    to this table, which is what makes de-identified export a query rather than a
    schema migration.
    """

    __tablename__ = "patients"
    __table_args__ = (
        CheckConstraint(
            "birth_year IS NULL OR (birth_year BETWEEN 1900 AND 2100)",
            name="birth_year_plausible",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    display_name: Mapped[str | None] = mapped_column(String(120))

    # Year, not full date of birth. DOB is a direct HIPAA Safe Harbor identifier
    # with outsized re-identification value, and v1 is adults-only so year is
    # sufficient. A pediatric module needs age in months and must revisit this.
    birth_year: Mapped[int | None] = mapped_column(SmallInteger)

    sex_at_birth: Mapped[SexAtBirth | None] = mapped_column(
        Enum(SexAtBirth, name="sex_at_birth", values_callable=lambda e: [m.value for m in e])
    )

    # Month precision: stored as the first of the month by convention.
    diagnosis_month: Mapped[date | None] = mapped_column(Date)

    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")

    user: Mapped["User"] = relationship(back_populates="patient")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Patient id={self.id}>"
