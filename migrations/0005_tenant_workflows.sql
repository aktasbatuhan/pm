-- Per-tenant workflow contract with revision history.
-- Each save creates a new revision; only one is_active=true per tenant at a time.
-- Run after 0004. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS tenant_workflows (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    revision            INTEGER NOT NULL,
    name                TEXT NOT NULL,
    body                TEXT NOT NULL,                  -- raw Markdown+YAML text
    rationale           TEXT,                           -- why this revision exists
    author              TEXT NOT NULL,                  -- user_id (UUID as text) or 'dash'
    is_active           BOOLEAN NOT NULL DEFAULT FALSE,
    based_on_signals    JSONB,                          -- evidence array, when author='dash'
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, revision)
);

-- Only one active revision per tenant.
CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_active_per_tenant
    ON tenant_workflows (tenant_id) WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_workflows_tenant_rev
    ON tenant_workflows (tenant_id, revision DESC);

INSERT INTO schema_migrations (version) VALUES ('0005_tenant_workflows')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
