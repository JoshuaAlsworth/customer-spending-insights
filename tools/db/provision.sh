#!/bin/sh
set -eu

: "${API_DB_PASSWORD:?API_DB_PASSWORD is required}"

# Deliberately invoked by ./dev provision for a named Compose project; never by API startup.
psql -h db -U customer_insights -d customer_insights -v ON_ERROR_STOP=1 -v api_password="$API_DB_PASSWORD" <<'SQL'
BEGIN;
DO $$
BEGIN
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
GRANT CONNECT ON DATABASE customer_insights TO customer_insights_api;
GRANT USAGE ON SCHEMA public TO customer_insights_api;
COMMIT;
SQL
