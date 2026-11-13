\set ON_ERROR_STOP on
BEGIN;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM dataset_instance WHERE dataset_id<>'spending-overview-isolated-fixture-v2') THEN
    RAISE EXCEPTION 'Refusing to seed a non-fixture dataset';
  END IF;
END $$;
SELECT NOT EXISTS (SELECT 1 FROM dataset_instance) AS apply_fixture \gset
\if :apply_fixture
INSERT INTO customers(id,display_name,login_id,status,primary_persona) VALUES
('fixture-f01','Fixture One','fixture-f01','ACTIVE','SALARIED'),
('fixture-f03','Fixture Three','fixture-f03','ACTIVE','SALARIED'),
('fixture-f09','Fixture Nine','fixture-f09','ACTIVE','SALARIED'),
('fixture-empty','Fixture Empty','fixture-empty','ACTIVE','STUDENT'),
('fixture-f04','Fixture Four','fixture-f04','ACTIVE','SALARIED'),
('fixture-large','Fixture Large','fixture-large','ACTIVE','SALARIED'),
('fixture-f14','Fixture Fourteen','fixture-f14','ACTIVE','SALARIED'),
('fixture-f15','Fixture Fifteen','fixture-f15','ACTIVE','SALARIED'),
('fixture-f16','Fixture Sixteen','fixture-f16','ACTIVE','SALARIED'),
('fixture-f17','Fixture Seventeen','fixture-f17','ACTIVE','SALARIED'),
('fixture-closed','Fixture Closed','fixture-closed','ACTIVE','SALARIED');
INSERT INTO credentials(customer_id,password_hash)
SELECT id,'$argon2id$v=19$m=65536,t=3,p=1$JQQTwIGsyFPKpJteh3HFaw$eCQQDC+GGMWU2xsBWvYHMm/rfOhCthNFKMGPy062J04'
FROM customers;
INSERT INTO accounts(id,customer_id,account_kind,alias,masked_suffix,currency,opened_on,status,balance_anchor_at,opening_balance_minor) VALUES
('f01-everyday','fixture-f01','EVERYDAY','Everyday','0042','ZAR','2025-01-01','OPEN','2025-01-01 00:00+02',500000),
('f01-savings','fixture-f01','SAVINGS','Savings','0019','ZAR','2025-01-01','OPEN','2025-01-01 00:00+02',150000),
('f03-everyday','fixture-f03','EVERYDAY','Everyday','0033','ZAR','2025-01-01','OPEN','2025-01-01 00:00+02',0),
('f09-everyday','fixture-f09','EVERYDAY','Everyday','0099','ZAR','2025-01-01','OPEN','2025-01-01 00:00+02',0),
('f04-everyday','fixture-f04','EVERYDAY','Everyday','0044','ZAR','2025-01-01','OPEN','2025-01-01 00:00+02',0),
('f04-savings','fixture-f04','SAVINGS','Savings','0045','ZAR','2025-01-01','OPEN','2025-01-01 00:00+02',0),
('large-everyday','fixture-large','EVERYDAY','Everyday','9999','ZAR','2025-01-01','OPEN','2025-01-01 00:00+02',0),
('f14-everyday','fixture-f14','EVERYDAY','Everyday','0014','ZAR','2026-09-01','OPEN','2026-09-01 00:00+02',500000),
('f15-everyday','fixture-f15','EVERYDAY','Everyday','0015','ZAR','2026-10-01','OPEN','2026-10-01 00:00+02',100000),
('f16-everyday','fixture-f16','EVERYDAY','Everyday','0016','ZAR','2026-09-01','OPEN','2026-09-01 00:00+02',400000),
('f16-savings','fixture-f16','SAVINGS','Savings','0017','ZAR','2026-09-01','OPEN','2026-09-01 00:00+02',60000),
('f17-negative','fixture-f17','EVERYDAY','Everyday','0018','ZAR','2026-10-01','OPEN','2026-10-01 00:00+02',10000),
('f17-zero','fixture-f17','SAVINGS','Savings','0019','ZAR','2026-10-01','OPEN','2026-10-01 00:00+02',0),
('closed-only','fixture-closed','EVERYDAY','Archived','0020','ZAR','2026-10-01','CLOSED','2026-10-01 00:00+02',100000);
INSERT INTO dataset_instance(singleton,dataset_id,instance_epoch,seed_content_hash,reference_date,generator_version)
VALUES(true,'spending-overview-isolated-fixture-v2','a4f4b3cc-f782-4ac5-992b-50ed15971211','manual-independent-fixture-v2','2026-10-31','isolated-test-only');
INSERT INTO transfer_groups(id,customer_id,kind) VALUES
('f01-transfer','fixture-f01','ORIGINAL'),('f04-transfer','fixture-f04','ORIGINAL'),('f16-transfer','fixture-f16','ORIGINAL');
INSERT INTO posted_entries(id,account_id,source_event_id,amount_minor,currency,transaction_type,effect_group,posted_at,occurred_at,raw_description,category_code,classification_provenance,original_entry_id,transfer_group_id) VALUES
('f01-salary','f01-everyday','fixture:f01:salary',2000000,'ZAR','SALARY_CREDIT','INCOME','2026-10-01 09:00+02','2026-10-01 09:00+02','Fixture salary',NULL,'NOT_APPLICABLE',NULL,NULL),
('f01-grocery','f01-everyday','fixture:f01:grocery',-100000,'ZAR','CARD_PURCHASE','SPEND','2026-10-02 09:00+02','2026-10-02 09:00+02','Fixture grocery','GROCERIES','OBLIGATION',NULL,NULL),
('f01-fee','f01-everyday','fixture:f01:fee',-5000,'ZAR','BANK_FEE','SPEND','2026-10-04 09:00+02','2026-10-04 09:00+02','Fixture fee','BANK_FEES','TYPE_RULE',NULL,NULL),
('f01-out','f01-everyday','fixture:f01:out',-200000,'ZAR','OWN_TRANSFER_OUT','INTERNAL','2026-10-05 09:00+02','2026-10-05 09:00+02','Own transfer',NULL,'NOT_APPLICABLE',NULL,'f01-transfer'),
('f01-in','f01-savings','fixture:f01:in',200000,'ZAR','OWN_TRANSFER_IN','INTERNAL','2026-10-05 09:00+02','2026-10-05 09:00+02','Own transfer',NULL,'NOT_APPLICABLE',NULL,'f01-transfer'),
('f04-out','f04-everyday','fixture:f04:out',-200000,'ZAR','OWN_TRANSFER_OUT','INTERNAL','2025-10-31 09:00+02','2025-10-31 09:00+02','Own transfer',NULL,'NOT_APPLICABLE',NULL,'f04-transfer'),
('f04-in','f04-savings','fixture:f04:in',200000,'ZAR','OWN_TRANSFER_IN','INTERNAL','2025-11-01 09:00+02','2025-11-01 09:00+02','Own transfer',NULL,'NOT_APPLICABLE',NULL,'f04-transfer'),
('f16-out','f16-everyday','fixture:f16:out',-80000,'ZAR','OWN_TRANSFER_OUT','INTERNAL','2026-09-30 09:00+02','2026-09-30 09:00+02','Own transfer',NULL,'NOT_APPLICABLE',NULL,'f16-transfer'),
('f16-in','f16-savings','fixture:f16:in',80000,'ZAR','OWN_TRANSFER_IN','INTERNAL','2026-10-01 09:00+02','2026-10-01 09:00+02','Own transfer',NULL,'NOT_APPLICABLE',NULL,'f16-transfer'),
('large-income','large-everyday','fixture:large:income',9007199254740993,'ZAR','SALARY_CREDIT','INCOME','2026-10-01 09:00+02','2026-10-01 09:00+02','Large exact income',NULL,'NOT_APPLICABLE',NULL,NULL);
INSERT INTO posted_entries(id,account_id,source_event_id,amount_minor,currency,transaction_type,effect_group,posted_at,occurred_at,raw_description,category_code,classification_provenance) VALUES
('f14-income','f14-everyday','fixture:f14:income',1000000,'ZAR','SALARY_CREDIT','INCOME','2026-09-10 09:00+02','2026-09-10 09:00+02','Fixture income',NULL,'NOT_APPLICABLE'),
('f14-september','f14-everyday','fixture:f14:september',-300000,'ZAR','CARD_PURCHASE','SPEND','2026-09-20 09:00+02','2026-09-20 09:00+02','Fixture purchase','GROCERIES','OBLIGATION'),
('f14-october','f14-everyday','fixture:f14:october',-200000,'ZAR','CARD_PURCHASE','SPEND','2026-10-20 09:00+02','2026-10-20 09:00+02','Fixture purchase','GROCERIES','OBLIGATION'),
('f17-fee','f17-negative','fixture:f17:fee',-15000,'ZAR','BANK_FEE','SPEND','2026-10-03 09:00+02','2026-10-03 09:00+02','Fixture fee','BANK_FEES','TYPE_RULE');
INSERT INTO posted_entries(id,account_id,source_event_id,amount_minor,currency,transaction_type,effect_group,posted_at,occurred_at,raw_description,category_code,classification_provenance,original_entry_id) VALUES
('f01-refund','f01-everyday','fixture:f01:refund',20000,'ZAR','SPEND_REFUND','SPEND','2026-10-03 09:00+02','2026-10-03 09:00+02','Fixture refund','GROCERIES','OBLIGATION','f01-grocery'),
('f03-original','f03-everyday','fixture:f03:original',-20000,'ZAR','CARD_PURCHASE','SPEND','2026-09-20 09:00+02','2026-09-20 09:00+02','Fixture health purchase','HEALTH','OBLIGATION',NULL),
('f03-refund','f03-everyday','fixture:f03:refund',20000,'ZAR','SPEND_REFUND','SPEND','2026-10-03 09:00+02','2026-10-03 09:00+02','Fixture health refund','HEALTH','OBLIGATION','f03-original'),
('f03-fee','f03-everyday','fixture:f03:fee',-5000,'ZAR','BANK_FEE','SPEND','2026-10-04 09:00+02','2026-10-04 09:00+02','Fixture fee','BANK_FEES','TYPE_RULE',NULL),
('f09-original','f09-everyday','fixture:f09:original',-12000,'ZAR','CARD_PURCHASE','SPEND','2026-09-20 09:00+02','2026-09-20 09:00+02','Harbor Health','HEALTH','MERCHANT',NULL);
INSERT INTO posted_entries(id,account_id,source_event_id,amount_minor,currency,transaction_type,effect_group,posted_at,occurred_at,raw_description,category_code,classification_provenance,original_entry_id) VALUES
('f09-salary','f09-everyday','fixture:f09:salary',1875000,'ZAR','SALARY_CREDIT','INCOME','2026-10-01 09:00+02','2026-10-01 09:00+02','Fixture salary',NULL,'NOT_APPLICABLE',NULL),
('f09-fee','f09-everyday','fixture:f09:fee',-7500,'ZAR','BANK_FEE','SPEND','2026-10-05 09:00+02','2026-10-05 09:00+02','Account fee','BANK_FEES','TYPE_RULE',NULL),
('f09-other','f09-everyday','fixture:f09:other',-60000,'ZAR','CARD_PURCHASE','SPEND','2026-10-10 09:00+02','2026-10-10 09:00+02','Harbor Home Store','UNCATEGORIZED','UNCATEGORIZED',NULL),
('f09-cash','f09-everyday','fixture:f09:cash',-100000,'ZAR','CASH_WITHDRAWAL','SPEND','2026-10-14 09:00+02','2026-10-14 09:00+02','ATM withdrawal','CASH_WITHDRAWALS','TYPE_RULE',NULL),
('f09-sent','f09-everyday','fixture:f09:sent',-157550,'ZAR','EXTERNAL_PAYMENT','SPEND','2026-10-17 09:00+02','2026-10-17 09:00+02','Money sent','MONEY_SENT','TYPE_RULE',NULL),
('f09-transport1','f09-everyday','fixture:f09:transport1',-120000,'ZAR','CARD_PURCHASE','SPEND','2026-10-21 09:00+02','2026-10-21 09:00+02','MetroLink Transport','TRANSPORT_FUEL','MERCHANT',NULL),
('f09-grocery1','f09-everyday','fixture:f09:grocery1',-185000,'ZAR','CARD_PURCHASE','SPEND','2026-10-24 09:00+02','2026-10-24 09:00+02','Cedar Market','GROCERIES','MERCHANT',NULL),
('f09-housing','f09-everyday','fixture:f09:housing',-420000,'ZAR','DEBIT_ORDER','SPEND','2026-10-27 09:00+02','2026-10-27 09:00+02','Oak Lane Properties','HOUSING_UTILITIES','OBLIGATION',NULL),
('f09-refund','f09-everyday','fixture:f09:refund',12000,'ZAR','SPEND_REFUND','SPEND','2026-10-28 09:00+02','2026-10-28 09:00+02','Harbor Health refund','HEALTH','MERCHANT','f09-original'),
('f09-transport2','f09-everyday','fixture:f09:transport2',-70000,'ZAR','CARD_PURCHASE','SPEND','2026-10-29 09:00+02','2026-10-29 09:00+02','Citylink Fuel','TRANSPORT_FUEL','MERCHANT',NULL),
('f09-grocery2','f09-everyday','fixture:f09:grocery2',-140000,'ZAR','CARD_PURCHASE','SPEND','2026-10-31 09:00+02','2026-10-31 09:00+02','Cedar Market','GROCERIES','MERCHANT',NULL);
INSERT INTO authorizations(id,account_id,authorized_amount_minor,occurred_at,lifecycle_status,raw_description,source_event_id) VALUES
('f09-pending1','f09-everyday',72000,'2026-10-31 10:00+02','PENDING','Citylink pending','fixture:f09:pending1'),
('f09-pending2','f09-everyday',43900,'2026-10-31 11:00+02','PENDING','Harborshop pending','fixture:f09:pending2');
\endif
COMMIT;
