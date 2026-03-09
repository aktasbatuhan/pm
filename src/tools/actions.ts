/**
 * Actions MCP server — lets agents propose actions that require human approval.
 *
 * Instead of executing directly, agents create action proposals that appear
 * in the UI for the human PM to approve or reject.
 */

import {
  createSdkMcpServer,
  tool,
  type McpSdkServerConfigWithInstance,
} from "@anthropic-ai/claude-agent-sdk";
import { z } from "zod/v4";
import { getDb, newId } from "../db/index.ts";
import { actions } from "../db/schema.ts";
import { desc } from "drizzle-orm";

export const ACTIONS_WRITE_TOOL_NAMES = [
  "mcp__actions__propose_action",
];

const proposeAction = tool(
  "propose_action",
  `Propose an action for human approval. The action will NOT execute immediately — it goes into the approval queue for the PM to review.

Use this when your analysis reveals something that should be DONE, not just reported. Types:
- github_issue: Create a new GitHub issue (payload: { repo, title, body, labels?, assignees? })
- github_comment: Comment on a PR or issue (payload: { repo, issue_number, body })
- slack_dm: Send a Slack message to someone (payload: { channel_or_user, message })
- github_label: Add/remove labels (payload: { repo, issue_number, labels, action: "add"|"remove" })
- custom: Any other action (payload: { description, details })`,
  {
    type: z.enum(["github_issue", "github_comment", "slack_dm", "github_label", "custom"]),
    title: z.string().describe("Short action title shown in approval queue"),
    description: z.string().describe("Why this action is needed — context for the PM reviewing it"),
    payload: z.string().describe("JSON string with action-specific parameters"),
    source_insight_id: z.string().optional().describe("Link to the insight that triggered this"),
    source_escalation_id: z.string().optional().describe("Link to the escalation that triggered this"),
  },
  async ({ type, title, description, payload, source_insight_id, source_escalation_id }) => {
    const db = getDb();
    const now = new Date();

    let parsedPayload: Record<string, unknown>;
    try {
      parsedPayload = JSON.parse(payload);
    } catch {
      return { content: [{ type: "text" as const, text: "Error: payload must be valid JSON" }], isError: true };
    }

    const id = newId();
    db.insert(actions).values({
      id,
      type,
      title,
      description,
      payload: parsedPayload,
      status: "pending",
      sourceInsightId: source_insight_id || null,
      sourceEscalationId: source_escalation_id || null,
      createdAt: now,
      updatedAt: now,
    }).run();

    return {
      content: [{ type: "text" as const, text: `Action proposed: "${title}" (${type}). Waiting for PM approval. ID: ${id}` }],
    };
  },
  { annotations: { readOnly: false } }
);

const listActions = tool(
  "list_actions",
  "List proposed actions and their status (pending, approved, rejected, executed, failed).",
  {
    status: z.string().optional().describe("Filter by status"),
    limit: z.number().optional().describe("Max results (default 20)"),
  },
  async ({ status, limit }) => {
    const db = getDb();
    let rows = db.select()
      .from(actions)
      .orderBy(desc(actions.createdAt))
      .limit(limit || 20)
      .all();

    if (status) {
      rows = rows.filter((r) => r.status === status);
    }

    const output = JSON.stringify(rows.map((r) => ({
      id: r.id,
      type: r.type,
      title: r.title,
      status: r.status,
      createdAt: r.createdAt?.toISOString(),
    })), null, 2);

    return { content: [{ type: "text" as const, text: output }] };
  },
  { annotations: { readOnly: true } }
);

export function createActionsMcpServer(): McpSdkServerConfigWithInstance {
  return createSdkMcpServer({
    name: "actions",
    version: "1.0.0",
    tools: [proposeAction, listActions],
  });
}
