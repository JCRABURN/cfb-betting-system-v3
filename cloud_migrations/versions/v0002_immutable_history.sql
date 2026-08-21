CREATE OR REPLACE FUNCTION cfb_v3_reject_immutable_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is immutable', TG_TABLE_NAME;
END;
$$;

DROP TRIGGER IF EXISTS cfb_v3_state_snapshots_immutable
    ON cfb_v3_state_snapshots;
CREATE TRIGGER cfb_v3_state_snapshots_immutable
BEFORE UPDATE OR DELETE ON cfb_v3_state_snapshots
FOR EACH ROW EXECUTE FUNCTION cfb_v3_reject_immutable_change();

DROP TRIGGER IF EXISTS cfb_v3_operation_commits_immutable
    ON cfb_v3_operation_commits;
CREATE TRIGGER cfb_v3_operation_commits_immutable
BEFORE UPDATE OR DELETE ON cfb_v3_operation_commits
FOR EACH ROW EXECUTE FUNCTION cfb_v3_reject_immutable_change();
