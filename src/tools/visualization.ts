import { z } from "zod/v4";
import {
  createSdkMcpServer,
  tool,
  type McpSdkServerConfigWithInstance,
} from "@anthropic-ai/claude-agent-sdk";

const renderChartTool = tool(
  "render_chart",
  `Render a Chart.js chart inline in the chat. Use for data comparisons, trends, and distributions.

The config parameter must be a valid JSON string with this structure:
{
  "type": "bar"|"line"|"pie"|"doughnut"|"radar"|"polarArea",
  "title": "optional title",
  "data": {
    "labels": ["Label1", "Label2"],
    "datasets": [{ "label": "Series", "data": [10, 20], "backgroundColor": "#e8912d" }]
  }
}

Colors: #e8912d (amber), #00c853 (green), #ff3d3d (red), #58a6ff (blue), #d29922 (yellow)`,
  {
    config: z.string().describe("JSON string containing Chart.js chart configuration"),
  },
  async ({ config }) => {
    try {
      const parsed = JSON.parse(config);
      const type = parsed.type || "bar";
      const title = parsed.title || type;
      const labelCount = parsed.data?.labels?.length || 0;
      return {
        content: [{
          type: "text" as const,
          text: `Chart rendered: ${title} (${labelCount} labels)`,
        }],
      };
    } catch {
      return {
        content: [{ type: "text" as const, text: "Error: Invalid JSON in config parameter" }],
        isError: true,
      };
    }
  },
  { annotations: { readOnly: true, destructive: false } }
);

const renderDiagramTool = tool(
  "render_diagram",
  "Render a Mermaid diagram inline in the chat. Use for flowcharts, gantt timelines, sequence diagrams, and more.",
  {
    code: z.string().describe("Valid Mermaid syntax"),
    title: z.string().optional().describe("Diagram title"),
  },
  async ({ code, title }) => {
    return {
      content: [{
        type: "text" as const,
        text: `Diagram rendered: ${title || "Mermaid diagram"} (${code.split("\n").length} lines)`,
      }],
    };
  },
  { annotations: { readOnly: true, destructive: false } }
);

// --- Export ---

export function createVisualizationMcpServer(): McpSdkServerConfigWithInstance {
  return createSdkMcpServer({
    name: "visualization",
    version: "0.1.0",
    tools: [renderChartTool, renderDiagramTool],
  });
}
