import { z } from "zod/v4";
import {
  createSdkMcpServer,
  tool,
  type McpSdkServerConfigWithInstance,
} from "@anthropic-ai/claude-agent-sdk";
import { getDb, newId } from "../db/index.ts";
import { jobs } from "../db/schema.ts";
import { eq } from "drizzle-orm";

/**
 * Parse a human-readable duration string into milliseconds.
 * Supports: "30m", "4h", "1d", "7d", "12h", "90m"
 */
function parseDuration(duration: string): number | null {
  const match = duration.match(/^(\d+)\s*(m|min|h|hr|d|day|w|week)s?$/i);
  if (!match) return null;
  const value = parseInt(match[1]!);
  const unit = match[2]!.toLowerCase();
  switch (unit) {
    case "m":
    case "min":
      return value * 60 * 1000;
    case "h":
    case "hr":
      return value * 60 * 60 * 1000;
    case "d":
    case "day":
      return value * 24 * 60 * 60 * 1000;
    case "w":
    case "week":
      return value * 7 * 24 * 60 * 60 * 1000;
    default:
      return null;
  }
}

/**
 * Parse a "run_at" string into a Date.
 * Accepts:
 * - ISO timestamps: "2026-02-17T09:00:00Z"
 * - Relative durations: "in 4h", "in 30m", "in 1d"
 */
function parseRunAt(runAt: string): Date | null {
  // Relative: "in 4h", "in 30 minutes"
  const relativeMatch = runAt.match(/^in\s+(.+)$/i);
  if (relativeMatch) {
    const ms = parseDuration(relativeMatch[1]!.trim());
    if (ms) return new Date(Date.now() + ms);
    return null;
  }

  // ISO timestamp
  const date = new Date(runAt);
  if (!isNaN(date.getTime())) return date;

  // Try as duration directly (shorthand for "in X")
  const ms = parseDuration(runAt);
  if (ms) return new Date(Date.now() + ms);

  return null;
}

// --- Tools ---

const scheduleJobTool = tool(
  "schedule_job",
  `Schedule a job to run at a specific time or on a recurring interval.
The job will execute as a new agent conversation with the given prompt.
Output is routed to the specified channel (default: log, or slack if configured).

Examples:
- One-time: schedule_job(prompt="Check sprint health", run_at="in 4h", channel="slack")
- Recurring: schedule_job(prompt="Daily standup report", run_at="in 1d", recurring=true, interval="1d", channel="slack")`,
  {
    prompt: z.string().describe("The prompt/task to execute when the job fires"),
    run_at: z.string().describe("When to run: ISO timestamp (2026-02-17T09:00:00Z) or relative (in 4h, in 30m, in 1d)"),
    recurring: z.boolean().optional().describe("If true, job repeats on interval after first run"),
    interval: z.string().optional().describe("Repeat interval for recurring jobs (e.g. 30m, 4h, 1d, 7d)"),
    channel: z.string().optional().describe("Output channel: 'log' (default) or 'slack'"),
  },
  async ({ prompt, run_at, recurring, interval, channel }) => {
    const nextRun = parseRunAt(run_at);
    if (!nextRun) {
      return {
        content: [{ type: "text" as const, text: `Error: Could not parse run_at "${run_at}". Use ISO timestamp or relative like "in 4h".` }],
        isError: true,
      };
    }

    let intervalMs: number | undefined;
    if (recurring) {
      if (!interval) {
        return {
          content: [{ type: "text" as const, text: "Error: Recurring jobs require an interval (e.g. '4h', '1d')." }],
          isError: true,
        };
      }
      intervalMs = parseDuration(interval) ?? undefined;
      if (!intervalMs) {
        return {
          content: [{ type: "text" as const, text: `Error: Could not parse interval "${interval}". Use format like "30m", "4h", "1d".` }],
          isError: true,
        };
      }
    }

    const db = getDb();
    const id = newId();
    const now = new Date();

    db.insert(jobs)
      .values({
        id,
        type: recurring ? "recurring" : "once",
        prompt,
        nextRunAt: nextRun,
        intervalMs: intervalMs,
        outputChannel: channel || "log",
        status: "active",
        createdAt: now,
        updatedAt: now,
      })
      .run();

    const result = {
      id,
      type: recurring ? "recurring" : "once",
      prompt: prompt.length > 80 ? prompt.slice(0, 80) + "..." : prompt,
      next_run: nextRun.toISOString(),
      interval: interval || null,
      channel: channel || "log",
    };

    return {
      content: [{ type: "text" as const, text: `Job scheduled:\n${JSON.stringify(result, null, 2)}` }],
    };
  },
  { annotations: { readOnly: false, destructive: false } }
);

const listJobsTool = tool(
  "list_jobs",
  "List all active scheduled jobs",
  {},
  async () => {
    const db = getDb();
    const allJobs = db
      .select()
      .from(jobs)
      .where(eq(jobs.status, "active"))
      .all();

    if (allJobs.length === 0) {
      return { content: [{ type: "text" as const, text: "No active jobs." }] };
    }

    const list = allJobs.map((j) => ({
      id: j.id,
      type: j.type,
      prompt: j.prompt.length > 80 ? j.prompt.slice(0, 80) + "..." : j.prompt,
      next_run: j.nextRunAt instanceof Date ? j.nextRunAt.toISOString() : new Date(j.nextRunAt as unknown as number).toISOString(),
      interval_ms: j.intervalMs,
      channel: j.outputChannel,
      last_run: j.lastRunAt ? (j.lastRunAt instanceof Date ? j.lastRunAt.toISOString() : new Date(j.lastRunAt as unknown as number).toISOString()) : null,
    }));

    return {
      content: [{ type: "text" as const, text: JSON.stringify(list, null, 2) }],
    };
  },
  { annotations: { readOnly: true } }
);

const cancelJobTool = tool(
  "cancel_job",
  "Cancel a scheduled job by ID",
  {
    id: z.string().describe("The job ID to cancel"),
  },
  async ({ id }) => {
    const db = getDb();
    const job = db.select().from(jobs).where(eq(jobs.id, id)).get();
    if (!job) {
      return {
        content: [{ type: "text" as const, text: `Error: Job ${id} not found.` }],
        isError: true,
      };
    }
    if (job.status !== "active") {
      return {
        content: [{ type: "text" as const, text: `Job ${id} is already ${job.status}.` }],
        isError: true,
      };
    }

    db.update(jobs)
      .set({ status: "cancelled", updatedAt: new Date() })
      .where(eq(jobs.id, id))
      .run();

    return {
      content: [{ type: "text" as const, text: `Cancelled job ${id}.` }],
    };
  },
  { annotations: { readOnly: false, destructive: false } }
);

// --- Export ---

const READ_TOOLS = [listJobsTool];
const WRITE_TOOLS = [scheduleJobTool, cancelJobTool];

export const SCHEDULER_WRITE_TOOL_NAMES = WRITE_TOOLS.map((t) => t.name);

export function createSchedulerMcpServer(): McpSdkServerConfigWithInstance {
  return createSdkMcpServer({
    name: "scheduler",
    version: "0.1.0",
    tools: [...READ_TOOLS, ...WRITE_TOOLS],
  });
}
