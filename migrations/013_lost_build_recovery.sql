-- Migration 013: lost-build recovery (publish-loss bug).
--
-- When a build directory is pruned off disk before its approved/pending row
-- publishes, the .rbxl is gone and retrying the upload can never succeed.
-- ApprovalGate now rebuilds from the original concept; but if that concept is
-- also gone, the row must terminate instead of retrying forever. That needs a
-- 'failed' status, which the original CHECK constraint disallowed.

BEGIN;

DO $$
DECLARE
    con_name TEXT;
BEGIN
    -- Only touch the table if we own it (mirrors the guard style in 004).
    IF to_regclass('public.pending_approvals') IS NULL THEN
        RETURN;
    END IF;

    -- Drop whatever CHECK constraint currently governs status (its name is the
    -- implicit pending_approvals_status_check, but discover it to be safe).
    FOR con_name IN
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        WHERE nsp.nspname = 'public'
          AND rel.relname = 'pending_approvals'
          AND con.contype = 'c'
          AND pg_get_constraintdef(con.oid) ILIKE '%status%'
    LOOP
        EXECUTE format(
            'ALTER TABLE pending_approvals DROP CONSTRAINT %I', con_name
        );
    END LOOP;

    ALTER TABLE pending_approvals
        ADD CONSTRAINT pending_approvals_status_check
        CHECK (status IN ('pending', 'approved', 'skipped', 'failed'));
END $$;

COMMIT;
