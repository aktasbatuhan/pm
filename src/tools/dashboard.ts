import { z } from "zod/v4";
import {
  createSdkMcpServer,
  tool,
  type McpSdkServerConfigWithInstance,
} from "@anthropic-ai/claude-agent-sdk";
import { eq } from "drizzle-orm";

import { getDb, newId } from "../db/index.ts";
import { dashboardWidgets, dashboardTabs } from "../db/schema.ts";

// --- Helpers ---

interface TabOptions {
  filters?: Record<string, string> | null;
  refreshPrompt?: string | null;
  refreshIntervalMs?: number | null;
}

/** Get or create a tab, returning its ID. */
function ensureTab(tabName: string, opts?: TabOptions | Record<string, string> | null): string {
  const db = getDb();

  // Normalize: if opts is a plain filters object (legacy call), wrap it
  let options: TabOptions;
  if (opts === null || opts === undefined) {
    options = {};
  } else if ("refreshPrompt" in opts || "refreshIntervalMs" in opts || "filters" in opts) {
    options = opts as TabOptions;
  } else {
    options = { filters: opts as Record<string, string> };
  }

  // Check if tab with this name exists
  const existing = db
    .select()
    .from(dashboardTabs)
    .all()
    .find((t) => t.name.toLowerCase() === tabName.toLowerCase());

  if (existing) {
    const updates: Record<string, unknown> = { updatedAt: new Date() };
    if (options.filters !== undefined) updates.filters = options.filters;
    if (options.refreshPrompt !== undefined) updates.refreshPrompt = options.refreshPrompt;
    if (options.refreshIntervalMs !== undefined) updates.refreshIntervalMs = options.refreshIntervalMs;

    if (Object.keys(updates).length > 1) {
      db.update(dashboardTabs)
        .set(updates)
        .where(eq(dashboardTabs.id, existing.id))
        .run();
    }
    return existing.id;
  }

  // Create new tab at the end
  const allTabs = db.select({ position: dashboardTabs.position }).from(dashboardTabs).all();
  const nextPos = allTabs.length ? Math.max(...allTabs.map((t) => t.position)) + 1 : 0;

  const id = `tab-${newId().slice(0, 8)}`;
  const now = new Date();
  db.insert(dashboardTabs).values({
    id,
    name: tabName,
    position: nextPos,
    filters: options.filters || null,
    refreshPrompt: options.refreshPrompt || null,
    refreshIntervalMs: options.refreshIntervalMs || null,
    lastRefreshedAt: options.refreshPrompt ? now : null,
    createdAt: now,
    updatedAt: now,
  }).run();

  return id;
}

// --- Tools ---

const getStateTool = tool(
  "dashboard_get_state",
  `Get the current dashboard layout. Returns all tabs and their widgets.

The dashboard has a built-in "Project" tab (always first) showing auto-generated GitHub project data.
Agent-created tabs are listed with their widgets. Call this first to understand what the user currently sees.`,
  { _dummy: z.string().optional().describe("unused") },
  async () => {
    const db = getDb();
    const tabs = db.select().from(dashboardTabs).orderBy(dashboardTabs.position).all();
    const widgets = db.select().from(dashboardWidgets).orderBy(dashboardWidgets.position).all();

    const result = {
      builtin_tab: "Project (auto-generated from GitHub data, always first)",
      custom_tabs: tabs.map((tab) => ({
        id: tab.id,
        name: tab.name,
        position: tab.position,
        filters: tab.filters || null,
        refreshPrompt: tab.refreshPrompt || null,
        refreshIntervalMs: tab.refreshIntervalMs || null,
        lastRefreshedAt: tab.lastRefreshedAt?.toISOString() || null,
        widgets: widgets
          .filter((w) => w.tabId === tab.id)
          .map((w) => ({
            id: w.id,
            type: w.type,
            title: w.title,
            size: w.size,
            position: w.position,
            config: w.config,
          })),
      })),
    };

    return {
      content: [{
        type: "text" as const,
        text: result.custom_tabs.length
          ? JSON.stringify(result, null, 2)
          : "Dashboard has only the built-in Project tab (auto-generated from GitHub data). No custom tabs yet.",
      }],
    };
  },
  { annotations: { readOnly: true, destructive: false } }
);

const addWidgetTool = tool(
  "dashboard_add_widget",
  `Add a new widget to a dashboard tab. The widget appears in real-time.

Widget types and config shapes:
- "stat-card": { "value": "42", "label": "Items", "trend": "+5", "color": "green"|"red"|"yellow"|"default" }
- "chart": Same as render_chart config — { "type": "bar"|"line"|"doughnut"|"pie"|"radar", "data": { "labels": [...], "datasets": [...] } }
- "table": { "headers": ["Col1","Col2"], "rows": [["a","b"],["c","d"]] }
- "list": { "items": [{ "text": "Item 1", "color": "#00c853" }] }
- "markdown": { "content": "## Title\\nSome **markdown** text" }

Sizes: "quarter" (1/4 width, for stat cards), "half" (1/2 width), "full" (full width)`,
  {
    id: z.string().optional().describe("Widget ID (auto-generated if omitted). Use a readable slug like 'chart-velocity'."),
    type: z.enum(["stat-card", "chart", "table", "list", "markdown"]).describe("Widget type"),
    title: z.string().describe("Widget title displayed in the header"),
    config: z.string().describe("JSON string with widget-type-specific configuration"),
    size: z.enum(["quarter", "half", "full"]).optional().describe("Widget size (default: half)"),
    position: z.number().optional().describe("Display order (0 = first). Defaults to end."),
    tab_name: z.string().optional().describe("Name of the tab to add to. Creates a new tab if it doesn't exist. Defaults to 'Custom'."),
  },
  async ({ id, type, title, config, size, position, tab_name }) => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(config);
    } catch {
      return { content: [{ type: "text" as const, text: "Error: config must be valid JSON" }], isError: true };
    }

    const tabId = ensureTab(tab_name || "Custom");
    const widgetId = id || `${type}-${newId().slice(0, 8)}`;
    const widgetSize = size || (type === "stat-card" ? "quarter" : "half");

    let pos = position;
    if (pos === undefined) {
      const last = getDb()
        .select({ position: dashboardWidgets.position })
        .from(dashboardWidgets)
        .where(eq(dashboardWidgets.tabId, tabId))
        .all();
      pos = last.length ? Math.max(...last.map((w) => w.position)) + 1 : 0;
    }

    const now = new Date();
    getDb().insert(dashboardWidgets).values({
      id: widgetId,
      tabId,
      type,
      title,
      size: widgetSize,
      config: parsed,
      position: pos,
      createdAt: now,
      updatedAt: now,
    }).run();

    const tabName = tab_name || "Custom";
    return {
      content: [{
        type: "text" as const,
        text: `Widget added to tab "${tabName}": "${title}" (${type}, ${widgetSize}) at position ${pos}`,
      }],
    };
  },
  { annotations: { readOnly: false, destructive: false } }
);

const removeWidgetTool = tool(
  "dashboard_remove_widget",
  "Remove a widget from the dashboard by its ID.",
  {
    widget_id: z.string().describe("The ID of the widget to remove"),
  },
  async ({ widget_id }) => {
    const existing = getDb()
      .select()
      .from(dashboardWidgets)
      .where(eq(dashboardWidgets.id, widget_id))
      .get();

    if (!existing) {
      return { content: [{ type: "text" as const, text: `Widget "${widget_id}" not found` }], isError: true };
    }

    getDb().delete(dashboardWidgets).where(eq(dashboardWidgets.id, widget_id)).run();

    return {
      content: [{ type: "text" as const, text: `Widget removed: "${existing.title}" (${widget_id})` }],
    };
  },
  { annotations: { readOnly: false, destructive: true } }
);

const updateWidgetTool = tool(
  "dashboard_update_widget",
  "Update an existing widget's title, config, or size. Only the provided fields are changed.",
  {
    widget_id: z.string().describe("The ID of the widget to update"),
    title: z.string().optional().describe("New title"),
    config: z.string().optional().describe("New config as JSON string"),
    size: z.enum(["quarter", "half", "full"]).optional().describe("New size"),
  },
  async ({ widget_id, title, config, size }) => {
    const existing = getDb()
      .select()
      .from(dashboardWidgets)
      .where(eq(dashboardWidgets.id, widget_id))
      .get();

    if (!existing) {
      return { content: [{ type: "text" as const, text: `Widget "${widget_id}" not found` }], isError: true };
    }

    const updates: Record<string, unknown> = { updatedAt: new Date() };
    if (title) updates.title = title;
    if (size) updates.size = size;
    if (config) {
      try {
        updates.config = JSON.parse(config);
      } catch {
        return { content: [{ type: "text" as const, text: "Error: config must be valid JSON" }], isError: true };
      }
    }

    getDb().update(dashboardWidgets).set(updates).where(eq(dashboardWidgets.id, widget_id)).run();

    return {
      content: [{ type: "text" as const, text: `Widget updated: "${title || existing.title}" (${widget_id})` }],
    };
  },
  { annotations: { readOnly: false, destructive: false } }
);

const setLayoutTool = tool(
  "dashboard_set_layout",
  `Create a new dashboard tab with a full set of widgets. This does NOT replace the built-in Project tab — it creates a new tab alongside it.

Each widget in the array needs: id, type, title, size, config (as object, not string), position.
The tab_name is required — it becomes a new tab the user can switch to.

**Filtered tabs**: Set filters to create a tab that auto-generates default dashboard widgets from GitHub data filtered by the given criteria. When filters are set AND no widgets are provided, the frontend generates default widgets (stat cards + charts + tables) from the filtered project data. Useful for sprint-specific or assignee-specific views.

Filter keys: "sprint", "assignee", "priority", "status", "repo". Values are matched case-insensitively.`,
  {
    tab_name: z.string().describe("Name for the new dashboard tab (e.g. 'Sprint 56 Review', 'Team Workload')"),
    widgets: z.string().optional().describe("JSON array of widget objects: [{ id, type, title, size, config, position }]. Optional if filters are set — frontend will auto-generate widgets from filtered data."),
    filters: z.string().optional().describe('JSON object of filters to apply to GitHub data, e.g. {"sprint":"56"} or {"assignee":"alice","status":"In Progress"}. When set, the tab dynamically filters project data.'),
    refresh_prompt: z.string().optional().describe("A self-contained prompt that will be run to refresh this tab's data. E.g. 'Fetch all blocked items from Sprint 56 and update the tab with current counts and issue list'. When set, the tab becomes refreshable."),
    refresh_interval_minutes: z.number().optional().describe("Auto-refresh interval in minutes (e.g. 30 for every 30 minutes). Omit for manual-only refresh. Only used when refresh_prompt is set."),
  },
  async ({ tab_name, widgets, filters, refresh_prompt, refresh_interval_minutes }) => {
    // Parse filters if provided
    let parsedFilters: Record<string, string> | null = null;
    if (filters) {
      try {
        parsedFilters = JSON.parse(filters);
        if (typeof parsedFilters !== "object" || Array.isArray(parsedFilters)) throw new Error("not object");
      } catch {
        return { content: [{ type: "text" as const, text: "Error: filters must be a valid JSON object" }], isError: true };
      }
    }

    const refreshIntervalMs = refresh_interval_minutes ? Math.round(refresh_interval_minutes * 60000) : null;

    // If no widgets provided but filters are set, create a filtered tab (frontend auto-generates widgets)
    if (!widgets && parsedFilters) {
      const tabId = ensureTab(tab_name, {
        filters: parsedFilters,
        refreshPrompt: refresh_prompt || null,
        refreshIntervalMs,
      });
      // Clear any existing widgets — frontend will auto-generate from filtered data
      getDb().delete(dashboardWidgets).where(eq(dashboardWidgets.tabId, tabId)).run();

      const filterDesc = Object.entries(parsedFilters).map(([k, v]) => `${k}=${v}`).join(", ");
      return {
        content: [{
          type: "text" as const,
          text: `Dashboard tab "${tab_name}" created with filters: ${filterDesc}. The dashboard will auto-generate widgets from filtered GitHub data.`,
        }],
      };
    }

    // Parse widgets
    let parsed: Array<{ id?: string; type: string; title: string; size?: string; config: Record<string, unknown>; position?: number }>;
    try {
      parsed = JSON.parse(widgets || "[]");
      if (!Array.isArray(parsed)) throw new Error("not array");
    } catch {
      return { content: [{ type: "text" as const, text: "Error: widgets must be a valid JSON array" }], isError: true };
    }

    const tabId = ensureTab(tab_name, {
      filters: parsedFilters,
      refreshPrompt: refresh_prompt || null,
      refreshIntervalMs,
    });
    const now = new Date();

    // Clear existing widgets in this tab
    getDb().delete(dashboardWidgets).where(eq(dashboardWidgets.tabId, tabId)).run();

    // Insert all widgets
    for (let i = 0; i < parsed.length; i++) {
      const w = parsed[i]!;
      getDb().insert(dashboardWidgets).values({
        id: w.id || `widget-${newId().slice(0, 8)}`,
        tabId,
        type: (w.type || "chart") as "stat-card" | "chart" | "table" | "list" | "markdown",
        title: w.title || "Widget",
        size: (w.size || "half") as "quarter" | "half" | "full",
        config: w.config || {},
        position: w.position ?? i,
        createdAt: now,
        updatedAt: now,
      }).run();
    }

    const filterNote = parsedFilters ? ` (filters: ${Object.entries(parsedFilters).map(([k, v]) => `${k}=${v}`).join(", ")})` : "";
    return {
      content: [{
        type: "text" as const,
        text: `Dashboard tab "${tab_name}" created with ${parsed.length} widgets${filterNote}`,
      }],
    };
  },
  { annotations: { readOnly: false, destructive: false } }
);

// --- Export ---

export const DASHBOARD_TOOL_NAMES = [
  getStateTool.name,
  addWidgetTool.name,
  removeWidgetTool.name,
  updateWidgetTool.name,
  setLayoutTool.name,
];

export function createDashboardMcpServer(): McpSdkServerConfigWithInstance {
  return createSdkMcpServer({
    name: "dashboard",
    version: "0.1.0",
    tools: [getStateTool, addWidgetTool, removeWidgetTool, updateWidgetTool, setLayoutTool],
  });
}
