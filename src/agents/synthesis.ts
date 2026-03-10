/**
 * Synthesis loop — the Head of Product reads escalations and produces cross-domain analysis.
 *
 * Event-driven: synthesis triggers when escalation thresholds are met,
 * not on a fixed timer. The Head of Product can also schedule its own
 * next run via the scheduler after each synthesis.
 */

import { getDb, newId } from "../db/index.ts";
import { escalations, synthesisRuns, chatSessions, messages } from "../db/schema.ts";
import { eq, and, desc } from "drizzle-orm";
import { chat } from "../agent/core.ts";
import { buildSynthesisConfig } from "./registry.ts";
import { sendSlackMessage } from "../tools/slack.ts";

// Event-driven thresholds
const ESCALATION_THRESHOLD = 3; // Run synthesis when N+ pending escalations accumulate
const COOLDOWN_MS = 30 * 60 * 1000; // Minimum 30 min between synthesis runs (prevents rapid re-triggers)
let lastSynthesisAt = 0;

/**
 * Check whether synthesis should run.
 * Event-driven triggers:
 * 1. Any critical escalation exists (immediate)
 * 2. N+ pending escalations accumulated (batch)
 * 3. Manual trigger (critical escalation from agentId="manual")
 */
export function shouldRunSynthesis(): boolean {
  const db = getDb();
  const now = Date.now();

  // Respect cooldown (except for critical)
  const withinCooldown = now - lastSynthesisAt < COOLDOWN_MS;

  const pendingEscalations = db.select()
    .from(escalations)
    .where(eq(escalations.status, "pending"))
    .all();

  if (pendingEscalations.length === 0) return false;

  // Critical escalations bypass cooldown
  const hasCritical = pendingEscalations.some(e => e.urgency === "critical");
  if (hasCritical) {
    console.log(`[synthesis] Triggered by critical escalation`);
    return true;
  }

  // Within cooldown, don't trigger for non-critical
  if (withinCooldown) return false;

  // Urgent escalations trigger immediately (outside cooldown)
  const hasUrgent = pendingEscalations.some(e => e.urgency === "urgent");
  if (hasUrgent) {
    console.log(`[synthesis] Triggered by urgent escalation`);
    return true;
  }

  // Batch threshold: enough pending escalations accumulated
  if (pendingEscalations.length >= ESCALATION_THRESHOLD) {
    console.log(`[synthesis] Triggered by ${pendingEscalations.length} pending escalations (threshold: ${ESCALATION_THRESHOLD})`);
    return true;
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

Now: read each sub-agent's state.md, cross-reference the escalations, query KPI signals, and produce your synthesis. Focus on connections between domains that individual agents can't see. Be specific and actionable.

After completing your synthesis, decide when the next synthesis should run based on what you found:
- If things are stable, you can schedule yourself to run in 4-6 hours
- If there are emerging issues, schedule for 1-2 hours
- If things are critical, schedule for 30-60 minutes
Use agents_set_schedule or the scheduler to set your next run.`;

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
  const textBlocks: string[] = []; // Completed text blocks (final responses, not narration)

  try {
    for await (const msg of chat(prompt, config)) {
      if (msg.type === "partial") {
        fullResponse += msg.content;
      } else if (msg.type === "text" && msg.content) {
        textBlocks.push(msg.content);
      }
    }
  } catch (err) {
    fullResponse = `[Synthesis Error] ${err instanceof Error ? err.message : String(err)}`;
    console.error("[synthesis] Failed:", err);
  }

  // Save full response (including narration) to chat session for audit
  if (fullResponse) {
    db.insert(messages).values({
      id: newId(),
      chatSessionId: sessionId,
      role: "assistant",
      content: fullResponse,
      createdAt: new Date(),
    }).run();
  }

  // For the synthesis summary, use the last substantial text block (the actual report)
  // rather than the full streaming output which includes narration between tool calls.
  // Fall back to the full response if no text blocks captured.
  const summarySource = textBlocks.length > 0
    ? (textBlocks.filter(b => b.length > 100).pop() ?? textBlocks[textBlocks.length - 1] ?? fullResponse)
    : fullResponse;

  // Record synthesis run (store up to 8000 chars to avoid cutting off reports)
  const runId = newId();
  db.insert(synthesisRuns).values({
    id: runId,
    escalationsProcessed: pending.map(e => e.id),
    summary: summarySource.slice(0, 8000),
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
