/**
 * PM Channel tool — lets the agent post proactively to the persistent PM channel.
 *
 * The PM channel is a direct persistent feed between the agent and the PM.
 * Unlike regular chat (reactive), the agent uses this to push ideas, observations,
 * synthesis summaries, or anything worth the PM's attention.
 *
 * Messages posted here also go to Slack, and Slack thread replies route back here.
 */

import {
  createSdkMcpServer,
  tool,
  type McpSdkServerConfigWithInstance,
} from "@anthropic-ai/claude-agent-sdk";
import { z } from "zod/v4";
import { getDb, newId } from "../db/index.ts";
import { messages, slackMessages } from "../db/schema.ts";
import { sendSlackMessage } from "./slack.ts";
import { toSlackMarkdown, splitMessage } from "../slack/formatter.ts";

export const PM_CHANNEL_WRITE_TOOL_NAMES = ["mcp__pm_channel__pm_post"];

const PM_SESSION_ID = "pm-channel";

const pmPost = tool(
  "pm_post",
  `Post a message to the PM channel — a persistent direct feed between you and the PM.

Use this for:
- Synthesis summaries (when something is worth the PM's attention)
- Strategic ideas and suggestions you want to surface proactively
- Important observations that don't need immediate action but are good to know
- Anything you'd say in a brief 1:1 with the PM

This replaces using slack_send_message for PM communication. Messages appear in the
dashboard PM Channel and are also sent to Slack. The PM can reply in either place.

Keep messages concise and human — like a thoughtful colleague, not a report.`,
  {
    message: z.string().describe("The message to send. Use Slack mrkdwn format: *bold*, _italic_. Keep it short and human."),
  },
  async ({ message }) => {
    const db = getDb();
    const now = new Date();
    const msgId = newId();

    // Store in PM channel session
    db.insert(messages).values({
      id: msgId,
      chatSessionId: PM_SESSION_ID,
      role: "assistant",
      content: message,
      createdAt: now,
    }).run();

    // Send to Slack and track ts for thread routing
    const slackText = toSlackMarkdown(message);
    const chunks = splitMessage(slackText);
    const slackResult = await sendSlackMessage(chunks[0]);

    if (slackResult) {
      db.insert(slackMessages).values({
        id: newId(),
        ts: slackResult.ts,
        channelId: slackResult.channel,
        sessionId: PM_SESSION_ID,
        createdAt: now,
      }).run();

      // Send remaining chunks if message was split
      for (let i = 1; i < chunks.length; i++) {
        await sendSlackMessage(chunks[i]);
      }
    }

    return {
      content: [{
        type: "text" as const,
        text: `Posted to PM channel${slackResult ? " and Slack" : " (Slack unavailable)"}`,
      }],
    };
  },
  { annotations: { readOnly: false } }
);

export function createPmChannelMcpServer(): McpSdkServerConfigWithInstance {
  return createSdkMcpServer({
    name: "pm_channel",
    version: "1.0.0",
    tools: [pmPost],
  });
}
