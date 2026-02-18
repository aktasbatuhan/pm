import { Database } from "bun:sqlite";
import { drizzle } from "drizzle-orm/bun-sqlite";
import { sql } from "drizzle-orm";
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
}

// Helper to generate IDs
export function newId(): string {
  return crypto.randomUUID();
}
