-- Migration 001: Initial schema
-- Autonomous Roblox Game Studio — Section 7
--
-- Idempotency note: indexes (and the extension) are created through guarded
-- DO blocks rather than bare `CREATE INDEX IF NOT EXISTS`. PostgreSQL runs the
-- table-ownership check when CREATE INDEX opens the table, *before* the
-- IF NOT EXISTS short-circuit — so re-running a bare statement against a table
-- owned by another role (e.g. a schema first created by the postgres
-- superuser) raises "must be owner of table ..." even when the index already
-- exists. Skipping the statement entirely when the object is present lets the
-- app role (studiobot) run migrations without owning the pre-existing schema.

BEGIN;

-- Extension for UUID generation (skip if already installed — avoids needing
-- CREATE privilege when a superuser installed it out-of-band)
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto') THEN
        EXECUTE 'CREATE EXTENSION "pgcrypto"';
    END IF;
END $$;

-- Concepts that passed the viability gate
CREATE TABLE IF NOT EXISTS concept_queue (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status        TEXT NOT NULL DEFAULT 'queued'
                      CHECK (status IN ('queued', 'building', 'published', 'failed')),
    concept_json  JSONB NOT NULL,
    opportunity_score FLOAT NOT NULL,
    genre         TEXT NOT NULL,
    mechanic_tag  TEXT NOT NULL
);

DO $$ BEGIN
    IF to_regclass('public.idx_concept_queue_status') IS NULL THEN
        EXECUTE 'CREATE INDEX idx_concept_queue_status ON concept_queue (status)';
    END IF;
    IF to_regclass('public.idx_concept_queue_score') IS NULL THEN
        EXECUTE 'CREATE INDEX idx_concept_queue_score ON concept_queue (opportunity_score DESC)';
    END IF;
END $$;

-- All published games
CREATE TABLE IF NOT EXISTS published_games (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    concept_id      UUID NOT NULL REFERENCES concept_queue (id),
    universe_id     BIGINT NOT NULL,
    place_id        BIGINT NOT NULL,
    genre_account   TEXT NOT NULL,
    published_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    game_title      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'live'
                        CHECK (status IN ('live', 'flagged', 'breakout', 'moderated'))
);

DO $$ BEGIN
    IF to_regclass('public.idx_published_games_status') IS NULL THEN
        EXECUTE 'CREATE INDEX idx_published_games_status ON published_games (status)';
    END IF;
    IF to_regclass('public.idx_published_games_genre') IS NULL THEN
        EXECUTE 'CREATE INDEX idx_published_games_genre ON published_games (genre_account)';
    END IF;
END $$;

-- Hourly metrics per game
CREATE TABLE IF NOT EXISTS game_metrics (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id             UUID NOT NULL REFERENCES published_games (id),
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ccu                 INT NOT NULL DEFAULT 0,
    session_length_avg  FLOAT,
    d1_retention        FLOAT,
    d7_retention        FLOAT,
    revenue_robux       INT NOT NULL DEFAULT 0,
    thumbnail_ctr       FLOAT
);

DO $$ BEGIN
    IF to_regclass('public.idx_game_metrics_game_id') IS NULL THEN
        EXECUTE 'CREATE INDEX idx_game_metrics_game_id ON game_metrics (game_id)';
    END IF;
    IF to_regclass('public.idx_game_metrics_timestamp') IS NULL THEN
        EXECUTE 'CREATE INDEX idx_game_metrics_timestamp ON game_metrics (timestamp DESC)';
    END IF;
END $$;

-- Build failures log
CREATE TABLE IF NOT EXISTS build_failures (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    concept_id    UUID,
    timestamp     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stage         TEXT NOT NULL,
    error_message TEXT NOT NULL,
    model_used    TEXT NOT NULL,
    retry_count   INT NOT NULL DEFAULT 0
);

DO $$ BEGIN
    IF to_regclass('public.idx_build_failures_concept') IS NULL THEN
        EXECUTE 'CREATE INDEX idx_build_failures_concept ON build_failures (concept_id)';
    END IF;
    IF to_regclass('public.idx_build_failures_time') IS NULL THEN
        EXECUTE 'CREATE INDEX idx_build_failures_time ON build_failures (timestamp DESC)';
    END IF;
END $$;

-- Feedback loop — per-mechanic signal weight adjustments
CREATE TABLE IF NOT EXISTS signal_weights (
    mechanic_tag  TEXT PRIMARY KEY,
    weight        FLOAT NOT NULL DEFAULT 1.0,
    last_updated  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed baseline weights for all known mechanics
INSERT INTO signal_weights (mechanic_tag, weight) VALUES
    ('idle_tycoon',    1.0),
    ('pet_collect',    1.0),
    ('survival_horror', 1.0),
    ('obby',           1.0),
    ('rpg_dungeon',    1.0),
    ('incremental_sim', 1.0)
ON CONFLICT (mechanic_tag) DO NOTHING;

-- Genre accounts — tracks status, used place slots, ban detection
CREATE TABLE IF NOT EXISTS genre_accounts (
    genre         TEXT PRIMARY KEY,
    account_name  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active', 'paused', 'banned')),
    places_used   INT NOT NULL DEFAULT 0,
    last_checked  TIMESTAMPTZ
);

-- Moderation incident log (Section 16)
CREATE TABLE IF NOT EXISTS moderation_incidents (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id       UUID NOT NULL REFERENCES published_games (id),
    genre_account TEXT NOT NULL,
    detected_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at   TIMESTAMPTZ,
    notes         TEXT
);

-- Orchestrator state — tracks consecutive viability gate rejections (Section 20)
CREATE TABLE IF NOT EXISTS orchestrator_state (
    key           TEXT PRIMARY KEY,
    value         TEXT NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO orchestrator_state (key, value) VALUES
    ('consecutive_viability_rejects', '0'),
    ('supervised_mode_approvals',     '0'),
    ('supervised_mode_active',        'true')
ON CONFLICT (key) DO NOTHING;

COMMIT;
