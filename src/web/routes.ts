import * as fs from "fs";
import * as path from "path";
import { Hono } from "hono";
import { bodyLimit } from "hono/body-limit";
import { streamSSE } from "hono/streaming";
import { chat, type AgentConfig, type ImageAttachment } from "../agent/core.ts";
import { WORKSPACE_DIR } from "../agent/sandbox.ts";
import { buildSystemPrompt } from "../agent/system-prompt.ts";
import { createGitHubMcpServer, createKnowledgeMcpServer, createSchedulerMcpServer, createSlackMcpServer, createVisualizationMcpServer, createPostHogMcpServer, createSandboxMcpServer, createMemoryMcpServer, createSignalsMcpServer, createIntelligenceMcpServer } from "../tools/index.ts";
import { WRITE_TOOL_NAMES } from "../tools/index.ts";
import { createDashboardMcpServer } from "../tools/dashboard.ts";
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
import { chatSessions, messages, users, invites, dashboardWidgets, dashboardTabs } from "../db/schema.ts";
import * as schema from "../db/schema.ts";
import { desc, eq } from "drizzle-orm";
import { refreshTab } from "../scheduler/tab-refresh.ts";
import { KNOWLEDGE_DIR } from "../paths.ts";
import {
  getSetupStatus,
  validateToken,
  listOrgs,
  listProjects,
  discoverReposFromProject,
  generateKnowledge,
  completeSetup,
  saveGitHubConfig,
} from "../setup/steps.ts";

// Shared MCP server instances
let githubServer: ReturnType<typeof createGitHubMcpServer> | null = null;
let knowledgeServer: ReturnType<typeof createKnowledgeMcpServer> | null = null;
let schedulerServer: ReturnType<typeof createSchedulerMcpServer> | null = null;
let slackServer: ReturnType<typeof createSlackMcpServer> | null = null;
let visualizationServer: ReturnType<typeof createVisualizationMcpServer> | null = null;
let posthogServer: ReturnType<typeof createPostHogMcpServer> | null = null;
let dashboardServer: ReturnType<typeof createDashboardMcpServer> | null = null;
let sandboxServer: ReturnType<typeof createSandboxMcpServer> | null = null;
let memoryServer: ReturnType<typeof createMemoryMcpServer> | null = null;
let signalsServer: ReturnType<typeof createSignalsMcpServer> | null = null;
let intelligenceServer: ReturnType<typeof createIntelligenceMcpServer> | null = null;

function resetMcpServers() {
  githubServer = null;
  knowledgeServer = null;
  schedulerServer = null;
  slackServer = null;
  visualizationServer = null;
  posthogServer = null;
  dashboardServer = null;
  sandboxServer = null;
  memoryServer = null;
  signalsServer = null;
  intelligenceServer = null;
}

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

function getDashboardServer() {
  if (!dashboardServer) dashboardServer = createDashboardMcpServer();
  return dashboardServer;
}

function getSandboxServer() {
  if (!sandboxServer) sandboxServer = createSandboxMcpServer();
  return sandboxServer;
}

function getMemoryServer() {
  if (!memoryServer) memoryServer = createMemoryMcpServer();
  return memoryServer;
}

function getSignalsServer() {
  if (!signalsServer) signalsServer = createSignalsMcpServer();
  return signalsServer;
}

function getIntelligenceServer() {
  if (!intelligenceServer) intelligenceServer = createIntelligenceMcpServer();
  return intelligenceServer;
}

/**
 * Run the initial intelligence bootstrap — scans the project, populates memory and creates first insights.
 * Called once after setup completes. Runs in background.
 */
async function bootstrapIntelligence() {
  const org = process.env.GITHUB_ORG || "unknown";
  const projectNumber = process.env.GITHUB_PROJECT_NUMBER || "0";

  console.log("[bootstrap] Starting intelligence bootstrap...");

  const config: AgentConfig = {
    systemPrompt: buildSystemPrompt(),
    mcpServers: {
      github: getGitHubServer(),
      knowledge: getKnowledgeServer(),
      dashboard: getDashboardServer(),
      memory: getMemoryServer(),
      signals: getSignalsServer(),
      intelligence: getIntelligenceServer(),
      ...getRemoteMcpServers(),
    },
    model: process.env.AGENT_MODEL || "google/gemini-3-flash-preview",
    workingDirectory: WORKSPACE_DIR,
  };

  const prompt = `You just finished initial setup for a new project: ${org} (GitHub Project #${projectNumber}).

Run the following bootstrap sequence to populate the intelligence layer:

1. **Scan the project**: Call github_list_project_items and github_list_project_fields to understand the current sprint state — items, statuses, assignees, priorities.

2. **Populate memory**: Write the following memory files based on what you find:
   - product.md — project name, repos involved, current sprint, top priorities
   - team.md — list of assignees you see in the project with their current workload
   - metrics.md — sprint stats: total items, status breakdown, completion rate

3. **Store signals**: For key metrics (items by status, items by priority, sprint completion %), store each as a signal via signal_store with source "github" and type "metric".

4. **Generate initial insights**: Based on your analysis, create 2-5 insights about:
   - Sprint health (on track? at risk?)
   - Any items without assignees
   - Any blocked or stale items
   - Workload balance across team members
   - Any recommendations

5. **Create a dashboard tab**: Use dashboard tools to create an "Intelligence" tab with:
   - 4 stat cards: sprint completion %, blocked items, unassigned items, team size
   - A table of your generated insights

Be thorough but concise. This is the user's first impression of the intelligence layer.`;

  let result = "";
  for await (const msg of chat(prompt, config)) {
    if (msg.type === "result") {
      result = msg.content;
    }
  }

  console.log("[bootstrap] Intelligence bootstrap complete:", result.substring(0, 200));
}

// Human-readable tool labels
const TOOL_LABELS: Record<string, string> = {
  "mcp__github__github_list_project_items": "Fetching project items",
  "mcp__github__github_list_project_fields": "Loading field configuration",
  "mcp__github__github_cli": "Running GitHub CLI",
  "mcp__github__github_list_issues": "Listing issues",
  "mcp__sandbox__sandbox_bash": "Running command",
  "mcp__sandbox__sandbox_write_file": "Writing file",
  "mcp__sandbox__sandbox_read_file": "Reading file",
  "mcp__sandbox__sandbox_list_dir": "Listing directory",
  "mcp__sandbox__sandbox_share_file": "Sharing file",
  "mcp__visualization__render_chart": "Generating chart",
  "mcp__visualization__render_diagram": "Generating diagram",
  "mcp__knowledge__knowledge_list_files": "Checking knowledge base",
  "mcp__knowledge__knowledge_read_file": "Reading knowledge",
  "mcp__knowledge__knowledge_update_file": "Updating knowledge",
  "mcp__knowledge__knowledge_append_to_file": "Updating knowledge",
  "mcp__dashboard__dashboard_get_state": "Reading dashboard",
  "mcp__dashboard__dashboard_set_layout": "Building dashboard",
  "mcp__dashboard__dashboard_add_widget": "Adding widget",
  "mcp__dashboard__dashboard_remove_widget": "Removing widget",
  "mcp__dashboard__dashboard_update_widget": "Updating widget",
  "mcp__scheduler__schedule_job": "Scheduling job",
  "mcp__scheduler__list_jobs": "Listing scheduled jobs",
  "mcp__scheduler__cancel_job": "Cancelling job",
  "mcp__slack__slack_send_message": "Sending to Slack",
  "mcp__posthog__posthog_query": "Querying analytics",
  "mcp__posthog__posthog_trends": "Fetching trends",
  "mcp__posthog__posthog_funnel": "Analyzing funnel",
  "mcp__posthog__posthog_list_events": "Listing events",
  "mcp__linear__linear_search_issues": "Searching Linear",
  "mcp__linear__linear_create_issue": "Creating Linear issue",
  "mcp__linear__linear_update_issue": "Updating Linear issue",
  "mcp__linear__linear_list_cycles": "Listing Linear cycles",
  "mcp__exa__web_search_exa": "Searching the web",
  "mcp__exa__company_research_exa": "Researching company",
  "mcp__memory__memory_list": "Listing memory",
  "mcp__memory__memory_read": "Reading memory",
  "mcp__memory__memory_search": "Searching memory",
  "mcp__memory__memory_follow_link": "Following memory link",
  "mcp__memory__memory_write": "Writing to memory",
  "mcp__memory__memory_update": "Updating memory",
  "mcp__memory__memory_delete": "Deleting memory",
  "mcp__signals__signal_store": "Storing signal",
  "mcp__signals__signal_query": "Querying signals",
  "mcp__signals__signal_sources": "Listing signal sources",
  "mcp__signals__insight_create": "Creating insight",
  "mcp__signals__insight_query": "Querying insights",
  "mcp__signals__insight_update": "Updating insight",
  "mcp__intelligence__intelligence_list_skills": "Listing skills",
  "mcp__intelligence__intelligence_get_skill": "Loading skill",
};

function formatToolName(name: string): string {
  // Strip mcp__server__ prefix and humanize
  const stripped = name.replace(/^mcp__\w+__/, "");
  return stripped
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
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
  // 50MB limit: allows up to 5 base64 images (~7.5MB each) plus message text
  app.post("/chat", bodyLimit({ maxSize: 50 * 1024 * 1024, onError: (c) => c.json({ error: "Payload too large" }, 413) }), async (c) => {
    const body = await c.req.json<{
      message: string;
      sessionId?: string;
      model?: string;
      images?: Array<{ data: string; media_type: string }>;
    }>();

    // Validate images
    const ALLOWED_IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
    if (body.images) {
      if (body.images.length > 5) {
        return c.json({ error: "Maximum 5 images per message" }, 400);
      }
      for (const img of body.images) {
        if (!ALLOWED_IMAGE_TYPES.includes(img.media_type)) {
          return c.json({ error: `Unsupported image type: ${img.media_type}` }, 400);
        }
        if (img.data.length > 10_000_000) {
          return c.json({ error: "Image too large (max ~7.5MB)" }, 400);
        }
      }
    }

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

    // Save user message (with image markers if present)
    const userContent = body.images?.length
      ? `${body.message}\n${body.images.map((img, i) => `[Image ${i + 1}: ${img.media_type}]`).join("\n")}`
      : body.message;
    db.insert(messages)
      .values({
        id: newId(),
        chatSessionId: sessionId,
        role: "user",
        content: userContent,
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
        dashboard: getDashboardServer(),
        sandbox: getSandboxServer(),
        memory: getMemoryServer(),
        signals: getSignalsServer(),
        intelligence: getIntelligenceServer(),
        ...getRemoteMcpServers(),
      },
      resume: session?.sessionId ?? undefined,
      model: body.model || process.env.AGENT_MODEL || "google/gemini-3-flash-preview",
      workingDirectory: WORKSPACE_DIR,
    };

    console.log(`[agent] chat request: model=${agentConfig.model}, prompt_len=${systemPrompt.length}, resume=${!!agentConfig.resume}`);

    return streamSSE(c, async (stream) => {
      let fullResponse = "";
      let sdkSessionId: string | undefined;

      try {
        // Build image attachments if present
        const imageAttachments: ImageAttachment[] | undefined = body.images?.map((img) => ({
          data: img.data,
          media_type: img.media_type,
        }));

        for await (const msg of chat(body.message, agentConfig, imageAttachments)) {
          if (msg.type === "thinking") {
            await stream.writeSSE({
              event: "thinking",
              data: JSON.stringify({}),
            });
          } else if (msg.type === "thinking_delta") {
            await stream.writeSSE({
              event: "thinking_delta",
              data: JSON.stringify({ content: msg.content }),
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
            } else if (msg.toolName?.startsWith("mcp__dashboard__")) {
              const dashTool = msg.toolName.replace("mcp__dashboard__", "");
              const actionMap: Record<string, string> = {
                dashboard_add_widget: "add",
                dashboard_remove_widget: "remove",
                dashboard_update_widget: "update",
                dashboard_set_layout: "set_layout",
              };
              const action = actionMap[dashTool];
              if (action) {
                console.log(`[agent] >> sending dashboard_update SSE event: ${action}`);
                // For set_layout, fetch the created tab info to send to frontend
                let extra: Record<string, unknown> = {};
                if (action === "set_layout" && msg.toolInput?.tab_name) {
                  const tab = getDb().select().from(dashboardTabs).all()
                    .find((t) => t.name === msg.toolInput!.tab_name);
                  if (tab) extra = { tab_id: tab.id, tab_name: tab.name, tab_position: tab.position, tab_filters: tab.filters || null };
                }
                await stream.writeSSE({
                  event: "dashboard_update",
                  data: JSON.stringify({ action, ...msg.toolInput, ...extra }),
                });
              }
            } else if (msg.toolName === "mcp__sandbox__sandbox_share_file" && msg.toolInput?.path) {
              // File sharing — emit SSE event for download chip
              const inputPath = String(msg.toolInput.path);
              const resolvedFile = inputPath.startsWith("/")
                ? inputPath
                : path.resolve(WORKSPACE_DIR, inputPath);
              const relPath = resolvedFile.startsWith(WORKSPACE_DIR)
                ? path.relative(WORKSPACE_DIR, resolvedFile)
                : path.basename(resolvedFile);
              const displayName = msg.toolInput.name ? String(msg.toolInput.name) : path.basename(resolvedFile);

              // Get file size if it exists
              let fileSize = 0;
              let sizeFormatted = "0KB";
              try {
                const stat = fs.statSync(resolvedFile);
                fileSize = stat.size;
                sizeFormatted = fileSize > 1048576 ? `${(fileSize / 1048576).toFixed(1)}MB` : `${(fileSize / 1024).toFixed(1)}KB`;
              } catch {}

              const fileInfo = { path: relPath, name: displayName, size: fileSize, sizeFormatted };

              await stream.writeSSE({
                event: "file_shared",
                data: JSON.stringify(fileInfo),
              });

              // Embed marker in fullResponse so file chips persist in DB
              fullResponse += `\n<!--FILE:${JSON.stringify(fileInfo)}-->\n`;
            } else {
              const toolData: Record<string, unknown> = { tool: msg.toolName };
              // Add human-readable label
              toolData.label = TOOL_LABELS[msg.toolName || ""] || formatToolName(msg.toolName || "");
              // Include detail for sandbox and other tools
              if (msg.toolInput) {
                if (msg.toolName === "mcp__sandbox__sandbox_bash" && msg.toolInput.command) {
                  toolData.detail = String(msg.toolInput.command).slice(0, 120);
                } else if (msg.toolName === "mcp__sandbox__sandbox_read_file" && msg.toolInput.path) {
                  toolData.detail = String(msg.toolInput.path);
                } else if (msg.toolName === "mcp__sandbox__sandbox_write_file" && msg.toolInput.path) {
                  toolData.detail = String(msg.toolInput.path);
                } else if (msg.toolName === "mcp__sandbox__sandbox_list_dir") {
                  toolData.detail = String(msg.toolInput.path || ".");
                }
              }
              await stream.writeSSE({
                event: "tool",
                data: JSON.stringify(toolData),
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
    const { token: rawToken } = await c.req.json<{ token: string }>();
    // __ENV__ sentinel = reuse token from environment
    const token = rawToken === "__ENV__" ? (process.env.GITHUB_TOKEN || "") : rawToken;
    const result = await validateToken(token);
    let orgs: string[] = [];
    if (result.valid) {
      orgs = await listOrgs(token);
    }
    return c.json({ ...result, orgs });
  });

  app.post("/setup/projects", async (c) => {
    const { token: rawToken, org } = await c.req.json<{ token: string; org: string }>();
    const token = rawToken === "__ENV__" ? (process.env.GITHUB_TOKEN || "") : rawToken;
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

    resetMcpServers();

    return c.json({ success: true, logs });
  });

  // Save GitHub config only (no knowledge generation)
  app.post("/setup/connect", async (c) => {
    const body = await c.req.json<{
      token: string;
      org: string;
      projectNumber: number;
    }>();

    const token = body.token === "__ENV__" ? (process.env.GITHUB_TOKEN || "") : body.token;
    const { created } = saveGitHubConfig({
      token,
      org: body.org,
      projectNumber: body.projectNumber,
    });

    resetMcpServers();
    return c.json({ success: true, created });
  });

  // Discover repos linked to the configured project
  app.post("/setup/discover-repos", async (c) => {
    const token = process.env.GITHUB_TOKEN;
    const org = process.env.GITHUB_ORG;
    const projectNumber = parseInt(process.env.GITHUB_PROJECT_NUMBER || "0", 10);

    if (!token || !org || !projectNumber) {
      return c.json({ error: "GitHub not configured. Run connect first." }, 400);
    }

    const repos = await discoverReposFromProject(token, org, projectNumber);
    return c.json({ repos });
  });

  // SSE endpoint for knowledge generation progress
  // Accepts ?repos=repo1,repo2 to generate for specific repos
  app.get("/setup/generate-knowledge", async (c) => {
    const token = process.env.GITHUB_TOKEN;
    const org = process.env.GITHUB_ORG;

    if (!token || !org) {
      return c.json({ error: "GitHub not configured. Run connect first." }, 400);
    }

    const reposParam = c.req.query("repos");
    const repos = reposParam ? reposParam.split(",").filter(Boolean) : [];

    if (repos.length === 0) {
      return c.json({ error: "No repositories specified." }, 400);
    }

    return streamSSE(c, async (stream) => {
      try {
        await stream.writeSSE({
          event: "progress",
          data: JSON.stringify({ phase: "discovery", message: `Generating knowledge for ${repos.length} repositories: ${repos.join(", ")}` }),
        });

        await generateKnowledge(org, repos, async (msg) => {
          let phase = "generating";
          if (msg.includes("Collecting")) phase = "collecting";
          else if (msg.includes("Fetching")) phase = "fetching";
          else if (msg.includes("Synthesizing")) phase = "synthesizing";
          else if (msg.includes("generated") || msg.includes("written") || msg.includes("Writing")) phase = "writing";
          else if (msg.includes("complete")) phase = "complete";
          else if (msg.includes("Skipped") || msg.includes("Failed") || msg.includes("failed")) phase = "warning";

          await stream.writeSSE({
            event: "progress",
            data: JSON.stringify({ phase, message: msg }),
          });
        }, token);

        await stream.writeSSE({
          event: "complete",
          data: JSON.stringify({ success: true }),
        });
      } catch (err) {
        await stream.writeSSE({
          event: "gen_error",
          data: JSON.stringify({ message: err instanceof Error ? err.message : String(err) }),
        });
      }
    });
  });

  // --- File Download API ---

  app.get("/files/:path{.+}", (c) => {
    const filePath = c.req.param("path");
    const resolved = path.resolve(WORKSPACE_DIR, filePath);

    // Security: ensure resolved path is within WORKSPACE_DIR
    if (!resolved.startsWith(WORKSPACE_DIR + path.sep) && resolved !== WORKSPACE_DIR) {
      return c.json({ error: "Access denied" }, 403);
    }

    if (!fs.existsSync(resolved) || !fs.statSync(resolved).isFile()) {
      return c.json({ error: "File not found" }, 404);
    }

    const ext = path.extname(resolved).toLowerCase();
    const mimeTypes: Record<string, string> = {
      ".csv": "text/csv",
      ".json": "application/json",
      ".txt": "text/plain",
      ".md": "text/markdown",
      ".html": "text/html",
      ".xml": "application/xml",
      ".pdf": "application/pdf",
      ".png": "image/png",
      ".jpg": "image/jpeg",
      ".jpeg": "image/jpeg",
      ".gif": "image/gif",
      ".svg": "image/svg+xml",
      ".zip": "application/zip",
      ".tar": "application/x-tar",
      ".gz": "application/gzip",
      ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      ".xls": "application/vnd.ms-excel",
    };
    const contentType = mimeTypes[ext] || "application/octet-stream";
    const fileName = path.basename(resolved);

    const fileBuffer = fs.readFileSync(resolved);
    return new Response(fileBuffer, {
      headers: {
        "Content-Type": contentType,
        "Content-Disposition": `attachment; filename="${fileName}"`,
        "Content-Length": String(fileBuffer.length),
      },
    });
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

  app.get("/dashboard/tabs", (c) => {
    const tabs = getDb()
      .select()
      .from(dashboardTabs)
      .orderBy(dashboardTabs.position)
      .all()
      .map((t) => ({
        ...t,
        refreshPrompt: t.refreshPrompt || null,
        refreshIntervalMs: t.refreshIntervalMs || null,
        lastRefreshedAt: t.lastRefreshedAt?.toISOString() || null,
      }));
    return c.json({ tabs });
  });

  app.get("/dashboard/tabs/:id/widgets", (c) => {
    const tabId = c.req.param("id");
    const widgets = getDb()
      .select()
      .from(dashboardWidgets)
      .where(eq(dashboardWidgets.tabId, tabId))
      .orderBy(dashboardWidgets.position)
      .all();
    return c.json({ widgets });
  });

  app.delete("/dashboard/tabs/:id", (c) => {
    const tabId = c.req.param("id");
    getDb().delete(dashboardWidgets).where(eq(dashboardWidgets.tabId, tabId)).run();
    getDb().delete(dashboardTabs).where(eq(dashboardTabs.id, tabId)).run();
    return c.json({ success: true });
  });

  // Manual tab refresh
  app.post("/dashboard/tabs/:id/refresh", async (c) => {
    const tabId = c.req.param("id");
    const tab = getDb()
      .select()
      .from(dashboardTabs)
      .where(eq(dashboardTabs.id, tabId))
      .get();

    if (!tab) return c.json({ error: "Tab not found" }, 404);
    if (!tab.refreshPrompt) return c.json({ error: "Tab has no refresh prompt configured" }, 400);

    // Run refresh in background, return immediately
    refreshTab(tab).catch((err) =>
      console.error(`[routes] Manual refresh failed for tab ${tabId}:`, err)
    );

    return c.json({ success: true, message: "Refresh started" });
  });

  app.put("/dashboard/tabs/reorder", async (c) => {
    const body = await c.req.json<{ tabs: Array<{ id: string; position: number }> }>();
    const now = new Date();
    for (const tab of body.tabs) {
      getDb().update(dashboardTabs)
        .set({ position: tab.position, updatedAt: now })
        .where(eq(dashboardTabs.id, tab.id))
        .run();
    }
    return c.json({ success: true });
  });

  app.get("/dashboard/layout", (c) => {
    const widgets = getDb()
      .select()
      .from(dashboardWidgets)
      .orderBy(dashboardWidgets.position)
      .all();
    return c.json({ widgets });
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

  // --- Bootstrap Intelligence (runs after setup) ---

  app.post("/bootstrap-intelligence", async (c) => {
    const org = process.env.GITHUB_ORG;
    const projectNumber = process.env.GITHUB_PROJECT_NUMBER;
    if (!org || !projectNumber) {
      return c.json({ error: "Not configured" }, 400);
    }

    // Fire and forget — run in background
    bootstrapIntelligence().catch((err) =>
      console.error("[bootstrap] Intelligence bootstrap failed:", err)
    );

    return c.json({ success: true, message: "Intelligence bootstrap started" });
  });

  // --- Insights API ---

  app.get("/insights", (c) => {
    const status = c.req.query("status");
    const category = c.req.query("category");
    let query = getDb().select().from(schema.insights);

    const rows = query.orderBy(desc(schema.insights.createdAt)).all();
    const filtered = rows.filter((r) => {
      if (status && r.status !== status) return false;
      if (category && r.category !== category) return false;
      return true;
    });
    return c.json({ insights: filtered });
  });

  app.patch("/insights/:id", async (c) => {
    const id = c.req.param("id");
    const body = await c.req.json<{ status?: string }>();
    if (body.status) {
      getDb()
        .update(schema.insights)
        .set({ status: body.status, updatedAt: new Date() })
        .where(eq(schema.insights.id, id))
        .run();
    }
    return c.json({ success: true });
  });

  app.get("/signals/recent", (c) => {
    const limit = parseInt(c.req.query("limit") || "50", 10);
    const rows = getDb()
      .select()
      .from(schema.signals)
      .orderBy(desc(schema.signals.createdAt))
      .limit(limit)
      .all();
    return c.json({ signals: rows });
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
