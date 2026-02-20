import { getDb } from "../db/index.ts";
import { dashboardTabs } from "../db/schema.ts";
import { eq, and, isNotNull } from "drizzle-orm";
import { chat, type AgentConfig } from "../agent/core.ts";
import { buildSystemPrompt } from "../agent/system-prompt.ts";
import { createGitHubMcpServer, createKnowledgeMcpServer, createDashboardMcpServer } from "../tools/index.ts";

const TAB_REFRESH_CHECK_MS = 60_000; // check every 60s
let running = false;

/**
 * Refresh a single tab by running its refresh prompt through a lightweight agent.
 * Only github + knowledge + dashboard tools are available (no slack, scheduler, sandbox).
 */
export async function refreshTab(tab: { id: string; name: string; refreshPrompt: string | null }): Promise<void> {
  if (!tab.refreshPrompt) return;

  console.log(`[tab-refresh] Refreshing tab "${tab.name}" (${tab.id})`);

  const config: AgentConfig = {
    systemPrompt: buildSystemPrompt(),
    mcpServers: {
      github: createGitHubMcpServer(),
      knowledge: createKnowledgeMcpServer(),
      dashboard: createDashboardMcpServer(),
    },
    allowedTools: ["mcp__github__*", "mcp__knowledge__*", "mcp__dashboard__*"],
    model: process.env.AGENT_MODEL || "google/gemini-3-flash-preview",
  };

  const prompt = `Refresh the dashboard tab "${tab.name}" (id: ${tab.id}). ${tab.refreshPrompt}`;

  try {
    for await (const _msg of chat(prompt, config)) {
      // consume stream — we only care about side effects (dashboard tool calls)
    }

    getDb()
      .update(dashboardTabs)
      .set({ lastRefreshedAt: new Date(), updatedAt: new Date() })
      .where(eq(dashboardTabs.id, tab.id))
      .run();

    console.log(`[tab-refresh] Tab "${tab.name}" refreshed`);
  } catch (error) {
    console.error(`[tab-refresh] Failed to refresh tab ${tab.id}:`, error);
  }
}

async function refreshDueTabs(): Promise<void> {
  const now = Date.now();
  const db = getDb();

  const tabs = db
    .select()
    .from(dashboardTabs)
    .where(and(
      isNotNull(dashboardTabs.refreshPrompt),
      isNotNull(dashboardTabs.refreshIntervalMs),
    ))
    .all();

  for (const tab of tabs) {
    const lastRefresh = tab.lastRefreshedAt?.getTime() || 0;
    const interval = tab.refreshIntervalMs || 0;
    if (interval <= 0) continue;
    if (now < lastRefresh + interval) continue;

    await refreshTab(tab);
  }
}

/**
 * Start the tab refresh background loop.
 */
export function startTabRefreshLoop(): void {
  if (running) return;
  running = true;

  console.log(`[tab-refresh] Loop started (checking every ${TAB_REFRESH_CHECK_MS / 1000}s)`);

  setTimeout(async () => {
    await refreshDueTabs().catch((err) => console.error("[tab-refresh] Error:", err));
    setInterval(async () => {
      try {
        await refreshDueTabs();
      } catch (err) {
        console.error("[tab-refresh] Tick error:", err);
      }
    }, TAB_REFRESH_CHECK_MS);
  }, 10_000); // 10s delay — let server start first
}
