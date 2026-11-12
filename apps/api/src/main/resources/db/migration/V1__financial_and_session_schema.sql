CREATE TABLE customers (
  id text PRIMARY KEY, display_name text NOT NULL, login_id text NOT NULL UNIQUE,
  status text NOT NULL CHECK (status IN ('ACTIVE','DISABLED')),
  primary_persona text NOT NULL CHECK (primary_persona IN ('STUDENT','SALARIED','FREELANCER')),
  modifiers text[] NOT NULL DEFAULT '{}', customer_revision bigint NOT NULL DEFAULT 0 CHECK (customer_revision >= 0)
);
CREATE TABLE credentials (
  customer_id text PRIMARY KEY REFERENCES customers(id), password_hash text NOT NULL CHECK (password_hash LIKE '$argon2id$%')
);
CREATE TABLE login_attempts (
  login_key text PRIMARY KEY, attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  window_started_at timestamptz NOT NULL, blocked_until timestamptz
);
CREATE TABLE accounts (
  id text PRIMARY KEY, customer_id text NOT NULL REFERENCES customers(id),
  account_kind text NOT NULL CHECK (account_kind IN ('EVERYDAY','SAVINGS','SECONDARY_TRANSACTIONAL')),
  alias text NOT NULL, masked_suffix char(4) NOT NULL CHECK (masked_suffix ~ '^[0-9]{4}$'),
  currency char(3) NOT NULL DEFAULT 'ZAR' CHECK (currency = 'ZAR'),
  opened_on date NOT NULL, status text NOT NULL CHECK (status IN ('OPEN','CLOSED')),
  UNIQUE (id, customer_id)
);
CREATE TABLE categories (
  code text PRIMARY KEY, display_name text NOT NULL, display_order smallint NOT NULL UNIQUE,
  policy_version text NOT NULL CHECK (policy_version = 'CSI-CAT-1.0')
);
INSERT INTO categories(code,display_name,display_order,policy_version) VALUES
('HOUSING_UTILITIES','Housing & utilities',1,'CSI-CAT-1.0'),('GROCERIES','Groceries',2,'CSI-CAT-1.0'),
('TRANSPORT_FUEL','Transport & fuel',3,'CSI-CAT-1.0'),('FOOD_DINING','Food & dining',4,'CSI-CAT-1.0'),
('SHOPPING','Shopping',5,'CSI-CAT-1.0'),('HEALTH','Health',6,'CSI-CAT-1.0'),
('SUBSCRIPTIONS_COMMS','Subscriptions & communications',7,'CSI-CAT-1.0'),
('INSURANCE_FIN_SERVICES','Insurance & financial services',8,'CSI-CAT-1.0'),
('EDUCATION','Education',9,'CSI-CAT-1.0'),('ENTERTAINMENT_LEISURE','Entertainment & leisure',10,'CSI-CAT-1.0'),
('CASH_WITHDRAWALS','Cash withdrawals',11,'CSI-CAT-1.0'),('MONEY_SENT','Money sent',12,'CSI-CAT-1.0'),
('BANK_FEES','Bank fees',13,'CSI-CAT-1.0'),('UNCATEGORIZED','Uncategorized',14,'CSI-CAT-1.0');
CREATE TABLE merchants (
  id text PRIMARY KEY, display_name text NOT NULL, mcc char(4),
  default_category_code text REFERENCES categories(code), descriptor_variant text,
  CHECK (mcc IS NULL OR mcc ~ '^[0-9]{4}$')
);
CREATE TABLE dataset_instance (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton), dataset_id text NOT NULL,
  instance_epoch uuid NOT NULL, seed_content_hash text NOT NULL,
  reference_date date NOT NULL, generator_version text NOT NULL,
  accepted_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE transfer_groups (
  id text PRIMARY KEY, customer_id text NOT NULL REFERENCES customers(id),
  kind text NOT NULL CHECK (kind IN ('ORIGINAL','REVERSAL'))
);
CREATE TABLE authorizations (
  id text PRIMARY KEY, account_id text NOT NULL REFERENCES accounts(id),
  authorized_amount_minor bigint NOT NULL CHECK (authorized_amount_minor > 0),
  occurred_at timestamptz NOT NULL, lifecycle_status text NOT NULL CHECK (lifecycle_status IN ('PENDING','POSTED','CANCELLED')),
  merchant_id text REFERENCES merchants(id), raw_description text NOT NULL CHECK (length(raw_description)>0),
  source_event_id text NOT NULL UNIQUE
);
CREATE TABLE posted_entries (
  id text PRIMARY KEY, account_id text NOT NULL REFERENCES accounts(id),
  source_event_id text NOT NULL UNIQUE, amount_minor bigint NOT NULL CHECK (amount_minor <> 0),
  currency char(3) NOT NULL CHECK (currency = 'ZAR'),
  transaction_type text NOT NULL CHECK (transaction_type IN (
    'SALARY_CREDIT','ALLOWANCE_CREDIT','EXTERNAL_RECEIPT','INTEREST_CREDIT',
    'CARD_PURCHASE','DEBIT_ORDER','EXTERNAL_PAYMENT','CASH_WITHDRAWAL','BANK_FEE',
    'SPEND_REFUND','SPEND_REVERSAL','INCOME_REVERSAL','OWN_TRANSFER_OUT','OWN_TRANSFER_IN',
    'OWN_TRANSFER_REVERSAL_OUT','OWN_TRANSFER_REVERSAL_IN')),
  effect_group text NOT NULL CHECK (effect_group IN ('INCOME','SPEND','INTERNAL')),
  posted_at timestamptz NOT NULL, occurred_at timestamptz NOT NULL,
  raw_description text NOT NULL CHECK (length(raw_description)>0),
  merchant_id text REFERENCES merchants(id), category_code text REFERENCES categories(code),
  classification_provenance text NOT NULL CHECK (classification_provenance IN
    ('TYPE_RULE','OBLIGATION','MERCHANT','MCC','UNCATEGORIZED','NOT_APPLICABLE')),
  original_entry_id text REFERENCES posted_entries(id),
  authorization_id text UNIQUE REFERENCES authorizations(id),
  transfer_group_id text REFERENCES transfer_groups(id),
  transaction_policy_version text NOT NULL DEFAULT 'CSI-TAX-1.0' CHECK (transaction_policy_version='CSI-TAX-1.0'),
  category_policy_version text NOT NULL DEFAULT 'CSI-CAT-1.0' CHECK (category_policy_version='CSI-CAT-1.0'),
  CHECK (posted_at >= occurred_at),
  CHECK ((effect_group='SPEND' AND category_code IS NOT NULL AND classification_provenance <> 'NOT_APPLICABLE') OR
         (effect_group<>'SPEND' AND category_code IS NULL AND classification_provenance='NOT_APPLICABLE')),
  CHECK ((transaction_type IN ('SALARY_CREDIT','ALLOWANCE_CREDIT','EXTERNAL_RECEIPT','INTEREST_CREDIT') AND amount_minor>0 AND effect_group='INCOME') OR
         (transaction_type='INCOME_REVERSAL' AND amount_minor<0 AND effect_group='INCOME') OR
         (transaction_type IN ('CARD_PURCHASE','DEBIT_ORDER','EXTERNAL_PAYMENT','CASH_WITHDRAWAL','BANK_FEE') AND amount_minor<0 AND effect_group='SPEND') OR
         (transaction_type IN ('SPEND_REFUND','SPEND_REVERSAL') AND amount_minor>0 AND effect_group='SPEND') OR
         (transaction_type IN ('OWN_TRANSFER_OUT','OWN_TRANSFER_REVERSAL_OUT') AND amount_minor<0 AND effect_group='INTERNAL') OR
         (transaction_type IN ('OWN_TRANSFER_IN','OWN_TRANSFER_REVERSAL_IN') AND amount_minor>0 AND effect_group='INTERNAL')),
  CHECK ((transaction_type IN ('SPEND_REFUND','SPEND_REVERSAL','INCOME_REVERSAL','OWN_TRANSFER_REVERSAL_OUT','OWN_TRANSFER_REVERSAL_IN')) = (original_entry_id IS NOT NULL)),
  CHECK ((effect_group='INTERNAL') = (transfer_group_id IS NOT NULL)),
  CHECK (authorization_id IS NULL OR transaction_type='CARD_PURCHASE'),
  CHECK (transaction_type <> 'BANK_FEE' OR category_code='BANK_FEES'),
  CHECK (transaction_type <> 'CASH_WITHDRAWAL' OR category_code='CASH_WITHDRAWALS'),
  CHECK (transaction_type <> 'EXTERNAL_PAYMENT' OR category_code='MONEY_SENT')
);
CREATE UNIQUE INDEX posted_entries_one_full_correction ON posted_entries(original_entry_id)
  WHERE transaction_type IN ('SPEND_REVERSAL','INCOME_REVERSAL');
CREATE INDEX posted_entries_scope ON posted_entries(account_id,posted_at);
CREATE INDEX posted_entries_transfer ON posted_entries(transfer_group_id);
CREATE INDEX accounts_owner ON accounts(customer_id);
CREATE TABLE source_events (source_event_id text PRIMARY KEY);
CREATE FUNCTION reserve_source_event() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO source_events VALUES (NEW.source_event_id);
  RETURN NEW;
END $$;
CREATE TRIGGER authorization_source BEFORE INSERT ON authorizations FOR EACH ROW EXECUTE FUNCTION reserve_source_event();
CREATE TRIGGER entry_source BEFORE INSERT ON posted_entries FOR EACH ROW EXECUTE FUNCTION reserve_source_event();
CREATE FUNCTION reject_posted_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'posted entries are immutable'; END $$;
CREATE TRIGGER posted_immutable BEFORE UPDATE OR DELETE ON posted_entries FOR EACH ROW EXECUTE FUNCTION reject_posted_mutation();

-- Exact Spring Session JDBC 4.1 PostgreSQL schema.
CREATE TABLE SPRING_SESSION (
  PRIMARY_ID CHAR(36) NOT NULL PRIMARY KEY, SESSION_ID CHAR(36) NOT NULL,
  CREATION_TIME BIGINT NOT NULL, LAST_ACCESS_TIME BIGINT NOT NULL,
  MAX_INACTIVE_INTERVAL INT NOT NULL, EXPIRY_TIME BIGINT NOT NULL,
  PRINCIPAL_NAME VARCHAR(100)
);
CREATE UNIQUE INDEX SPRING_SESSION_IX1 ON SPRING_SESSION (SESSION_ID);
CREATE INDEX SPRING_SESSION_IX2 ON SPRING_SESSION (EXPIRY_TIME);
CREATE INDEX SPRING_SESSION_IX3 ON SPRING_SESSION (PRINCIPAL_NAME);
CREATE TABLE SPRING_SESSION_ATTRIBUTES (
  SESSION_PRIMARY_ID CHAR(36) NOT NULL REFERENCES SPRING_SESSION(PRIMARY_ID) ON DELETE CASCADE,
  ATTRIBUTE_NAME VARCHAR(200) NOT NULL, ATTRIBUTE_BYTES BYTEA NOT NULL,
  PRIMARY KEY (SESSION_PRIMARY_ID, ATTRIBUTE_NAME)
);
