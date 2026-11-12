CREATE OR REPLACE FUNCTION validate_authorization_state() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE linked_count integer; current_status text; auth_id text;
BEGIN
  IF TG_TABLE_NAME='posted_entries' THEN
    auth_id := NEW.authorization_id;
  ELSE
    auth_id := NEW.id;
  END IF;
  SELECT lifecycle_status INTO current_status FROM authorizations WHERE id=auth_id;
  SELECT count(*) INTO linked_count FROM posted_entries WHERE authorization_id=auth_id;
  IF (current_status='POSTED' AND linked_count<>1)
    OR (current_status<>'POSTED' AND linked_count<>0) THEN
    RAISE EXCEPTION 'authorization lifecycle does not match posted entry';
  END IF;
  RETURN NULL;
END $$;
