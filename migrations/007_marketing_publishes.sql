-- Migration 007: marketing video publish log (improvement 7)

BEGIN;

CREATE TABLE IF NOT EXISTS marketing_publishes (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id       UUID REFERENCES published_games (id),
    platform      TEXT,            -- 'youtube' | 'tiktok' | 'instagram'
    video_url     TEXT,
    published_at  TIMESTAMPTZ,
    status        TEXT,            -- 'success' | 'failed'
    error_message TEXT
);

-- Guarded so a re-run against a table owned by another role skips cleanly
-- instead of tripping CREATE INDEX's ownership check (see 001 header note).
DO $$ BEGIN
    IF to_regclass('public.idx_marketing_publishes_game') IS NULL THEN
        EXECUTE 'CREATE INDEX idx_marketing_publishes_game ON marketing_publishes (game_id)';
    END IF;
END $$;

COMMIT;
