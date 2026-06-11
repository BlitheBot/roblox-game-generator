-- Migration 004: supervised-mode approval flow (spec Section 12)
-- pending_approvals gains the publish payload so an approved row can be
-- published without re-running the build, plus a processed marker.

BEGIN;

ALTER TABLE pending_approvals
    ADD COLUMN IF NOT EXISTS rbxl_path      TEXT,
    ADD COLUMN IF NOT EXISTS thumbnail_path TEXT,
    ADD COLUMN IF NOT EXISTS description    TEXT,
    ADD COLUMN IF NOT EXISTS processed_at   TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_pending_approvals_status
    ON pending_approvals (status) WHERE processed_at IS NULL;

COMMIT;
