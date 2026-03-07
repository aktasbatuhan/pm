# PM Agent — Project Context for Claude Code

## What This Is
An open-source AI product management agent. It connects to your team's GitHub, Slack, and other tools to help with sprint planning, status tracking, risk detection, and coordination.

## Tech Stack
- **Runtime**: Bun
- **Framework**: Hono (web server)
- **DB**: SQLite via Drizzle ORM
- **Agent**: Claude Agent SDK (`@anthropic-ai/claude-agent-sdk`)
- **LLM routing**: OpenRouter (default model: `google/gemini-3-flash-preview`)
- **MCP servers**: GitHub, Knowledge, Scheduler, Slack, Visualization, PostHog, Dashboard, Sandbox, Memory, Signals, Intelligence + remote MCP
- **Deploy**: Docker or any platform (Railway, Fly, etc.)

## Key Env Vars
- `AGENT_NAME` — Agent's display name (default: "Dash")
- `AGENT_MODEL` — OpenRouter model ID (default: `google/gemini-3-flash-preview`)
- `GITHUB_ORG`, `GITHUB_TOKEN`, `GITHUB_PROJECT_NUMBER` — GitHub config
- `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_DEFAULT_CHANNEL` — Slack config
- `OPENROUTER_API_KEY` — LLM provider
- `AUTH_TOKEN` — Web UI auth (optional)

## Entry Points
- **Web**: `src/web/routes.ts` — Hono routes, SSE chat streaming
- **Slack**: `src/slack/bot.ts` — Socket Mode bot, thread-based conversations
- **Scheduler**: `src/scheduler/loop.ts` — Recurring jobs, tab refresh
- **Agent core**: `src/agent/core.ts` — Shared `chat()` function used by all entry points

## Git Remotes
- `origin` → public open-source repo (github.com/aktasbatuhan/pm)
- `heydash` → private repo for deployed instances (github.com/aktasbatuhan/heydash)
- Push to both when making changes: `git push heydash main` then `git push origin main`
- Never commit secrets, company-specific knowledge files, or database files

## Common Pitfalls
- **Config drift between web and Slack**: Both entry points build their own `AgentConfig`. When adding a new MCP server or tool, update BOTH `routes.ts` and `bot.ts`, plus `allowedTools` in `core.ts`. Consider refactoring into a shared `buildAgentConfig()` function.
- **Hardcoded models**: All model references should use `process.env.AGENT_MODEL || "google/gemini-3-flash-preview"`. Never hardcode a specific model.
- **System prompt**: `buildSystemPrompt()` in `system-prompt.ts` is the single source. Slack wraps it with `buildSlackSystemPrompt()` which strips visualization and adds Slack formatting rules.

## Adding a New MCP Server
Follow this checklist when adding a new tool/MCP server:
1. Create `src/tools/<name>.ts` with `createSdkMcpServer()` + `tool()` definitions
2. Export from `src/tools/index.ts` (server factory + write tool names)
3. Add to `WRITE_TOOL_NAMES` array in `src/tools/index.ts` if it has write tools
4. Wire into `src/web/routes.ts` — import, lazy singleton, getter, add to mcpServers config, add tool labels
5. Wire into `src/slack/bot.ts` — import, add to mcpServers config, add to allowedTools
6. Add `"mcp__<name>__*"` to default `allowedTools` in `src/agent/core.ts`
7. Add usage instructions to `src/agent/system-prompt.ts`

## Intelligence Architecture (v1.0)
- **Memory**: Markdown files in `data/memory/` with wiki-style `[[links]]` and `updated_at` frontmatter. Persistent across sessions.
- **Signal Store**: DB-backed ingestion of signals from external sources + insight generation.
- **Skills**: Workflow definitions in `skills/` directory. Agent reads them via intelligence MCP server and follows step-by-step.
- **Proactive loop**: Scheduler runs skill prompts (daily briefing, anomaly detection) on intervals. Agent uses memory + signals to produce actionable insights.

## Status (as of March 2026)
- **Version**: 0.2.0 (MIT licensed)
- **Branch**: main (clean)
- **State**: Core platform + v1.0 intelligence layer (memory, signals, skills).
- **Next**: Briefing UI tab, community MCP servers (Stripe, GA), GitHub webhooks for real-time signals.
