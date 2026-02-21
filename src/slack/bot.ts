import { App } from "@slack/bolt";
import { chat, type AgentConfig, type ImageAttachment } from "../agent/core.ts";
import { WORKSPACE_DIR } from "../agent/sandbox.ts";
import { buildSystemPrompt } from "../agent/system-prompt.ts";
import {
  createGitHubMcpServer,
  createKnowledgeMcpServer,
  createSchedulerMcpServer,
  createSlackMcpServer,
  createDashboardMcpServer,
  createSandboxMcpServer,
  createPostHogMcpServer,
} from "../tools/index.ts";
import { getRemoteMcpServers } from "../tools/remote.ts";
import { getDb, newId } from "../db/index.ts";
import { chatSessions, messages } from "../db/schema.ts";
import { eq, and } from "drizzle-orm";
import { toSlackMarkdown, splitMessage } from "./formatter.ts";
import { getSettingArray } from "../db/settings.ts";

// Track active threads to prevent concurrent processing
const activeThreads = new Set<string>();

/**
 * Check if a Slack user/channel is allowed to interact with the bot.
 * Defaults to allow all if no restrictions configured.
 */
function isSlackAccessAllowed(userId: string, channelId: string): boolean {
  const allowedUsers = getSettingArray("slack.allowed_users");
  const allowedChannels = getSettingArray("slack.allowed_channels");

  const hasUserRestriction = allowedUsers.length > 0 && allowedUsers[0] !== "all";
  const hasChannelRestriction = allowedChannels.length > 0 && allowedChannels[0] !== "all";

  if (!hasUserRestriction && !hasChannelRestriction) return true;
  if (hasUserRestriction && !allowedUsers.includes(userId)) return false;
  if (hasChannelRestriction && !allowedChannels.includes(channelId)) return false;

  return true;
}

/**
 * Build a system prompt adapted for Slack (no visualization, Slack formatting hints).
 */
function buildSlackSystemPrompt(): string {
  let prompt = buildSystemPrompt();

  // Strip visualization section
  const vizStart = prompt.indexOf("## Data Visualization");
  if (vizStart !== -1) {
    const nextSection = prompt.indexOf("\n\n##", vizStart + 1);
    prompt = nextSection !== -1
      ? prompt.slice(0, vizStart) + prompt.slice(nextSection)
      : prompt.slice(0, vizStart);
  }

  prompt += `

## Slack Context
You are responding in a Slack conversation thread. Formatting rules:
- Use Slack mrkdwn: *bold*, _italic_, ~strikethrough~, \`code\`, \`\`\`code blocks\`\`\`
- Do NOT use markdown headings (## or #). Use *bold text* for section titles.
- Do NOT use markdown tables. Present tabular data as bullet lists or code blocks.
- Do NOT attempt to render charts or diagrams. Use text summaries with bullet points.
- Keep responses concise — Slack is chat, not a document viewer.
- You are replying directly in the thread. Do NOT use slack_send_message to reply to the current user — that tool is for broadcasting to other channels.`;

  return prompt;
}

/**
 * Find or create a DB session for a Slack thread.
 */
function resolveSession(channelId: string, threadTs: string): {
  sessionId: string;
  sdkResumeId: string | undefined;
} {
  const db = getDb();

  const existing = db
    .select()
    .from(chatSessions)
    .where(
      and(
        eq(chatSessions.slackChannelId, channelId),
        eq(chatSessions.slackThreadTs, threadTs),
      ),
    )
    .get();

  if (existing) {
    return {
      sessionId: existing.id,
      sdkResumeId: existing.sessionId ?? undefined,
    };
  }

  const id = newId();
  const now = new Date();
  db.insert(chatSessions)
    .values({
      id,
      name: `[Slack] ${new Date().toLocaleString()}`,
      slackChannelId: channelId,
      slackThreadTs: threadTs,
      createdAt: now,
      updatedAt: now,
    })
    .run();

  return { sessionId: id, sdkResumeId: undefined };
}

/**
 * Core processing: run the agent and post response to Slack thread.
 */
async function processAgentRequest(
  client: any,
  channelId: string,
  threadTs: string,
  userText: string,
  images?: ImageAttachment[],
): Promise<void> {
  const threadKey = `${channelId}:${threadTs}`;
  if (activeThreads.has(threadKey)) return;
  activeThreads.add(threadKey);

  try {
    // Post thinking indicator
    const thinkingMsg = await client.chat.postMessage({
      channel: channelId,
      thread_ts: threadTs,
      text: ":hourglass_flowing_sand: Thinking...",
    });
    const thinkingTs = thinkingMsg.ts;

    // Resolve thread → session
    const { sessionId, sdkResumeId } = resolveSession(channelId, threadTs);

    // Save user message
    const db = getDb();
    db.insert(messages)
      .values({
        id: newId(),
        chatSessionId: sessionId,
        role: "user",
        content: userText,
        createdAt: new Date(),
      })
      .run();

    // Build agent config (no visualization)
    const config: AgentConfig = {
      systemPrompt: buildSlackSystemPrompt(),
      mcpServers: {
        github: createGitHubMcpServer(),
        knowledge: createKnowledgeMcpServer(),
        scheduler: createSchedulerMcpServer(),
        slack: createSlackMcpServer(),
        dashboard: createDashboardMcpServer(),
        sandbox: createSandboxMcpServer(),
        posthog: createPostHogMcpServer(),
        ...getRemoteMcpServers(),
      },
      allowedTools: [
        "mcp__github__*",
        "mcp__knowledge__*",
        "mcp__scheduler__*",
        "mcp__slack__*",
        "mcp__dashboard__*",
        "mcp__exa__*",
        "mcp__sandbox__*",
        "mcp__linear__*",
        "mcp__posthog__*",
      ],
      resume: sdkResumeId,
      model: process.env.AGENT_MODEL || "google/gemini-3-flash-preview",
      workingDirectory: WORKSPACE_DIR,
    };

    // Run agent
    let fullResponse = "";
    let hasPartials = false;
    let sdkSessionId: string | undefined;
    let lastUpdateTime = 0;

    try {
      for await (const msg of chat(userText, config, images)) {
        if (msg.type === "partial") {
          fullResponse += msg.content;
          hasPartials = true;
        } else if (msg.type === "text" && !hasPartials) {
          // Only use finalized text if no streaming deltas were received
          fullResponse += msg.content;
        }

        // Update thinking message with tool progress (max once per 3s)
        if (msg.type === "tool_use" && thinkingTs) {
          const now = Date.now();
          if (now - lastUpdateTime > 3000) {
            lastUpdateTime = now;
            const toolLabel = msg.toolName
              ?.replace("mcp__", "")
              .replace("__", ": ")
              .replace(/_/g, " ");
            try {
              await client.chat.update({
                channel: channelId,
                ts: thinkingTs,
                text: `:hourglass_flowing_sand: Working... _${toolLabel}_`,
              });
            } catch {
              /* rate limit, ignore */
            }
          }
        }

        if (msg.sessionId) sdkSessionId = msg.sessionId;
      }
    } catch (err) {
      fullResponse = `Error: ${err instanceof Error ? err.message : String(err)}`;
    }

    // Convert and split for Slack
    const slackText = toSlackMarkdown(
      fullResponse || "I had trouble generating a response. Please try again.",
    );
    const chunks = splitMessage(slackText);

    // Replace thinking message with first chunk
    if (thinkingTs) {
      try {
        await client.chat.update({
          channel: channelId,
          ts: thinkingTs,
          text: chunks[0],
        });
      } catch {
        await client.chat.postMessage({
          channel: channelId,
          thread_ts: threadTs,
          text: chunks[0],
        });
      }
    }

    // Post remaining chunks
    for (let i = 1; i < chunks.length; i++) {
      await client.chat.postMessage({
        channel: channelId,
        thread_ts: threadTs,
        text: chunks[i],
      });
    }

    // Save assistant response (original GFM, not Slack-converted)
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

    // Update SDK session ID for resume
    if (sdkSessionId) {
      db.update(chatSessions)
        .set({ sessionId: sdkSessionId, updatedAt: new Date() })
        .where(eq(chatSessions.id, sessionId))
        .run();
    }
  } catch (err) {
    console.error("[slack] Error processing request:", err);
  } finally {
    activeThreads.delete(threadKey);
  }
}

/**
 * Start the Slack bot via Socket Mode. No-op if env vars are missing.
 */
export function startSlackBot(): void {
  const botToken = process.env.SLACK_BOT_TOKEN;
  const appToken = process.env.SLACK_APP_TOKEN;

  if (!botToken || !appToken) {
    console.log("[slack] SLACK_BOT_TOKEN or SLACK_APP_TOKEN not set, skipping bot");
    return;
  }

  const app = new App({
    token: botToken,
    appToken: appToken,
    socketMode: true,
  });

  // Handle DMs
  app.message(async ({ message, client }) => {
    if ("bot_id" in message || message.subtype) return;

    const userId = ("user" in message) ? message.user as string : undefined;
    if (!userId || !isSlackAccessAllowed(userId, message.channel)) return;

    const text = ("text" in message) ? message.text || "" : "";
    const files = ("files" in message) ? (message as any).files as any[] : [];

    // Download image attachments from Slack
    const images: ImageAttachment[] = [];
    if (files && files.length > 0) {
      for (const file of files) {
        if (file.mimetype?.startsWith("image/") && file.url_private_download) {
          try {
            const resp = await fetch(file.url_private_download, {
              headers: { Authorization: `Bearer ${process.env.SLACK_BOT_TOKEN}` },
            });
            const buffer = await resp.arrayBuffer();
            const base64 = Buffer.from(buffer).toString("base64");
            images.push({ data: base64, media_type: file.mimetype });
          } catch (err) {
            console.error(`[slack] Failed to download file ${file.name}:`, err);
          }
        }
      }
    }

    if (!text && images.length === 0) return;

    const threadTs = ("thread_ts" in message ? message.thread_ts : undefined) || message.ts;
    await processAgentRequest(
      client, message.channel, threadTs!,
      text || "Describe these images",
      images.length > 0 ? images : undefined,
    );
  });

  // App Home tab
  const agentName = process.env.AGENT_NAME || "Dash";
  app.event("app_home_opened", async ({ event, client }) => {
    await client.views.publish({
      user_id: event.user,
      view: {
        type: "home",
        blocks: [
          {
            type: "header",
            text: { type: "plain_text", text: agentName, emoji: true },
          },
          {
            type: "section",
            text: {
              type: "mrkdwn",
              text: `Hey! I'm ${agentName}, your AI team member. I work alongside the product and engineering team — I know the codebase, the sprints, the people, and the priorities. Ask me anything right here in Slack.`,
            },
          },
          { type: "divider" },
          {
            type: "header",
            text: { type: "plain_text", text: "How It Works", emoji: true },
          },
          {
            type: "section",
            text: {
              type: "mrkdwn",
              text: "*1. DM me directly*\nSend me a message in this DM to start a conversation. I'll maintain context across the thread.",
            },
          },
          {
            type: "section",
            text: {
              type: "mrkdwn",
              text: "*2. @mention me in channels*\nTag me in any channel I'm added to and I'll respond in a thread.",
            },
          },
          {
            type: "section",
            text: {
              type: "mrkdwn",
              text: "*3. Share images*\nAttach screenshots or images to your message — I can analyze them and answer questions about what you share.",
            },
          },
          { type: "divider" },
          {
            type: "header",
            text: { type: "plain_text", text: "What I Can Do", emoji: true },
          },
          {
            type: "section",
            fields: [
              { type: "mrkdwn", text: ":mag:  *Search GitHub*\nIssues, PRs, code, projects" },
              { type: "mrkdwn", text: ":bar_chart:  *Standup & Digest*\nDaily summaries of activity" },
              { type: "mrkdwn", text: ":hammer_and_wrench:  *Run Commands*\nExecute scripts in a sandbox" },
              { type: "mrkdwn", text: ":page_facing_up:  *Generate Reports*\nCSV exports, analysis files" },
              { type: "mrkdwn", text: ":brain:  *Knowledge Base*\nLearn about your repos & team" },
              { type: "mrkdwn", text: ":calendar:  *Scheduled Jobs*\nAutomate recurring tasks" },
            ],
          },
          { type: "divider" },
          {
            type: "header",
            text: { type: "plain_text", text: "Example Messages", emoji: true },
          },
          {
            type: "section",
            text: {
              type: "mrkdwn",
              text: "```What PRs were merged this week?\nGive me a standup summary\nWhat's the status of issue #42?\nAnalyze open bugs and export to CSV\nWhat is the team working on right now?```",
            },
          },
          {
            type: "context",
            elements: [
              {
                type: "mrkdwn",
                text: `Powered by ${agentName}  •  Responses use AI and may not always be accurate`,
              },
            ],
          },
        ],
      },
    });
  });

  // Handle @mentions in channels
  app.event("app_mention", async ({ event, client }) => {
    if (!event.user || !isSlackAccessAllowed(event.user, event.channel)) return;

    const threadTs = event.thread_ts || event.ts;
    const userText = event.text.replace(/<@[A-Z0-9]+>/gi, "").trim() || "Hello!";
    await processAgentRequest(client, event.channel, threadTs, userText);
  });

  app
    .start()
    .then(() => console.log("[slack] Bot connected via Socket Mode"))
    .catch((err) => console.error("[slack] Failed to start:", err));
}
