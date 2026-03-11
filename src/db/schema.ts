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

// --- Multi-Agent System ---

export const subAgents = sqliteTable("sub_agents", {
  id: text("id").primaryKey(),
  name: text("name").notNull().unique(), // 'sprint-health', 'code-quality', etc.
  displayName: text("display_name").notNull(),
  domain: text("domain").notNull(), // description of what this agent owns
  status: text("status").$type<"active" | "paused" | "disabled">().notNull().default("active"),
  scheduleIntervalMs: integer("schedule_interval_ms").notNull(),
  lastRunAt: integer("last_run_at", { mode: "timestamp" }),
  nextRunAt: integer("next_run_at", { mode: "timestamp" }),
  memoryPartition: text("memory_partition").notNull(), // e.g. 'agents/sprint-health'
  config: text("config", { mode: "json" }).$type<Record<string, unknown>>(),
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp" }).notNull(),
});

export const escalations = sqliteTable("escalations", {
  id: text("id").primaryKey(),
  agentId: text("agent_id").notNull(),
  urgency: text("urgency").$type<"info" | "attention" | "urgent" | "critical">().notNull().default("info"),
  category: text("category").notNull(), // 'blocker', 'risk', 'opportunity', 'anomaly', 'kpi-breach', 'recommendation'
  title: text("title").notNull(),
  summary: text("summary").notNull(),
  data: text("data", { mode: "json" }).$type<Record<string, unknown>>(),
  status: text("status").$type<"pending" | "synthesized" | "actioned" | "dismissed">().notNull().default("pending"),
  synthesizedIn: text("synthesized_in"), // synthesis run ID
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp" }).notNull(),
});

export const kpis = sqliteTable("kpis", {
  id: text("id").primaryKey(),
  agentId: text("agent_id"), // NULL = org-level
  name: text("name").notNull(),
  displayName: text("display_name").notNull(),
  targetValue: integer("target_value").notNull(),
  currentValue: integer("current_value"),
  unit: text("unit").notNull(), // 'percent', 'hours', 'count', 'ratio'
  direction: text("direction").$type<"higher_is_better" | "lower_is_better">().notNull().default("higher_is_better"),
  thresholdWarning: integer("threshold_warning"),
  thresholdCritical: integer("threshold_critical"),
  measuredAt: integer("measured_at", { mode: "timestamp" }),
  status: text("status").$type<"on-track" | "at-risk" | "breached">().notNull().default("on-track"),
  history: text("history", { mode: "json" }).$type<Array<{ value: number; timestamp: number }>>(),
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp" }).notNull(),
});

export const synthesisRuns = sqliteTable("synthesis_runs", {
  id: text("id").primaryKey(),
  chatSessionId: text("chat_session_id"), // session ID for reply/discussion
  escalationsProcessed: text("escalations_processed", { mode: "json" }).$type<string[]>(),
  summary: text("summary").notNull(),
  actions: text("actions", { mode: "json" }).$type<Record<string, unknown>>(),
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
});

// --- Action Queue (agent-proposed actions requiring human approval) ---

export const actions = sqliteTable("actions", {
  id: text("id").primaryKey(),
  type: text("type").$type<"github_issue" | "github_comment" | "slack_dm" | "github_label" | "custom">().notNull(),
  title: text("title").notNull(),
  description: text("description").notNull(),
  payload: text("payload", { mode: "json" }).$type<Record<string, unknown>>().notNull(),
  status: text("status").$type<"pending" | "approved" | "rejected" | "executed" | "failed">().notNull().default("pending"),
  sourceInsightId: text("source_insight_id"),
  sourceEscalationId: text("source_escalation_id"),
  executionResult: text("execution_result"),
  createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp" }).notNull(),
});

export type SubAgent = typeof subAgents.$inferSelect;
export type Escalation = typeof escalations.$inferSelect;
export type Kpi = typeof kpis.$inferSelect;
export type SynthesisRun = typeof synthesisRuns.$inferSelect;
export type Action = typeof actions.$inferSelect;
