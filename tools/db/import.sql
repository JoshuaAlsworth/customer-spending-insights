-- Operator-only import, executed under the migration owner; every accepted row commits together.
BEGIN;
SELECT pg_advisory_xact_lock(684283891);
SELECT set_config('csi.import_dataset_id', :'dataset_id', true), set_config('csi.import_seed_hash', :'seed_hash', true);
DO $$ BEGIN
  IF current_database() <> 'customer_insights' OR current_user <> 'customer_insights' THEN
    RAISE EXCEPTION 'Wrong import database or role';
  END IF;
END $$;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM dataset_instance) OR EXISTS (SELECT 1 FROM customers)
     OR EXISTS (SELECT 1 FROM accounts) OR EXISTS (SELECT 1 FROM posted_entries)
     OR EXISTS (SELECT 1 FROM authorizations) OR EXISTS (SELECT 1 FROM merchants) THEN
    RAISE EXCEPTION 'Import requires an empty database; approved replay uses the operator preflight';
  END IF;
END $$;
CREATE TEMP TABLE customers_stage (LIKE customers INCLUDING DEFAULTS);
CREATE TEMP TABLE accounts_stage (LIKE accounts INCLUDING DEFAULTS);
CREATE TEMP TABLE credentials_stage (LIKE credentials INCLUDING DEFAULTS);
CREATE TEMP TABLE merchants_stage (LIKE merchants INCLUDING DEFAULTS);
CREATE TEMP TABLE categories_stage (LIKE categories INCLUDING DEFAULTS);
CREATE TEMP TABLE authorizations_stage (LIKE authorizations INCLUDING DEFAULTS);
CREATE TEMP TABLE posted_stage (LIKE posted_entries INCLUDING DEFAULTS);
COPY customers_stage(id,display_name,login_id,status,primary_persona,modifiers,customer_revision) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '\N');
COPY accounts_stage(id,customer_id,account_kind,alias,masked_suffix,currency,opened_on,status) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '\N');
COPY credentials_stage(customer_id,password_hash) FROM STDIN WITH (FORMAT csv, HEADER true);
COPY merchants_stage(id,display_name,mcc,default_category_code,descriptor_variant) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '\N');
COPY categories_stage(code,display_name,display_order,policy_version) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '\N');
COPY authorizations_stage(id,account_id,authorized_amount_minor,occurred_at,lifecycle_status,merchant_id,raw_description,source_event_id) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '\N');
COPY posted_stage(id,account_id,source_event_id,amount_minor,currency,transaction_type,effect_group,posted_at,occurred_at,raw_description,merchant_id,category_code,classification_provenance,original_entry_id,authorization_id,transfer_group_id) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '\N');
CREATE INDEX accounts_stage_id ON accounts_stage(id);
CREATE INDEX posted_stage_account ON posted_stage(account_id);
CREATE INDEX posted_stage_authorization ON posted_stage(authorization_id);
ANALYZE accounts_stage;
ANALYZE posted_stage;
DO $$ BEGIN
  IF EXISTS ((SELECT code,display_name,display_order,policy_version FROM categories_stage EXCEPT SELECT code,display_name,display_order,policy_version FROM categories)
    UNION ALL (SELECT code,display_name,display_order,policy_version FROM categories EXCEPT SELECT code,display_name,display_order,policy_version FROM categories_stage))
    OR (SELECT count(*) FROM categories_stage)<>14 THEN
    RAISE EXCEPTION 'Category policy differs from migrated catalogue';
  END IF;
  IF (SELECT count(*) FROM credentials_stage)<>(SELECT count(*) FROM customers_stage)
     OR EXISTS (SELECT 1 FROM credentials_stage cr LEFT JOIN customers_stage c ON c.id=cr.customer_id WHERE c.id IS NULL) THEN
    RAISE EXCEPTION 'Incomplete runtime credentials';
  END IF;
  IF EXISTS (SELECT source_event_id FROM (SELECT source_event_id FROM authorizations_stage UNION ALL SELECT source_event_id FROM posted_stage) s GROUP BY source_event_id HAVING count(*)>1) THEN
    RAISE EXCEPTION 'Duplicate source event identity';
  END IF;
  IF EXISTS (SELECT 1 FROM posted_stage p WHERE p.transaction_type IN ('OWN_TRANSFER_REVERSAL_OUT','OWN_TRANSFER_REVERSAL_IN')) THEN
    RAISE EXCEPTION 'Fixture-only transfer reversal is not allowed in generated import';
  END IF;
  IF EXISTS (
    SELECT 1 FROM posted_stage p LEFT JOIN merchants_stage m ON m.id=p.merchant_id
    LEFT JOIN posted_stage original ON original.id=p.original_entry_id
    WHERE
      (p.transaction_type IN ('CARD_PURCHASE','DEBIT_ORDER') AND (
        p.classification_provenance NOT IN ('OBLIGATION','MERCHANT','MCC','UNCATEGORIZED')
        OR (p.classification_provenance='MERCHANT' AND (m.default_category_code IS NULL OR m.default_category_code<>p.category_code))
        OR (p.classification_provenance='MCC' AND (m.id IS NULL OR m.default_category_code IS NOT NULL OR m.mcc IS DISTINCT FROM '5411' OR p.category_code<>'GROCERIES'))
        OR (p.classification_provenance='UNCATEGORIZED' AND (p.category_code<>'UNCATEGORIZED' OR m.default_category_code IS NOT NULL OR m.mcc='5411'))
      ))
      OR (p.transaction_type='BANK_FEE' AND (p.category_code<>'BANK_FEES' OR p.classification_provenance<>'TYPE_RULE'))
      OR (p.transaction_type='CASH_WITHDRAWAL' AND (p.category_code<>'CASH_WITHDRAWALS' OR p.classification_provenance<>'TYPE_RULE'))
      OR (p.transaction_type='EXTERNAL_PAYMENT' AND (p.category_code<>'MONEY_SENT' OR p.classification_provenance<>'TYPE_RULE'))
      OR (p.transaction_type IN ('SPEND_REFUND','SPEND_REVERSAL') AND (
        original.id IS NULL OR p.category_code IS DISTINCT FROM original.category_code
        OR p.classification_provenance IS DISTINCT FROM original.classification_provenance
      ))
  ) THEN
    RAISE EXCEPTION 'Invalid classification policy';
  END IF;
  IF EXISTS (SELECT 1 FROM posted_stage p JOIN accounts_stage a ON a.id=p.account_id WHERE (p.posted_at AT TIME ZONE 'Africa/Johannesburg')::date < a.opened_on) THEN
    RAISE EXCEPTION 'Posting predates opening';
  END IF;
  IF EXISTS (SELECT 1 FROM authorizations_stage a LEFT JOIN posted_stage p ON p.authorization_id=a.id
    GROUP BY a.id,a.lifecycle_status HAVING count(p.id) <> CASE WHEN a.lifecycle_status='POSTED' THEN 1 ELSE 0 END) THEN
    RAISE EXCEPTION 'Invalid authorization lifecycle';
  END IF;
END $$;
INSERT INTO customers(id,display_name,login_id,status,primary_persona,modifiers,customer_revision)
  SELECT id,display_name,login_id,status,primary_persona,modifiers,customer_revision FROM customers_stage ORDER BY id;
INSERT INTO credentials(customer_id,password_hash) SELECT customer_id,password_hash FROM credentials_stage ORDER BY customer_id;
INSERT INTO accounts(id,customer_id,account_kind,alias,masked_suffix,currency,opened_on,status)
  SELECT id,customer_id,account_kind,alias,masked_suffix,currency,opened_on,status FROM accounts_stage ORDER BY id;
INSERT INTO merchants(id,display_name,mcc,default_category_code,descriptor_variant)
  SELECT id,display_name,mcc,default_category_code,descriptor_variant FROM merchants_stage ORDER BY id;
INSERT INTO authorizations(id,account_id,authorized_amount_minor,occurred_at,lifecycle_status,merchant_id,raw_description,source_event_id)
  SELECT id,account_id,authorized_amount_minor,occurred_at,lifecycle_status,merchant_id,raw_description,source_event_id FROM authorizations_stage ORDER BY id;
INSERT INTO transfer_groups(id,customer_id,kind)
  SELECT DISTINCT p.transfer_group_id,a.customer_id,'ORIGINAL' FROM posted_stage p JOIN accounts_stage a ON a.id=p.account_id
  WHERE p.transfer_group_id IS NOT NULL;
INSERT INTO posted_entries(id,account_id,source_event_id,amount_minor,currency,transaction_type,effect_group,posted_at,occurred_at,raw_description,merchant_id,category_code,classification_provenance,original_entry_id,authorization_id,transfer_group_id)
  SELECT id,account_id,source_event_id,amount_minor,currency,transaction_type,effect_group,posted_at,occurred_at,raw_description,merchant_id,category_code,classification_provenance,original_entry_id,authorization_id,transfer_group_id
  FROM posted_stage ORDER BY id;
INSERT INTO dataset_instance(singleton,dataset_id,instance_epoch,seed_content_hash,reference_date,generator_version)
  VALUES(true,:'dataset_id',gen_random_uuid(),:'seed_hash','2026-10-31',:'generator_version');
ANALYZE customers;
ANALYZE accounts;
ANALYZE posted_entries;
ANALYZE authorizations;
COMMIT;
