import { input, select, confirm } from "@inquirer/prompts";
import chalk from "chalk";
import { chat, type AgentConfig } from "../agent/core.ts";
import { buildSystemPrompt } from "../agent/system-prompt.ts";
import { createCanUseTool } from "../agent/permissions.ts";
import { createGitHubMcpServer, createKnowledgeMcpServer, createSchedulerMcpServer, createSlackMcpServer, createVisualizationMcpServer } from "../tools/index.ts";
import { getDb, newId } from "../db/index.ts";
import { chatSessions, messages } from "../db/schema.ts";
import { desc, eq } from "drizzle-orm";
import { renderMessage, renderToolApproval, Spinner } from "./renderer.ts";

// Slash command mappings
const SLASH_COMMANDS: Record<string, string> = {
  "/standup":
    "Analyze the current sprint and give me a daily standup report. Focus on: what's in progress, what's blocked, what was completed recently, and any risks.",
  "/analyze":
    "Deep analysis of the current sprint: health, risks, blockers, progress, team workload, and actionable recommendations.",
  "/estimate":
    "Estimate effort for the specified issue using the Fibonacci scale (1, 2, 3, 5, 8, 13). Provide reasoning, breakdown, assumptions, and risks.",
};

async function approvalHandler(
  toolName: string,
  toolInput: Record<string, unknown>
): Promise<boolean> {
  console.log(renderToolApproval(toolName, toolInput));
  return confirm({ message: "  Approve this action?", default: false });
}

export async function startTui() {
  console.log(chalk.bold("\n  PM Agent\n"));
  console.log(chalk.dim("  Type a message, use /commands, or Ctrl+C to exit.\n"));

  const mode = await select({
    message: "What would you like to do?",
    choices: [
      { name: "Chat", value: "chat", description: "Start a new conversation" },
      {
        name: "Resume session",
        value: "resume",
        description: "Continue a previous conversation",
      },
      { name: "Exit", value: "exit" },
    ],
  });

  if (mode === "exit") return;

  let resumeSessionId: string | undefined;
  let chatSessionId: string;

  if (mode === "resume") {
    const db = getDb();
    const sessions = db
      .select()
      .from(chatSessions)
      .orderBy(desc(chatSessions.updatedAt))
      .limit(10)
      .all();

    if (sessions.length === 0) {
      console.log(chalk.yellow("  No previous sessions found. Starting new chat.\n"));
      chatSessionId = newId();
    } else {
      const picked = await select({
        message: "Select session:",
        choices: [
          ...sessions.map((s) => ({
            name: `${s.name} (${new Date(s.createdAt).toLocaleDateString()})`,
            value: s.id,
          })),
          { name: "New session", value: "__new__" },
        ],
      });

      if (picked === "__new__") {
        chatSessionId = newId();
      } else {
        const session = sessions.find((s) => s.id === picked);
        chatSessionId = picked;
        resumeSessionId = session?.sessionId ?? undefined;
      }
    }
  } else {
    chatSessionId = newId();
  }

  // Create new session in DB if needed
  if (!resumeSessionId) {
    const db = getDb();
    db.insert(chatSessions)
      .values({
        id: chatSessionId,
        name: `Session ${new Date().toLocaleString()}`,
        createdAt: new Date(),
        updatedAt: new Date(),
      })
      .run();
  }

  // Build agent config
  const githubServer = createGitHubMcpServer();
  const knowledgeServer = createKnowledgeMcpServer();
  const schedulerServer = createSchedulerMcpServer();
  const slackServer = createSlackMcpServer();
  const visualizationServer = createVisualizationMcpServer();
  const systemPrompt = buildSystemPrompt();
  const canUseTool = createCanUseTool(approvalHandler);

  const agentConfig: AgentConfig = {
    systemPrompt,
    mcpServers: { github: githubServer, knowledge: knowledgeServer, scheduler: schedulerServer, slack: slackServer, visualization: visualizationServer },
    canUseTool,
    resume: resumeSessionId,
    model: process.env.AGENT_MODEL || undefined,
  };

  // Chat loop
  while (true) {
    let userInput: string;
    try {
      userInput = await input({ message: chalk.cyan(">") });
    } catch {
      // User pressed Ctrl+C
      break;
    }

    const trimmed = userInput.trim();
    if (!trimmed) continue;
    if (trimmed === "/exit" || trimmed === "/quit") break;

    // Handle slash commands
    let prompt = trimmed;
    if (trimmed.startsWith("/")) {
      const parts = trimmed.split(" ");
      const cmd = parts[0]!;
      const args = parts.slice(1).join(" ");

      if (SLASH_COMMANDS[cmd]) {
        prompt = SLASH_COMMANDS[cmd]!;
        if (args) prompt += ` Issue: ${args}`;
        console.log(chalk.dim(`  Running: ${cmd}\n`));
      } else {
        console.log(chalk.yellow(`  Unknown command: ${cmd}`));
        console.log(
          chalk.dim(
            `  Available: ${Object.keys(SLASH_COMMANDS).join(", ")}, /exit`
          )
        );
        continue;
      }
    }

    // Save user message
    const db = getDb();
    db.insert(messages)
      .values({
        id: newId(),
        chatSessionId,
        role: "user",
        content: prompt,
        createdAt: new Date(),
      })
      .run();

    // Stream response
    let fullResponse = "";
    let sdkSessionId: string | undefined;
    const spinner = new Spinner();

    try {
      for await (const msg of chat(prompt, agentConfig)) {
        if (msg.type === "thinking") {
          spinner.start("Thinking...");
          continue;
        } else if (msg.type === "typing") {
          spinner.start("Typing...");
          continue;
        }

        // Stop spinner when content arrives
        if (msg.type === "partial" || msg.type === "text" || msg.type === "tool_use") {
          spinner.stop();
        }

        const rendered = renderMessage(msg);
        if (rendered) {
          process.stdout.write(rendered);
        }

        if (msg.type === "text") {
          fullResponse += msg.content;
        } else if (msg.type === "partial") {
          fullResponse += msg.content;
        }

        if (msg.sessionId) {
          sdkSessionId = msg.sessionId;
        }
      }
    } catch (err) {
      console.log(
        chalk.red(
          `\n  Error: ${err instanceof Error ? err.message : String(err)}`
        )
      );
    }

    spinner.stop();
    console.log("\n");

    // Save assistant response
    if (fullResponse) {
      db.insert(messages)
        .values({
          id: newId(),
          chatSessionId,
          role: "assistant",
          content: fullResponse,
          createdAt: new Date(),
        })
        .run();
    }

    // Update session with SDK session ID for future resume
    if (sdkSessionId) {
      db.update(chatSessions)
        .set({ sessionId: sdkSessionId, updatedAt: new Date() })
        .where(eq(chatSessions.id, chatSessionId))
        .run();
      agentConfig.resume = sdkSessionId;
    }
  }

  console.log(chalk.dim("\n  Goodbye.\n"));
}
