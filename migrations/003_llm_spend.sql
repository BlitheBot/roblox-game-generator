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

CREATE INDEX IF NOT EXISTS idx_llm_spend_time ON llm_spend (timestamp DESC);

COMMIT;
