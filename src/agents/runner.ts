/**
 * Sub-agent runner — executes a sub-agent and promotes escalation signals.
 *
 * After each run, scans for signals with source="agent:<name>" type="escalation"
 * and promotes them into the escalations table for the synthesis loop.
 */

import { getDb, newId } from "../db/index.ts";
import { subAgents, escalations, signals, chatSessions, messages } from "../db/schema.ts";
import type { SubAgent } from "../db/schema.ts";
import { eq, and, gte, like } from "drizzle-orm";
import { desc } from "drizzle-orm";
import { chat } from "../agent/core.ts";
import { buildSubAgentConfig } from "./registry.ts";

export interface SubAgentRunResult {
  agentName: string;
  success: boolean;
  escalationsCreated: number;
  durationMs: number;
  error?: string;
}

/**
 * Run a single sub-agent.
 */
export async function runSubAgent(agent: SubAgent): Promise<SubAgentRunResult> {
  const startTime = Date.now();
  const db = getDb();
  const now = new Date();

  console.log(`[agents] Running sub-agent: ${agent.displayName}`);

  // Mark as running by advancing nextRunAt immediately (prevents re-trigger)
  const nextRun = new Date(now.getTime() + agent.scheduleIntervalMs);
  db.update(subAgents)
    .set({ nextRunAt: nextRun, updatedAt: now })
    .where(eq(subAgents.id, agent.id))
    .run();

  // Build config and prompt
  const config = buildSubAgentConfig(agent);
  const prompt = `Run your analysis cycle now. Check your domain, measure KPIs, update your state, and escalate anything that needs the Head of Product's attention. Current time: ${now.toISOString()}`;

  // Create a session for auditing
  const sessionId = newId();
  db.insert(chatSessions).values({
    id: sessionId,
    name: `[Agent] ${agent.displayName} — ${now.toISOString().split("T")[0]}`,
    createdAt: now,
    updatedAt: now,
  }).run();

  db.insert(messages).values({
    id: newId(),
    chatSessionId: sessionId,
    role: "user",
    content: prompt,
    createdAt: now,
  }).run();

  let fullResponse = "";
  let success = true;
  let error: string | undefined;

  try {
    for await (const msg of chat(prompt, config)) {
      if (msg.type === "partial") {
        fullResponse += msg.content;
      }
    }
  } catch (err) {
    success = false;
    error = err instanceof Error ? err.message : String(err);
    fullResponse = `[Agent Error] ${error}`;
    console.error(`[agents] ${agent.displayName} failed:`, err);
  }

  // Save response
  if (fullResponse) {
    db.insert(messages).values({
      id: newId(),
      chatSessionId: sessionId,
      role: "assistant",
      content: fullResponse,
      createdAt: new Date(),
    }).run();
  }

  // Promote escalation signals to escalations table
  const escalationsCreated = promoteEscalations(agent);

  // Update lastRunAt
  const completedAt = new Date();
  db.update(subAgents)
    .set({ lastRunAt: completedAt, updatedAt: completedAt })
    .where(eq(subAgents.id, agent.id))
    .run();

  const durationMs = Date.now() - startTime;
  console.log(`[agents] ${agent.displayName} completed in ${(durationMs / 1000).toFixed(1)}s — ${escalationsCreated} escalations`);

  return {
    agentName: agent.name,
    success,
    escalationsCreated,
    durationMs,
    error,
  };
}

/**
 * Scan for escalation signals from a sub-agent and promote them to the escalations table.
 * Returns the number of escalations created.
 */
function promoteEscalations(agent: SubAgent): number {
  const db = getDb();

  // Find unprocessed escalation signals from this agent
  // Convention: source="agent:<name>", type="escalation"
  const agentSource = `agent:${agent.name}`;
  const recentSignals = db.select()
    .from(signals)
    .where(and(
      eq(signals.source, agentSource),
      eq(signals.type, "escalation"),
    ))
    .orderBy(desc(signals.createdAt))
    .all();

  let count = 0;
  const now = new Date();

  for (const signal of recentSignals) {
    // Check if this signal was already promoted (by looking for matching escalation)
    const existing = db.select()
      .from(escalations)
      .where(and(
        eq(escalations.agentId, agent.id),
        eq(escalations.title, tryParseTitle(signal.data)),
      ))
      .all();

    // Skip if we already have an escalation with this exact title from this agent (dedup)
    const title = tryParseTitle(signal.data);
    if (!title) continue;

    // Only promote signals created in the last run window
    const windowMs = agent.scheduleIntervalMs + 60_000; // interval + 1 min buffer
    const windowStart = new Date(Date.now() - windowMs);
    if (signal.createdAt < windowStart) continue;

    // Check for existing escalation with same title that's still pending
    const alreadyExists = existing.some(e =>
      e.status === "pending" && e.title === title
    );
    if (alreadyExists) continue;

    try {
      const parsed = JSON.parse(signal.data);
      db.insert(escalations).values({
        id: newId(),
        agentId: agent.id,
        urgency: parsed.urgency || "info",
        category: parsed.category || "recommendation",
        title: parsed.title || "Untitled escalation",
        summary: parsed.summary || signal.summary || "",
        data: parsed.supporting_data || null,
        status: "pending",
        createdAt: now,
        updatedAt: now,
      }).run();
      count++;
    } catch {
      // Signal data wasn't valid escalation JSON — skip
      console.warn(`[agents] Skipping malformed escalation signal ${signal.id} from ${agent.name}`);
    }
  }

  return count;
}

function tryParseTitle(data: string): string {
  try {
    return JSON.parse(data).title || "";
  } catch {
    return "";
  }
}
