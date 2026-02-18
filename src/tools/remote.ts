import type { McpServerConfig } from "@anthropic-ai/claude-agent-sdk";

/**
 * Create an Exa web search MCP server config (remote HTTP).
 * Returns null if EXA_API_KEY is not set.
 */
export function createExaMcpServer(): McpServerConfig | null {
  const apiKey = process.env.EXA_API_KEY;
  if (!apiKey) return null;
  return {
    type: "http",
    url: `https://mcp.exa.ai/mcp?exaApiKey=${apiKey}`,
  };
}

/**
 * Create a Granola meeting notes MCP server config (remote HTTP).
 * Returns null if GRANOLA_API_KEY is not set.
 */
export function createGranolaMcpServer(): McpServerConfig | null {
  const apiKey = process.env.GRANOLA_API_KEY;
  if (!apiKey) return null;
  return {
    type: "http",
    url: "https://mcp.granola.ai/mcp",
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

  const granola = createGranolaMcpServer();
  if (granola) servers.granola = granola;

  return servers;
}
