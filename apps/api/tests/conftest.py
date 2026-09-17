import asyncio
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from helpers import DEFAULT_ONBOARDING

TEST_DB_NAME = "eoehelp_test"


def _admin_url() -> str:
    base = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://eoehelp:eoehelp@localhost:5432/eoehelp"
    )
    return base.rsplit("/", 1)[0] + "/postgres"


def _test_url() -> str:
    base = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://eoehelp:eoehelp@localhost:5432/eoehelp"
    )
    return base.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return _test_url()


@pytest.fixture(scope="session", autouse=True)
def _configure_environment() -> None:
    """Point the application at a dedicated test database before settings load."""
    os.environ["DATABASE_URL"] = _test_url()
    os.environ["ENVIRONMENT"] = "local"
    os.environ.setdefault("SMTP_HOST", "localhost")

    # Settings are cached; clear so the test database URL above takes effect even
    # if something imported the module earlier in collection.
    from eoehelp_api.config import get_settings

    get_settings.cache_clear()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _database(_configure_environment: None) -> AsyncIterator[None]:
    admin = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"')
        await conn.exec_driver_sql(f'CREATE DATABASE "{TEST_DB_NAME}"')
    await admin.dispose()

    config = Config(str(_alembic_ini()))
    config.set_main_option("sqlalchemy.url", _test_url())
    # alembic's env.py calls asyncio.run(), which cannot nest inside the loop
    # pytest-asyncio is already running, so migrate on a worker thread.
    await asyncio.to_thread(command.upgrade, config, "head")

    yield

    from eoehelp_api.db.session import dispose_engine

    await dispose_engine()

    admin = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.exec_driver_sql(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{TEST_DB_NAME}' AND pid <> pg_backend_pid()"
        )
        await conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"')
    await admin.dispose()


def _alembic_ini():
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest_asyncio.fixture(autouse=True)
async def _isolate_engine_per_test() -> AsyncIterator[None]:
    """Dispose the shared engine at the end of each test.

    pytest-asyncio runs every test on a fresh event loop, while the engine is a
    module-level singleton. Without this, the second test reuses pooled
    connections bound to the previous, now-closed loop and fails with
    "attached to a different loop".
    """
    from eoehelp_api.db.session import dispose_engine

    yield
    await dispose_engine()


@pytest_asyncio.fixture
async def clean_tables(_database: None) -> AsyncIterator[None]:
    """Truncate between tests.

    audit_log is included: each test asserts on the trail it produced, and
    leftover rows from a previous test make those assertions meaningless.
    """
    engine = create_async_engine(_test_url())
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            # clinical_instruments, medication_catalog, and ingredient_catalog are
            # deliberately absent: all are reference data seeded by a migration,
            # and truncating one would break the foreign keys the patient-owned
            # rows depend on.
            "TRUNCATE users, patients, consents, research_consent_scopes, "
            "magic_link_tokens, refresh_tokens, symptom_entries, medications, "
            "medication_doses, custom_ingredients, food_log_items, "
            "food_log_item_ingredients, audit_log RESTART IDENTITY CASCADE"
        )
    await engine.dispose()
    yield


@pytest_asyncio.fixture
async def session(clean_tables: None) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(_test_url())
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


class CapturingEmailSender:
    """Stands in for SMTP, recording what would have been sent."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, to: str, subject: str, text_body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": text_body})

    async def send_magic_link(self, *, to: str, link: str, ttl_minutes: int) -> None:
        self.sent.append({"to": to, "link": link, "subject": "magic-link"})

    @property
    def last_link(self) -> str:
        return self.sent[-1]["link"]


@pytest.fixture
def email_sender() -> CapturingEmailSender:
    return CapturingEmailSender()


@pytest_asyncio.fixture
async def client(clean_tables: None) -> AsyncIterator[AsyncClient]:
    from eoehelp_api.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


# --- authenticated-patient helpers -------------------------------------------
#
# Reaching any clinical endpoint takes a magic link, a verification, and
# onboarding. These fixtures compress that into one call so a test about symptom
# entries reads as a test about symptom entries.

MAGIC_LINK_TOKEN_RE = re.compile(r"token=([A-Za-z0-9_-]+)")


@pytest.fixture
def sign_in(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Awaitable[str]]:
    """Sign a fresh account in, returning its access token."""

    captured: list[str] = []

    async def fake_send(_self: object, *, to: str, link: str, ttl_minutes: int) -> None:
        captured.append(link)

    monkeypatch.setattr("eoehelp_api.services.email.EmailSender.send_magic_link", fake_send)

    async def _sign_in(email: str = "patient@example.com") -> str:
        requested = await client.post("/api/v1/auth/magic-link", json={"email": email})
        assert requested.status_code == 202
        match = MAGIC_LINK_TOKEN_RE.search(captured[-1])
        assert match is not None
        verified = await client.post(
            "/api/v1/auth/magic-link/verify", json={"token": match.group(1)}
        )
        assert verified.status_code == 200
        return str(verified.json()["access_token"])

    return _sign_in


@pytest.fixture
def onboard(
    client: AsyncClient, sign_in: Callable[..., Awaitable[str]]
) -> Callable[..., Awaitable[tuple[str, dict[str, Any]]]]:
    """Sign in and complete onboarding, returning (access token, patient).

    The token onboarding returns is the one to use: the pre-onboarding token has
    no patient id in it, so every patient-scoped route rejects it.
    """

    async def _onboard(
        email: str = "patient@example.com", **overrides: object
    ) -> tuple[str, dict[str, Any]]:
        access = await sign_in(email)
        payload = {**DEFAULT_ONBOARDING, **overrides}
        response = await client.post(
            "/api/v1/me/onboarding",
            json=payload,
            headers={"Authorization": f"Bearer {access}"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        return str(body["access_token"]), dict(body["patient"])

    return _onboard
