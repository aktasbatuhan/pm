-- Drop briefs.cover_url. Cover image generation (fal.ai nano-banana-2) is
-- removed entirely; the column is no longer read or written.
-- Run after 0006. Idempotent.

BEGIN;

ALTER TABLE briefs DROP COLUMN IF EXISTS cover_url;

INSERT INTO schema_migrations (version) VALUES ('0007_drop_cover_url')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
