CREATE FUNCTION validate_account_limit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM 1 FROM customers WHERE id=NEW.customer_id FOR UPDATE;
  IF (SELECT count(*) FROM accounts WHERE customer_id=NEW.customer_id)>=4 THEN
    RAISE EXCEPTION 'customer account limit exceeded';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER account_limit BEFORE INSERT ON accounts FOR EACH ROW EXECUTE FUNCTION validate_account_limit();

CREATE FUNCTION validate_authorization() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE opened date;
BEGIN
  SELECT opened_on INTO STRICT opened FROM accounts WHERE id=NEW.account_id;
  IF (NEW.occurred_at AT TIME ZONE 'Africa/Johannesburg')::date<opened THEN
    RAISE EXCEPTION 'authorization before account opening';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF OLD.lifecycle_status<>'PENDING' OR NEW.lifecycle_status NOT IN ('POSTED','CANCELLED')
       OR ROW(NEW.id,NEW.account_id,NEW.authorized_amount_minor,NEW.occurred_at,
              NEW.merchant_id,NEW.raw_description,NEW.source_event_id)
          IS DISTINCT FROM
          ROW(OLD.id,OLD.account_id,OLD.authorized_amount_minor,OLD.occurred_at,
              OLD.merchant_id,OLD.raw_description,OLD.source_event_id) THEN
      RAISE EXCEPTION 'invalid authorization state change';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER authorization_valid BEFORE INSERT OR UPDATE ON authorizations
  FOR EACH ROW EXECUTE FUNCTION validate_authorization();

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
       OR original.account_id<>NEW.account_id THEN
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
    ELSIF original.effect_group<>'INTERNAL' OR NEW.amount_minor<>-original.amount_minor THEN
      RAISE EXCEPTION 'invalid transfer reversal';
    END IF;
  END IF;
  IF NEW.effect_group='INTERNAL' AND
    (SELECT customer_id FROM transfer_groups WHERE id=NEW.transfer_group_id)<>owner_id THEN
    RAISE EXCEPTION 'transfer owner mismatch';
  END IF;
  RETURN NEW;
END $$;
