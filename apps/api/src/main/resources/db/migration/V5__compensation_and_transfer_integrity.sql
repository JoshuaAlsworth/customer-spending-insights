CREATE OR REPLACE FUNCTION validate_posted_entry() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  owner_id text; opened date; original posted_entries%ROWTYPE; prior_credit bigint;
  auth authorizations%ROWTYPE;
BEGIN
  SELECT customer_id, opened_on INTO STRICT owner_id, opened FROM accounts WHERE id=NEW.account_id;
  IF (NEW.posted_at AT TIME ZONE 'Africa/Johannesburg')::date < opened THEN
    RAISE EXCEPTION 'posting before account opening';
  END IF;
  IF NEW.authorization_id IS NOT NULL THEN
    SELECT * INTO STRICT auth FROM authorizations WHERE id=NEW.authorization_id FOR UPDATE;
    IF auth.account_id<>NEW.account_id OR auth.lifecycle_status<>'POSTED'
       OR NEW.posted_at<auth.occurred_at THEN
      RAISE EXCEPTION 'invalid authorization posting';
    END IF;
  END IF;
  IF NEW.original_entry_id IS NOT NULL THEN
    SELECT * INTO STRICT original FROM posted_entries WHERE id=NEW.original_entry_id FOR UPDATE;
    IF original.posted_at>=NEW.posted_at OR original.currency<>NEW.currency
       OR (SELECT customer_id FROM accounts WHERE id=original.account_id)<>owner_id THEN
      RAISE EXCEPTION 'invalid compensation original';
    END IF;
    IF NEW.transaction_type='SPEND_REFUND' THEN
      IF original.transaction_type<>'CARD_PURCHASE' OR NEW.category_code<>original.category_code THEN
        RAISE EXCEPTION 'invalid refund original or category';
      END IF;
      SELECT COALESCE(sum(amount_minor),0) INTO prior_credit FROM posted_entries
        WHERE original_entry_id=original.id AND transaction_type='SPEND_REFUND';
      IF prior_credit + NEW.amount_minor > -original.amount_minor
         OR EXISTS (SELECT 1 FROM posted_entries WHERE original_entry_id=original.id AND transaction_type='SPEND_REVERSAL') THEN
        RAISE EXCEPTION 'refund exceeds original or follows reversal';
      END IF;
    ELSIF NEW.transaction_type='SPEND_REVERSAL' THEN
      IF original.transaction_type NOT IN ('CARD_PURCHASE','DEBIT_ORDER','EXTERNAL_PAYMENT','CASH_WITHDRAWAL','BANK_FEE')
         OR NEW.amount_minor<>-original.amount_minor OR NEW.category_code<>original.category_code
         OR EXISTS (SELECT 1 FROM posted_entries WHERE original_entry_id=original.id) THEN
        RAISE EXCEPTION 'invalid full spending reversal';
      END IF;
    ELSIF NEW.transaction_type='INCOME_REVERSAL' THEN
      IF original.effect_group<>'INCOME' OR original.amount_minor<=0
         OR NEW.amount_minor<>-original.amount_minor THEN
        RAISE EXCEPTION 'invalid income reversal';
      END IF;
    ELSIF original.effect_group<>'INTERNAL' OR original.account_id<>NEW.account_id
         OR NEW.amount_minor<>-original.amount_minor THEN
      RAISE EXCEPTION 'invalid transfer reversal';
    END IF;
  END IF;
  IF NEW.effect_group='INTERNAL' AND
    (SELECT customer_id FROM transfer_groups WHERE id=NEW.transfer_group_id)<>owner_id THEN
    RAISE EXCEPTION 'transfer owner mismatch';
  END IF;
  RETURN NEW;
END $$;

CREATE UNIQUE INDEX posted_entries_one_transfer_reversal ON posted_entries(original_entry_id)
  WHERE transaction_type IN ('OWN_TRANSFER_REVERSAL_OUT','OWN_TRANSFER_REVERSAL_IN');

CREATE OR REPLACE FUNCTION validate_transfer_pair() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE pairs integer; total numeric; distinct_accounts integer; kinds text[];
        group_kind text; original_groups integer; original_legs integer;
BEGIN
  SELECT count(*),sum(amount_minor::numeric),count(DISTINCT account_id),array_agg(transaction_type ORDER BY transaction_type)
    INTO pairs,total,distinct_accounts,kinds FROM posted_entries WHERE transfer_group_id=NEW.transfer_group_id;
  SELECT kind INTO STRICT group_kind FROM transfer_groups WHERE id=NEW.transfer_group_id;
  IF pairs<>2 OR total<>0 OR distinct_accounts<>2 OR
     (group_kind='ORIGINAL' AND kinds<>ARRAY['OWN_TRANSFER_IN','OWN_TRANSFER_OUT']) OR
     (group_kind='REVERSAL' AND kinds<>ARRAY['OWN_TRANSFER_REVERSAL_IN','OWN_TRANSFER_REVERSAL_OUT']) THEN
    RAISE EXCEPTION 'invalid transfer pair';
  END IF;
  IF group_kind='REVERSAL' THEN
    SELECT count(DISTINCT original.transfer_group_id),count(DISTINCT original.id)
      INTO original_groups,original_legs
      FROM posted_entries reversal JOIN posted_entries original ON original.id=reversal.original_entry_id
      JOIN transfer_groups source_group ON source_group.id=original.transfer_group_id
      WHERE reversal.transfer_group_id=NEW.transfer_group_id AND source_group.kind='ORIGINAL';
    IF original_groups<>1 OR original_legs<>2 THEN
      RAISE EXCEPTION 'transfer reversal does not reference one original pair';
    END IF;
  END IF;
  RETURN NULL;
END $$;
