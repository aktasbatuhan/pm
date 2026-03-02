import { getDb, newId } from "../db/index.ts";
import { jobs } from "../db/schema.ts";
import { eq, lte, and } from "drizzle-orm";
import { chat, type AgentConfig } from "../agent/core.ts";
import { WORKSPACE_DIR } from "../agent/sandbox.ts";
import { buildSystemPrompt } from "../agent/system-prompt.ts";
import { createGitHubMcpServer, createKnowledgeMcpServer, createSchedulerMcpServer, createSlackMcpServer, createVisualizationMcpServer, createDashboardMcpServer, createSandboxMcpServer } from "../tools/index.ts";
import { getRemoteMcpServers } from "../tools/remote.ts";
import { sendSlackMessage } from "../tools/slack.ts";
import { chatSessions, messages } from "../db/schema.ts";

const CHECK_INTERVAL_MS = 30_000; // Check every 30 seconds
let running = false;

/**
 * Build an agent config for executing a scheduled job.
 * If a chatSessionId is provided, resume that session for context.
 */
function buildJobAgentConfig(resumeSessionId?: string): AgentConfig {
  // Look up SDK session ID for resume
  let sdkResumeId: string | undefined;
  if (resumeSessionId) {
    const session = getDb()
      .select()
      .from(chatSessions)
      .where(eq(chatSessions.id, resumeSessionId))
      .get();
    sdkResumeId = session?.sessionId ?? undefined;
  }

  return {
    systemPrompt: buildSystemPrompt(),
    mcpServers: {
      github: createGitHubMcpServer(),
      knowledge: createKnowledgeMcpServer(),
      scheduler: createSchedulerMcpServer(),
      slack: createSlackMcpServer(),
      visualization: createVisualizationMcpServer(),
      dashboard: createDashboardMcpServer(),
      sandbox: createSandboxMcpServer(),
      ...getRemoteMcpServers(),
    },
    resume: sdkResumeId,
    model: process.env.AGENT_MODEL || "google/gemini-3-flash-preview",
    workingDirectory: WORKSPACE_DIR,
  };
}

/**
 * Send content to the job's output channel.
 */
async function deliverOutput(job: typeof jobs.$inferSelect, content: string): Promise<void> {
  if (job.outputChannel === "slack" && content) {
    const sent = await sendSlackMessage(content);
    if (!sent) {
      console.warn(`[scheduler] Failed to send job ${job.id} output to Slack`);
    } else {
      console.log(`[scheduler] Job ${job.id} output sent to Slack`);
    }
  } else if (content) {
    console.log(`[scheduler] Job ${job.id} output (log):\n${content.slice(0, 500)}`);
  }
}

/**
 * Execute a single job.
 * - If job has `content`: just deliver the pre-composed message. No agent needed.
 * - If job has `prompt`: run the agent to generate a response, then deliver.
 */
async function executeJob(job: typeof jobs.$inferSelect): Promise<void> {
  const db = getDb();
  const now = new Date();

  // Immediately advance nextRunAt (or mark completed) BEFORE executing,
  // so the next tick() doesn't pick up this job again while it's running.
  if (job.type === "recurring" && job.intervalMs) {
    const nextRun = new Date(now.getTime() + job.intervalMs);
    db.update(jobs)
      .set({ nextRunAt: nextRun, updatedAt: now })
      .where(eq(jobs.id, job.id))
      .run();
  } else {
    db.update(jobs)
      .set({ status: "completed", updatedAt: now })
      .where(eq(jobs.id, job.id))
      .run();
  }

  console.log(`[scheduler] Executing job ${job.id} (${job.content ? "direct message" : "agent task"})`);

  if (job.content) {
    // Direct message — just deliver it
    await deliverOutput(job, job.content);
  } else {
    // Agent task — run the prompt through the agent
    const config = buildJobAgentConfig(job.chatSessionId ?? undefined);
    let fullResponse = "";

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

    db.insert(messages)
      .values({
        id: newId(),
        chatSessionId: sessionId,
        role: "user",
        content: job.prompt,
        createdAt: now,
      })
      .run();

    try {
      for await (const msg of chat(job.prompt, config)) {
        if (msg.type === "partial") {
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

    // Deliver output
    await deliverOutput(job, fullResponse);
  }

  // Record lastRunAt (nextRunAt was already advanced before execution)
  const completedAt = new Date();
  db.update(jobs)
    .set({ lastRunAt: completedAt, updatedAt: completedAt })
    .where(eq(jobs.id, job.id))
    .run();

  if (job.type === "recurring" && job.intervalMs) {
    const nextRun = db.select().from(jobs).where(eq(jobs.id, job.id)).get()?.nextRunAt;
    console.log(`[scheduler] Job ${job.id} done. Next run: ${nextRun ? new Date(nextRun).toISOString() : "unknown"}`);
  } else {
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
