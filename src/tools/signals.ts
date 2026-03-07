import { z } from "zod/v4";
import {
  createSdkMcpServer,
  tool,
  type McpSdkServerConfigWithInstance,
} from "@anthropic-ai/claude-agent-sdk";
import { getDb, newId } from "../db/index.ts";
import { signals, insights } from "../db/schema.ts";
import { eq, desc, and, gte, like } from "drizzle-orm";

/**
 * Signal Store MCP Server — ingests signals from external tools and tracks insights.
 *
 * Signals: raw data points from connected services (analytics, revenue, app stores, etc.)
 * Insights: agent-generated analysis and recommendations derived from signals.
 *
 * External MCP servers (GA, Stripe, etc.) call store_signal to push data.
 * The intelligence loop queries signals and creates insights.
 */

// --- Signal Tools ---

const storeSignal = tool(
  "signal_store",
  "Store a signal from an external data source. Signals are raw data points (metrics, events, reviews) that feed the intelligence loop.",
  {
    source: z.string().describe("Source identifier (e.g. 'google-analytics', 'stripe', 'app-store', 'github', 'posthog')"),
    type: z.string().describe("Signal type (e.g. 'metric', 'event', 'review', 'anomaly', 'revenue')"),
    data: z.string().describe("JSON string of the signal data"),
    summary: z.string().optional().describe("Human-readable one-line summary of the signal"),
  },
  async ({ source, type, data, summary }) => {
    const db = getDb();
    const id = newId();
    const now = new Date();

    db.insert(signals)
      .values({
        id,
        source,
        type,
        data,
        summary: summary || null,
        createdAt: now,
      })
      .run();

    return {
      content: [{ type: "text" as const, text: `Signal stored: ${id} (${source}/${type})` }],
    };
  },
  { annotations: { readOnly: false, destructive: false } }
);

const querySignals = tool(
  "signal_query",
  "Query stored signals. Filter by source, type, or time range. Returns most recent first.",
  {
    source: z.string().optional().describe("Filter by source (e.g. 'stripe')"),
    type: z.string().optional().describe("Filter by type (e.g. 'revenue')"),
    since_hours: z.number().optional().describe("Only signals from the last N hours (default: 24)"),
    limit: z.number().optional().describe("Max results (default: 20)"),
  },
  async ({ source, type, since_hours, limit: maxResults }) => {
    const db = getDb();
    const hours = since_hours ?? 24;
    const lim = maxResults ?? 20;
    const since = new Date(Date.now() - hours * 60 * 60 * 1000);

    const conditions = [gte(signals.createdAt, since)];
    if (source) conditions.push(eq(signals.source, source));
    if (type) conditions.push(eq(signals.type, type));

    const rows = db
      .select()
      .from(signals)
      .where(and(...conditions))
      .orderBy(desc(signals.createdAt))
      .limit(lim)
      .all();

    if (rows.length === 0) {
      return { content: [{ type: "text" as const, text: "No signals found matching the query." }] };
    }

    const output = rows.map(r =>
      `[${r.createdAt.toISOString()}] ${r.source}/${r.type}${r.summary ? ` — ${r.summary}` : ""}\n${r.data}`
    ).join("\n\n---\n\n");

    return { content: [{ type: "text" as const, text: `${rows.length} signals found:\n\n${output}` }] };
  },
  { annotations: { readOnly: true } }
);

const getSignalSources = tool(
  "signal_sources",
  "List all distinct signal sources and types with counts. Useful for understanding what data is available.",
  {},
  async () => {
    const db = getDb();
    const rows = db
      .select()
      .from(signals)
      .all();

    const sourceMap = new Map<string, number>();
    for (const r of rows) {
      const key = `${r.source}/${r.type}`;
      sourceMap.set(key, (sourceMap.get(key) || 0) + 1);
    }

    if (sourceMap.size === 0) {
      return { content: [{ type: "text" as const, text: "No signals stored yet." }] };
    }

    const output = [...sourceMap.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([key, count]) => `- ${key}: ${count} signals`)
      .join("\n");

    return { content: [{ type: "text" as const, text: output }] };
  },
  { annotations: { readOnly: true } }
);

// --- Insight Tools ---

const createInsight = tool(
  "insight_create",
  "Create an insight derived from signal analysis. Insights are recommendations or observations the agent surfaces to the user.",
  {
    title: z.string().describe("Short title for the insight"),
    summary: z.string().describe("Detailed analysis and recommendation"),
    signal_ids: z.string().optional().describe("Comma-separated signal IDs that informed this insight"),
    category: z.string().optional().describe("Category: 'anomaly', 'trend', 'recommendation', 'risk', 'opportunity'"),
    priority: z.string().optional().describe("Priority: 'low', 'medium', 'high', 'critical'"),
  },
  async ({ title, summary, signal_ids, category, priority }) => {
    const db = getDb();
    const id = newId();
    const now = new Date();

    db.insert(insights)
      .values({
        id,
        title,
        summary,
        signalIds: signal_ids || null,
        category: category || "recommendation",
        priority: priority || "medium",
        status: "new",
        createdAt: now,
        updatedAt: now,
      })
      .run();

    return {
      content: [{ type: "text" as const, text: `Insight created: ${id} — "${title}"` }],
    };
  },
  { annotations: { readOnly: false, destructive: false } }
);

const queryInsights = tool(
  "insight_query",
  "Query insights. Filter by status, category, or priority.",
  {
    status: z.string().optional().describe("Filter: 'new', 'acknowledged', 'actioned', 'dismissed'"),
    category: z.string().optional().describe("Filter: 'anomaly', 'trend', 'recommendation', 'risk', 'opportunity'"),
    limit: z.number().optional().describe("Max results (default: 10)"),
  },
  async ({ status, category, limit: maxResults }) => {
    const db = getDb();
    const lim = maxResults ?? 10;

    const conditions: any[] = [];
    if (status) conditions.push(eq(insights.status, status));
    if (category) conditions.push(eq(insights.category, category));

    const query = conditions.length > 0
      ? db.select().from(insights).where(and(...conditions))
      : db.select().from(insights);

    const rows = query
      .orderBy(desc(insights.createdAt))
      .limit(lim)
      .all();

    if (rows.length === 0) {
      return { content: [{ type: "text" as const, text: "No insights found." }] };
    }

    const output = rows.map(r =>
      `### ${r.title}\n- **Status**: ${r.status} | **Priority**: ${r.priority} | **Category**: ${r.category}\n- **Created**: ${r.createdAt.toISOString()}\n- **ID**: ${r.id}\n\n${r.summary}`
    ).join("\n\n---\n\n");

    return { content: [{ type: "text" as const, text: output }] };
  },
  { annotations: { readOnly: true } }
);

const updateInsight = tool(
  "insight_update",
  "Update an insight's status (e.g. mark as acknowledged, actioned, or dismissed).",
  {
    id: z.string().describe("Insight ID"),
    status: z.string().describe("New status: 'acknowledged', 'actioned', 'dismissed'"),
  },
  async ({ id, status }) => {
    const db = getDb();
    const existing = db.select().from(insights).where(eq(insights.id, id)).get();
    if (!existing) {
      return {
        content: [{ type: "text" as const, text: `Error: Insight not found: ${id}` }],
        isError: true,
      };
    }

    db.update(insights)
      .set({ status, updatedAt: new Date() })
      .where(eq(insights.id, id))
      .run();

    return {
      content: [{ type: "text" as const, text: `Insight ${id} updated to: ${status}` }],
    };
  },
  { annotations: { readOnly: false, destructive: false } }
);

// --- Export ---

const READ_TOOLS = [querySignals, getSignalSources, queryInsights];
const WRITE_TOOLS = [storeSignal, createInsight, updateInsight];

export const SIGNALS_WRITE_TOOL_NAMES = WRITE_TOOLS.map((t) => t.name);

export function createSignalsMcpServer(): McpSdkServerConfigWithInstance {
  return createSdkMcpServer({
    name: "signals",
    version: "0.1.0",
    tools: [...READ_TOOLS, ...WRITE_TOOLS],
  });
}
