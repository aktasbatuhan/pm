import * as fs from "fs";
import * as path from "path";
import { z } from "zod/v4";
import {
  createSdkMcpServer,
  tool,
  type McpSdkServerConfigWithInstance,
} from "@anthropic-ai/claude-agent-sdk";
import { MEMORY_DIR } from "../paths.ts";

/**
 * Memory MCP Server — file-based institutional memory with entity linking.
 *
 * Inspired by mem-agent (https://github.com/firstbatchxyz/mem-agent-mcp).
 * Uses markdown files with wiki-style [[links]] to build a knowledge graph.
 * The main agent delegates memory operations to a subagent that uses these tools.
 *
 * Directory structure:
 *   memory/
 *   ├── product.md              # Product overview, vision, state
 *   ├── team.md                 # Team members, roles, capacity
 *   ├── metrics.md              # Key metrics and baselines
 *   ├── decisions/              # Institutional decisions with context
 *   ├── entities/               # Product concepts, features, systems
 *   ├── signals/                # Baselines and anomaly history
 *   └── sessions/               # Extracted session summaries
 */

function ensureMemoryDir() {
  if (!fs.existsSync(MEMORY_DIR)) {
    fs.mkdirSync(MEMORY_DIR, { recursive: true });
  }
}

function resolveSafe(filePath: string): string | null {
  const resolved = path.resolve(MEMORY_DIR, filePath);
  if (!resolved.startsWith(MEMORY_DIR + path.sep) && resolved !== MEMORY_DIR) {
    return null;
  }
  if (!resolved.endsWith(".md")) return null;
  return resolved;
}

function nowISO(): string {
  return new Date().toISOString();
}

/**
 * Inject or update the `updated_at` frontmatter field in a markdown file.
 */
function touchUpdatedAt(content: string): string {
  const now = nowISO();
  const fmRegex = /^---\n([\s\S]*?)\n---/;
  const match = content.match(fmRegex);

  if (match) {
    let fm = match[1];
    if (/^updated_at:/m.test(fm)) {
      fm = fm.replace(/^updated_at:.*$/m, `updated_at: ${now}`);
    } else {
      fm = `updated_at: ${now}\n${fm}`;
    }
    return content.replace(fmRegex, `---\n${fm}\n---`);
  }

  // No frontmatter — add it
  return `---\nupdated_at: ${now}\ncreated_at: ${now}\n---\n\n${content}`;
}

// --- Read Tools ---

const listMemoryFiles = tool(
  "memory_list",
  "List all memory files as a tree. Shows the full memory graph structure.",
  {},
  async () => {
    ensureMemoryDir();
    const files: string[] = [];
    function walk(dir: string) {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.name.startsWith(".")) continue;
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          walk(full);
        } else if (entry.name.endsWith(".md")) {
          files.push(path.relative(MEMORY_DIR, full));
        }
      }
    }
    walk(MEMORY_DIR);
    return {
      content: [{ type: "text" as const, text: files.length === 0 ? "Memory is empty." : files.join("\n") }],
    };
  },
  { annotations: { readOnly: true } }
);

const readMemoryFile = tool(
  "memory_read",
  "Read a memory file. Use to check existing knowledge before writing.",
  {
    path: z.string().describe("Relative path within memory/ (e.g. 'product.md', 'entities/billing.md', 'decisions/2026-03-pricing.md')"),
  },
  async ({ path: filePath }) => {
    const resolved = resolveSafe(filePath);
    if (!resolved) {
      return {
        content: [{ type: "text" as const, text: "Error: Invalid path. Must be a .md file within memory/." }],
        isError: true,
      };
    }
    try {
      const content = fs.readFileSync(resolved, "utf-8");
      return { content: [{ type: "text" as const, text: content }] };
    } catch {
      return {
        content: [{ type: "text" as const, text: `File not found: ${filePath}` }],
        isError: true,
      };
    }
  },
  { annotations: { readOnly: true } }
);

const searchMemory = tool(
  "memory_search",
  "Search across all memory files for a keyword or phrase. Returns matching file paths and surrounding context.",
  {
    query: z.string().describe("Search term or phrase to find across all memory files"),
  },
  async ({ query: searchQuery }) => {
    ensureMemoryDir();
    const results: { file: string; matches: string[] }[] = [];
    const queryLower = searchQuery.toLowerCase();

    function walk(dir: string) {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.name.startsWith(".")) continue;
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          walk(full);
        } else if (entry.name.endsWith(".md")) {
          try {
            const content = fs.readFileSync(full, "utf-8");
            const lines = content.split("\n");
            const matchLines: string[] = [];
            for (let i = 0; i < lines.length; i++) {
              if (lines[i].toLowerCase().includes(queryLower)) {
                // Include surrounding context (1 line before and after)
                const start = Math.max(0, i - 1);
                const end = Math.min(lines.length - 1, i + 1);
                const snippet = lines.slice(start, end + 1).join("\n");
                matchLines.push(`L${i + 1}: ${snippet}`);
              }
            }
            if (matchLines.length > 0) {
              results.push({
                file: path.relative(MEMORY_DIR, full),
                matches: matchLines.slice(0, 5), // cap at 5 matches per file
              });
            }
          } catch {}
        }
      }
    }
    walk(MEMORY_DIR);

    if (results.length === 0) {
      return { content: [{ type: "text" as const, text: `No matches found for "${searchQuery}".` }] };
    }

    const output = results.map(r =>
      `## ${r.file}\n${r.matches.join("\n---\n")}`
    ).join("\n\n");

    return { content: [{ type: "text" as const, text: output }] };
  },
  { annotations: { readOnly: true } }
);

const followLink = tool(
  "memory_follow_link",
  "Follow a [[wiki-style link]] to read the linked memory file. Links use format [[path/to/file]].",
  {
    link: z.string().describe("Wiki-style link, e.g. '[[entities/billing.md]]' or '[[decisions/2026-03-pricing.md]]'"),
  },
  async ({ link }) => {
    // Parse [[path/to/file]] or [[path/to/file.md]]
    let filePath = link.replace(/^\[\[/, "").replace(/\]\]$/, "");
    if (!filePath.endsWith(".md")) filePath += ".md";

    const resolved = resolveSafe(filePath);
    if (!resolved) {
      return {
        content: [{ type: "text" as const, text: `Error: Invalid link: ${link}` }],
        isError: true,
      };
    }
    try {
      const content = fs.readFileSync(resolved, "utf-8");
      return { content: [{ type: "text" as const, text: `# ${filePath}\n\n${content}` }] };
    } catch {
      return {
        content: [{ type: "text" as const, text: `Linked file not found: ${filePath}` }],
        isError: true,
      };
    }
  },
  { annotations: { readOnly: true } }
);

// --- Write Tools ---

const writeMemoryFile = tool(
  "memory_write",
  "Create or overwrite a memory file. Automatically adds/updates the `updated_at` frontmatter. Use [[wiki-style links]] to connect entities.",
  {
    path: z.string().describe("Relative path within memory/ (e.g. 'entities/billing.md', 'decisions/2026-03-pricing.md')"),
    content: z.string().describe("Full markdown content. Use [[path/to/entity.md]] for entity links."),
  },
  async ({ path: filePath, content }) => {
    const resolved = resolveSafe(filePath);
    if (!resolved) {
      return {
        content: [{ type: "text" as const, text: "Error: Invalid path. Must be a .md file within memory/." }],
        isError: true,
      };
    }
    try {
      const dir = path.dirname(resolved);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
      fs.writeFileSync(resolved, touchUpdatedAt(content), "utf-8");
      return { content: [{ type: "text" as const, text: `Written: ${filePath}` }] };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  },
  { annotations: { readOnly: false, destructive: false } }
);

const updateMemoryFile = tool(
  "memory_update",
  "Find and replace content in a memory file. Automatically updates the `updated_at` timestamp.",
  {
    path: z.string().describe("Relative path within memory/"),
    old_content: z.string().describe("Exact text to find in the file"),
    new_content: z.string().describe("Text to replace it with"),
  },
  async ({ path: filePath, old_content, new_content }) => {
    const resolved = resolveSafe(filePath);
    if (!resolved) {
      return {
        content: [{ type: "text" as const, text: "Error: Invalid path." }],
        isError: true,
      };
    }
    try {
      let content = fs.readFileSync(resolved, "utf-8");
      if (!content.includes(old_content)) {
        return {
          content: [{ type: "text" as const, text: `Error: Could not find the specified content in ${filePath}.` }],
          isError: true,
        };
      }
      content = content.replace(old_content, new_content);
      fs.writeFileSync(resolved, touchUpdatedAt(content), "utf-8");
      return { content: [{ type: "text" as const, text: `Updated: ${filePath}` }] };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  },
  { annotations: { readOnly: false, destructive: false } }
);

const deleteMemoryFile = tool(
  "memory_delete",
  "Delete a memory file. Use when information is no longer relevant.",
  {
    path: z.string().describe("Relative path within memory/"),
  },
  async ({ path: filePath }) => {
    const resolved = resolveSafe(filePath);
    if (!resolved) {
      return {
        content: [{ type: "text" as const, text: "Error: Invalid path." }],
        isError: true,
      };
    }
    try {
      fs.unlinkSync(resolved);
      return { content: [{ type: "text" as const, text: `Deleted: ${filePath}` }] };
    } catch {
      return {
        content: [{ type: "text" as const, text: `Error: File not found: ${filePath}` }],
        isError: true,
      };
    }
  },
  { annotations: { readOnly: false, destructive: true } }
);

// --- Export ---

const READ_TOOLS = [listMemoryFiles, readMemoryFile, searchMemory, followLink];
const WRITE_TOOLS = [writeMemoryFile, updateMemoryFile, deleteMemoryFile];

export const MEMORY_WRITE_TOOL_NAMES = WRITE_TOOLS.map((t) => t.name);

export function createMemoryMcpServer(): McpSdkServerConfigWithInstance {
  ensureMemoryDir();
  return createSdkMcpServer({
    name: "memory",
    version: "0.1.0",
    tools: [...READ_TOOLS, ...WRITE_TOOLS],
  });
}
