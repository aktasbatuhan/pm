-- Chat sessions + messages, per-tenant.
-- Run after 0002_per_tenant_tables.sql.
-- Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS agent_sessions (
    id                  TEXT PRIMARY KEY,
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source              TEXT NOT NULL,           -- web | cli | slack | system
    user_id             TEXT,                    -- legacy gateway user id, not auth.users
    model               TEXT,
    model_config        JSONB,
    system_prompt       TEXT,
    parent_session_id   TEXT REFERENCES agent_sessions(id) ON DELETE SET NULL,
    title               TEXT,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at            TIMESTAMPTZ,
    end_reason          TEXT,
    message_count       INTEGER NOT NULL DEFAULT 0,
    tool_call_count     INTEGER NOT NULL DEFAULT 0,
    input_tokens        INTEGER NOT NULL DEFAULT 0,
    output_tokens       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_tenant_started ON agent_sessions(tenant_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_tenant_source ON agent_sessions(tenant_id, source, started_at DESC);

CREATE TABLE IF NOT EXISTS agent_messages (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    session_id          TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    role                TEXT NOT NULL,
    content             TEXT,
    tool_call_id        TEXT,
    tool_calls          JSONB,
    tool_name           TEXT,
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    token_count         INTEGER,
    finish_reason       TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_session_ts ON agent_messages(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_tenant ON agent_messages(tenant_id, timestamp DESC);

INSERT INTO schema_migrations (version) VALUES ('0003_agent_sessions')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
