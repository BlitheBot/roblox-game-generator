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

CREATE INDEX IF NOT EXISTS idx_marketing_publishes_game ON marketing_publishes (game_id);

COMMIT;
