import * as fs from "fs";
import * as path from "path";
import { Hono } from "hono";
import { streamSSE } from "hono/streaming";
import { chat, type AgentConfig } from "../agent/core.ts";
import { buildSystemPrompt } from "../agent/system-prompt.ts";
import { createGitHubMcpServer, createKnowledgeMcpServer, createSchedulerMcpServer, createSlackMcpServer, createVisualizationMcpServer, createPostHogMcpServer } from "../tools/index.ts";
import { WRITE_TOOL_NAMES } from "../tools/index.ts";
import { fetchProjectItems, fetchRecentActivity, type ProjectItem } from "../tools/github.ts";
import { getRemoteMcpServers } from "../tools/remote.ts";
import {
  getAllSettings,
  setSetting,
  deleteSetting,
  maskApiKey,
  SETTING_KEYS,
  SENSITIVE_KEYS,
} from "../db/settings.ts";
import { getDb, newId } from "../db/index.ts";
import { chatSessions, messages, users, invites } from "../db/schema.ts";
import { desc, eq } from "drizzle-orm";
import { KNOWLEDGE_DIR } from "../paths.ts";
import {
  getSetupStatus,
  validateToken,
  listOrgs,
  listProjects,
  discoverReposFromProject,
  generateKnowledge,
  completeSetup,
} from "../setup/steps.ts";

// Shared MCP server instances
let githubServer: ReturnType<typeof createGitHubMcpServer> | null = null;
let knowledgeServer: ReturnType<typeof createKnowledgeMcpServer> | null = null;
let schedulerServer: ReturnType<typeof createSchedulerMcpServer> | null = null;
let slackServer: ReturnType<typeof createSlackMcpServer> | null = null;
let visualizationServer: ReturnType<typeof createVisualizationMcpServer> | null = null;
let posthogServer: ReturnType<typeof createPostHogMcpServer> | null = null;

function getGitHubServer() {
  if (!githubServer) githubServer = createGitHubMcpServer();
  return githubServer;
}

function getKnowledgeServer() {
  if (!knowledgeServer) knowledgeServer = createKnowledgeMcpServer();
  return knowledgeServer;
}

function getSchedulerServer() {
  if (!schedulerServer) schedulerServer = createSchedulerMcpServer();
  return schedulerServer;
}

function getSlackServer() {
  if (!slackServer) slackServer = createSlackMcpServer();
  return slackServer;
}

function getVisualizationServer() {
  if (!visualizationServer) visualizationServer = createVisualizationMcpServer();
  return visualizationServer;
}

function getPostHogServer() {
  if (!posthogServer) posthogServer = createPostHogMcpServer();
  return posthogServer;
}

// Pending approval state (simple in-memory for localhost)
const pendingApprovals = new Map<
  string,
  {
    toolName: string;
    input: Record<string, unknown>;
    resolve: (approved: boolean) => void;
  }
>();

// Knowledge path validation helper
function resolveKnowledgePath(filePath: string): string | null {
  const resolved = path.resolve(KNOWLEDGE_DIR, filePath);
  if (!resolved.startsWith(KNOWLEDGE_DIR + path.sep) && resolved !== KNOWLEDGE_DIR) {
    return null;
  }
  if (!resolved.endsWith(".md")) return null;
  return resolved;
}

function computeDashboardStats(items: ProjectItem[]) {
  const statusCounts: Record<string, number> = {};
  const assigneeWorkload: Record<string, Record<string, number>> = {};
  const priorityCounts: Record<string, number> = {};
  const inProgress: ProjectItem[] = [];

  for (const item of items) {
    const status = item.status || "No Status";
    statusCounts[status] = (statusCounts[status] || 0) + 1;

    if (status.toLowerCase() === "in progress") {
      inProgress.push(item);
    }

    const priority = (item.priority as string) || "No Priority";
    priorityCounts[priority] = (priorityCounts[priority] || 0) + 1;

    const assignees = item.assignees.length > 0 ? item.assignees : ["Unassigned"];
    for (const a of assignees) {
      if (!assigneeWorkload[a]) assigneeWorkload[a] = {};
      assigneeWorkload[a][status] = (assigneeWorkload[a][status] || 0) + 1;
    }
  }

  // Sprint progress: status breakdown per sprint
  const sprintBreakdown: Record<string, Record<string, number>> = {};
  for (const item of items) {
    const sprint = item.custom_fields?.sprint;
    if (sprint == null) continue;
    const sprintKey = String(sprint);
    const st = item.status || "No Status";
    if (!sprintBreakdown[sprintKey]) sprintBreakdown[sprintKey] = {};
    sprintBreakdown[sprintKey][st] = (sprintBreakdown[sprintKey][st] || 0) + 1;
  }

  const total = items.length;
  const done = items.filter(
    (i) => (i.status || "").toLowerCase() === "done" || i.state === "CLOSED",
  ).length;
  const blocked = items.filter(
    (i) => (i.status || "").toLowerCase() === "blocked",
  ).length;

  return {
    statusCounts,
    assigneeWorkload,
    inProgress,
    priorityCounts,
    sprintBreakdown,
    overview: {
      total,
      done,
      completionPct: total > 0 ? Math.round((done / total) * 100) : 0,
      inProgressCount: inProgress.length,
      blocked,
    },
  };
}

function extractFilters(items: ProjectItem[]) {
  const sprints = new Set<string>();
  const assignees = new Set<string>();
  const priorities = new Set<string>();
  const statuses = new Set<string>();
  const repositories = new Set<string>();

  for (const item of items) {
    if (item.status) statuses.add(item.status);
    if (item.priority) priorities.add(String(item.priority));
    if (item.repository) repositories.add(item.repository);
    for (const a of item.assignees) assignees.add(a);
    const sprint = item.custom_fields?.sprint;
    if (sprint != null) sprints.add(String(sprint));
  }

  return {
    sprints: [...sprints].sort((a, b) => Number(b) - Number(a)),
    assignees: [...assignees].sort(),
    priorities: [...priorities],
    statuses: [...statuses],
    repositories: [...repositories].sort(),
  };
}

export function createRoutes() {
  const app = new Hono();

  // Health check
  app.get("/health", (c) =>
    c.json({ status: "ok", timestamp: new Date().toISOString() })
  );

  // List sessions (filtered by user)
  app.get("/sessions", (c) => {
    const db = getDb();
    const userId = c.get("userId");
    let query = db.select().from(chatSessions).orderBy(desc(chatSessions.updatedAt)).limit(50);
    if (userId) {
      query = query.where(eq(chatSessions.userId, userId)) as typeof query;
    }
    const sessions = query.all();
    return c.json(sessions);
  });

  // Create session
  app.post("/sessions", async (c) => {
    const db = getDb();
    const id = newId();
    const userId = c.get("userId") || null;
    const name = `Session ${new Date().toLocaleString()}`;
    db.insert(chatSessions)
      .values({
        id,
        name,
        userId,
        createdAt: new Date(),
        updatedAt: new Date(),
      })
      .run();
    return c.json({ id, name });
  });

  // Delete session
  app.delete("/sessions/:id", (c) => {
    const db = getDb();
    const id = c.req.param("id");
    db.delete(messages).where(eq(messages.chatSessionId, id)).run();
    db.delete(chatSessions).where(eq(chatSessions.id, id)).run();
    return c.json({ success: true });
  });

  // Get session messages
  app.get("/sessions/:id/messages", (c) => {
    const db = getDb();
    const sessionId = c.req.param("id");
    const msgs = db
      .select()
      .from(messages)
      .where(eq(messages.chatSessionId, sessionId))
      .all();
    return c.json(msgs);
  });

  // Chat with streaming (SSE)
  app.post("/chat", async (c) => {
    const body = await c.req.json<{
      message: string;
      sessionId?: string;
    }>();

    const db = getDb();
    let sessionId = body.sessionId;

    // Create session if needed
    if (!sessionId) {
      sessionId = newId();
      const userId = c.get("userId") || null;
      db.insert(chatSessions)
        .values({
          id: sessionId,
          name: `Session ${new Date().toLocaleString()}`,
          userId,
          createdAt: new Date(),
          updatedAt: new Date(),
        })
        .run();
    }

    // Save user message
    db.insert(messages)
      .values({
        id: newId(),
        chatSessionId: sessionId,
        role: "user",
        content: body.message,
        createdAt: new Date(),
      })
      .run();

    // Get SDK session ID for resume
    const session = db
      .select()
      .from(chatSessions)
      .where(eq(chatSessions.id, sessionId))
      .get();

    // Build agent config
    const systemPrompt = buildSystemPrompt();
    const agentConfig: AgentConfig = {
      systemPrompt,
      mcpServers: {
        github: getGitHubServer(),
        knowledge: getKnowledgeServer(),
        scheduler: getSchedulerServer(),
        slack: getSlackServer(),
        visualization: getVisualizationServer(),
        posthog: getPostHogServer(),
        ...getRemoteMcpServers(),
      },
      canUseTool: async (_toolName, input, _options) => {
        return { behavior: "allow" as const, updatedInput: input };
      },
      resume: session?.sessionId ?? undefined,
      model: process.env.AGENT_MODEL || undefined,
    };

    console.log(`[agent] chat request: model=${agentConfig.model}, prompt_len=${systemPrompt.length}, resume=${!!agentConfig.resume}`);

    return streamSSE(c, async (stream) => {
      let fullResponse = "";
      let sdkSessionId: string | undefined;

      try {
        for await (const msg of chat(body.message, agentConfig)) {
          if (msg.type === "thinking") {
            await stream.writeSSE({
              event: "thinking",
              data: JSON.stringify({}),
            });
          } else if (msg.type === "typing") {
            await stream.writeSSE({
              event: "typing",
              data: JSON.stringify({}),
            });
          } else if (msg.type === "partial") {
            await stream.writeSSE({
              event: "delta",
              data: JSON.stringify({ content: msg.content }),
            });
            fullResponse += msg.content;
          } else if (msg.type === "text") {
            fullResponse += msg.content;
          } else if (msg.type === "tool_use") {
            console.log(`[agent] tool_use: ${msg.toolName}`, msg.toolInput ? JSON.stringify(msg.toolInput).slice(0, 200) : "(no input)");
            if (msg.toolName?.startsWith("mcp__visualization__")) {
              console.log(`[agent] >> sending visualization SSE event`);
              const vizTool = msg.toolName.replace("mcp__visualization__", "");
              await stream.writeSSE({
                event: "visualization",
                data: JSON.stringify({
                  tool: vizTool,
                  input: msg.toolInput,
                }),
              });
              // Embed markers in fullResponse so charts persist in DB
              if (vizTool === "render_chart" && msg.toolInput?.config) {
                fullResponse += `\n<!--CHART:${typeof msg.toolInput.config === "string" ? msg.toolInput.config : JSON.stringify(msg.toolInput.config)}-->\n`;
              } else if (vizTool === "render_diagram") {
                fullResponse += `\n<!--DIAGRAM:${JSON.stringify(msg.toolInput)}-->\n`;
              }
            } else {
              await stream.writeSSE({
                event: "tool",
                data: JSON.stringify({ tool: msg.toolName }),
              });
            }
          } else if (msg.type === "result") {
            await stream.writeSSE({
              event: "done",
              data: JSON.stringify({
                sessionId,
                costUsd: msg.costUsd,
                isError: msg.isError,
              }),
            });
          }

          if (msg.sessionId) {
            sdkSessionId = msg.sessionId;
          }
        }
      } catch (err) {
        await stream.writeSSE({
          event: "error",
          data: JSON.stringify({
            message: err instanceof Error ? err.message : String(err),
          }),
        });
      }

      // Save assistant response
      if (fullResponse) {
        db.insert(messages)
          .values({
            id: newId(),
            chatSessionId: sessionId!,
            role: "assistant",
            content: fullResponse,
            createdAt: new Date(),
          })
          .run();
      }

      // Update SDK session ID
      if (sdkSessionId && sessionId) {
        db.update(chatSessions)
          .set({ sessionId: sdkSessionId, updatedAt: new Date() })
          .where(eq(chatSessions.id, sessionId))
          .run();
      }
    });
  });

  // --- Knowledge API ---

  // List all knowledge files
  app.get("/knowledge", (c) => {
    const files: Array<{ path: string; size: number }> = [];
    function walk(dir: string) {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.name.startsWith(".")) continue;
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          walk(full);
        } else if (entry.name.endsWith(".md")) {
          const stat = fs.statSync(full);
          files.push({
            path: path.relative(KNOWLEDGE_DIR, full),
            size: stat.size,
          });
        }
      }
    }
    if (fs.existsSync(KNOWLEDGE_DIR)) walk(KNOWLEDGE_DIR);
    return c.json(files);
  });

  // Read a knowledge file
  app.get("/knowledge/:path{.+}", (c) => {
    const filePath = c.req.param("path");
    const resolved = resolveKnowledgePath(filePath);
    if (!resolved) return c.json({ error: "Invalid path" }, 400);
    if (!fs.existsSync(resolved)) return c.json({ error: "Not found" }, 404);
    const content = fs.readFileSync(resolved, "utf-8");
    return c.json({ path: filePath, content });
  });

  // Update/create a knowledge file
  app.put("/knowledge/:path{.+}", async (c) => {
    const filePath = c.req.param("path");
    const resolved = resolveKnowledgePath(filePath);
    if (!resolved) return c.json({ error: "Invalid path" }, 400);
    const body = await c.req.json<{ content: string }>();
    const dir = path.dirname(resolved);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(resolved, body.content, "utf-8");
    return c.json({ success: true, path: filePath });
  });

  // Delete a knowledge file
  app.delete("/knowledge/:path{.+}", (c) => {
    const filePath = c.req.param("path");
    if (filePath === "skills.md") {
      return c.json({ error: "Cannot delete skills.md" }, 403);
    }
    const resolved = resolveKnowledgePath(filePath);
    if (!resolved) return c.json({ error: "Invalid path" }, 400);
    if (!fs.existsSync(resolved)) return c.json({ error: "Not found" }, 404);
    fs.unlinkSync(resolved);
    return c.json({ success: true });
  });

  // --- Setup API ---

  app.get("/setup/status", (c) => {
    return c.json(getSetupStatus());
  });

  app.post("/setup/validate-token", async (c) => {
    const { token } = await c.req.json<{ token: string }>();
    const result = await validateToken(token);
    let orgs: string[] = [];
    if (result.valid) {
      orgs = await listOrgs(token);
    }
    return c.json({ ...result, orgs });
  });

  app.post("/setup/projects", async (c) => {
    const { token, org } = await c.req.json<{ token: string; org: string }>();
    const projects = await listProjects(token, org);
    return c.json({ projects });
  });

  app.post("/setup/complete", async (c) => {
    const body = await c.req.json<{
      token: string;
      org: string;
      projectNumber: number;
      generateKnowledgeFiles: boolean;
    }>();

    const logs: string[] = [];

    if (body.generateKnowledgeFiles) {
      const repos = await discoverReposFromProject(body.token, body.org, body.projectNumber);
      logs.push(`Found ${repos.length} repositories from project`);
      await generateKnowledge(body.org, repos, (msg) => logs.push(msg), body.token);
    }

    const { created } = completeSetup({
      token: body.token,
      org: body.org,
      projectNumber: body.projectNumber,
    });
    logs.push(created ? ".env created" : ".env updated");

    // Reset cached MCP servers so they pick up new config
    githubServer = null;
    knowledgeServer = null;
    schedulerServer = null;
    slackServer = null;
    visualizationServer = null;
    posthogServer = null;

    return c.json({ success: true, logs });
  });

  // --- Dashboard API ---

  app.get("/dashboard", async (c) => {
    const org = process.env.GITHUB_ORG;
    const projectNumber = parseInt(process.env.GITHUB_PROJECT_NUMBER || "0", 10);

    if (!org || !projectNumber) {
      return c.json({ error: "GITHUB_ORG and GITHUB_PROJECT_NUMBER must be set" }, 400);
    }

    try {
      const items = await fetchProjectItems(org, projectNumber);
      const stats = computeDashboardStats(items);
      const filters = extractFilters(items);
      return c.json({ items, stats, filters, fetchedAt: new Date().toISOString() });
    } catch (err) {
      return c.json(
        { error: err instanceof Error ? err.message : String(err) },
        500,
      );
    }
  });

  app.get("/dashboard/activity", async (c) => {
    const org = process.env.GITHUB_ORG;
    const projectNumber = parseInt(process.env.GITHUB_PROJECT_NUMBER || "0", 10);

    if (!org || !projectNumber) {
      return c.json({ error: "GITHUB_ORG and GITHUB_PROJECT_NUMBER must be set" }, 400);
    }

    try {
      const items = await fetchProjectItems(org, projectNumber);
      const repos = [...new Set(items.map((i) => i.repository).filter(Boolean))] as string[];

      if (repos.length === 0) {
        return c.json({ activities: [], fetchedAt: new Date().toISOString() });
      }

      const activities = await fetchRecentActivity(org, repos, 30);
      return c.json({ activities, fetchedAt: new Date().toISOString() });
    } catch (err) {
      return c.json(
        { error: err instanceof Error ? err.message : String(err) },
        500,
      );
    }
  });

  // --- Settings API ---

  app.get("/settings", (c) => {
    const all = getAllSettings();
    const masked = { ...all };
    for (const key of SENSITIVE_KEYS) {
      if (masked[key]) {
        masked[key] = maskApiKey(String(masked[key]));
      }
    }
    return c.json(masked);
  });

  app.put("/settings", async (c) => {
    const body = await c.req.json<Record<string, unknown>>();
    for (const [key, value] of Object.entries(body)) {
      if (!SETTING_KEYS.includes(key)) continue;
      if (value === null || value === "") {
        deleteSetting(key);
      } else {
        setSetting(key, value);
      }
    }
    return c.json({ success: true });
  });

  // --- Team API ---

  function getRequestUser(c: any) {
    const userId = c.get("userId");
    if (!userId) return null;
    return getDb().select().from(users).where(eq(users.id, userId)).get() || null;
  }

  // List team members (admin only)
  app.get("/team", (c) => {
    const user = getRequestUser(c);
    if (!user || user.role !== "admin") return c.json({ error: "Forbidden" }, 403);

    const members = getDb().select({
      id: users.id,
      name: users.name,
      role: users.role,
      createdAt: users.createdAt,
    }).from(users).all();

    return c.json(members);
  });

  // Create invite (admin only)
  app.post("/team/invites", async (c) => {
    const user = getRequestUser(c);
    if (!user || user.role !== "admin") return c.json({ error: "Forbidden" }, 403);

    const token = crypto.randomUUID();
    const id = newId();
    getDb().insert(invites).values({
      id,
      token,
      createdBy: user.id,
      createdAt: new Date(),
    }).run();

    return c.json({ token, link: `/join/${token}` });
  });

  // Remove team member (admin only)
  app.delete("/team/:id", (c) => {
    const user = getRequestUser(c);
    if (!user || user.role !== "admin") return c.json({ error: "Forbidden" }, 403);

    const targetId = c.req.param("id");
    if (targetId === user.id) return c.json({ error: "Cannot remove yourself" }, 400);

    getDb().delete(users).where(eq(users.id, targetId)).run();
    return c.json({ success: true });
  });

  // Approve pending action
  app.post("/approvals/:id", async (c) => {
    const id = c.req.param("id");
    const { approved } = await c.req.json<{ approved: boolean }>();
    const pending = pendingApprovals.get(id);
    if (!pending) {
      return c.json({ error: "No pending approval found" }, 404);
    }
    pending.resolve(approved);
    pendingApprovals.delete(id);
    return c.json({ status: approved ? "approved" : "denied" });
  });

  return app;
}
