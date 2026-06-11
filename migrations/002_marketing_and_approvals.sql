-- Migration 002: A/B thumbnail tests + supervised-mode approval queue

BEGIN;

-- Thumbnail A/B tests (spec 5.2 phase 1)
CREATE TABLE IF NOT EXISTS thumbnail_tests (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id       UUID NOT NULL REFERENCES published_games (id),
    variant       TEXT NOT NULL CHECK (variant IN ('primary', 'alternate')),
    started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at    TIMESTAMPTZ,
    ctr           FLOAT,
    winner        BOOLEAN
);

CREATE INDEX IF NOT EXISTS idx_thumbnail_tests_game ON thumbnail_tests (game_id);

-- Supervised-mode approval queue (spec Section 12)
CREATE TABLE IF NOT EXISTS pending_approvals (
    game_id        UUID PRIMARY KEY,
    concept_id     UUID NOT NULL,
    game_title     TEXT NOT NULL,
    summary        TEXT NOT NULL,
    build_dir      TEXT NOT NULL,
    genre          TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'approved', 'skipped')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at     TIMESTAMPTZ
);

COMMIT;
