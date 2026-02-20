import * as fs from "fs";
import * as path from "path";
import { z } from "zod/v4";
import {
  createSdkMcpServer,
  tool,
  type McpSdkServerConfigWithInstance,
} from "@anthropic-ai/claude-agent-sdk";
import { isDangerousCommand, isPathAllowed, WORKSPACE_DIR } from "../agent/sandbox.ts";

// --- Bash Tool ---

const bashTool = tool(
  "sandbox_bash",
  `Execute a shell command in the sandbox workspace (${WORKSPACE_DIR}). Available runtimes: bun, git, gh (GitHub CLI), curl, standard unix tools. Use for: cloning repos, running scripts, data processing, file operations, code analysis. Blocked: process killing, env/secret access, system modification, database deletion.`,
  {
    command: z.string().describe("The shell command to execute"),
    timeout_ms: z.number().optional().describe("Timeout in milliseconds (default: 30000, max: 120000)"),
  },
  async ({ command, timeout_ms }) => {
    const reason = isDangerousCommand(command);
    if (reason) {
      return {
        content: [{ type: "text" as const, text: `Blocked: ${reason}` }],
        isError: true,
      };
    }

    const timeout = Math.min(timeout_ms || 30000, 120000);
    try {
      const proc = Bun.spawn(["bash", "-c", command], {
        cwd: WORKSPACE_DIR,
        stdout: "pipe",
        stderr: "pipe",
        env: { ...process.env, HOME: WORKSPACE_DIR },
      });

      const timer = setTimeout(() => proc.kill(), timeout);
      const [stdout, stderr] = await Promise.all([
        new Response(proc.stdout).text(),
        new Response(proc.stderr).text(),
      ]);
      clearTimeout(timer);

      const exitCode = proc.exitCode ?? (await proc.exited);
      const output = stdout + (stderr ? `\n[stderr] ${stderr}` : "");
      const truncated = output.length > 50000 ? output.slice(0, 50000) + "\n...[truncated]" : output;

      return {
        content: [{ type: "text" as const, text: `[exit ${exitCode}]\n${truncated}` }],
        isError: exitCode !== 0,
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

// --- Read File Tool ---

const readFileTool = tool(
  "sandbox_read_file",
  "Read a file from the sandbox workspace or /tmp. Returns file content as text.",
  {
    path: z.string().describe("Absolute path or path relative to workspace"),
  },
  async ({ path: filePath }) => {
    const resolved = filePath.startsWith("/")
      ? filePath
      : path.resolve(WORKSPACE_DIR, filePath);

    try {
      const content = fs.readFileSync(resolved, "utf-8");
      const truncated = content.length > 100000
        ? content.slice(0, 100000) + "\n...[truncated]"
        : content;
      return { content: [{ type: "text" as const, text: truncated }] };
    } catch {
      return {
        content: [{ type: "text" as const, text: `Error: Cannot read file: ${resolved}` }],
        isError: true,
      };
    }
  },
  { annotations: { readOnly: true } }
);

// --- Write File Tool ---

const writeFileTool = tool(
  "sandbox_write_file",
  `Write content to a file. Writes are restricted to ${WORKSPACE_DIR}, /tmp, and the knowledge directory.`,
  {
    path: z.string().describe("Absolute path or path relative to workspace"),
    content: z.string().describe("The content to write"),
  },
  async ({ path: filePath, content }) => {
    const resolved = filePath.startsWith("/")
      ? filePath
      : path.resolve(WORKSPACE_DIR, filePath);

    if (!isPathAllowed(resolved)) {
      return {
        content: [{ type: "text" as const, text: `Blocked: Writes restricted to ${WORKSPACE_DIR}, /tmp, and knowledge directory` }],
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
        content: [{ type: "text" as const, text: `Written: ${resolved} (${content.length} bytes)` }],
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

// --- List Directory Tool ---

const listDirTool = tool(
  "sandbox_list_dir",
  "List files and directories in a given path within the workspace.",
  {
    path: z.string().optional().describe("Absolute path or relative to workspace (default: workspace root)"),
  },
  async ({ path: dirPath }) => {
    const resolved = dirPath
      ? (dirPath.startsWith("/") ? dirPath : path.resolve(WORKSPACE_DIR, dirPath))
      : WORKSPACE_DIR;

    try {
      const entries = fs.readdirSync(resolved, { withFileTypes: true });
      const lines = entries.map((e) => {
        const suffix = e.isDirectory() ? "/" : "";
        try {
          const stat = fs.statSync(path.join(resolved, e.name));
          const size = e.isDirectory() ? "-" : `${stat.size}B`;
          return `${suffix ? "d" : "-"} ${size.padStart(10)} ${e.name}${suffix}`;
        } catch {
          return `? ${e.name}${suffix}`;
        }
      });
      return {
        content: [{ type: "text" as const, text: `${resolved}/\n${lines.join("\n")}` }],
      };
    } catch {
      return {
        content: [{ type: "text" as const, text: `Error: Cannot list directory: ${resolved}` }],
        isError: true,
      };
    }
  },
  { annotations: { readOnly: true } }
);

// --- Share File Tool ---

const shareFileTool = tool(
  "sandbox_share_file",
  `Share a file from the workspace with the user so they can download it. Use this after creating files (CSV reports, exports, analysis results, etc.) that the user should be able to download. The file must exist in ${WORKSPACE_DIR} or /tmp.`,
  {
    path: z.string().describe("Absolute path or path relative to workspace"),
    name: z.string().optional().describe("Display name for the download (defaults to filename)"),
  },
  async ({ path: filePath, name }) => {
    const resolved = filePath.startsWith("/")
      ? filePath
      : path.resolve(WORKSPACE_DIR, filePath);

    try {
      const stat = fs.statSync(resolved);
      if (!stat.isFile()) {
        return {
          content: [{ type: "text" as const, text: `Error: ${resolved} is not a file` }],
          isError: true,
        };
      }

      // Make path relative to workspace for the download URL
      const relativePath = resolved.startsWith(WORKSPACE_DIR)
        ? path.relative(WORKSPACE_DIR, resolved)
        : path.basename(resolved);
      const displayName = name || path.basename(resolved);
      const sizeKb = (stat.size / 1024).toFixed(1);

      return {
        content: [{
          type: "text" as const,
          text: JSON.stringify({
            shared: true,
            path: relativePath,
            name: displayName,
            size: stat.size,
            sizeFormatted: stat.size > 1048576 ? `${(stat.size / 1048576).toFixed(1)}MB` : `${sizeKb}KB`,
          }),
        }],
      };
    } catch {
      return {
        content: [{ type: "text" as const, text: `Error: File not found: ${resolved}` }],
        isError: true,
      };
    }
  },
  { annotations: { readOnly: true } }
);

// --- Export ---

const READ_TOOLS = [readFileTool, listDirTool];
const WRITE_TOOLS = [bashTool, writeFileTool, shareFileTool];

export const SANDBOX_TOOL_NAMES = [...READ_TOOLS, ...WRITE_TOOLS].map((t) => t.name);

export function createSandboxMcpServer(): McpSdkServerConfigWithInstance {
  return createSdkMcpServer({
    name: "sandbox",
    version: "0.1.0",
    tools: [...READ_TOOLS, ...WRITE_TOOLS],
  });
}
