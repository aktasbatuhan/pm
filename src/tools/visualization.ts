import { z } from "zod/v4";
import {
  createSdkMcpServer,
  tool,
  type McpSdkServerConfigWithInstance,
} from "@anthropic-ai/claude-agent-sdk";

const renderChartTool = tool(
  "render_chart",
  "Render a Chart.js chart inline in the chat. Use for data comparisons, trends, and distributions.",
  {
    type: z.enum(["bar", "line", "pie", "doughnut", "radar", "polarArea"]).describe("Chart type"),
    title: z.string().optional().describe("Chart title"),
    data: z.object({
      labels: z.array(z.string()).describe("Axis labels or category names"),
      datasets: z.array(z.object({
        label: z.string().describe("Dataset label"),
        data: z.array(z.number()).describe("Numeric data points"),
        backgroundColor: z.union([z.string(), z.array(z.string())]).optional().describe("Color(s) for bars/segments"),
      })).describe("One or more datasets to plot"),
    }),
    options: z.record(z.string(), z.any()).optional().describe("Extra Chart.js options"),
  },
  async ({ type, title, data, options }) => {
    return {
      content: [{
        type: "text" as const,
        text: `Chart rendered: ${title || type} (${data.labels.length} labels, ${data.datasets.length} datasets)`,
      }],
    };
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
