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
  "Send a message to Slack via the configured incoming webhook. Use this to notify the team about sprint updates, alerts, or scheduled job results.",
  {
    text: z.string().describe("The message text to send (supports Slack markdown/mrkdwn)"),
  },
  async ({ text }) => {
    const url = getWebhookUrl();
    if (!url) {
      return {
        content: [{ type: "text" as const, text: "Error: SLACK_WEBHOOK_URL is not configured. Cannot send Slack messages." }],
        isError: true,
      };
    }

    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });

      if (!res.ok) {
        const body = await res.text();
        return {
          content: [{ type: "text" as const, text: `Error: Slack webhook returned ${res.status}: ${body}` }],
          isError: true,
        };
      }

      return {
        content: [{ type: "text" as const, text: "Message sent to Slack." }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
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
 * Send a message to Slack directly (used by the job runner for output routing).
 */
export async function sendSlackMessage(text: string): Promise<boolean> {
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
