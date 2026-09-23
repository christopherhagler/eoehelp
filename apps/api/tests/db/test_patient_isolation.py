"""Row-level security: the backstop behind application-level scoping.

These tests connect as `app_runtime` — the unprivileged role the deployed
application uses — because RLS is bypassed by table owners and superusers. Run
as the owner, every one of these would pass while proving nothing.

`consents` has no case of its own here on purpose: the digest column added in
0006 sits inside the policy and the grants migration 0001 already gave the
table, because those are table-level rather than per column. What 0006 does add
is its append-only property, and that is asserted next door in
test_consent_grants.py, which is also where the reference-table grants are
proved — see its note on why proving them here would have been misleading.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

from eoehelp_api.identity import documents
from eoehelp_api.identity.enums import ConsentType
from helpers import app_role_url


@pytest_asyncio.fixture
async def app_role_engine(clean_tables: None, test_database_url: str):
    engine = create_async_engine(app_role_url(test_database_url), poolclass=None)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - environment-dependent
        await engine.dispose()
        pytest.skip("app_runtime role unavailable in this environment")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def two_patients(session) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed two patients as the owner, bypassing RLS to set up the fixture."""
    ids: list[uuid.UUID] = []
    for email in ("alice@example.com", "bob@example.com"):
        user_id = (
            await session.execute(
                text(
                    "INSERT INTO users (email, role, status) "
                    "VALUES (:email, 'patient', 'active') RETURNING id"
                ),
                {"email": email},
            )
        ).scalar_one()
        patient_id = (
            await session.execute(
                text(
                    "INSERT INTO patients (user_id, display_name) VALUES (:uid, :name) RETURNING id"
                ),
                {"uid": user_id, "name": email.split("@")[0]},
            )
        ).scalar_one()
        # A published triple, not an invented one. The foreign key to
        # legal_documents now refuses anything else — and a fixture that
        # invents evidence is how the reproducibility invariant was lost in the
        # first place.
        terms = documents.current_for(ConsentType.TERMS_OF_SERVICE)
        await session.execute(
            text(
                "INSERT INTO consents "
                "(patient_id, consent_type, document_version, document_sha256, granted) "
                "VALUES (:pid, 'terms_of_service', :version, :digest, true)"
            ),
            {"pid": patient_id, "version": terms.version, "digest": terms.sha256},
        )
        await session.execute(
            text(
                "INSERT INTO symptom_entries "
                "(patient_id, entry_date, ate_solid_food, dysphagia_occurred, "
                " entry_method, instrument_code, instrument_version) "
                "VALUES (:pid, CURRENT_DATE, true, false, 'same_day', 'DSQ', 'v4.0')"
            ),
            {"pid": patient_id},
        )
        medication_id = (
            await session.execute(
                text(
                    "INSERT INTO medications "
                    "(patient_id, medication_code, started_on) "
                    "VALUES (:pid, 'omeprazole', CURRENT_DATE) RETURNING id"
                ),
                {"pid": patient_id},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO medication_doses (patient_id, medication_id, taken_at, status) "
                "VALUES (:pid, :mid, now(), 'taken')"
            ),
            {"pid": patient_id, "mid": medication_id},
        )
        custom_id = (
            await session.execute(
                text(
                    "INSERT INTO custom_ingredients "
                    "(patient_id, name, name_key, canonical_key, allergen_groups) "
                    "VALUES (:pid, 'Relish', 'relish', 'en:relish', '{}') RETURNING id"
                ),
                {"pid": patient_id},
            )
        ).scalar_one()
        item_id = (
            await session.execute(
                text(
                    "INSERT INTO food_log_items "
                    "(patient_id, eaten_on, meal, name, name_key, entry_method) "
                    "VALUES (:pid, CURRENT_DATE, 'lunch', 'Sandwich', 'sandwich', 'same_day') "
                    "RETURNING id"
                ),
                {"pid": patient_id},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO food_log_item_ingredients "
                "(patient_id, item_id, ingredient_code, custom_ingredient_id, position, "
                " canonical_key, display_name, provenance) "
                "VALUES (:pid, :item, 'bread', NULL, 0, 'en:bread', 'Bread', 'patient'), "
                "(:pid, :item, NULL, :custom, 1, 'en:relish', 'Relish', 'patient')"
            ),
            {"pid": patient_id, "item": item_id, "custom": custom_id},
        )
        scope_id = (
            await session.execute(
                text(
                    "INSERT INTO endoscopies (patient_id, performed_on, indication) "
                    "VALUES (:pid, CURRENT_DATE, 'diagnosis') RETURNING id"
                ),
                {"pid": patient_id},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO biopsies (patient_id, endoscopy_id, location, peak_eos_per_hpf, "
                "peak_eos_comparator, position) VALUES (:pid, :sid, 'distal', 40, 'exact', 0)"
            ),
            {"pid": patient_id, "sid": scope_id},
        )
        await session.execute(
            text(
                "INSERT INTO dilations (patient_id, endoscopy_id, dilator_type) "
                "VALUES (:pid, :sid, 'balloon')"
            ),
            {"pid": patient_id, "sid": scope_id},
        )
        ids.append(patient_id)
    await session.commit()
    return ids[0], ids[1]


async def _insert_entry(engine, *, scope: uuid.UUID, patient_id: uuid.UUID) -> None:
    """Insert a symptom entry under one patient's scope, on behalf of another.

    Split out so the assertion below is a single statement, and so the scope and
    the row's owner are visibly separate arguments.
    """
    async with engine.connect() as conn, conn.begin():
        await conn.execute(
            text("SELECT set_config('app.current_patient_id', :v, true)"),
            {"v": str(scope)},
        )
        await conn.execute(
            text(
                "INSERT INTO symptom_entries "
                "(patient_id, entry_date, ate_solid_food, dysphagia_occurred, entry_method, "
                " instrument_code, instrument_version) "
                "VALUES (:pid, CURRENT_DATE - 1, true, false, 'same_day', 'DSQ', 'v4.0')"
            ),
            {"pid": str(patient_id)},
        )


async def _scoped_rows(engine, patient_id: uuid.UUID | None, table: str) -> int:
    async with engine.connect() as conn, conn.begin():
        await conn.execute(
            text("SELECT set_config('app.current_patient_id', :v, true)"),
            {"v": str(patient_id) if patient_id else ""},
        )
        return (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


class TestRowLevelSecurity:
    async def test_unscoped_query_returns_nothing(self, app_role_engine, two_patients) -> None:
        """The property that matters: a forgotten filter leaks nothing.

        Without this, RLS is a policy you believe works rather than one you know does.
        """
        assert await _scoped_rows(app_role_engine, None, "patients") == 0
        assert await _scoped_rows(app_role_engine, None, "consents") == 0
        assert await _scoped_rows(app_role_engine, None, "symptom_entries") == 0
        assert await _scoped_rows(app_role_engine, None, "medications") == 0
        assert await _scoped_rows(app_role_engine, None, "medication_doses") == 0
        assert await _scoped_rows(app_role_engine, None, "custom_ingredients") == 0
        assert await _scoped_rows(app_role_engine, None, "food_log_items") == 0
        assert await _scoped_rows(app_role_engine, None, "food_log_item_ingredients") == 0
        for table in ("endoscopies", "biopsies", "dilations"):
            assert await _scoped_rows(app_role_engine, None, table) == 0

    async def test_scope_limits_results_to_one_patient(self, app_role_engine, two_patients) -> None:
        alice, bob = two_patients
        assert await _scoped_rows(app_role_engine, alice, "patients") == 1
        assert await _scoped_rows(app_role_engine, bob, "patients") == 1
        assert await _scoped_rows(app_role_engine, alice, "consents") == 1
        assert await _scoped_rows(app_role_engine, alice, "symptom_entries") == 1
        assert await _scoped_rows(app_role_engine, bob, "symptom_entries") == 1
        assert await _scoped_rows(app_role_engine, alice, "medications") == 1
        assert await _scoped_rows(app_role_engine, alice, "medication_doses") == 1
        assert await _scoped_rows(app_role_engine, bob, "medications") == 1
        assert await _scoped_rows(app_role_engine, alice, "custom_ingredients") == 1
        assert await _scoped_rows(app_role_engine, alice, "food_log_items") == 1
        assert await _scoped_rows(app_role_engine, alice, "food_log_item_ingredients") == 2
        assert await _scoped_rows(app_role_engine, bob, "food_log_item_ingredients") == 2
        for table in ("endoscopies", "biopsies", "dilations"):
            assert await _scoped_rows(app_role_engine, alice, table) == 1
            assert await _scoped_rows(app_role_engine, bob, table) == 1

    async def test_one_patient_cannot_read_another_by_id(
        self, app_role_engine, two_patients
    ) -> None:
        alice, bob = two_patients
        async with app_role_engine.connect() as conn, conn.begin():
            await conn.execute(
                text("SELECT set_config('app.current_patient_id', :v, true)"),
                {"v": str(alice)},
            )
            found = (
                await conn.execute(
                    text("SELECT count(*) FROM patients WHERE id = :bob"),
                    {"bob": str(bob)},
                )
            ).scalar_one()
        assert found == 0, "explicitly naming another patient's id must still return nothing"

    async def test_scope_does_not_leak_across_transactions(
        self, app_role_engine, two_patients
    ) -> None:
        """Catches `SET` where `SET LOCAL` was meant.

        A session-scoped setting would survive on the pooled connection and hand
        the next borrower the previous patient's scope.
        """
        alice, _ = two_patients
        async with app_role_engine.connect() as conn:
            async with conn.begin():
                await conn.execute(
                    text("SELECT set_config('app.current_patient_id', :v, true)"),
                    {"v": str(alice)},
                )
                assert (await conn.execute(text("SELECT count(*) FROM patients"))).scalar_one() == 1

            # Same physical connection, new transaction, no scope applied.
            async with conn.begin():
                leaked = (await conn.execute(text("SELECT count(*) FROM patients"))).scalar_one()
        assert leaked == 0, "patient scope leaked into a subsequent transaction"

    async def test_a_row_cannot_be_written_for_another_patient(
        self, app_role_engine, two_patients
    ) -> None:
        """The policy governs INSERT as well as SELECT.

        With no separate WITH CHECK clause, Postgres applies the USING expression
        to writes too, so a scoped session cannot plant a row on someone else's
        record even if the application layer were bypassed entirely.
        """
        alice, bob = two_patients
        with pytest.raises(ProgrammingError, match="row-level security"):
            await _insert_entry(app_role_engine, scope=alice, patient_id=bob)

    async def test_a_row_can_be_written_for_the_scoped_patient(
        self, app_role_engine, two_patients
    ) -> None:
        """The other half of the same property: the write policy is not simply
        refusing everything, which would make the test above pass for the wrong
        reason."""
        alice, _ = two_patients
        await _insert_entry(app_role_engine, scope=alice, patient_id=alice)
        assert await _scoped_rows(app_role_engine, alice, "symptom_entries") == 2

    async def test_app_role_is_not_a_table_owner(self, app_role_engine) -> None:
        """Owners bypass RLS, which would make every policy above inert."""
        async with app_role_engine.connect() as conn:
            owned = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM pg_tables "
                        "WHERE schemaname = 'public' AND tableowner = 'app_runtime'"
                    )
                )
            ).scalar_one()
        assert owned == 0

    async def test_every_patient_owned_table_has_row_level_security(self, app_role_engine) -> None:
        """A new table with a patient_id and no policy is the gap this layer exists
        to close, and it is exactly the kind a migration forgets. Checked from the
        catalog, so the next table is covered without anyone editing this test."""
        async with app_role_engine.connect() as conn:
            unprotected = (
                (
                    await conn.execute(
                        text(
                            "SELECT c.relname FROM pg_class c "
                            "JOIN pg_namespace n ON n.oid = c.relnamespace "
                            "JOIN pg_attribute a ON a.attrelid = c.oid "
                            "WHERE n.nspname = 'public' AND c.relkind = 'r' "
                            "AND a.attname = 'patient_id' AND NOT a.attisdropped "
                            "AND NOT c.relrowsecurity "
                            "ORDER BY c.relname"
                        )
                    )
                )
                .scalars()
                .all()
            )
        # audit_log names a patient but is append-only and never read by the
        # application; its protection is the grant, not a policy.
        assert list(unprotected) == ["audit_log"]

    async def test_reference_data_is_read_only_for_the_application(self, app_role_engine) -> None:
        async with app_role_engine.connect() as conn:
            assert (
                await conn.execute(text("SELECT count(*) FROM ingredient_catalog"))
            ).scalar_one() > 100
        for statement in (
            "INSERT INTO ingredient_catalog (code, name, allergen_groups, aliases) "
            "VALUES ('x', 'X', '{}', '{}')",
            "UPDATE ingredient_catalog SET allergen_groups = '{}' WHERE code = 'milk'",
            "DELETE FROM ingredient_catalog WHERE code = 'milk'",
        ):
            with pytest.raises(ProgrammingError, match="permission denied"):
                async with app_role_engine.connect() as conn, conn.begin():
                    await conn.execute(text(statement))

    async def test_the_published_document_ledger_is_read_only(self, app_role_engine) -> None:
        """It is the record of what was published; only a migration writes it.

        If the application could write here it could publish a revision to
        match a file it had just changed, which is the whole defect back again
        with an extra step.
        """
        terms = documents.current_for(ConsentType.TERMS_OF_SERVICE)
        async with app_role_engine.connect() as conn:
            found = (
                await conn.execute(
                    text("SELECT count(*) FROM legal_documents WHERE content_sha256 = :digest"),
                    {"digest": terms.sha256},
                )
            ).scalar_one()
            assert found == 1

        for statement in (
            "INSERT INTO legal_documents (consent_type, version, content_sha256) "
            "VALUES ('terms_of_service', 'tos-2099-01', repeat('b', 64))",
            "UPDATE legal_documents SET content_sha256 = repeat('c', 64)",
            "DELETE FROM legal_documents",
        ):
            with pytest.raises(ProgrammingError, match="permission denied"):
                async with app_role_engine.connect() as conn, conn.begin():
                    await conn.execute(text(statement))


class TestResearchConsentScopes:
    """The table that passed the catalogue test by having no patient_id at all.

    It records which parts of their record a patient agreed to share for
    research. Nothing grants that consent yet, which is exactly why this is the
    moment to put it inside the backstop.
    """

    @pytest_asyncio.fixture
    async def scoped_consent(self, session, two_patients) -> tuple[uuid.UUID, uuid.UUID]:
        """One research consent with a scope, for Alice. Seeded as the owner."""
        alice, _ = two_patients
        terms = documents.current_for(ConsentType.TERMS_OF_SERVICE)
        consent_id = (
            await session.execute(
                text(
                    "INSERT INTO consents "
                    "(patient_id, consent_type, document_version, document_sha256, granted) "
                    "VALUES (:pid, 'terms_of_service', :version, :digest, true) RETURNING id"
                ),
                {"pid": alice, "version": terms.version, "digest": terms.sha256},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO research_consent_scopes (consent_id, patient_id, scope) "
                "VALUES (:cid, :pid, 'symptoms')"
            ),
            {"cid": consent_id, "pid": alice},
        )
        await session.commit()
        return alice, consent_id

    async def test_one_patient_cannot_read_another_patients_scopes(
        self, app_role_engine, two_patients, scoped_consent
    ) -> None:
        alice, bob = two_patients
        async with app_role_engine.connect() as conn, conn.begin():
            await conn.execute(
                text("SELECT set_config('app.current_patient_id', :pid, true)"),
                {"pid": str(bob)},
            )
            visible = (
                await conn.execute(text("SELECT count(*) FROM research_consent_scopes"))
            ).scalar_one()
        assert visible == 0

        # And Alice sees it, so the assertion above is about the policy rather
        # than about a fixture that silently wrote nothing.
        async with app_role_engine.connect() as conn, conn.begin():
            await conn.execute(
                text("SELECT set_config('app.current_patient_id', :pid, true)"),
                {"pid": str(alice)},
            )
            own = (
                await conn.execute(text("SELECT count(*) FROM research_consent_scopes"))
            ).scalar_one()
        assert own == 1

    async def test_a_scope_cannot_claim_a_patient_its_consent_does_not_belong_to(
        self, app_role_engine, two_patients, scoped_consent
    ) -> None:
        """The composite foreign key, not the policy.

        Bob names Alice's consent with his own patient id: the triple does not
        exist in `consents`, so this fails before row-level security is ever
        consulted. Matched on the constraint name so it cannot pass on a
        permission error instead.
        """
        _, bob = two_patients
        _, consent_id = scoped_consent
        async with app_role_engine.connect() as conn, conn.begin():
            await conn.execute(
                text("SELECT set_config('app.current_patient_id', :pid, true)"),
                {"pid": str(bob)},
            )
            insert = text(
                "INSERT INTO research_consent_scopes (consent_id, patient_id, scope) "
                "VALUES (:cid, :pid, 'diet')"
            )
            with pytest.raises(
                IntegrityError, match="fk_research_consent_scopes_consent_id_consents"
            ):
                await conn.execute(insert, {"cid": consent_id, "pid": str(bob)})

    async def test_a_scope_cannot_be_planted_in_another_patients_record(
        self, app_role_engine, two_patients, scoped_consent
    ) -> None:
        """The policy, not the foreign key — and the dangerous direction.

        Bob writes a row that is internally consistent (Alice's consent, Alice's
        patient id), so the foreign key is satisfied. Only the policy stops it,
        and without that check the previous test would pass with the policy
        dropped entirely.
        """
        alice, bob = two_patients
        _, consent_id = scoped_consent
        async with app_role_engine.connect() as conn, conn.begin():
            await conn.execute(
                text("SELECT set_config('app.current_patient_id', :pid, true)"),
                {"pid": str(bob)},
            )
            insert = text(
                "INSERT INTO research_consent_scopes (consent_id, patient_id, scope) "
                "VALUES (:cid, :pid, 'diet')"
            )
            with pytest.raises(ProgrammingError, match="row-level security"):
                await conn.execute(insert, {"cid": consent_id, "pid": str(alice)})


async def test_database_constraint_names_match_the_models(session) -> None:
    """Names are how a later migration finds a constraint to change.

    Migrations 0002-0005 once produced doubled names (``ck_x_ck_x_...``) that no
    later migration could drop by the name the model gives. This compares the
    database with the models, so that cannot recur unnoticed.
    """
    from sqlalchemy import CheckConstraint

    from eoehelp_api.db.base import Base

    def conventional(table: str, name: str) -> str:
        # The metadata may already have applied the convention to the name.
        prefix = f"ck_{table}_"
        return name if name.startswith(prefix) else prefix + name

    expected = {
        (table.name, conventional(table.name, str(constraint.name)))
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name
    }
    actual = set(
        (
            await session.execute(
                text(
                    "SELECT c.relname, k.conname FROM pg_constraint k "
                    "JOIN pg_class c ON c.oid = k.conrelid "
                    "WHERE k.contype = 'c' AND k.connamespace = 'public'::regnamespace "
                    "AND c.relname <> 'alembic_version'"
                )
            )
        ).all()
    )
    assert actual == expected
