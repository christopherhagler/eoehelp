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
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_runtime;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_runtime;
