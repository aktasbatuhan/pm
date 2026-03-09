/**
 * Sub-agent registry — seeds defaults, queries agents, builds scoped configs.
 */

import { getDb, newId } from "../db/index.ts";
import { subAgents } from "../db/schema.ts";
import type { SubAgent } from "../db/schema.ts";
import { eq } from "drizzle-orm";
import type { AgentConfig } from "../agent/core.ts";
import {
  createGitHubMcpServer,
  createKnowledgeMcpServer,
  createMemoryMcpServer,
  createSignalsMcpServer,
  createIntelligenceMcpServer,
  createSchedulerMcpServer,
  createSlackMcpServer,
  createVisualizationMcpServer,
  createPostHogMcpServer,
  createActionsMcpServer,
  createAgentsMcpServer,
} from "../tools/index.ts";
import { createDashboardMcpServer } from "../tools/dashboard.ts";
import { getRemoteMcpServers } from "../tools/remote.ts";
import { WORKSPACE_DIR } from "../agent/sandbox.ts";
import {
  buildSprintHealthPrompt,
  buildCodeQualityPrompt,
  buildProductSignalsPrompt,
  buildTeamDynamicsPrompt,
  buildSynthesisPrompt,
} from "./prompts.ts";

// Hours to ms
const H = 60 * 60 * 1000;

interface AgentDefinition {
  name: string;
  displayName: string;
  domain: string;
  scheduleIntervalMs: number;
  memoryPartition: string;
}

const DEFAULT_AGENTS: AgentDefinition[] = [
  {
    name: "sprint-health",
    displayName: "Sprint Health Agent",
    domain: "Sprint velocity, completion rates, blocked items, delivery pace",
    scheduleIntervalMs: 4 * H,
    memoryPartition: "agents/sprint-health",
  },
  {
    name: "code-quality",
    displayName: "Code Quality Agent",
    domain: "PR health, review cycles, code quality signals, tech debt",
    scheduleIntervalMs: 6 * H,
    memoryPartition: "agents/code-quality",
  },
  {
    name: "product-signals",
    displayName: "Product Signals Agent",
    domain: "Analytics, user feedback, revenue signals, external product health",
    scheduleIntervalMs: 8 * H,
    memoryPartition: "agents/product-signals",
  },
  {
    name: "team-dynamics",
    displayName: "Team Dynamics Agent",
    domain: "Workload balance, contributor activity patterns, collaboration health",
    scheduleIntervalMs: 12 * H,
    memoryPartition: "agents/team-dynamics",
  },
];

/**
 * Seed default sub-agents and KPIs if the table is empty.
 */
export function initSubAgents(): void {
  const db = getDb();
  const existing = db.select().from(subAgents).all();
  if (existing.length > 0) return;

  const now = new Date();

  for (const def of DEFAULT_AGENTS) {
    const agentId = newId();
    // Stagger first runs so they don't all fire at once
    const staggerMs = DEFAULT_AGENTS.indexOf(def) * 5 * 60 * 1000; // 5 min apart
    const firstRun = new Date(now.getTime() + 60_000 + staggerMs); // start 1 min after boot, staggered

    db.insert(subAgents).values({
      id: agentId,
      name: def.name,
      displayName: def.displayName,
      domain: def.domain,
      status: "active",
      scheduleIntervalMs: def.scheduleIntervalMs,
      nextRunAt: firstRun,
      memoryPartition: def.memoryPartition,
      createdAt: now,
      updatedAt: now,
    }).run();

    console.log(`[agents] Seeded sub-agent: ${def.displayName} (first run: ${firstRun.toISOString()})`);
  }

  // KPIs are NOT seeded here — the main agent (Head of Product) sets them
  // during the first synthesis run after analyzing the actual project state.
  console.log("[agents] Sub-agents initialized. KPIs will be set by the Head of Product during first synthesis.");
}

/**
 * Get all sub-agents.
 */
export function getSubAgents(): SubAgent[] {
  return getDb().select().from(subAgents).all();
}

/**
 * Get a sub-agent by name.
 */
export function getSubAgent(name: string): SubAgent | undefined {
  return getDb().select().from(subAgents).where(eq(subAgents.name, name)).get();
}

/**
 * Build a scoped MCP server set for a sub-agent.
 */
function buildMcpServers(agentName: string): Record<string, ReturnType<typeof createGitHubMcpServer>> {
  const base: Record<string, ReturnType<typeof createGitHubMcpServer>> = {
    signals: createSignalsMcpServer(),
    memory: createMemoryMcpServer(),
    intelligence: createIntelligenceMcpServer(),
    agents: createAgentsMcpServer(),
  };

  switch (agentName) {
    case "sprint-health":
      base.github = createGitHubMcpServer();
      break;
    case "code-quality":
      base.github = createGitHubMcpServer();
      break;
    case "product-signals":
      base.posthog = createPostHogMcpServer();
      break;
    case "team-dynamics":
      base.github = createGitHubMcpServer();
      base.slack = createSlackMcpServer();
      break;
  }

  return base;
}

/**
 * Build allowed tools list for a sub-agent.
 */
function buildAllowedTools(agentName: string): string[] {
  // All sub-agents can read agent state and adjust their own schedule
  const base = [
    "mcp__signals__*", "mcp__memory__*", "mcp__intelligence__*",
    "mcp__agents__agents_list", "mcp__agents__agents_set_schedule",
    "mcp__agents__agents_kpi_list",
  ];

  switch (agentName) {
    case "sprint-health":
    case "code-quality":
      return [...base, "mcp__github__*"];
    case "product-signals":
      return [...base, "mcp__posthog__*", "mcp__github__*"];
    case "team-dynamics":
      return [...base, "mcp__github__*", "mcp__slack__*"];
    default:
      return base;
  }
}

/**
 * Build the system prompt for a sub-agent.
 */
function buildSubAgentSystemPrompt(agentName: string): string {
  const org = process.env.GITHUB_ORG || "unknown";
  const projectNumber = process.env.GITHUB_PROJECT_NUMBER || "0";

  switch (agentName) {
    case "sprint-health":
      return buildSprintHealthPrompt(org, projectNumber);
    case "code-quality":
      return buildCodeQualityPrompt(org);
    case "product-signals":
      return buildProductSignalsPrompt(org);
    case "team-dynamics":
      return buildTeamDynamicsPrompt(org);
    default:
      throw new Error(`Unknown sub-agent: ${agentName}`);
  }
}

/**
 * Build a full AgentConfig for running a sub-agent.
 */
export function buildSubAgentConfig(agent: SubAgent): AgentConfig {
  return {
    systemPrompt: buildSubAgentSystemPrompt(agent.name),
    mcpServers: buildMcpServers(agent.name),
    allowedTools: buildAllowedTools(agent.name),
    model: process.env.SUBAGENT_MODEL || process.env.AGENT_MODEL || "google/gemini-3-flash-preview",
    workingDirectory: WORKSPACE_DIR,
  };
}

/**
 * Build the synthesis agent config (Head of Product — has access to everything).
 */
export function buildSynthesisConfig(): AgentConfig {
  const org = process.env.GITHUB_ORG || "unknown";
  const projectNumber = process.env.GITHUB_PROJECT_NUMBER || "0";

  return {
    systemPrompt: buildSynthesisPrompt(org, projectNumber),
    mcpServers: {
      github: createGitHubMcpServer(),
      knowledge: createKnowledgeMcpServer(),
      scheduler: createSchedulerMcpServer(),
      slack: createSlackMcpServer(),
      visualization: createVisualizationMcpServer(),
      dashboard: createDashboardMcpServer(),
      memory: createMemoryMcpServer(),
      signals: createSignalsMcpServer(),
      intelligence: createIntelligenceMcpServer(),
      posthog: createPostHogMcpServer(),
      actions: createActionsMcpServer(),
      agents: createAgentsMcpServer(),
      ...getRemoteMcpServers(),
    },
    allowedTools: [
      "mcp__github__*", "mcp__knowledge__*", "mcp__scheduler__*",
      "mcp__slack__*", "mcp__visualization__*", "mcp__posthog__*",
      "mcp__dashboard__*", "mcp__memory__*", "mcp__signals__*",
      "mcp__intelligence__*", "mcp__actions__*", "mcp__agents__*",
    ],
    model: process.env.AGENT_MODEL || "google/gemini-3-flash-preview",
    workingDirectory: WORKSPACE_DIR,
  };
}
