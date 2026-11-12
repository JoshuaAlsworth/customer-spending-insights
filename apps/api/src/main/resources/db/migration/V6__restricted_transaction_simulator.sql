CREATE TABLE simulator_events (
  event_id text PRIMARY KEY,
  operation text NOT NULL CHECK (operation IN ('pending','post','cancel')),
  payload jsonb NOT NULL,
  payload_fingerprint text NOT NULL,
  result jsonb
);

CREATE TABLE simulator_approval (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  dataset_id text NOT NULL,
  seed_content_hash text NOT NULL,
  instance_epoch uuid NOT NULL
);

CREATE FUNCTION simulate_transaction(operation_name text, event_key text, request jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
  event_name text;
  existing simulator_events%ROWTYPE;
  dataset dataset_instance%ROWTYPE;
  account accounts%ROWTYPE;
  auth authorizations%ROWTYPE;
  merchant merchants%ROWTYPE;
  amount bigint;
  event_time timestamptz;
  posting_time timestamptz;
  category text;
  provenance text;
  outcome jsonb;
BEGIN
  IF current_database() <> 'customer_insights' OR current_user <> 'customer_insights'
     OR session_user <> 'customer_insights_simulator' THEN
    RAISE EXCEPTION 'Simulator target or identity is invalid';
  END IF;
  IF event_key IS NULL OR event_key !~ '^[A-Za-z0-9_-]{1,80}$'
     OR operation_name NOT IN ('pending','post','cancel') OR jsonb_typeof(request) <> 'object' THEN
    RAISE EXCEPTION 'Invalid simulator request';
  END IF;
  IF (operation_name='pending' AND (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(request) key)
        <> ARRAY['account_id','amount_minor','description','merchant_id','occurred_at'])
     OR (operation_name='post' AND (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(request) key)
        <> ARRAY['amount_minor','authorization_id','posted_at'])
     OR (operation_name='cancel' AND (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(request) key)
        <> ARRAY['authorization_id','cancelled_at']) THEN
    RAISE EXCEPTION 'Invalid simulator payload';
  END IF;
  event_name := 'sim:event:' || event_key;
  SELECT d.* INTO dataset FROM dataset_instance d
    JOIN simulator_approval s ON s.singleton=d.singleton
      AND s.dataset_id=d.dataset_id AND s.seed_content_hash=d.seed_content_hash
      AND s.instance_epoch=d.instance_epoch
    WHERE d.singleton=true FOR SHARE OF d,s;
  IF NOT FOUND THEN RAISE EXCEPTION 'Simulator dataset is not approved'; END IF;
  INSERT INTO simulator_events(event_id,operation,payload,payload_fingerprint)
    VALUES(event_name,operation_name,request,encode(sha256(convert_to(request::text,'UTF8')),'hex'))
    ON CONFLICT DO NOTHING;
  SELECT * INTO STRICT existing FROM simulator_events WHERE event_id=event_name FOR UPDATE;
  IF existing.operation <> operation_name OR existing.payload <> request THEN
    RAISE EXCEPTION 'Idempotency key conflicts with an existing request';
  END IF;
  IF existing.result IS NOT NULL THEN
    RETURN existing.result || jsonb_build_object('replayed',true);
  END IF;

  IF operation_name='pending' THEN
    IF jsonb_typeof(request->'amount_minor') <> 'number'
       OR request->>'amount_minor' !~ '^[0-9]{1,18}$'
       OR coalesce(length(request->>'description'),0) NOT BETWEEN 1 AND 200
       OR request->>'account_id' !~ '^[A-Za-z0-9_-]{1,80}$'
       OR request->>'merchant_id' !~ '^[A-Za-z0-9_-]{1,80}$'
       OR request->>'occurred_at' !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?\+02:00$' THEN
      RAISE EXCEPTION 'Invalid pending fields';
    END IF;
    amount := (request->>'amount_minor')::bigint;
    event_time := (request->>'occurred_at')::timestamptz;
    SELECT a.* INTO STRICT account FROM accounts a JOIN customers c ON c.id=a.customer_id
      WHERE a.id=request->>'account_id' AND a.status='OPEN' AND c.status='ACTIVE';
    SELECT * INTO STRICT merchant FROM merchants WHERE id=request->>'merchant_id';
    IF amount <= 0 OR (event_time AT TIME ZONE 'Africa/Johannesburg')::date < account.opened_on THEN
      RAISE EXCEPTION 'Ineligible pending amount or account date';
    END IF;
    PERFORM 1 FROM source_events WHERE source_event_id='sim:auth:' || event_key;
    IF FOUND THEN RAISE EXCEPTION 'Source event already exists'; END IF;
  ELSE
    IF request->>'authorization_id' !~ '^[A-Za-z0-9_:-]{1,120}$' THEN
      RAISE EXCEPTION 'Invalid authorization ID';
    END IF;
    IF operation_name='post' THEN
      IF jsonb_typeof(request->'amount_minor') <> 'number'
         OR request->>'amount_minor' !~ '^[0-9]{1,18}$'
         OR request->>'posted_at' !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?\+02:00$' THEN
        RAISE EXCEPTION 'Invalid posting fields';
      END IF;
      amount := (request->>'amount_minor')::bigint;
      posting_time := (request->>'posted_at')::timestamptz;
      IF amount <= 0 THEN RAISE EXCEPTION 'Final amount must be positive'; END IF;
    END IF;
    IF operation_name='cancel' THEN
      IF request->>'cancelled_at' !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?\+02:00$' THEN
        RAISE EXCEPTION 'Invalid cancellation time';
      END IF;
      event_time := (request->>'cancelled_at')::timestamptz;
    END IF;
    SELECT * INTO STRICT auth FROM authorizations WHERE id=request->>'authorization_id' FOR UPDATE;
    SELECT a.* INTO STRICT account FROM accounts a JOIN customers c ON c.id=a.customer_id
      WHERE a.id=auth.account_id AND a.status='OPEN' AND c.status='ACTIVE';
    IF auth.lifecycle_status <> 'PENDING' THEN
      RAISE EXCEPTION 'Authorization is no longer pending';
    END IF;
    IF operation_name='post' AND posting_time < auth.occurred_at THEN
      RAISE EXCEPTION 'Posting precedes authorization';
    END IF;
    IF operation_name='cancel' AND event_time < auth.occurred_at THEN
      RAISE EXCEPTION 'Cancellation precedes authorization';
    END IF;
  END IF;

  IF operation_name='pending' THEN
    event_time := (request->>'occurred_at')::timestamptz;
  ELSIF operation_name='post' THEN
    event_time := posting_time;
  END IF;
  IF (event_time AT TIME ZONE 'Africa/Johannesburg')::date > dataset.reference_date
     OR (event_time AT TIME ZONE 'Africa/Johannesburg')::date <
       (dataset.reference_date - CASE WHEN dataset.dataset_id LIKE 'synthetic-demo-%' THEN interval '18 months' ELSE interval '24 months' END)::date THEN
    RAISE EXCEPTION 'Event is outside the supported dataset window';
  END IF;

  IF operation_name='pending' THEN
    INSERT INTO authorizations(id,account_id,authorized_amount_minor,occurred_at,lifecycle_status,
      merchant_id,raw_description,source_event_id)
    VALUES('sim_auth_' || event_key,account.id,amount,event_time,'PENDING',merchant.id,
      request->>'description','sim:auth:' || event_key);
    outcome := jsonb_build_object('operation',operation_name,'authorization_id','sim_auth_' || event_key,
      'status','PENDING','customer_id',account.customer_id);
  ELSIF operation_name='post' THEN
    UPDATE authorizations SET lifecycle_status='POSTED' WHERE id=auth.id;
    SELECT * INTO merchant FROM merchants WHERE id=auth.merchant_id;
    IF merchant.default_category_code IS NOT NULL THEN
      category := merchant.default_category_code; provenance := 'MERCHANT';
    ELSIF merchant.mcc='5411' THEN
      category := 'GROCERIES'; provenance := 'MCC';
    ELSE
      category := 'UNCATEGORIZED'; provenance := 'UNCATEGORIZED';
    END IF;
    INSERT INTO posted_entries(id,account_id,source_event_id,amount_minor,currency,
      transaction_type,effect_group,posted_at,occurred_at,raw_description,merchant_id,
      category_code,classification_provenance,authorization_id)
    VALUES('sim_entry_' || event_key,account.id,'sim:entry:' || event_key,-amount,'ZAR',
      'CARD_PURCHASE','SPEND',posting_time,auth.occurred_at,auth.raw_description,auth.merchant_id,
      category,provenance,auth.id);
    outcome := jsonb_build_object('operation',operation_name,'authorization_id',auth.id,
      'entry_id','sim_entry_' || event_key,'status','POSTED','customer_id',account.customer_id,
      'amount_minor',-amount);
  ELSE
    UPDATE authorizations SET lifecycle_status='CANCELLED' WHERE id=auth.id;
    outcome := jsonb_build_object('operation',operation_name,'authorization_id',auth.id,
      'status','CANCELLED','customer_id',account.customer_id,
      'cancelled_at',request->>'cancelled_at');
  END IF;
  UPDATE customers SET customer_revision=customer_revision+1 WHERE id=account.customer_id;
  UPDATE simulator_events SET result=outcome WHERE event_id=event_name;
  RETURN outcome || jsonb_build_object('replayed',false);
END $$;

REVOKE ALL ON FUNCTION simulate_transaction(text,text,jsonb) FROM PUBLIC;

-- Financial triggers must retain their existing checks when called by the function-only role.
ALTER FUNCTION reserve_source_event() SECURITY DEFINER SET search_path = pg_catalog, public;
ALTER FUNCTION validate_authorization() SECURITY DEFINER SET search_path = pg_catalog, public;
ALTER FUNCTION validate_posted_entry() SECURITY DEFINER SET search_path = pg_catalog, public;
ALTER FUNCTION validate_authorization_state() SECURITY DEFINER SET search_path = pg_catalog, public;
