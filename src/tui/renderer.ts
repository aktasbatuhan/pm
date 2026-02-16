import chalk from "chalk";
import type { AgentMessage } from "../agent/core.ts";

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

export class Spinner {
  private interval: ReturnType<typeof setInterval> | null = null;
  private frame = 0;
  private label = "";

  start(label: string) {
    this.stop();
    this.label = label;
    this.frame = 0;
    this.render();
    this.interval = setInterval(() => this.render(), 80);
  }

  stop() {
    if (this.interval) {
      clearInterval(this.interval);
      this.interval = null;
      process.stdout.write("\r\x1b[K"); // clear line
    }
  }

  private render() {
    const f = SPINNER_FRAMES[this.frame % SPINNER_FRAMES.length]!;
    process.stdout.write(`\r  ${chalk.cyan(f)} ${chalk.dim(this.label)}`);
    this.frame++;
  }
}

export function renderMessage(msg: AgentMessage): string {
  switch (msg.type) {
    case "text":
      return msg.content;
    case "tool_use":
      return chalk.dim(`  [${msg.toolName}]`);
    case "result":
      if (msg.isError) {
        return chalk.red(`\nError: ${msg.content}`);
      }
      if (msg.costUsd !== undefined) {
        return chalk.dim(`\n  ($${msg.costUsd.toFixed(4)})`);
      }
      return "";
    case "partial":
      return msg.content;
    case "thinking":
    case "typing":
      return ""; // handled by spinner in tui/index.ts
    default:
      return "";
  }
}

export function renderToolApproval(
  toolName: string,
  input: Record<string, unknown>
): string {
  const lines = [
    "",
    chalk.yellow.bold("  Approval Required"),
    chalk.yellow(`  Tool: ${toolName}`),
  ];

  if (toolName === "github_create_issue") {
    lines.push(chalk.yellow(`  Repo: ${input.owner}/${input.repo}`));
    lines.push(chalk.yellow(`  Title: ${input.title}`));
    if (input.body) {
      const body = String(input.body);
      lines.push(
        chalk.yellow(`  Body: ${body.length > 100 ? body.slice(0, 100) + "..." : body}`)
      );
    }
  } else if (toolName === "github_update_issue") {
    lines.push(chalk.yellow(`  Repo: ${input.owner}/${input.repo}`));
    lines.push(chalk.yellow(`  Issue: #${input.issue_number}`));
    const fields = Object.keys(input).filter(
      (k) => !["owner", "repo", "issue_number"].includes(k)
    );
    lines.push(chalk.yellow(`  Updating: ${fields.join(", ")}`));
  } else if (toolName === "github_add_comment") {
    lines.push(chalk.yellow(`  Repo: ${input.owner}/${input.repo}`));
    lines.push(chalk.yellow(`  Issue: #${input.issue_number}`));
    const body = String(input.body || "");
    lines.push(
      chalk.yellow(`  Comment: ${body.length > 100 ? body.slice(0, 100) + "..." : body}`)
    );
  }

  lines.push("");
  return lines.join("\n");
}
