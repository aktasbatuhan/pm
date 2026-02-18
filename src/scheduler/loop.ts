import { getDb, newId } from "../db/index.ts";
import { jobs } from "../db/schema.ts";
import { eq, lte, and } from "drizzle-orm";
import { chat, type AgentConfig } from "../agent/core.ts";
import { buildSystemPrompt } from "../agent/system-prompt.ts";
import { createGitHubMcpServer, createKnowledgeMcpServer, createSchedulerMcpServer, createSlackMcpServer, createVisualizationMcpServer } from "../tools/index.ts";
import { WRITE_TOOL_NAMES } from "../tools/index.ts";
import { getRemoteMcpServers } from "../tools/remote.ts";
import { sendSlackMessage } from "../tools/slack.ts";
import { chatSessions, messages } from "../db/schema.ts";

const CHECK_INTERVAL_MS = 30_000; // Check every 30 seconds
let running = false;

/**
 * Build an agent config for executing a scheduled job.
 * Each job gets its own MCP server instances.
 */
function buildJobAgentConfig(): AgentConfig {
  return {
    systemPrompt: buildSystemPrompt(),
    mcpServers: {
      github: createGitHubMcpServer(),
      knowledge: createKnowledgeMcpServer(),
      scheduler: createSchedulerMcpServer(),
      slack: createSlackMcpServer(),
      visualization: createVisualizationMcpServer(),
      ...getRemoteMcpServers(),
    },
    canUseTool: async (toolName) => {
      // Auto-allow all tools for scheduled jobs
      return { behavior: "allow" as const };
    },
    model: process.env.AGENT_MODEL || undefined,
  };
}

/**
 * Execute a single job: run the prompt through the agent, collect output, route to channel.
 */
async function executeJob(job: typeof jobs.$inferSelect): Promise<void> {
  const db = getDb();
  const now = new Date();

  console.log(`[scheduler] Executing job ${job.id}: ${job.prompt.slice(0, 60)}...`);

  // Create a session for this job run
  const sessionId = newId();
  db.insert(chatSessions)
    .values({
      id: sessionId,
      name: `[Job] ${job.prompt.slice(0, 40)}...`,
      createdAt: now,
      updatedAt: now,
    })
    .run();

  // Save the job prompt as a user message
  db.insert(messages)
    .values({
      id: newId(),
      chatSessionId: sessionId,
      role: "user",
      content: job.prompt,
      createdAt: now,
    })
    .run();

  const config = buildJobAgentConfig();
  let fullResponse = "";

  try {
    for await (const msg of chat(job.prompt, config)) {
      if (msg.type === "text" || msg.type === "partial") {
        fullResponse += msg.content;
      }
    }
  } catch (err) {
    fullResponse = `[Job Error] ${err instanceof Error ? err.message : String(err)}`;
    console.error(`[scheduler] Job ${job.id} failed:`, err);
  }

  // Save response
  if (fullResponse) {
    db.insert(messages)
      .values({
        id: newId(),
        chatSessionId: sessionId,
        role: "assistant",
        content: fullResponse,
        createdAt: new Date(),
      })
      .run();
  }

  // Route output to channel
  if (job.outputChannel === "slack" && fullResponse) {
    const sent = await sendSlackMessage(fullResponse);
    if (!sent) {
      console.warn(`[scheduler] Failed to send job ${job.id} output to Slack`);
    }
  }

  // Update job state
  if (job.type === "recurring" && job.intervalMs) {
    // Schedule next run
    const nextRun = new Date(now.getTime() + job.intervalMs);
    db.update(jobs)
      .set({ nextRunAt: nextRun, lastRunAt: now, updatedAt: now })
      .where(eq(jobs.id, job.id))
      .run();
    console.log(`[scheduler] Job ${job.id} next run: ${nextRun.toISOString()}`);
  } else {
    // One-time job — mark completed
    db.update(jobs)
      .set({ status: "completed", lastRunAt: now, updatedAt: now })
      .where(eq(jobs.id, job.id))
      .run();
    console.log(`[scheduler] Job ${job.id} completed`);
  }
}

/**
 * Check for due jobs and execute them.
 */
async function tick(): Promise<void> {
  const db = getDb();
  const now = new Date();

  const dueJobs = db
    .select()
    .from(jobs)
    .where(and(eq(jobs.status, "active"), lte(jobs.nextRunAt, now)))
    .all();

  for (const job of dueJobs) {
    try {
      await executeJob(job);
    } catch (err) {
      console.error(`[scheduler] Failed to execute job ${job.id}:`, err);
    }
  }
}

/**
 * Start the background job loop.
 */
export function startJobLoop(): void {
  if (running) return;
  running = true;

  console.log(`[scheduler] Job loop started (checking every ${CHECK_INTERVAL_MS / 1000}s)`);

  // Initial check after a short delay (let the server start first)
  setTimeout(async () => {
    await tick();
    // Then check on interval
    setInterval(async () => {
      try {
        await tick();
      } catch (err) {
        console.error("[scheduler] Tick error:", err);
      }
    }, CHECK_INTERVAL_MS);
  }, 5000);
}
