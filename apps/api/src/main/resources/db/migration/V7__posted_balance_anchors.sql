-- Nullable only for databases that predate anchored datasets; the importer requires both values.
ALTER TABLE accounts ADD COLUMN balance_anchor_at timestamptz;
ALTER TABLE accounts ADD COLUMN opening_balance_minor bigint;
ALTER TABLE accounts ADD CONSTRAINT account_anchor_pair CHECK
  ((balance_anchor_at IS NULL) = (opening_balance_minor IS NULL));
ALTER TABLE accounts ADD CONSTRAINT account_anchor_midnight CHECK
  (balance_anchor_at IS NULL OR
   (balance_anchor_at AT TIME ZONE 'Africa/Johannesburg')::time = time '00:00:00');
ALTER TABLE accounts ADD CONSTRAINT account_anchor_chronology CHECK
  (balance_anchor_at IS NULL OR
   ((balance_anchor_at AT TIME ZONE 'Africa/Johannesburg')::date >= opened_on AND
    (balance_anchor_at AT TIME ZONE 'Africa/Johannesburg')::date <= date '2026-10-31'));

CREATE FUNCTION guard_account_anchor() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.balance_anchor_at IS NOT NULL AND
     (NEW.balance_anchor_at IS DISTINCT FROM OLD.balance_anchor_at OR
      NEW.opening_balance_minor IS DISTINCT FROM OLD.opening_balance_minor) THEN
    RAISE EXCEPTION 'Opening anchor is immutable';
  END IF;
  IF NEW.balance_anchor_at IS NOT NULL AND EXISTS (
    SELECT 1 FROM posted_entries p WHERE p.account_id=NEW.id AND p.posted_at<NEW.balance_anchor_at
  ) THEN
    RAISE EXCEPTION 'Opening anchor follows posted activity';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER account_anchor_guard BEFORE UPDATE ON accounts
  FOR EACH ROW EXECUTE FUNCTION guard_account_anchor();

CREATE FUNCTION guard_posted_anchor() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE anchor timestamptz;
BEGIN
  SELECT balance_anchor_at INTO anchor FROM accounts WHERE id=NEW.account_id FOR SHARE;
  IF anchor IS NOT NULL AND NEW.posted_at<anchor THEN
    RAISE EXCEPTION 'Posting predates opening anchor';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER posted_anchor_guard BEFORE INSERT ON posted_entries
  FOR EACH ROW EXECUTE FUNCTION guard_posted_anchor();
