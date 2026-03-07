import { sqliteTable, text, integer } from "drizzle-orm/sqlite-core";

export const users = sqliteTable("users", {
  id: text("id").primaryKey(),
  name: text("name").notNull(),
  role: text("role").$type<"admin" | "member">().notNull().default("member"),
  token: text("token").notNull().unique(),
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
});

export const invites = sqliteTable("invites", {
  id: text("id").primaryKey(),
  token: text("token").notNull().unique(),
  createdBy: text("created_by").notNull(),
  usedBy: text("used_by"),
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
});

export const chatSessions = sqliteTable("chat_sessions", {
  id: text("id").primaryKey(),
  name: text("name").notNull(),
  sessionId: text("session_id"), // SDK session ID for resume
  userId: text("user_id"),
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
  content: text("content"), // pre-composed message — if set, scheduler sends directly without running agent
  chatSessionId: text("chat_session_id"), // original session for context resume
  nextRunAt: integer("next_run_at", { mode: "timestamp" }).notNull(),
  intervalMs: integer("interval_ms"), // for recurring jobs
  outputChannel: text("output_channel").notNull().default("log"), // 'log', 'slack'
  status: text("status").$type<"active" | "paused" | "completed" | "cancelled">().notNull().default("active"),
  lastRunAt: integer("last_run_at", { mode: "timestamp" }),
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp" }).notNull(),
});

export const dashboardTabs = sqliteTable("dashboard_tabs", {
  id: text("id").primaryKey(),
  name: text("name").notNull(),
  position: integer("position").notNull().default(0),
  filters: text("filters", { mode: "json" }).$type<Record<string, string> | null>(),
  refreshPrompt: text("refresh_prompt"),
  refreshIntervalMs: integer("refresh_interval_ms"),
  lastRefreshedAt: integer("last_refreshed_at", { mode: "timestamp" }),
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp" }).notNull(),
});

export const dashboardWidgets = sqliteTable("dashboard_widgets", {
  id: text("id").primaryKey(),
  tabId: text("tab_id"),
  type: text("type").$type<"stat-card" | "chart" | "table" | "list" | "markdown">().notNull(),
  title: text("title").notNull(),
  size: text("size").$type<"quarter" | "half" | "full">().notNull().default("half"),
  config: text("config", { mode: "json" }).$type<Record<string, unknown>>().notNull(),
  position: integer("position").notNull().default(0),
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp" }).notNull(),
});

export type User = typeof users.$inferSelect;
export type Invite = typeof invites.$inferSelect;
export type Setting = typeof settings.$inferSelect;
export type Job = typeof jobs.$inferSelect;
export type NewJob = typeof jobs.$inferInsert;
export type DashboardTab = typeof dashboardTabs.$inferSelect;
export type NewDashboardTab = typeof dashboardTabs.$inferInsert;
export type DashboardWidget = typeof dashboardWidgets.$inferSelect;
export type NewDashboardWidget = typeof dashboardWidgets.$inferInsert;

// --- Signal Store ---

export const signals = sqliteTable("signals", {
  id: text("id").primaryKey(),
  source: text("source").notNull(), // e.g. 'google-analytics', 'stripe', 'app-store'
  type: text("type").notNull(), // e.g. 'metric', 'event', 'review', 'revenue'
  data: text("data").notNull(), // JSON string
  summary: text("summary"), // human-readable one-liner
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
});

export const insights = sqliteTable("insights", {
  id: text("id").primaryKey(),
  title: text("title").notNull(),
  summary: text("summary").notNull(),
  signalIds: text("signal_ids"), // comma-separated signal IDs
  category: text("category").notNull().default("recommendation"), // anomaly, trend, recommendation, risk, opportunity
  priority: text("priority").notNull().default("medium"), // low, medium, high, critical
  status: text("status").notNull().default("new"), // new, acknowledged, actioned, dismissed
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp" }).notNull(),
});

export type Signal = typeof signals.$inferSelect;
export type NewSignal = typeof signals.$inferInsert;
export type Insight = typeof insights.$inferSelect;
export type NewInsight = typeof insights.$inferInsert;
