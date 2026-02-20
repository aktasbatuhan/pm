import {
  query,
  type SDKMessage,
  type SDKAssistantMessage,
  type SDKResultMessage,
  type SDKPartialAssistantMessage,
  type McpSdkServerConfigWithInstance,
  type McpServerConfig,
  type CanUseTool,
} from "@anthropic-ai/claude-agent-sdk";

export interface AgentConfig {
  systemPrompt: string;
  mcpServers: Record<string, McpServerConfig>;
  canUseTool?: CanUseTool;
  sessionId?: string;
  resume?: string;
  model?: string;
  allowedTools?: string[];
}

export interface AgentMessage {
  type: "text" | "tool_use" | "result" | "partial" | "thinking" | "typing";
  content: string;
  toolName?: string;
  toolInput?: Record<string, unknown>;
  isError?: boolean;
  sessionId?: string;
  costUsd?: number;
}

export async function* chat(
  userMessage: string,
  config: AgentConfig
): AsyncGenerator<AgentMessage> {
  const q = query({
    prompt: userMessage,
    options: {
      systemPrompt: config.systemPrompt,
      mcpServers: config.mcpServers,
      canUseTool: config.canUseTool,
      tools: [],
      allowedTools: config.allowedTools ?? ["mcp__github__*", "mcp__knowledge__*", "mcp__scheduler__*", "mcp__slack__*", "mcp__visualization__*", "mcp__posthog__*", "mcp__dashboard__*", "mcp__exa__*", "mcp__granola__*"],
      includePartialMessages: true,
      resume: config.resume,
      sessionId: config.sessionId,
      maxTurns: 20,
      permissionMode: "default",
      model: config.model,
    },
  });

  let emittedThinking = false;
  let emittedTyping = false;

  for await (const message of q) {
    for (const parsed of parseMessage(message, emittedThinking, emittedTyping)) {
      if (parsed.type === "thinking") emittedThinking = true;
      if (parsed.type === "typing") emittedTyping = true;
      yield parsed;
    }

    // Reset flags on new assistant messages (new turn)
    if (message.type === "assistant") {
      emittedThinking = false;
      emittedTyping = false;
    }
  }
}

function parseMessage(
  message: SDKMessage,
  alreadyThinking: boolean,
  alreadyTyping: boolean
): AgentMessage[] {
  const results: AgentMessage[] = [];

  if (message.type === "assistant") {
    const msg = message as SDKAssistantMessage;
    for (const block of msg.message.content) {
      if (block.type === "text") {
        results.push({
          type: "text",
          content: block.text,
          sessionId: msg.session_id,
        });
      } else if (block.type === "tool_use") {
        results.push({
          type: "tool_use",
          content: `Using ${block.name}...`,
          toolName: block.name,
          toolInput: block.input as Record<string, unknown>,
          sessionId: msg.session_id,
        });
      }
    }
  } else if (message.type === "result") {
    const msg = message as SDKResultMessage;
    if (msg.subtype === "success") {
      results.push({
        type: "result",
        content: msg.result,
        sessionId: msg.session_id,
        costUsd: msg.total_cost_usd,
      });
    } else {
      results.push({
        type: "result",
        content: `Error: ${msg.errors?.join(", ") || "Unknown error"}`,
        isError: true,
        sessionId: msg.session_id,
        costUsd: msg.total_cost_usd,
      });
    }
  } else if (message.type === "stream_event") {
    const msg = message as SDKPartialAssistantMessage;

    if (msg.event.type === "content_block_start") {
      const block = (msg.event as { content_block?: { type: string } })
        .content_block;
      if (block?.type === "thinking" && !alreadyThinking) {
        results.push({ type: "thinking", content: "" });
      }
    } else if (msg.event.type === "content_block_delta") {
      const delta = msg.event.delta;
      if ("text" in delta) {
        if (!alreadyTyping) {
          results.push({ type: "typing", content: "" });
        }
        results.push({ type: "partial", content: delta.text });
      }
    }
  }

  return results;
}
