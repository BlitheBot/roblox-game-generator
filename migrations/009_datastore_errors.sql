-- Migration 009: in-game DataStore failure telemetry (PART A FIX 3)
-- Populated when a published game POSTs DataStore failures to a VPS ingest
-- endpoint (Config.TelemetryUrl). No ingest server ships in this repo yet;
-- the table exists so that wiring has a destination.

BEGIN;

CREATE TABLE IF NOT EXISTS datastore_errors (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id       TEXT,
    operation     TEXT,
    key           TEXT,
    error_message TEXT,
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_datastore_errors_time ON datastore_errors (occurred_at DESC);

COMMIT;
