/**
 * Synthesis loop — the Head of Product reads escalations and produces cross-domain analysis.
 */

import { getDb, newId } from "../db/index.ts";
import { escalations, synthesisRuns, chatSessions, messages } from "../db/schema.ts";
import { eq, and, desc } from "drizzle-orm";
import { chat } from "../agent/core.ts";
import { buildSynthesisConfig } from "./registry.ts";
import { sendSlackMessage } from "../tools/slack.ts";

const SYNTHESIS_INTERVAL_MS = 2 * 60 * 60 * 1000; // 2 hours
let lastSynthesisAt = 0;

/**
 * Check whether synthesis should run.
 * Triggers on:
 * 1. Regular interval (every 2 hours)
 * 2. Critical escalation exists
 */
export function shouldRunSynthesis(): boolean {
  const db = getDb();
  const now = Date.now();

  // Check for critical escalations
  const criticalCount = db.select()
    .from(escalations)
    .where(and(
      eq(escalations.status, "pending"),
      eq(escalations.urgency, "critical"),
    ))
    .all().length;

  if (criticalCount > 0) {
    console.log(`[synthesis] Triggered by ${criticalCount} critical escalation(s)`);
    return true;
  }

  // Check regular interval
  if (now - lastSynthesisAt >= SYNTHESIS_INTERVAL_MS) {
    // Only run if there are pending escalations
    const pendingCount = db.select()
      .from(escalations)
      .where(eq(escalations.status, "pending"))
      .all().length;

    if (pendingCount > 0) {
      console.log(`[synthesis] Regular interval — ${pendingCount} pending escalation(s)`);
      return true;
    }
  }

  return false;
}

/**
 * Run the synthesis loop.
 */
export async function runSynthesis(): Promise<void> {
  const db = getDb();
  const now = new Date();
  lastSynthesisAt = Date.now();

  // Get pending escalations
  const pending = db.select()
    .from(escalations)
    .where(eq(escalations.status, "pending"))
    .orderBy(desc(escalations.createdAt))
    .all();

  if (pending.length === 0) {
    console.log("[synthesis] No pending escalations — skipping");
    return;
  }

  console.log(`[synthesis] Starting synthesis with ${pending.length} escalation(s)`);

  // Build escalation summary for the prompt
  const escalationSummary = pending.map(e =>
    `### [${e.urgency.toUpperCase()}] ${e.title}\n- **Agent**: ${e.agentId}\n- **Category**: ${e.category}\n- **Created**: ${e.createdAt.toISOString()}\n\n${e.summary}`
  ).join("\n\n---\n\n");

  const config = buildSynthesisConfig();
  const prompt = `Run your synthesis cycle now. Current time: ${now.toISOString()}

## Pending Escalations (${pending.length})

${escalationSummary}

---

Now: read each sub-agent's state.md, cross-reference the escalations, query KPI signals, and produce your synthesis. Focus on connections between domains that individual agents can't see. Be specific and actionable.`;

  // Create session
  const sessionId = newId();
  db.insert(chatSessions).values({
    id: sessionId,
    name: `[Synthesis] ${now.toISOString().split("T")[0]} ${now.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })}`,
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

  try {
    for await (const msg of chat(prompt, config)) {
      if (msg.type === "partial") {
        fullResponse += msg.content;
      }
    }
  } catch (err) {
    fullResponse = `[Synthesis Error] ${err instanceof Error ? err.message : String(err)}`;
    console.error("[synthesis] Failed:", err);
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

  // Record synthesis run
  const runId = newId();
  db.insert(synthesisRuns).values({
    id: runId,
    escalationsProcessed: pending.map(e => e.id),
    summary: fullResponse.slice(0, 2000),
    createdAt: new Date(),
  }).run();

  // Mark escalations as synthesized
  for (const esc of pending) {
    db.update(escalations)
      .set({ status: "synthesized", synthesizedIn: runId, updatedAt: new Date() })
      .where(eq(escalations.id, esc.id))
      .run();
  }

  // Send Slack alert if there were urgent/critical items
  const hasUrgent = pending.some(e => e.urgency === "critical" || e.urgency === "urgent");
  if (hasUrgent && fullResponse) {
    const slackSummary = `*Synthesis Report* (${pending.length} escalations processed)\n\n${fullResponse.slice(0, 1500)}`;
    await sendSlackMessage(slackSummary);
  }

  console.log(`[synthesis] Complete — processed ${pending.length} escalations`);
}
