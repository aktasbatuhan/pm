import type { CanUseTool } from "@anthropic-ai/claude-agent-sdk";
import * as path from "path";

const DATA_DIR = process.env.DATA_DIR || process.cwd();

export const WORKSPACE_DIR = path.join(
  process.env.SANDBOX_DIR || DATA_DIR,
  process.env.SANDBOX_DIR ? "" : "workspace"
);

// Patterns that indicate dangerous bash commands
const DANGEROUS_PATTERNS: Array<[RegExp, string]> = [
  // Database destruction
  [/rm\s.*pm-agent\.db/i, "Cannot delete the application database"],
  [/rm\s+-rf?\s+\/data(?:\/|$)/, "Cannot delete persistent data directory"],
  [/rm\s+-rf?\s+\/\s/, "Cannot delete root filesystem"],
  // Process manipulation
  [/\bkill\s/, "Cannot kill processes"],
  [/\bpkill\s/, "Cannot kill processes"],
  [/\bkillall\s/, "Cannot kill processes"],
  // Server interference
  [/bun\s+run\s+src\/index/, "Cannot restart the server"],
  // Environment/secret access
  [/\bcat\s+.*\.env\b/, "Cannot read environment files"],
  [/\bprintenv\b/, "Cannot list environment variables"],
  [/\b(?:^|\s)env\b(?!\s+\S+=)/, "Cannot list environment variables"],
  [/echo\s+.*\$[A-Z_]*(TOKEN|KEY|SECRET|PASSWORD)/, "Cannot echo secrets"],
  // System modification
  [/\bapt-get\s/, "Cannot modify system packages"],
  [/\bchmod\s.*\/(?:data|app)\b/, "Cannot modify system permissions"],
  [/\bchown\s/, "Cannot change file ownership"],
  // Disk bombs
  [/\bdd\s+if=/, "Cannot use dd"],
  [/\bmkfs\b/, "Cannot create filesystems"],
];

export function isDangerousCommand(command: string): string | null {
  for (const [pattern, reason] of DANGEROUS_PATTERNS) {
    if (pattern.test(command)) {
      return reason;
    }
  }
  return null;
}

const ALLOWED_WRITE_PREFIXES = [
  WORKSPACE_DIR,
  "/tmp",
  path.join(DATA_DIR, "knowledge"),
];

export function isPathAllowed(filePath: string): boolean {
  const normalized = path.resolve(
    filePath.startsWith("/") ? filePath : path.join(WORKSPACE_DIR, filePath)
  );
  return ALLOWED_WRITE_PREFIXES.some((prefix) => normalized.startsWith(prefix));
}

export const sandboxCanUseTool: CanUseTool = async (
  toolName,
  input,
  _options
) => {
  if (toolName === "Bash") {
    const command = String(input.command || "");
    const reason = isDangerousCommand(command);
    if (reason) {
      return { behavior: "deny" as const, message: `Blocked: ${reason}` };
    }
  }

  if (toolName === "Write" || toolName === "Edit") {
    const filePath = String(input.file_path || "");
    if (filePath && !isPathAllowed(filePath)) {
      return {
        behavior: "deny" as const,
        message: `Write operations are restricted to ${WORKSPACE_DIR}, /tmp, and knowledge directory`,
      };
    }
  }

  return { behavior: "allow" as const, updatedInput: input };
};
