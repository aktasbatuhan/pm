-- Per-tenant data tables. Mirrors the SQLite schemas, with tenant_id added
-- and types modernized (UUIDs, timestamptz, JSONB).
-- Run after 0001_foundations.sql.
-- Idempotent: safe to re-run.

BEGIN;

-- Workspace state (one row per tenant)
CREATE TABLE IF NOT EXISTS workspace_meta (
    tenant_id           UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    onboarding_status   TEXT NOT NULL DEFAULT 'not_started',
    onboarding_phase    TEXT,
    onboarded_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workspace_blueprint (
    tenant_id   UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary     TEXT NOT NULL DEFAULT '',
    updated_by  TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workspace_learnings (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    category        TEXT NOT NULL,
    content         TEXT NOT NULL,
    source_thread   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_learnings_tenant ON workspace_learnings(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS workspace_threads (
    thread_id   TEXT PRIMARY KEY,
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    platform    TEXT NOT NULL,
    last_active TIMESTAMPTZ NOT NULL,
    summary     TEXT NOT NULL,
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_threads_tenant ON workspace_threads(tenant_id, last_active DESC);

-- Briefs
CREATE TABLE IF NOT EXISTS briefs (
    id                  TEXT PRIMARY KEY,
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    summary             TEXT NOT NULL,
    headline            TEXT DEFAULT '',
    action_items        JSONB NOT NULL DEFAULT '[]'::jsonb,
    suggested_prompts   JSONB DEFAULT '[]'::jsonb,
    data_sources        TEXT,
    cover_url           TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_briefs_tenant_created ON briefs(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS brief_actions (
    id                  TEXT PRIMARY KEY,
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    brief_id            TEXT NOT NULL REFERENCES briefs(id) ON DELETE CASCADE,
    category            TEXT NOT NULL,
    title               TEXT NOT NULL,
    description         TEXT NOT NULL,
    priority            TEXT NOT NULL DEFAULT 'medium',
    status              TEXT NOT NULL DEFAULT 'pending',
    chat_session_id     TEXT,
    references_json     JSONB DEFAULT '[]'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_actions_tenant_status ON brief_actions(tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_actions_brief ON brief_actions(brief_id);

-- Goals
CREATE TABLE IF NOT EXISTS goals (
    id                  TEXT PRIMARY KEY,
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    title               TEXT NOT NULL,
    description         TEXT,
    target_date         TEXT,
    status              TEXT NOT NULL DEFAULT 'active',
    progress            INTEGER DEFAULT 0,
    trajectory          TEXT,
    related_items       JSONB DEFAULT '[]'::jsonb,
    action_items        JSONB DEFAULT '[]'::jsonb,
    last_evaluated_at   TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_goals_tenant ON goals(tenant_id, status);

CREATE TABLE IF NOT EXISTS goal_snapshots (
    id              TEXT PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    goal_id         TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    progress        INTEGER DEFAULT 0,
    trajectory      TEXT,
    action_items    JSONB DEFAULT '[]'::jsonb,
    brief_id        TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_goal_snapshots_tenant ON goal_snapshots(tenant_id, goal_id, created_at DESC);

-- KPIs
CREATE TABLE IF NOT EXISTS kpis (
    id                  TEXT PRIMARY KEY,
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    description         TEXT,
    unit                TEXT,
    direction           TEXT DEFAULT 'higher',
    target_value        DOUBLE PRECISION,
    current_value       DOUBLE PRECISION,
    previous_value      DOUBLE PRECISION,
    measurement_plan    TEXT DEFAULT '',
    measurement_status  TEXT DEFAULT 'pending',
    measurement_error   TEXT,
    cron_job_id         TEXT,
    status              TEXT DEFAULT 'active',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_measured_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_kpis_tenant ON kpis(tenant_id, status);

CREATE TABLE IF NOT EXISTS kpi_values (
    id              TEXT PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    kpi_id          TEXT NOT NULL REFERENCES kpis(id) ON DELETE CASCADE,
    value           DOUBLE PRECISION NOT NULL,
    source          TEXT,
    notes           TEXT,
    recorded_at     TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kpi_values_tenant ON kpi_values(tenant_id, kpi_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS kpi_flags (
    id              TEXT PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    kpi_id          TEXT NOT NULL REFERENCES kpis(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT,
    references_json JSONB DEFAULT '[]'::jsonb,
    brief_id        TEXT,
    status          TEXT DEFAULT 'open',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_kpi_flags_tenant ON kpi_flags(tenant_id, status);

-- Integrations
CREATE TABLE IF NOT EXISTS integration_connections (
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    platform        TEXT NOT NULL,
    auth_type       TEXT NOT NULL,
    credentials     TEXT NOT NULL,            -- encrypted JSON; vault refs in target arch
    status          TEXT NOT NULL DEFAULT 'pending',
    display_name    TEXT,
    connected_at    TIMESTAMPTZ,
    last_verified   TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, platform)
);

CREATE TABLE IF NOT EXISTS integration_github_installations (
    installation_id             TEXT PRIMARY KEY,
    tenant_id                   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    account_login               TEXT NOT NULL,
    account_type                TEXT,
    repo_selection              TEXT,
    cached_token                TEXT,
    cached_token_expires_at     TIMESTAMPTZ,
    installed_at                TIMESTAMPTZ NOT NULL,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_gh_installs_tenant ON integration_github_installations(tenant_id);

CREATE TABLE IF NOT EXISTS oauth_states (
    state       TEXT PRIMARY KEY,
    tenant_id   UUID REFERENCES tenants(id) ON DELETE CASCADE,
    purpose     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_oauth_states_created ON oauth_states(created_at);

CREATE TABLE IF NOT EXISTS tenant_onboarding_profile (
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    PRIMARY KEY (tenant_id, key)
);

-- Apply updated_at triggers where needed
DROP TRIGGER IF EXISTS workspace_meta_updated_at ON workspace_meta;
CREATE TRIGGER workspace_meta_updated_at BEFORE UPDATE ON workspace_meta
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS brief_actions_updated_at ON brief_actions;
CREATE TRIGGER brief_actions_updated_at BEFORE UPDATE ON brief_actions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS goals_updated_at ON goals;
CREATE TRIGGER goals_updated_at BEFORE UPDATE ON goals
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS kpis_updated_at ON kpis;
CREATE TRIGGER kpis_updated_at BEFORE UPDATE ON kpis
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS kpi_flags_updated_at ON kpi_flags;
CREATE TRIGGER kpi_flags_updated_at BEFORE UPDATE ON kpi_flags
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS gh_installs_updated_at ON integration_github_installations;
CREATE TRIGGER gh_installs_updated_at BEFORE UPDATE ON integration_github_installations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

INSERT INTO schema_migrations (version) VALUES ('0002_per_tenant_tables')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
