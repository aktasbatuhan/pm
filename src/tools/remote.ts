import type { McpServerConfig } from "@anthropic-ai/claude-agent-sdk";
import { getSettingString } from "../db/settings.ts";

/**
 * Create an Exa web search MCP server config (remote HTTP).
 * Returns null if EXA_API_KEY is not set.
 */
export function createExaMcpServer(): McpServerConfig | null {
  const apiKey = getSettingString("integration.exa_api_key");
  if (!apiKey) return null;
  return {
    type: "http",
    url: `https://mcp.exa.ai/mcp?exaApiKey=${apiKey}`,
  };
}

/**
 * Create a Linear issue tracking MCP server config (remote HTTP).
 * Returns null if LINEAR_API_KEY is not set.
 */
export function createLinearMcpServer(): McpServerConfig | null {
  const apiKey = getSettingString("integration.linear_api_key");
  if (!apiKey) return null;
  return {
    type: "http",
    url: "https://mcp.linear.app/mcp",
    headers: {
      Authorization: `Bearer ${apiKey}`,
    },
  };
}

/**
 * Collect all configured remote MCP servers.
 * Only includes servers whose API keys are set.
 */
export function getRemoteMcpServers(): Record<string, McpServerConfig> {
  const servers: Record<string, McpServerConfig> = {};

  const exa = createExaMcpServer();
  if (exa) servers.exa = exa;

  const linear = createLinearMcpServer();
  if (linear) servers.linear = linear;

  return servers;
}
