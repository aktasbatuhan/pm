import * as fs from "fs";
import * as path from "path";
import { z } from "zod/v4";
import {
  createSdkMcpServer,
  tool,
  type McpSdkServerConfigWithInstance,
} from "@anthropic-ai/claude-agent-sdk";
import { KNOWLEDGE_DIR } from "../paths.ts";

function resolveSafe(filePath: string): string | null {
  const resolved = path.resolve(KNOWLEDGE_DIR, filePath);
  if (!resolved.startsWith(KNOWLEDGE_DIR + path.sep) && resolved !== KNOWLEDGE_DIR) {
    return null;
  }
  if (!resolved.endsWith(".md")) return null;
  return resolved;
}

// --- Read Tools ---

const listFilesTool = tool(
  "knowledge_list_files",
  "List all knowledge files in the knowledge directory recursively",
  {},
  async () => {
    const files: string[] = [];
    function walk(dir: string) {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.name.startsWith(".")) continue;
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          walk(full);
        } else if (entry.name.endsWith(".md")) {
          files.push(path.relative(KNOWLEDGE_DIR, full));
        }
      }
    }
    walk(KNOWLEDGE_DIR);
    return {
      content: [{ type: "text" as const, text: JSON.stringify(files, null, 2) }],
    };
  },
  { annotations: { readOnly: true } }
);

const readFileTool = tool(
  "knowledge_read_file",
  "Read the contents of a specific knowledge file",
  {
    path: z.string().describe("Relative path within knowledge/ (e.g. 'overview.md' or 'repos/my-repo.md')"),
  },
  async ({ path: filePath }) => {
    const resolved = resolveSafe(filePath);
    if (!resolved) {
      return {
        content: [{ type: "text" as const, text: "Error: Invalid path. Must be a .md file within knowledge/." }],
        isError: true,
      };
    }
    try {
      const content = fs.readFileSync(resolved, "utf-8");
      return { content: [{ type: "text" as const, text: content }] };
    } catch {
      return {
        content: [{ type: "text" as const, text: `Error: File not found: ${filePath}` }],
        isError: true,
      };
    }
  },
  { annotations: { readOnly: true } }
);

// --- Write Tools ---

const updateFileTool = tool(
  "knowledge_update_file",
  "Create or overwrite a knowledge file with new content. Use this to update existing knowledge or create new knowledge files.",
  {
    path: z.string().describe("Relative path within knowledge/ (e.g. 'overview.md' or 'repos/new-repo.md')"),
    content: z.string().describe("The full markdown content to write"),
  },
  async ({ path: filePath, content }) => {
    const resolved = resolveSafe(filePath);
    if (!resolved) {
      return {
        content: [{ type: "text" as const, text: "Error: Invalid path. Must be a .md file within knowledge/." }],
        isError: true,
      };
    }
    try {
      const dir = path.dirname(resolved);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
      fs.writeFileSync(resolved, content, "utf-8");
      return {
        content: [{ type: "text" as const, text: `Updated: ${filePath}` }],
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

const appendFileTool = tool(
  "knowledge_append_to_file",
  "Append content to an existing knowledge file. Useful for adding new sections or notes without replacing existing content.",
  {
    path: z.string().describe("Relative path within knowledge/ (e.g. 'overview.md')"),
    content: z.string().describe("The markdown content to append"),
  },
  async ({ path: filePath, content }) => {
    const resolved = resolveSafe(filePath);
    if (!resolved) {
      return {
        content: [{ type: "text" as const, text: "Error: Invalid path. Must be a .md file within knowledge/." }],
        isError: true,
      };
    }
    if (!fs.existsSync(resolved)) {
      return {
        content: [{ type: "text" as const, text: `Error: File not found: ${filePath}. Use knowledge_update_file to create new files.` }],
        isError: true,
      };
    }
    try {
      fs.appendFileSync(resolved, "\n" + content, "utf-8");
      return {
        content: [{ type: "text" as const, text: `Appended to: ${filePath}` }],
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

// --- Export MCP Server ---

const READ_TOOLS = [listFilesTool, readFileTool];
const WRITE_TOOLS = [updateFileTool, appendFileTool];

export const KNOWLEDGE_WRITE_TOOL_NAMES = WRITE_TOOLS.map((t) => t.name);

export function createKnowledgeMcpServer(): McpSdkServerConfigWithInstance {
  return createSdkMcpServer({
    name: "knowledge",
    version: "0.1.0",
    tools: [...READ_TOOLS, ...WRITE_TOOLS],
  });
}
