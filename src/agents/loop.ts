/**
 * Sub-agent orchestration loop.
 *
 * Called from the main scheduler tick. Checks which sub-agents are due,
 * runs them sequentially, then checks if synthesis should trigger.
 */

import { getDb } from "../db/index.ts";
import { subAgents } from "../db/schema.ts";
import { and, eq, lte } from "drizzle-orm";
import { runSubAgent } from "./runner.ts";
import { shouldRunSynthesis, runSynthesis } from "./synthesis.ts";
import { initSubAgents } from "./registry.ts";

let initialized = false;
let running = false;

/**
 * Initialize sub-agents on first call (seeds defaults if needed).
 */
function ensureInitialized(): void {
  if (initialized) return;
  initialized = true;

  // Only initialize if GitHub is configured (agents need it)
  if (!process.env.GITHUB_ORG || !process.env.GITHUB_PROJECT_NUMBER) {
    console.log("[agents] Skipping init — GitHub not configured yet");
    return;
  }

  initSubAgents();
}

/**
 * Run all due sub-agents, then check synthesis trigger.
 * Called from the main scheduler loop alongside tick().
 */
export async function runDueSubAgents(): Promise<void> {
  // Don't run concurrently
  if (running) return;
  running = true;

  try {
    ensureInitialized();

    if (!process.env.GITHUB_ORG || !process.env.GITHUB_PROJECT_NUMBER) return;

    const db = getDb();
    const now = new Date();

    // Find due sub-agents
    const dueAgents = db.select()
      .from(subAgents)
      .where(and(
        eq(subAgents.status, "active"),
        lte(subAgents.nextRunAt, now),
      ))
      .all();

    if (dueAgents.length === 0 && !shouldRunSynthesis()) return;

    // Run sub-agents sequentially (avoid SQLite write contention)
    for (const agent of dueAgents) {
      try {
        await runSubAgent(agent);
      } catch (err) {
        console.error(`[agents] Failed to run ${agent.name}:`, err);
      }
    }

    // Check if synthesis should run
    if (shouldRunSynthesis()) {
      try {
        await runSynthesis();
      } catch (err) {
        console.error("[agents] Synthesis failed:", err);
      }
    }
  } finally {
    running = false;
  }
}
