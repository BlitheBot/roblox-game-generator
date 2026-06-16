-- Migration 010: publish rate limiting (core feature)
--
-- Adds scheduling support to pending_approvals so rate-limited games can wait
-- for an open slot, an opportunity_score column on concept_queue for the
-- rate limiter's high-opportunity exception, a status view, and supporting
-- indexes.
--
-- ALTER TABLE / CREATE INDEX trip the table-ownership check when opening the
-- table, *before* their IF NOT EXISTS short-circuit. Guard on catalog
-- presence so a re-run against a table owned by another role is a true no-op
-- (see the 001/004 header notes).

BEGIN;

DO $$
DECLARE
    col RECORD;
BEGIN
    -- pending_approvals: scheduling columns
    FOR col IN
        SELECT * FROM (VALUES
            ('scheduled_publish_after', 'TIMESTAMPTZ'),
            ('rate_limit_reason',       'TEXT')
        ) AS c(name, type)
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'pending_approvals'
              AND column_name = col.name
        ) THEN
            EXECUTE format('ALTER TABLE pending_approvals ADD COLUMN %I %s',
                           col.name, col.type);
        END IF;
    END LOOP;

    -- concept_queue.opportunity_score already exists in 001 (NOT NULL); this
    -- guard makes the column add a true no-op on existing databases while
    -- still creating it on any schema that predates it.
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'concept_queue'
          AND column_name = 'opportunity_score'
    ) THEN
        EXECUTE 'ALTER TABLE concept_queue ADD COLUMN opportunity_score FLOAT';
    END IF;

    -- Indexes for efficient rate-limit queries
    IF to_regclass('public.idx_published_games_rate_limit') IS NULL THEN
        EXECUTE 'CREATE INDEX idx_published_games_rate_limit '
                'ON published_games (genre_account, published_at, status)';
    END IF;
    IF to_regclass('public.idx_pending_approvals_scheduled') IS NULL THEN
        EXECUTE 'CREATE INDEX idx_pending_approvals_scheduled '
                'ON pending_approvals (scheduled_publish_after, status)';
    END IF;
END $$;

-- Quick rate-limit status view (per genre account)
CREATE OR REPLACE VIEW publish_rate_status AS
SELECT
    genre_account,
    COUNT(*) FILTER (WHERE published_at > NOW() - INTERVAL '7 days')  AS games_this_week,
    COUNT(*) FILTER (WHERE published_at > NOW() - INTERVAL '24 hours') AS games_today,
    MAX(published_at)                                                  AS last_published_at,
    EXTRACT(EPOCH FROM (NOW() - MAX(published_at))) / 3600             AS hours_since_last_publish,
    COUNT(*)                                                           AS total_published
FROM published_games
-- Mirror the rate limiter's predicate exactly so the view and the limiter
-- always agree on the count (published_games has no 'failed' status today, so
-- this currently counts every row — kept aligned for future-proofing).
WHERE status NOT IN ('failed')
GROUP BY genre_account;

COMMIT;
