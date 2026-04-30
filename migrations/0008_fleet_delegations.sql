-- Provider-agnostic delegation inventory.
-- Stores opaque provider handles plus the latest normalized status snapshot so
-- supervisor / observer / briefs can stop rediscovering only GitHub-shaped work.
-- Run after 0007. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS fleet_delegations (
    id                    TEXT PRIMARY KEY,
    tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider              TEXT NOT NULL,
    provider_handle_key   TEXT NOT NULL,
    handle_json           JSONB NOT NULL DEFAULT '{}'::jsonb,
    state                 TEXT NOT NULL DEFAULT 'unknown',
    state_detail          TEXT DEFAULT '',
    summary               TEXT DEFAULT '',
    repo                  TEXT,
    issue_number          INTEGER,
    task_id               TEXT,
    agent_id              TEXT,
    pr_number             INTEGER,
    artifacts_json        JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw_json              JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_activity_at      TIMESTAMPTZ,
    terminal_at           TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, provider, provider_handle_key)
);

CREATE INDEX IF NOT EXISTS idx_fleet_delegations_tenant_state
    ON fleet_delegations (tenant_id, state, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_fleet_delegations_provider
    ON fleet_delegations (tenant_id, provider, provider_handle_key);

CREATE INDEX IF NOT EXISTS idx_fleet_delegations_repo_issue
    ON fleet_delegations (tenant_id, repo, issue_number);

INSERT INTO schema_migrations (version) VALUES ('0008_fleet_delegations')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
