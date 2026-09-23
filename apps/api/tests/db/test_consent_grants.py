"""Grants are what we said they are — in the database the application runs in.

The consent table is legal evidence, so the database enforces append-only.

The model's docstring has always said rows are never updated and never deleted
— a revocation is a new row. Until migration 0006 only the docstring said it:
`app_runtime` held UPDATE and DELETE on every table except `audit_log`, so one
careless repository, or one compromised process, could rewrite `granted` and
`document_sha256` and leave the audit trail none the wiser.

This is the same argument migration 0001 makes for `audit_log`, applied to the
other table that has to hold up years later.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


async def _app_role_exists(session: AsyncSession) -> bool:
    return (
        await session.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime'"))
    ).scalar_one_or_none() is not None


class TestConsentGrants:
    async def test_the_app_role_cannot_update_or_delete_a_consent(
        self, session: AsyncSession
    ) -> None:
        if not await _app_role_exists(session):
            pytest.skip("app_runtime role not present in this database")

        for privilege in ("UPDATE", "DELETE"):
            granted = (
                await session.execute(
                    text("SELECT has_table_privilege('app_runtime', 'consents', :priv)"),
                    {"priv": privilege},
                )
            ).scalar_one()
            assert granted is False, f"app_runtime must not hold {privilege} on consents"

    async def test_the_app_role_can_still_record_and_read_consent(
        self, session: AsyncSession
    ) -> None:
        """Revocation writes a new row and onboarding reads the current ones, so
        removing INSERT or SELECT would break consent rather than protect it."""
        if not await _app_role_exists(session):
            pytest.skip("app_runtime role not present in this database")

        for privilege in ("INSERT", "SELECT"):
            granted = (
                await session.execute(
                    text("SELECT has_table_privilege('app_runtime', 'consents', :priv)"),
                    {"priv": privilege},
                )
            ).scalar_one()
            assert granted is True, f"app_runtime needs {privilege} on consents"


class TestReferenceDataGrants:
    """Reference data is readable and not writable, and this is where that is
    proved rather than assumed.

    `test_reference_data_is_read_only_for_the_application` in the isolation
    suite asserted the same property and passed while it was false of the
    development database: `ALTER DEFAULT PRIVILEGES` in the Postgres init
    script handed `app_runtime` full DML on every table created afterwards, so
    each migration's deliberate `GRANT SELECT` added nothing. It went unnoticed
    because default privileges are per database, and the test database is
    created with `CREATE DATABASE` and inherits none of them — so the test
    described a database nobody ran.

    That is why the last test here asserts the *absence* of default privileges
    rather than any particular grant: it is the one assertion that makes the
    test database and the real one provably the same shape.
    """

    REFERENCE_TABLES = ("clinical_instruments", "medication_catalog", "ingredient_catalog")

    @pytest.mark.parametrize("table", REFERENCE_TABLES)
    async def test_reference_tables_are_not_writable(
        self, session: AsyncSession, table: str
    ) -> None:
        if not await _app_role_exists(session):
            pytest.skip("app_runtime role not present in this database")

        for privilege in ("INSERT", "UPDATE", "DELETE"):
            granted = (
                await session.execute(
                    text("SELECT has_table_privilege('app_runtime', :table, :priv)"),
                    {"table": table, "priv": privilege},
                )
            ).scalar_one()
            assert granted is False, (
                f"app_runtime must not hold {privilege} on {table}: the clinical layer "
                "trusts this data, and the DSQ definition every score is computed "
                "against lives in it"
            )

        readable = (
            await session.execute(
                text("SELECT has_table_privilege('app_runtime', :table, 'SELECT')"),
                {"table": table},
            )
        ).scalar_one()
        assert readable is True, f"app_runtime needs SELECT on {table}"

    async def test_the_application_cannot_move_the_migration_head(
        self, session: AsyncSession
    ) -> None:
        if not await _app_role_exists(session):
            pytest.skip("app_runtime role not present in this database")

        for privilege in ("INSERT", "UPDATE", "DELETE"):
            granted = (
                await session.execute(
                    text("SELECT has_table_privilege('app_runtime', 'alembic_version', :priv)"),
                    {"priv": privilege},
                )
            ).scalar_one()
            assert granted is False, f"app_runtime must not hold {privilege} on alembic_version"

    async def test_the_published_ledger_is_readable_and_not_writable(
        self, session: AsyncSession
    ) -> None:
        """Reference data: a migration publishes, the application only reads.

        Write access here would let the application publish a revision to match
        a file it had just changed, which is the original defect with one extra
        step.
        """
        if not await _app_role_exists(session):
            pytest.skip("app_runtime role not present in this database")

        for privilege in ("INSERT", "UPDATE", "DELETE"):
            granted = (
                await session.execute(
                    text("SELECT has_table_privilege('app_runtime', 'legal_documents', :priv)"),
                    {"priv": privilege},
                )
            ).scalar_one()
            assert granted is False, f"app_runtime must not hold {privilege} on legal_documents"

        assert (
            await session.execute(
                text("SELECT has_table_privilege('app_runtime', 'legal_documents', 'SELECT')")
            )
        ).scalar_one() is True

    async def test_research_consent_scopes_are_append_only_too(self, session: AsyncSession) -> None:
        """They are part of the same evidence as the consent they hang off."""
        if not await _app_role_exists(session):
            pytest.skip("app_runtime role not present in this database")

        for privilege in ("UPDATE", "DELETE"):
            granted = (
                await session.execute(
                    text(
                        "SELECT has_table_privilege("
                        "'app_runtime', 'research_consent_scopes', :priv)"
                    ),
                    {"priv": privilege},
                )
            ).scalar_one()
            assert granted is False, (
                f"app_runtime must not hold {privilege} on research_consent_scopes"
            )

        for privilege in ("INSERT", "SELECT"):
            granted = (
                await session.execute(
                    text(
                        "SELECT has_table_privilege("
                        "'app_runtime', 'research_consent_scopes', :priv)"
                    ),
                    {"priv": privilege},
                )
            ).scalar_one()
            assert granted is True, f"app_runtime needs {privilege} on research_consent_scopes"

    async def test_no_default_privileges_exist_in_the_application_database(
        self, application_database_url: str
    ) -> None:
        """Checked against the database the application runs in, not this one.

        This is the assertion whose absence let the defect live. Default
        privileges are per database: `ALTER DEFAULT PRIVILEGES` in the Postgres
        init script gave `app_runtime` full DML on every table created
        afterwards in the `eoehelp` database, while the test database — created
        with `CREATE DATABASE`, inheriting none — passed a read-only assertion
        that was false next door. Running it against the real database is the
        only version that would have failed.
        """
        engine = create_async_engine(application_database_url)
        try:
            async with engine.connect() as connection:
                granted = (
                    await connection.execute(text("SELECT count(*) FROM pg_default_acl"))
                ).scalar_one()
        finally:
            await engine.dispose()

        assert granted == 0, (
            "ALTER DEFAULT PRIVILEGES grants privileges on tables nobody has reviewed, "
            "and makes every explicit GRANT in every migration advisory. Grant per "
            "table in the migration that creates it instead, and rebuild the database."
        )
