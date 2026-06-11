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
ALTER TABLE published_games
    ADD COLUMN IF NOT EXISTS failure_recorded BOOLEAN NOT NULL DEFAULT FALSE;

COMMIT;
