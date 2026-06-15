-- Migration 005: 48-hour SEO description refresh cadence (improvement 4)
-- Tracks when each live game's description was last regenerated so the
-- scheduler can refresh every game on a strict 48h cycle.

BEGIN;

ALTER TABLE published_games
    ADD COLUMN IF NOT EXISTS last_description_refresh TIMESTAMPTZ;

-- Existing games refresh on the next cycle (NULL = immediately due)

COMMIT;
