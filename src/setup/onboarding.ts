import { input, select, confirm } from "@inquirer/prompts";
import chalk from "chalk";
import {
  validateToken,
  listOrgs,
  listProjects,
  discoverReposFromProject,
  generateKnowledge,
  completeSetup,
} from "./steps.ts";

export async function runSetup() {
  console.log(chalk.bold("\n  PM Agent Setup\n"));
  console.log(chalk.dim("  Connect your GitHub Project and generate knowledge.\n"));

  // 1. LLM key
  const hasLlmKey = process.env.OPENROUTER_API_KEY || process.env.ANTHROPIC_API_KEY;
  let anthropicKey: string | undefined;
  let openrouterKey: string | undefined;

  if (!hasLlmKey) {
    const provider = (await select({
      message: "LLM provider:",
      choices: [
        { name: "OpenRouter (recommended)", value: "openrouter" },
        { name: "Anthropic (direct)", value: "anthropic" },
      ],
    })) as string;

    if (provider === "openrouter") {
      openrouterKey = await input({
        message: "OpenRouter API key:",
        validate: (v) => (v.startsWith("sk-or-") ? true : "Must start with sk-or-"),
      });
      process.env.OPENROUTER_API_KEY = openrouterKey;
    } else {
      anthropicKey = await input({
        message: "Anthropic API key:",
        validate: (v) => (v.startsWith("sk-ant-") ? true : "Must start with sk-ant-"),
      });
      process.env.ANTHROPIC_API_KEY = anthropicKey;
    }
  } else {
    const which = process.env.OPENROUTER_API_KEY ? "OpenRouter" : "Anthropic";
    console.log(chalk.green(`  ${which} API key found.`));
  }

  // 2. GitHub token
  let token = process.env.GITHUB_TOKEN || "";
  if (!token) {
    token = await input({
      message: "GitHub personal access token:",
      validate: (v) =>
        v.startsWith("ghp_") || v.startsWith("github_pat_") ? true : "Must start with ghp_ or github_pat_",
    });
    process.env.GITHUB_TOKEN = token;
  } else {
    console.log(chalk.green("  GitHub token found."));
  }

  // Validate
  const { valid, username } = await validateToken(token);
  if (!valid) {
    console.log(chalk.red("  Invalid GitHub token."));
    process.exit(1);
  }
  console.log(chalk.green(`  Authenticated as ${username}`));

  // 3. Organization
  let org = process.env.GITHUB_ORG || "";
  if (!org) {
    const orgs = await listOrgs(token);
    if (orgs.length > 0) {
      org = (await select({
        message: "Select organization:",
        choices: [
          ...orgs.map((o) => ({ name: o, value: o })),
          { name: "Enter manually...", value: "__manual__" },
        ],
      })) as string;
      if (org === "__manual__") {
        org = await input({ message: "Organization name:" });
      }
    } else {
      org = await input({ message: "Organization or username:", default: username });
    }
  } else {
    console.log(chalk.green(`  Organization: ${org}`));
  }

  // 4. Project
  console.log(chalk.dim("\n  Fetching projects...\n"));
  const projects = await listProjects(token, org);

  let projectNumber: number;
  if (projects.length > 0) {
    projectNumber = (await select({
      message: "Select project:",
      choices: projects.map((p) => ({
        name: `#${p.number} — ${p.title}`,
        value: p.number,
      })),
    })) as number;
  } else {
    const num = await input({ message: "Project number:" });
    projectNumber = parseInt(num, 10);
  }

  // 5. Save config
  completeSetup({ token, org, projectNumber, anthropicKey, openrouterKey });
  console.log(chalk.green("\n  Configuration saved to .env"));

  // 6. Generate knowledge
  const shouldGenerate = await confirm({
    message: "Generate knowledge files from GitHub?",
    default: true,
  });

  if (shouldGenerate) {
    const repos = await discoverReposFromProject(token, org, projectNumber);
    console.log(chalk.dim(`  Found ${repos.length} repos from project\n`));

    await generateKnowledge(org, repos, (msg) => {
      if (msg.includes("Skipped")) {
        console.log(chalk.yellow(`  ⚠ ${msg}`));
      } else if (msg.includes("created")) {
        console.log(chalk.green(`  ✓ ${msg}`));
      } else {
        console.log(chalk.dim(`  ${msg}`));
      }
    });
  }

  console.log(chalk.bold.green("\n  Setup complete! Run `bun run start` to begin.\n"));
}
