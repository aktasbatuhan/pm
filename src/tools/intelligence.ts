import * as fs from "fs";
import * as path from "path";
import { z } from "zod/v4";
import {
  createSdkMcpServer,
  tool,
  type McpSdkServerConfigWithInstance,
} from "@anthropic-ai/claude-agent-sdk";

/**
 * Intelligence MCP Server — skill discovery and execution templates.
 *
 * Skills are markdown workflow definitions in the `skills/` directory.
 * This server lets the agent list and read them to follow structured
 * intelligence workflows (daily briefing, anomaly detection, etc.).
 */

const SKILLS_DIR = path.join(process.cwd(), "skills");

const listSkills = tool(
  "intelligence_list_skills",
  "List all available intelligence skills (daily-briefing, anomaly-detection, etc.). Each skill is a structured workflow the agent can follow.",
  {},
  async () => {
    try {
      const files = fs.readdirSync(SKILLS_DIR)
        .filter(f => f.endsWith(".md"))
        .map(f => f.replace(".md", ""));
      return {
        content: [{
          type: "text" as const,
          text: files.length === 0
            ? "No skills found."
            : `Available skills:\n${files.map(f => `- ${f}`).join("\n")}`,
        }],
      };
    } catch {
      return {
        content: [{ type: "text" as const, text: "Skills directory not found." }],
        isError: true,
      };
    }
  },
  { annotations: { readOnly: true } }
);

const getSkill = tool(
  "intelligence_get_skill",
  "Read a skill definition to follow its workflow. Returns the full markdown with steps, tools to use, and scheduler prompt.",
  {
    name: z.string().describe("Skill name (e.g. 'daily-briefing', 'anomaly-detection', 'sprint-recommendation', 'weekly-digest')"),
  },
  async ({ name }) => {
    const safeName = name.replace(/[^a-z0-9-]/gi, "");
    const filePath = path.join(SKILLS_DIR, `${safeName}.md`);
    try {
      const content = fs.readFileSync(filePath, "utf-8");
      return { content: [{ type: "text" as const, text: content }] };
    } catch {
      return {
        content: [{ type: "text" as const, text: `Skill not found: ${name}` }],
        isError: true,
      };
    }
  },
  { annotations: { readOnly: true } }
);

const TOOLS = [listSkills, getSkill];

export const INTELLIGENCE_TOOL_NAMES: string[] = [];

export function createIntelligenceMcpServer(): McpSdkServerConfigWithInstance {
  return createSdkMcpServer({
    name: "intelligence",
    version: "0.1.0",
    tools: TOOLS,
  });
}
