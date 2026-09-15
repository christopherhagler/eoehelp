"""Async engine, session factory, and the row-level-security scoping hook."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from eoehelp_api.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_pre_ping=True,
            echo=False,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False, autoflush=False
        )
    return _session_factory


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


RLS_SETTING = "app.current_patient_id"


async def apply_rls_scope(session: AsyncSession, patient_id: uuid.UUID | None) -> None:
    """Bind the current transaction to one patient for row-level security.

    set_config with is_local=true rather than `SET LOCAL`: both are
    transaction-scoped, but only the function form accepts a bind parameter, so
    the patient id is never interpolated into SQL text.

    Transaction-scoped is the load-bearing part. A session-scoped `SET` would
    persist on the pooled connection and leak into whichever request borrowed it
    next, turning the isolation backstop into a cross-patient disclosure.
    """
    value = str(patient_id) if patient_id is not None else ""
    await session.execute(
        text(f"SELECT set_config('{RLS_SETTING}', :value, true)"), {"value": value}
    )


@asynccontextmanager
async def session_scope(
    patient_id: uuid.UUID | None = None,
) -> AsyncIterator[AsyncSession]:
    """Open a transaction scoped to a patient, committing on clean exit."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await apply_rls_scope(session, patient_id)
        yield session
