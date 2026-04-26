-- Bucket #3: signals + reports + team pulse + changelogs (per-tenant).
-- Run after 0003. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS signal_sources (
    id              TEXT PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL,
    config          JSONB NOT NULL DEFAULT '{}'::jsonb,
    filter          TEXT,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    last_fetched_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sources_tenant ON signal_sources(tenant_id);

CREATE TABLE IF NOT EXISTS signals (
    id                  TEXT PRIMARY KEY,
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_id           TEXT NOT NULL REFERENCES signal_sources(id) ON DELETE CASCADE,
    title               TEXT,
    body                TEXT,
    url                 TEXT,
    author              TEXT,
    relevance_score     DOUBLE PRECISION DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'new',
    metadata            JSONB DEFAULT '{}'::jsonb,
    external_created_at TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_signals_tenant_status ON signals(tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_source ON signals(source_id, created_at DESC);

CREATE TABLE IF NOT EXISTS report_templates (
    id              TEXT PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    body            TEXT NOT NULL,
    resources       JSONB NOT NULL DEFAULT '{}'::jsonb,
    schedule        TEXT DEFAULT 'none',
    cron_job_id     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_templates_tenant ON report_templates(tenant_id);

CREATE TABLE IF NOT EXISTS reports (
    id          TEXT PRIMARY KEY,
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    template_id TEXT NOT NULL REFERENCES report_templates(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_reports_tenant ON reports(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS team_pulse (
    id                  TEXT PRIMARY KEY,
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    member_name         TEXT NOT NULL,
    github_handle       TEXT,
    prs_merged          INTEGER DEFAULT 0,
    reviews_done        INTEGER DEFAULT 0,
    days_since_active   INTEGER DEFAULT 0,
    flags               JSONB DEFAULT '[]'::jsonb,
    period              TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pulse_tenant_period ON team_pulse(tenant_id, period, created_at DESC);

CREATE TABLE IF NOT EXISTS changelogs (
    id              TEXT PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    content         TEXT NOT NULL,
    period_start    TIMESTAMPTZ,
    period_end      TIMESTAMPTZ,
    pr_count        INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_changelogs_tenant ON changelogs(tenant_id, created_at DESC);

DROP TRIGGER IF EXISTS templates_updated_at ON report_templates;
CREATE TRIGGER templates_updated_at BEFORE UPDATE ON report_templates
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

INSERT INTO schema_migrations (version) VALUES ('0004_signals_reports_pulse_changelogs')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
