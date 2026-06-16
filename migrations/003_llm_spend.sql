-- Migration 003: LLM spend log — feeds the "OpenRouter spend > $15 in 7 days"
-- alert (spec 6.4). One row per OpenRouter chat completion.

BEGIN;

CREATE TABLE IF NOT EXISTS llm_spend (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model             TEXT NOT NULL,
    prompt_tokens     INT,
    completion_tokens INT,
    cost_usd          FLOAT NOT NULL DEFAULT 0
);

-- Guarded so a re-run against a table owned by another role skips cleanly
-- instead of tripping CREATE INDEX's ownership check (see 001 header note).
DO $$ BEGIN
    IF to_regclass('public.idx_llm_spend_time') IS NULL THEN
        EXECUTE 'CREATE INDEX idx_llm_spend_time ON llm_spend (timestamp DESC)';
    END IF;
END $$;

COMMIT;
