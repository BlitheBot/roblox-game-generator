-- Migration 005: 48-hour SEO description refresh cadence (improvement 4)
-- Tracks when each live game's description was last regenerated so the
-- scheduler can refresh every game on a strict 48h cycle.

BEGIN;

-- Guarded so a re-run against a table owned by another role skips cleanly
-- instead of tripping ALTER TABLE's ownership check (see 001 header note).
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'published_games'
          AND column_name = 'last_description_refresh'
    ) THEN
        EXECUTE 'ALTER TABLE published_games ADD COLUMN last_description_refresh TIMESTAMPTZ';
    END IF;
END $$;

-- Existing games refresh on the next cycle (NULL = immediately due)

COMMIT;
