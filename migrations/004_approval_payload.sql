-- Migration 004: supervised-mode approval flow (spec Section 12)
-- pending_approvals gains the publish payload so an approved row can be
-- published without re-running the build, plus a processed marker.

BEGIN;

-- ADD COLUMN / CREATE INDEX trip the ownership check when opening the table,
-- before their IF NOT EXISTS short-circuit. Guard on catalog presence so a
-- re-run against a table owned by another role is a true no-op (see 001 note).
DO $$
DECLARE
    col RECORD;
BEGIN
    FOR col IN
        SELECT * FROM (VALUES
            ('rbxl_path',      'TEXT'),
            ('thumbnail_path', 'TEXT'),
            ('description',    'TEXT'),
            ('processed_at',   'TIMESTAMPTZ')
        ) AS c(name, type)
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'pending_approvals'
              AND column_name = col.name
        ) THEN
            EXECUTE format('ALTER TABLE pending_approvals ADD COLUMN %I %s',
                           col.name, col.type);
        END IF;
    END LOOP;

    IF to_regclass('public.idx_pending_approvals_status') IS NULL THEN
        EXECUTE 'CREATE INDEX idx_pending_approvals_status '
                'ON pending_approvals (status) WHERE processed_at IS NULL';
    END IF;
END $$;

COMMIT;
