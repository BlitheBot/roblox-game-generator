-- Migration 006: failure pattern memory (improvement 6)
-- Tracks mechanic+genre combos whose games failed to exceed 5 CCU after
-- 30 days live. At 3 recorded failures the combo is permanently
-- suppressed and the ScoringEngine hard-excludes it (until !unsuppress).

BEGIN;

CREATE TABLE IF NOT EXISTS failure_memory (
    mechanic_tag           TEXT,
    genre                  TEXT,
    fail_count             INT DEFAULT 0,
    last_failed            TIMESTAMPTZ,
    permanently_suppressed BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (mechanic_tag, genre)
);

-- Each game contributes at most one failure to its combo
-- Guarded so a re-run against a table owned by another role skips cleanly
-- instead of tripping ALTER TABLE's ownership check (see 001 header note).
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'published_games'
          AND column_name = 'failure_recorded'
    ) THEN
        EXECUTE 'ALTER TABLE published_games ADD COLUMN failure_recorded BOOLEAN NOT NULL DEFAULT FALSE';
    END IF;
END $$;

COMMIT;
