-- Migration 012: SEO title A/B testing (Improvement 5)
--
-- Tracks the 48-hour, 3-variant title test per published game. Guarded index
-- creation per the 001 ownership-check convention.

BEGIN;

CREATE TABLE IF NOT EXISTS title_ab_tests (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id           UUID REFERENCES published_games (id),
    universe_id       BIGINT NOT NULL,
    genre_account     TEXT NOT NULL,
    variant_0         TEXT NOT NULL,
    variant_1         TEXT NOT NULL,
    variant_2         TEXT NOT NULL,
    current_variant   INT DEFAULT 0,
    winning_variant   INT,
    winning_title     TEXT,
    test_started_at   TIMESTAMPTZ DEFAULT NOW(),
    test_ends_at      TIMESTAMPTZ,
    last_rotation_at  TIMESTAMPTZ,
    status            TEXT DEFAULT 'running'
                          CHECK (status IN ('running', 'complete', 'failed')),
    completed_at      TIMESTAMPTZ
);

DO $$ BEGIN
    IF to_regclass('public.idx_title_ab_tests_status') IS NULL THEN
        EXECUTE 'CREATE INDEX idx_title_ab_tests_status ON title_ab_tests (status)';
    END IF;
END $$;

COMMIT;
