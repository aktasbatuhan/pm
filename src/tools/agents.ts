/**
 * Agents MCP Server — manage sub-agents, escalation inbox, and KPIs.
 *
 * Gives the main agent and users control over the multi-agent system.
 */

import { z } from "zod/v4";
import {
  createSdkMcpServer,
  tool,
  type McpSdkServerConfigWithInstance,
} from "@anthropic-ai/claude-agent-sdk";
import { getDb, newId } from "../db/index.ts";
import { subAgents, escalations, kpis, synthesisRuns } from "../db/schema.ts";
import { eq, and, desc } from "drizzle-orm";

// --- Sub-agent management ---

const listSubAgents = tool(
  "agents_list",
  "List all sub-agents with their status, schedule, and last run time.",
  {},
  async () => {
    const agents = getDb().select().from(subAgents).all();
    if (agents.length === 0) {
      return { content: [{ type: "text" as const, text: "No sub-agents configured. They are seeded automatically when GitHub is configured." }] };
    }
    const output = agents.map(a =>
      `### ${a.displayName} (\`${a.name}\`)\n- **Status**: ${a.status}\n- **Domain**: ${a.domain}\n- **Schedule**: every ${(a.scheduleIntervalMs / 3600000).toFixed(1)}h\n- **Last run**: ${a.lastRunAt?.toISOString() || "never"}\n- **Next run**: ${a.nextRunAt?.toISOString() || "not scheduled"}`
    ).join("\n\n");
    return { content: [{ type: "text" as const, text: output }] };
  },
  { annotations: { readOnly: true } }
);

const pauseSubAgent = tool(
  "agents_pause",
  "Pause or resume a sub-agent.",
  {
    name: z.string().describe("Sub-agent name (e.g. 'sprint-health')"),
    action: z.enum(["pause", "resume"]).describe("Whether to pause or resume"),
  },
  async ({ name, action }) => {
    const db = getDb();
    const agent = db.select().from(subAgents).where(eq(subAgents.name, name)).get();
    if (!agent) return { content: [{ type: "text" as const, text: `Sub-agent not found: ${name}` }], isError: true };

    const newStatus = action === "pause" ? "paused" : "active";
    const updates: Record<string, unknown> = { status: newStatus, updatedAt: new Date() };
    if (action === "resume") {
      updates.nextRunAt = new Date(Date.now() + 60_000); // run in 1 min after resume
    }

    db.update(subAgents).set(updates as any).where(eq(subAgents.id, agent.id)).run();
    return { content: [{ type: "text" as const, text: `${agent.displayName} ${action}d.` }] };
  },
  { annotations: { readOnly: false } }
);

// --- Escalation inbox ---

const readEscalations = tool(
  "agents_escalation_inbox",
  "Read the escalation inbox. Shows pending escalations from sub-agents, ordered by urgency.",
  {
    status: z.string().optional().describe("Filter by status: 'pending', 'synthesized', 'actioned', 'dismissed' (default: 'pending')"),
    limit: z.number().optional().describe("Max results (default: 20)"),
  },
  async ({ status, limit: maxResults }) => {
    const db = getDb();
    const filterStatus = (status || "pending") as "pending" | "synthesized" | "actioned" | "dismissed";
    const lim = maxResults ?? 20;

    const rows = db.select()
      .from(escalations)
      .where(eq(escalations.status, filterStatus))
      .orderBy(desc(escalations.createdAt))
      .limit(lim)
      .all();

    if (rows.length === 0) {
      return { content: [{ type: "text" as const, text: `No ${filterStatus} escalations.` }] };
    }

    const output = rows.map(e =>
      `### [${e.urgency.toUpperCase()}] ${e.title}\n- **Agent**: ${e.agentId} | **Category**: ${e.category}\n- **Created**: ${e.createdAt.toISOString()}\n- **ID**: ${e.id}\n\n${e.summary}`
    ).join("\n\n---\n\n");

    return { content: [{ type: "text" as const, text: `${rows.length} ${filterStatus} escalation(s):\n\n${output}` }] };
  },
  { annotations: { readOnly: true } }
);

const updateEscalation = tool(
  "agents_escalation_update",
  "Update an escalation's status (e.g. mark as actioned or dismissed).",
  {
    id: z.string().describe("Escalation ID"),
    status: z.enum(["actioned", "dismissed"]).describe("New status"),
  },
  async ({ id, status }) => {
    const db = getDb();
    const existing = db.select().from(escalations).where(eq(escalations.id, id)).get();
    if (!existing) return { content: [{ type: "text" as const, text: `Escalation not found: ${id}` }], isError: true };

    db.update(escalations).set({ status, updatedAt: new Date() }).where(eq(escalations.id, id)).run();
    return { content: [{ type: "text" as const, text: `Escalation ${id} marked as ${status}.` }] };
  },
  { annotations: { readOnly: false } }
);

// --- KPI management ---

const listKpis = tool(
  "agents_kpi_list",
  "List all KPIs with current values, targets, and status.",
  {
    agent_name: z.string().optional().describe("Filter by sub-agent name (shows all if omitted)"),
  },
  async ({ agent_name }) => {
    const db = getDb();
    let rows;
    if (agent_name) {
      const agent = db.select().from(subAgents).where(eq(subAgents.name, agent_name)).get();
      if (!agent) return { content: [{ type: "text" as const, text: `Agent not found: ${agent_name}` }], isError: true };
      rows = db.select().from(kpis).where(eq(kpis.agentId, agent.id)).all();
    } else {
      rows = db.select().from(kpis).all();
    }

    if (rows.length === 0) {
      return { content: [{ type: "text" as const, text: "No KPIs configured." }] };
    }

    const output = rows.map(k => {
      const arrow = k.direction === "higher_is_better" ? "↑" : "↓";
      const current = k.currentValue != null ? `${k.currentValue}${k.unit === "percent" ? "%" : ` ${k.unit}`}` : "not measured";
      const target = `${k.targetValue}${k.unit === "percent" ? "%" : ` ${k.unit}`}`;
      return `- **${k.displayName}** ${arrow}: ${current} / target: ${target} — **${k.status}**`;
    }).join("\n");

    return { content: [{ type: "text" as const, text: output }] };
  },
  { annotations: { readOnly: true } }
);

const setKpi = tool(
  "agents_kpi_set",
  "Update a KPI's target or thresholds. Use this to adjust goals based on team performance.",
  {
    kpi_id: z.string().describe("KPI ID"),
    target_value: z.number().optional().describe("New target value"),
    threshold_warning: z.number().optional().describe("New warning threshold"),
    threshold_critical: z.number().optional().describe("New critical threshold"),
  },
  async ({ kpi_id, target_value, threshold_warning, threshold_critical }) => {
    const db = getDb();
    const existing = db.select().from(kpis).where(eq(kpis.id, kpi_id)).get();
    if (!existing) return { content: [{ type: "text" as const, text: `KPI not found: ${kpi_id}` }], isError: true };

    const updates: Record<string, unknown> = { updatedAt: new Date() };
    if (target_value != null) updates.targetValue = target_value;
    if (threshold_warning != null) updates.thresholdWarning = threshold_warning;
    if (threshold_critical != null) updates.thresholdCritical = threshold_critical;

    db.update(kpis).set(updates as any).where(eq(kpis.id, kpi_id)).run();
    return { content: [{ type: "text" as const, text: `KPI ${existing.displayName} updated.` }] };
  },
  { annotations: { readOnly: false } }
);

// --- Schedule management ---

const setSchedule = tool(
  "agents_set_schedule",
  `Change a sub-agent's run interval. Any agent can adjust its own schedule or the Head of Product can adjust any agent's schedule.

Guidelines for self-adjustment:
- Increase frequency (shorter interval) when: sprint end is near, critical issues detected, high activity period
- Decrease frequency (longer interval) when: stable period, no escalations, low project activity
- Minimum: 1 hour. Maximum: 24 hours.
- Also optionally set next_run_at to control when the next run happens (e.g. "run again in 30 minutes")`,
  {
    name: z.string().describe("Sub-agent name (e.g. 'sprint-health')"),
    interval_hours: z.number().optional().describe("New interval in hours (min: 1, max: 24)"),
    next_run_in_minutes: z.number().optional().describe("Schedule next run in N minutes from now (overrides normal schedule for one cycle)"),
  },
  async ({ name, interval_hours, next_run_in_minutes }) => {
    const db = getDb();
    const agent = db.select().from(subAgents).where(eq(subAgents.name, name)).get();
    if (!agent) return { content: [{ type: "text" as const, text: `Sub-agent not found: ${name}` }], isError: true };

    const updates: Record<string, unknown> = { updatedAt: new Date() };

    if (interval_hours != null) {
      const clamped = Math.max(1, Math.min(24, interval_hours));
      updates.scheduleIntervalMs = clamped * 3600000;
    }

    if (next_run_in_minutes != null) {
      const mins = Math.max(1, next_run_in_minutes);
      updates.nextRunAt = new Date(Date.now() + mins * 60000);
    }

    db.update(subAgents).set(updates as any).where(eq(subAgents.id, agent.id)).run();

    const parts: string[] = [];
    if (interval_hours != null) parts.push(`interval → ${Math.max(1, Math.min(24, interval_hours))}h`);
    if (next_run_in_minutes != null) parts.push(`next run → in ${Math.max(1, next_run_in_minutes)} min`);

    return { content: [{ type: "text" as const, text: `${agent.displayName} schedule updated: ${parts.join(", ")}` }] };
  },
  { annotations: { readOnly: false } }
);

// --- Synthesis ---

const triggerSynthesis = tool(
  "agents_run_synthesis",
  "Manually trigger a synthesis run. The Head of Product will analyze all pending escalations.",
  {},
  async () => {
    // We just return instructions — the actual synthesis is triggered via the loop
    // For now, mark a signal that triggers it
    const db = getDb();
    db.insert(escalations as any).values({
      id: newId(),
      agentId: "manual",
      urgency: "critical",
      category: "recommendation",
      title: "Manual synthesis requested",
      summary: "User or agent manually triggered a synthesis run.",
      status: "pending",
      createdAt: new Date(),
      updatedAt: new Date(),
    }).run();
    return { content: [{ type: "text" as const, text: "Synthesis triggered. It will run on the next scheduler tick (within 30 seconds)." }] };
  },
  { annotations: { readOnly: false } }
);

const recentSynthesis = tool(
  "agents_synthesis_history",
  "View recent synthesis runs and their summaries.",
  {
    limit: z.number().optional().describe("Max results (default: 5)"),
  },
  async ({ limit: maxResults }) => {
    const db = getDb();
    const lim = maxResults ?? 5;
    const rows = db.select().from(synthesisRuns).orderBy(desc(synthesisRuns.createdAt)).limit(lim).all();

    if (rows.length === 0) {
      return { content: [{ type: "text" as const, text: "No synthesis runs yet." }] };
    }

    const output = rows.map(r =>
      `### Synthesis — ${r.createdAt.toISOString()}\n- **Escalations processed**: ${(r.escalationsProcessed || []).length}\n\n${r.summary.slice(0, 500)}${r.summary.length > 500 ? "..." : ""}`
    ).join("\n\n---\n\n");

    return { content: [{ type: "text" as const, text: output }] };
  },
  { annotations: { readOnly: true } }
);

// --- Export ---

const READ_TOOLS = [listSubAgents, readEscalations, listKpis, recentSynthesis];
const WRITE_TOOLS = [pauseSubAgent, setSchedule, updateEscalation, setKpi, triggerSynthesis];

export const AGENTS_WRITE_TOOL_NAMES = WRITE_TOOLS.map(t => t.name);

export function createAgentsMcpServer(): McpSdkServerConfigWithInstance {
  return createSdkMcpServer({
    name: "agents",
    version: "0.1.0",
    tools: [...READ_TOOLS, ...WRITE_TOOLS],
  });
}
