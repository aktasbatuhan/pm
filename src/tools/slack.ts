import { z } from "zod/v4";
import {
  createSdkMcpServer,
  tool,
  type McpSdkServerConfigWithInstance,
} from "@anthropic-ai/claude-agent-sdk";

function getWebhookUrl(): string | null {
  return process.env.SLACK_WEBHOOK_URL || null;
}

const sendMessageTool = tool(
  "slack_send_message",
  "Send a message to a Slack channel. Use this to notify the team about sprint updates, alerts, or scheduled job results. If you are already responding in a Slack thread, do NOT use this tool to reply — your response is posted automatically. Use this only to broadcast to other channels.",
  {
    text: z.string().describe("The message text to send (supports Slack markdown/mrkdwn)"),
    channel: z.string().optional().describe("Slack channel ID or name (e.g. #general). If omitted, uses default channel or webhook."),
  },
  async ({ text, channel }) => {
    const sent = await sendSlackMessage(text, channel);
    if (!sent) {
      return {
        content: [{ type: "text" as const, text: "Error: Could not send Slack message. Check SLACK_BOT_TOKEN or SLACK_WEBHOOK_URL configuration." }],
        isError: true,
      };
    }
    return {
      content: [{ type: "text" as const, text: `Message sent to Slack${channel ? ` (${channel})` : ""}.` }],
    };
  },
  { annotations: { readOnly: false, destructive: false } }
);

// --- Export ---

export const SLACK_WRITE_TOOL_NAMES = [sendMessageTool.name];

export function createSlackMcpServer(): McpSdkServerConfigWithInstance {
  return createSdkMcpServer({
    name: "slack",
    version: "0.1.0",
    tools: [sendMessageTool],
  });
}

/**
 * Send a message to Slack. Prefers Bot API when SLACK_BOT_TOKEN is set,
 * falls back to incoming webhook.
 */
export async function sendSlackMessage(text: string, channel?: string): Promise<boolean> {
  const botToken = process.env.SLACK_BOT_TOKEN;
  const targetChannel = channel || process.env.SLACK_DEFAULT_CHANNEL;

  // Prefer Bot API
  if (botToken && targetChannel) {
    try {
      const res = await fetch("https://slack.com/api/chat.postMessage", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${botToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ channel: targetChannel, text }),
      });
      const data = (await res.json()) as { ok: boolean };
      if (data.ok) return true;
    } catch {
      // Fall through to webhook
    }
  }

  // Fallback: webhook
  const url = getWebhookUrl();
  if (!url) return false;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    return res.ok;
  } catch {
    return false;
  }
}
