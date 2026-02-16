import type { CanUseTool } from "@anthropic-ai/claude-agent-sdk";
import { WRITE_TOOL_NAMES } from "../tools/index.ts";

type ApprovalHandler = (
  toolName: string,
  input: Record<string, unknown>
) => Promise<boolean>;

export function createCanUseTool(onApproval: ApprovalHandler): CanUseTool {
  return async (toolName, input, _options) => {
    // Auto-allow all read tools
    if (!WRITE_TOOL_NAMES.includes(toolName)) {
      return { behavior: "allow" as const };
    }

    // Write tools need user approval
    const approved = await onApproval(toolName, input);

    if (approved) {
      return { behavior: "allow" as const };
    }

    return {
      behavior: "deny" as const,
      message: `User denied ${toolName} operation.`,
    };
  };
}
