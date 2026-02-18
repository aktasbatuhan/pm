import { sqliteTable, text, integer } from "drizzle-orm/sqlite-core";

export const chatSessions = sqliteTable("chat_sessions", {
  id: text("id").primaryKey(),
  name: text("name").notNull(),
  sessionId: text("session_id"), // SDK session ID for resume
  slackChannelId: text("slack_channel_id"),
  slackThreadTs: text("slack_thread_ts"),
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp" }).notNull(),
});

export const messages = sqliteTable("messages", {
  id: text("id").primaryKey(),
  chatSessionId: text("chat_session_id")
    .notNull()
    .references(() => chatSessions.id),
  role: text("role").$type<"user" | "assistant" | "system">().notNull(),
  content: text("content").notNull(),
  metadata: text("metadata", { mode: "json" }).$type<Record<string, unknown>>(),
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
});

export const settings = sqliteTable("settings", {
  key: text("key").primaryKey(),
  value: text("value", { mode: "json" }).notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp" }).notNull(),
});

export type ChatSession = typeof chatSessions.$inferSelect;
export type NewChatSession = typeof chatSessions.$inferInsert;
export type Message = typeof messages.$inferSelect;
export type NewMessage = typeof messages.$inferInsert;
export const jobs = sqliteTable("jobs", {
  id: text("id").primaryKey(),
  type: text("type").$type<"once" | "recurring">().notNull(),
  prompt: text("prompt").notNull(),
  nextRunAt: integer("next_run_at", { mode: "timestamp" }).notNull(),
  intervalMs: integer("interval_ms"), // for recurring jobs
  outputChannel: text("output_channel").notNull().default("log"), // 'log', 'slack'
  status: text("status").$type<"active" | "paused" | "completed" | "cancelled">().notNull().default("active"),
  lastRunAt: integer("last_run_at", { mode: "timestamp" }),
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp" }).notNull(),
});

export type Setting = typeof settings.$inferSelect;
export type Job = typeof jobs.$inferSelect;
export type NewJob = typeof jobs.$inferInsert;
