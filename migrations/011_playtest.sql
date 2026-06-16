-- Migration 011: PlaytesterAgent results (Improvement 1)
--
-- Stores the pre-publish playtest score/result on the concept and surfaces a
-- short summary on the approval row so the Discord approval message can show
-- it. Guarded DO block per the 001/004 ownership-check convention.

BEGIN;

DO $$
DECLARE
    col RECORD;
BEGIN
    FOR col IN
        SELECT * FROM (VALUES
            ('concept_queue',     'playtest_score',   'FLOAT'),
            ('concept_queue',     'playtest_json',    'JSONB'),
            ('pending_approvals', 'playtest_score',   'FLOAT'),
            ('pending_approvals', 'playtest_summary', 'TEXT')
        ) AS c(tbl, name, type)
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = col.tbl
              AND column_name = col.name
        ) THEN
            EXECUTE format('ALTER TABLE %I ADD COLUMN %I %s',
                           col.tbl, col.name, col.type);
        END IF;
    END LOOP;
END $$;

COMMIT;
