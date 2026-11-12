#!/bin/sh
set -eu

: "${API_DB_PASSWORD:?API_DB_PASSWORD is required}"

# Deliberately invoked by ./dev provision for a named Compose project; never by API startup.
psql -h "${DB_HOST:-db}" -U customer_insights -d customer_insights -v ON_ERROR_STOP=1 -v api_password="$API_DB_PASSWORD" <<'SQL'
BEGIN;
DO $$
BEGIN
  IF current_database() <> 'customer_insights'
     OR current_user <> 'customer_insights'
     OR NOT EXISTS (
       SELECT 1 FROM pg_database d JOIN pg_roles r ON r.oid=d.datdba
       WHERE d.datname=current_database() AND r.rolname='customer_insights'
     )
     OR NOT EXISTS (
       SELECT 1 FROM pg_namespace n JOIN pg_roles r ON r.oid=n.nspowner
       WHERE n.nspname='public' AND r.rolname IN ('customer_insights','pg_database_owner')
     )
     OR EXISTS (
       SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
       WHERE n.nspname='public' AND c.relkind IN ('r','S')
         AND c.relowner <> (SELECT oid FROM pg_roles WHERE rolname='customer_insights')
     )
     OR to_regclass('public.dataset_instance') IS NULL
     OR to_regclass('public.spring_session') IS NULL THEN
    RAISE EXCEPTION 'Provisioning requires the dedicated customer_insights database and owned public schema';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname = 'customer_insights_api'
      AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  ) OR EXISTS (
    SELECT 1 FROM pg_auth_members m
    JOIN pg_roles r ON r.oid = m.member
    WHERE r.rolname = 'customer_insights_api'
  ) OR EXISTS (
    SELECT 1 FROM pg_shdepend d
    JOIN pg_roles r ON r.oid = d.refobjid
    WHERE r.rolname = 'customer_insights_api'
      AND d.refclassid = 'pg_authid'::regclass AND d.deptype = 'o'
  ) THEN
    RAISE EXCEPTION 'Existing API role has elevated attributes, memberships or object ownership';
  END IF;
END $$;
SELECT 'CREATE ROLE customer_insights_api LOGIN NOINHERIT PASSWORD ' || quote_literal(:'api_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'customer_insights_api') \gexec
SELECT 'ALTER ROLE customer_insights_api LOGIN NOINHERIT PASSWORD ' || quote_literal(:'api_password') \gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM customer_insights_api;
REVOKE CREATE, TEMPORARY ON DATABASE customer_insights FROM PUBLIC;
REVOKE CREATE, TEMPORARY ON DATABASE customer_insights FROM customer_insights_api;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM customer_insights_api;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM customer_insights_api;
ALTER DEFAULT PRIVILEGES FOR ROLE customer_insights IN SCHEMA public
  REVOKE ALL ON TABLES FROM customer_insights_api;
ALTER DEFAULT PRIVILEGES FOR ROLE customer_insights IN SCHEMA public
  REVOKE ALL ON SEQUENCES FROM customer_insights_api;
GRANT CONNECT ON DATABASE customer_insights TO customer_insights_api;
GRANT USAGE ON SCHEMA public TO customer_insights_api;
GRANT SELECT ON customers, accounts, categories, merchants, dataset_instance,
  authorizations, posted_entries, transfer_groups TO customer_insights_api;
GRANT SELECT ON credentials TO customer_insights_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON login_attempts, spring_session,
  spring_session_attributes TO customer_insights_api;
DO $$
DECLARE financial_table text;
BEGIN
  FOREACH financial_table IN ARRAY ARRAY['customers','accounts','categories','merchants',
    'dataset_instance','authorizations','posted_entries','transfer_groups','source_events','credentials'] LOOP
    IF has_table_privilege('customer_insights_api', financial_table, 'INSERT')
       OR has_table_privilege('customer_insights_api', financial_table, 'UPDATE')
       OR has_table_privilege('customer_insights_api', financial_table, 'DELETE')
       OR has_table_privilege('customer_insights_api', financial_table, 'TRUNCATE')
       OR has_table_privilege('customer_insights_api', financial_table, 'REFERENCES')
       OR has_table_privilege('customer_insights_api', financial_table, 'TRIGGER') THEN
      RAISE EXCEPTION 'API role retains financial write privileges on %', financial_table;
    END IF;
  END LOOP;
END $$;
COMMIT;
SQL
