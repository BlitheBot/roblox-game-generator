-- One-time database bootstrap — run ONCE as the postgres superuser.
--
-- The application connects as a non-superuser role (default: studiobot) and
-- runs migrations automatically at every service start (see db/connection.py,
-- run_migrations). Those migrations CREATE INDEX and ALTER TABLE, both of
-- which require the connecting role to OWN the table. If the schema was first
-- created by some other role (e.g. the postgres superuser ran the CREATE TABLE
-- statements by hand), the app role does not own those tables and migrations
-- fail with:
--
--     InsufficientPrivilegeError: must be owner of table concept_queue
--
-- A non-owner cannot fix this itself (ALTER ... OWNER / REASSIGN OWNED both
-- require ownership), so this step must run as a superuser. It is idempotent:
-- re-running it is harmless.
--
-- Usage (the database name and role match DEPLOY.md / your DATABASE_URL):
--
--     sudo -u postgres psql -d roblox_studio \
--         -v app_role=studiobot -f scripts/setup_db.sql
--
-- On Windows / local dev:
--
--     psql -U postgres -d roblox_studio -v app_role=studiobot -f scripts/setup_db.sql
--
-- If you don't pass -v app_role=..., it defaults to studiobot.

\if :{?app_role}
\else
  \set app_role studiobot
\endif

\echo Granting ownership of database :"app_role"...

-- The role must already exist (DEPLOY.md step 4 creates it). Make it own the
-- database and the public schema so anything it creates from here on is owned
-- by it automatically.
ALTER DATABASE :"DBNAME" OWNER TO :"app_role";
ALTER SCHEMA public OWNER TO :"app_role";

-- Hand over every existing object in THIS database (tables, indexes, sequences,
-- etc.) that is currently owned by the superuser running this script. This is
-- the line that actually clears the "must be owner of table" error for tables
-- the superuser created by hand. REASSIGN OWNED only touches the current
-- database, never global/system objects.
REASSIGN OWNED BY CURRENT_USER TO :"app_role";

-- Make sure the app role can use the schema and that future objects created by
-- anyone in public are usable by it.
GRANT ALL ON SCHEMA public TO :"app_role";
GRANT ALL ON ALL TABLES IN SCHEMA public TO :"app_role";
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO :"app_role";

\echo Done. The app role now owns the schema; migrations will run cleanly.
