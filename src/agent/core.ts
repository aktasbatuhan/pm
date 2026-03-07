import {
  query,
  type SDKMessage,
  type SDKAssistantMessage,
  type SDKResultMessage,
  type SDKPartialAssistantMessage,
  type SDKUserMessage,
  type McpSdkServerConfigWithInstance,
  type McpServerConfig,
  type CanUseTool,
} from "@anthropic-ai/claude-agent-sdk";

export interface ImageAttachment {
  data: string;
  media_type: string;
}

export interface AgentConfig {
  systemPrompt: string;
  mcpServers: Record<string, McpServerConfig>;
  canUseTool?: CanUseTool;
  sessionId?: string;
  resume?: string;
  model?: string;
  allowedTools?: string[];
  workingDirectory?: string;
}

export interface AgentMessage {
  type: "text" | "tool_use" | "result" | "partial" | "thinking" | "typing" | "thinking_delta";
  content: string;
  toolName?: string;
  toolInput?: Record<string, unknown>;
  isError?: boolean;
  sessionId?: string;
  costUsd?: number;
}

export async function* chat(
  userMessage: string,
  config: AgentConfig,
  images?: ImageAttachment[]
): AsyncGenerator<AgentMessage> {
  // Ensure sub-agents use the same model as the main agent (not haiku default)
  const effectiveModel = config.model || process.env.AGENT_MODEL || "google/gemini-3-flash-preview";
  if (!process.env.CLAUDE_CODE_SUBAGENT_MODEL) {
    process.env.CLAUDE_CODE_SUBAGENT_MODEL = effectiveModel;
  }

  // Build prompt: multimodal if images are attached, plain string otherwise
  let prompt: string | AsyncIterable<SDKUserMessage>;

  if (images && images.length > 0) {
    const content: Array<Record<string, unknown>> = [];
    for (const img of images) {
      content.push({
        type: "image",
        source: {
          type: "base64",
          media_type: img.media_type,
          data: img.data,
        },
      });
    }
    if (userMessage) {
      content.push({ type: "text", text: userMessage });
    }

    async function* generateMessages(): AsyncGenerator<SDKUserMessage> {
      yield {
        type: "user" as const,
        message: {
          role: "user" as const,
          content: content as any,
        },
        parent_tool_use_id: null,
        session_id: "",
      };
    }
    prompt = generateMessages();
  } else {
    prompt = userMessage;
  }

  const q = query({
    prompt,
    options: {
      systemPrompt: config.systemPrompt,
      mcpServers: config.mcpServers,
      canUseTool: config.canUseTool,
      tools: [],
      allowedTools: config.allowedTools ?? [
        "mcp__github__*", "mcp__knowledge__*", "mcp__scheduler__*",
        "mcp__slack__*", "mcp__visualization__*", "mcp__posthog__*",
        "mcp__dashboard__*", "mcp__exa__*",
        "mcp__sandbox__*", "mcp__linear__*",
        "mcp__memory__*", "mcp__signals__*",
        "mcp__intelligence__*",
      ],
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
      if ("thinking" in delta) {
        results.push({ type: "thinking_delta", content: (delta as any).thinking });
      } else if ("text" in delta) {
        if (!alreadyTyping) {
          results.push({ type: "typing", content: "" });
        }
        results.push({ type: "partial", content: delta.text });
      }
    }
  }

  return results;
}
