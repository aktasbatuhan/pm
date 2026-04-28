-- Allow brief_actions without a parent brief.
-- Workflow proposals filed by the evolver are tenant-scoped action items
-- that don't belong to a specific brief — they describe a suggested change
-- to the workflow contract itself.
-- Run after 0005. Idempotent.

BEGIN;

ALTER TABLE brief_actions
    ALTER COLUMN brief_id DROP NOT NULL;

INSERT INTO schema_migrations (version) VALUES ('0006_brief_actions_optional_brief')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
