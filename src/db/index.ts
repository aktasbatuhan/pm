import { Database } from "bun:sqlite";
import { drizzle } from "drizzle-orm/bun-sqlite";
import { sql, eq } from "drizzle-orm";
import * as schema from "./schema.ts";
import { DB_PATH } from "../paths.ts";

let db: ReturnType<typeof drizzle<typeof schema>>;

export function getDb() {
  if (!db) {
    const sqlite = new Database(DB_PATH);
    sqlite.exec("PRAGMA journal_mode = WAL");
    db = drizzle(sqlite, { schema });
    migrate();
  }
  return db;
}

function migrate() {
  getDb().run(sql`
    CREATE TABLE IF NOT EXISTS chat_sessions (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      session_id TEXT,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    )
  `);

  getDb().run(sql`
    CREATE TABLE IF NOT EXISTS messages (
      id TEXT PRIMARY KEY,
      chat_session_id TEXT NOT NULL REFERENCES chat_sessions(id),
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      metadata TEXT,
      created_at INTEGER NOT NULL
    )
  `);

  getDb().run(sql`
    CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL,
      updated_at INTEGER NOT NULL
    )
  `);

  // Slack bot columns (safe to re-run — ALTER TABLE throws if column exists)
  try { getDb().run(sql`ALTER TABLE chat_sessions ADD COLUMN slack_channel_id TEXT`); } catch {}
  try { getDb().run(sql`ALTER TABLE chat_sessions ADD COLUMN slack_thread_ts TEXT`); } catch {}
  getDb().run(sql`CREATE INDEX IF NOT EXISTS idx_slack_thread ON chat_sessions(slack_channel_id, slack_thread_ts)`);

  // Users table
  getDb().run(sql`
    CREATE TABLE IF NOT EXISTS users (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      role TEXT NOT NULL DEFAULT 'member',
      token TEXT NOT NULL UNIQUE,
      created_at INTEGER NOT NULL
    )
  `);

  // Invites table
  getDb().run(sql`
    CREATE TABLE IF NOT EXISTS invites (
      id TEXT PRIMARY KEY,
      token TEXT NOT NULL UNIQUE,
      created_by TEXT NOT NULL,
      used_by TEXT,
      created_at INTEGER NOT NULL
    )
  `);

  // Add userId to chat sessions
  try { getDb().run(sql`ALTER TABLE chat_sessions ADD COLUMN user_id TEXT`); } catch {}

  // Auto-create admin user from AUTH_TOKEN
  const authToken = process.env.AUTH_TOKEN;
  if (authToken) {
    const existing = getDb()
      .select()
      .from(schema.users)
      .where(eq(schema.users.token, authToken))
      .get();
    if (!existing) {
      getDb().insert(schema.users).values({
        id: crypto.randomUUID(),
        name: "Admin",
        role: "admin",
        token: authToken,
        createdAt: new Date(),
      }).run();
    }
  }

  getDb().run(sql`
    CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY,
      type TEXT NOT NULL DEFAULT 'once',
      prompt TEXT NOT NULL,
      next_run_at INTEGER NOT NULL,
      interval_ms INTEGER,
      output_channel TEXT NOT NULL DEFAULT 'log',
      status TEXT NOT NULL DEFAULT 'active',
      last_run_at INTEGER,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    )
  `);

  getDb().run(sql`
    CREATE TABLE IF NOT EXISTS dashboard_widgets (
      id TEXT PRIMARY KEY,
      type TEXT NOT NULL,
      title TEXT NOT NULL,
      size TEXT NOT NULL DEFAULT 'half',
      config TEXT NOT NULL,
      position INTEGER NOT NULL DEFAULT 0,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    )
  `);

  // Dashboard tabs
  getDb().run(sql`
    CREATE TABLE IF NOT EXISTS dashboard_tabs (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      position INTEGER NOT NULL DEFAULT 0,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    )
  `);

  // Add tab_id column to dashboard_widgets
  try { getDb().run(sql`ALTER TABLE dashboard_widgets ADD COLUMN tab_id TEXT`); } catch {}

  // Add filters column to dashboard_tabs
  try { getDb().run(sql`ALTER TABLE dashboard_tabs ADD COLUMN filters TEXT`); } catch {}

  // Add content + chat_session_id columns to jobs (for direct-send and context resume)
  try { getDb().run(sql`ALTER TABLE jobs ADD COLUMN content TEXT`); } catch {}
  try { getDb().run(sql`ALTER TABLE jobs ADD COLUMN chat_session_id TEXT`); } catch {}

  // Tab refresh columns
  try { getDb().run(sql`ALTER TABLE dashboard_tabs ADD COLUMN refresh_prompt TEXT`); } catch {}
  try { getDb().run(sql`ALTER TABLE dashboard_tabs ADD COLUMN refresh_interval_ms INTEGER`); } catch {}
  try { getDb().run(sql`ALTER TABLE dashboard_tabs ADD COLUMN last_refreshed_at INTEGER`); } catch {}

  // Signal store
  getDb().run(sql`
    CREATE TABLE IF NOT EXISTS signals (
      id TEXT PRIMARY KEY,
      source TEXT NOT NULL,
      type TEXT NOT NULL,
      data TEXT NOT NULL,
      summary TEXT,
      created_at INTEGER NOT NULL
    )
  `);
  getDb().run(sql`CREATE INDEX IF NOT EXISTS idx_signals_source ON signals(source, type)`);
  getDb().run(sql`CREATE INDEX IF NOT EXISTS idx_signals_time ON signals(created_at)`);

  // Insights
  getDb().run(sql`
    CREATE TABLE IF NOT EXISTS insights (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      summary TEXT NOT NULL,
      signal_ids TEXT,
      category TEXT NOT NULL DEFAULT 'recommendation',
      priority TEXT NOT NULL DEFAULT 'medium',
      status TEXT NOT NULL DEFAULT 'new',
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    )
  `);
  getDb().run(sql`CREATE INDEX IF NOT EXISTS idx_insights_status ON insights(status)`);

  // --- Multi-Agent System ---

  getDb().run(sql`
    CREATE TABLE IF NOT EXISTS sub_agents (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL UNIQUE,
      display_name TEXT NOT NULL,
      domain TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'active',
      schedule_interval_ms INTEGER NOT NULL,
      last_run_at INTEGER,
      next_run_at INTEGER,
      memory_partition TEXT NOT NULL,
      config TEXT,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    )
  `);

  getDb().run(sql`
    CREATE TABLE IF NOT EXISTS escalations (
      id TEXT PRIMARY KEY,
      agent_id TEXT NOT NULL,
      urgency TEXT NOT NULL DEFAULT 'info',
      category TEXT NOT NULL,
      title TEXT NOT NULL,
      summary TEXT NOT NULL,
      data TEXT,
      status TEXT NOT NULL DEFAULT 'pending',
      synthesized_in TEXT,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    )
  `);
  getDb().run(sql`CREATE INDEX IF NOT EXISTS idx_escalations_status ON escalations(status)`);
  getDb().run(sql`CREATE INDEX IF NOT EXISTS idx_escalations_agent ON escalations(agent_id)`);
  getDb().run(sql`CREATE INDEX IF NOT EXISTS idx_escalations_urgency ON escalations(urgency)`);

  getDb().run(sql`
    CREATE TABLE IF NOT EXISTS kpis (
      id TEXT PRIMARY KEY,
      agent_id TEXT,
      name TEXT NOT NULL,
      display_name TEXT NOT NULL,
      target_value INTEGER NOT NULL,
      current_value INTEGER,
      unit TEXT NOT NULL,
      direction TEXT NOT NULL DEFAULT 'higher_is_better',
      threshold_warning INTEGER,
      threshold_critical INTEGER,
      measured_at INTEGER,
      status TEXT NOT NULL DEFAULT 'on-track',
      history TEXT,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    )
  `);
  getDb().run(sql`CREATE INDEX IF NOT EXISTS idx_kpis_agent ON kpis(agent_id)`);

  getDb().run(sql`
    CREATE TABLE IF NOT EXISTS synthesis_runs (
      id TEXT PRIMARY KEY,
      escalations_processed TEXT,
      summary TEXT NOT NULL,
      actions TEXT,
      created_at INTEGER NOT NULL
    )
  `);

  // Synthesis run: add chat_session_id for reply/discussion
  try { getDb().run(sql`ALTER TABLE synthesis_runs ADD COLUMN chat_session_id TEXT`); } catch {}

  // Action queue (agent-proposed actions requiring human approval)
  getDb().run(sql`
    CREATE TABLE IF NOT EXISTS actions (
      id TEXT PRIMARY KEY,
      type TEXT NOT NULL,
      title TEXT NOT NULL,
      description TEXT NOT NULL,
      payload TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      source_insight_id TEXT,
      source_escalation_id TEXT,
      execution_result TEXT,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    )
  `);
  getDb().run(sql`CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status)`);
}

// Helper to generate IDs
export function newId(): string {
  return crypto.randomUUID();
}
