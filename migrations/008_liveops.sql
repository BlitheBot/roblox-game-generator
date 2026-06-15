-- Migration 008: LiveOps bot (improvement 8)

BEGIN;

-- Weekly top-5 selection queue
CREATE TABLE IF NOT EXISTS liveops_queue (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id     UUID REFERENCES published_games (id),
    week_start  TIMESTAMPTZ,
    update_type TEXT,   -- 'content_drop' | 'balance_tune' | 'seasonal_reskin' | 'full'
    status      TEXT,   -- 'queued' | 'building' | 'published' | 'failed'
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes guarded on catalog presence so a re-run against tables owned by
-- another role skips cleanly instead of tripping the ownership check that
-- CREATE INDEX runs when it opens the table (see 001 header note).
DO $$ BEGIN
    IF to_regclass('public.idx_liveops_queue_week') IS NULL THEN
        EXECUTE 'CREATE INDEX idx_liveops_queue_week ON liveops_queue (week_start)';
    END IF;
END $$;

-- Balance change audit trail
CREATE TABLE IF NOT EXISTS balance_history (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id            UUID REFERENCES published_games (id),
    changed_at         TIMESTAMPTZ DEFAULT NOW(),
    metric_trigger     TEXT,
    change_description TEXT,
    patch_json         JSONB
);

DO $$ BEGIN
    IF to_regclass('public.idx_balance_history_game') IS NULL THEN
        EXECUTE 'CREATE INDEX idx_balance_history_game ON balance_history (game_id)';
    END IF;
END $$;

-- Seasonal reskin originals + scheduled revert
CREATE TABLE IF NOT EXISTS seasonal_overrides (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id                UUID REFERENCES published_games (id),
    original_title         TEXT,
    original_description   TEXT,
    original_thumbnail_url TEXT,
    season                 TEXT,
    revert_after           TIMESTAMPTZ,
    reverted               BOOLEAN DEFAULT FALSE
);

DO $$ BEGIN
    IF to_regclass('public.idx_seasonal_overrides_due') IS NULL THEN
        EXECUTE 'CREATE INDEX idx_seasonal_overrides_due '
                'ON seasonal_overrides (revert_after) WHERE reverted = FALSE';
    END IF;
END $$;

-- Weekly run log
CREATE TABLE IF NOT EXISTS liveops_log (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_at        TIMESTAMPTZ DEFAULT NOW(),
    games_updated INT,
    games_failed  INT,
    summary_json  JSONB
);

COMMIT;
