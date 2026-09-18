"""Declarative base and shared column conventions."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, MetaData, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Explicit naming so Alembic autogenerate produces stable, reviewable migration
# names instead of Postgres defaults that churn between runs.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def pg_enum(enum_type: type[enum.Enum], name: str) -> Enum:
    """A native Postgres enum that stores each member's value, not its name.

    SQLAlchemy stores names by default, so `DysphagiaRelief.DRANK_LIQUID` would
    land as 'DRANK_LIQUID' while the migrations, the API, and every export use
    'drank_liquid'.
    """
    return Enum(enum_type, name=name, values_callable=lambda e: [m.value for m in e])


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKey:
    """UUID keys throughout: these appear in URLs and export files, where a
    sequential id would leak record counts and permit enumeration."""

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
