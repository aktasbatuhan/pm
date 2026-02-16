import { existsSync } from "fs";
import { join } from "path";

// Load .env if present
const envPath = join(import.meta.dir, "../.env");
if (existsSync(envPath)) {
  const { readFileSync } = await import("fs");
  const content = readFileSync(envPath, "utf-8");
  for (const line of content.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eqIdx = trimmed.indexOf("=");
    if (eqIdx === -1) continue;
    const key = trimmed.slice(0, eqIdx);
    const value = trimmed.slice(eqIdx + 1);
    if (!process.env[key]) {
      process.env[key] = value;
    }
  }
}

// Configure OpenRouter as backend
// The Claude Agent SDK reads ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN
if (process.env.OPENROUTER_API_KEY) {
  process.env.ANTHROPIC_BASE_URL = "https://openrouter.ai/api";
  process.env.ANTHROPIC_AUTH_TOKEN = process.env.OPENROUTER_API_KEY;
  process.env.ANTHROPIC_API_KEY = "";
}

const command = process.argv[2] || "tui";

switch (command) {
  case "tui":
  case "start": {
    const { startTui } = await import("./tui/index.ts");
    await startTui();
    break;
  }
  case "web": {
    const { startServer } = await import("./web/server.ts");
    const port = parseInt(process.env.PORT || "3000", 10);
    startServer(port);
    break;
  }
  case "setup": {
    const { runSetup } = await import("./setup/onboarding.ts");
    await runSetup();
    break;
  }
  default:
    console.error(`Unknown command: ${command}`);
    console.error("Usage: bun run start [tui|web|setup]");
    process.exit(1);
}
