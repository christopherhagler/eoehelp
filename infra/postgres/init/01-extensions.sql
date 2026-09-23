-- Runs once on first container start, before Alembic.
-- gen_random_uuid() (pgcrypto) backs every primary key; citext backs case-insensitive
-- email uniqueness. Alembic migrations assume both already exist.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

-- The application connects as a role that owns no tables, so row-level security
-- policies actually bind to it. Table owners and superusers bypass RLS by default,
-- which would silently disable the isolation backstop.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
        CREATE ROLE app_runtime LOGIN PASSWORD 'app_runtime_local_only';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE eoehelp TO app_runtime;
GRANT USAGE ON SCHEMA public TO app_runtime;

-- Deliberately no ALTER DEFAULT PRIVILEGES. Granting DML on every future table
-- made each migration's considered grant cosmetic: `GRANT SELECT ON
-- ingredient_catalog` added nothing when the role already held INSERT, UPDATE
-- and DELETE on it by default, so the application could rewrite the DSQ
-- definition every symptom score is computed against, and could move
-- alembic_version. It also hid itself, because default privileges are per
-- database: the test database is created with CREATE DATABASE, inherits no
-- default ACL, and so passed a read-only assertion that was false in the
-- database the application actually runs against.
--
-- Every migration grants explicitly, per table, so nothing depends on a
-- default. A new table with no grant fails loudly the first time it is read,
-- which is the right way for that mistake to surface.

-- Bounds on the application role, so one stuck request cannot stall a table.
-- A session left idle inside a transaction holds its locks indefinitely: the
-- next migration's ACCESS EXCLUSIVE request queues behind it, and then every
-- read and write of that table queues behind the migration. That turns one
-- leaked connection into a table-wide outage during a deploy. These are role
-- settings rather than server settings so migrations, which run as the owner,
-- keep the time they need.
ALTER ROLE app_runtime SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE app_runtime SET statement_timeout = '30s';
ALTER ROLE app_runtime SET lock_timeout = '5s';
