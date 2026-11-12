#!/bin/sh
set -eu
: "${SIMULATOR_DB_PASSWORD:?SIMULATOR_DB_PASSWORD is required}"
: "${SIMULATOR_APPROVED_DATASET_ID:?Approved dataset ID is required}"
: "${SIMULATOR_APPROVED_SEED_HASH:?Approved seed hash is required}"
: "${SIMULATOR_APPROVED_EPOCH:=}"
psql -X -h db -U customer_insights -d customer_insights -v ON_ERROR_STOP=1 \
  -v simulator_password="$SIMULATOR_DB_PASSWORD" \
  -v approved_dataset_id="$SIMULATOR_APPROVED_DATASET_ID" \
  -v approved_seed_hash="$SIMULATOR_APPROVED_SEED_HASH" \
  -v approved_epoch="$SIMULATOR_APPROVED_EPOCH" <<'SQL'
BEGIN;
SELECT set_config('csi.approved_dataset_id', :'approved_dataset_id', true),
       set_config('csi.approved_seed_hash', :'approved_seed_hash', true),
       set_config('csi.approved_epoch', :'approved_epoch', true);
DO $$
BEGIN
  IF current_database()<>'customer_insights' OR current_user<>'customer_insights'
     OR to_regprocedure('public.simulate_transaction(text,text,jsonb)') IS NULL
     OR EXISTS (
       SELECT 1 FROM pg_roles WHERE rolname='customer_insights_simulator'
         AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
     ) OR EXISTS (
       SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
       WHERE r.rolname='customer_insights_simulator'
     ) OR EXISTS (
       SELECT 1 FROM pg_shdepend d JOIN pg_roles r ON r.oid=d.refobjid
       WHERE r.rolname='customer_insights_simulator'
         AND d.refclassid='pg_authid'::regclass AND d.deptype='o'
     ) THEN
    RAISE EXCEPTION 'Simulator provisioning requires the approved database and unprivileged role';
  END IF;
  PERFORM 1 FROM dataset_instance d
  WHERE d.singleton=true AND d.dataset_id=current_setting('csi.approved_dataset_id')
    AND d.seed_content_hash=current_setting('csi.approved_seed_hash')
    AND (current_setting('csi.approved_epoch')=''
      OR d.instance_epoch::text=current_setting('csi.approved_epoch'))
  FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Actual dataset does not match the trusted approval identity';
  END IF;
  INSERT INTO simulator_approval(singleton,dataset_id,seed_content_hash,instance_epoch)
    SELECT singleton,dataset_id,seed_content_hash,instance_epoch FROM dataset_instance
    WHERE singleton=true ON CONFLICT DO NOTHING;
  IF NOT EXISTS (
    SELECT 1 FROM simulator_approval s JOIN dataset_instance d ON d.singleton=s.singleton
    WHERE s.singleton=true AND s.dataset_id=d.dataset_id
      AND s.seed_content_hash=d.seed_content_hash AND s.instance_epoch=d.instance_epoch
  ) THEN
    RAISE EXCEPTION 'Existing simulator approval belongs to another dataset instance';
  END IF;
END $$;
SELECT 'CREATE ROLE customer_insights_simulator LOGIN NOINHERIT PASSWORD ' || quote_literal(:'simulator_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='customer_insights_simulator') \gexec
SELECT 'ALTER ROLE customer_insights_simulator LOGIN NOINHERIT PASSWORD ' || quote_literal(:'simulator_password') \gexec
REVOKE ALL ON SCHEMA public FROM customer_insights_simulator;
REVOKE CREATE, TEMPORARY ON DATABASE customer_insights FROM customer_insights_simulator;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM customer_insights_simulator;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM customer_insights_simulator;
GRANT CONNECT ON DATABASE customer_insights TO customer_insights_simulator;
GRANT USAGE ON SCHEMA public TO customer_insights_simulator;
GRANT EXECUTE ON FUNCTION simulate_transaction(text,text,jsonb) TO customer_insights_simulator;
DO $$
DECLARE object_name text;
BEGIN
  FOREACH object_name IN ARRAY ARRAY['customers','accounts','credentials','spring_session',
    'dataset_instance','simulator_approval','authorizations','posted_entries','source_events','simulator_events'] LOOP
    IF has_table_privilege('customer_insights_simulator',object_name,'SELECT')
       OR has_table_privilege('customer_insights_simulator',object_name,'INSERT')
       OR has_table_privilege('customer_insights_simulator',object_name,'UPDATE')
       OR has_table_privilege('customer_insights_simulator',object_name,'DELETE')
       OR has_table_privilege('customer_insights_simulator',object_name,'TRUNCATE') THEN
      RAISE EXCEPTION 'Simulator role has direct table access on %', object_name;
    END IF;
  END LOOP;
END $$;
COMMIT;
SQL
