# PM Agent — Project Context for Claude Code

## What This Is
An open-source AI product management agent. It connects to your team's GitHub, Slack, and other tools to help with sprint planning, status tracking, risk detection, and coordination.

## Tech Stack
- **Runtime**: Bun
- **Framework**: Hono (web server)
- **DB**: SQLite via Drizzle ORM
- **Agent**: Claude Agent SDK (`@anthropic-ai/claude-agent-sdk`)
- **LLM routing**: OpenRouter (default model: `google/gemini-3-flash-preview`)
- **MCP servers**: GitHub, Knowledge, Scheduler, Slack, Visualization, PostHog, Dashboard, Sandbox + remote MCP
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
- **Config drift between web and Slack**: Both entry points build their own `AgentConfig`. When adding a new MCP server or tool, update BOTH `routes.ts` and `bot.ts`. Consider refactoring into a shared `buildAgentConfig()` function.
- **Hardcoded models**: All model references should use `process.env.AGENT_MODEL || "google/gemini-3-flash-preview"`. Never hardcode a specific model.
- **System prompt**: `buildSystemPrompt()` in `system-prompt.ts` is the single source. Slack wraps it with `buildSlackSystemPrompt()` which strips visualization and adds Slack formatting rules.

## Status (as of March 2026)
- **Version**: 0.1.0 (MIT licensed)
- **Branch**: main (clean)
- **State**: Shipped. All core features working (chat, GitHub, knowledge, Slack, auth, deployment).
- **Next**: Email notifications, GitHub webhook listener, session pruning, visual sprint board.
