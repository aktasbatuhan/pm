# PM Agent — Project Context for Claude Code

## Architecture: Two-Repo Strategy

This project follows a **two-repo architecture**. When making changes, always consider which repo is affected and whether the other needs updating.

### Repo 1: `pm-agent` (this repo)
- **What**: The PM agent itself — self-hostable, potentially open-source
- **Repo**: github.com/aktasbatuhan/pm
- **Deploy**: Each customer gets their own Railway instance running this exact code
- **Config**: All customer-specific config is via env vars (GitHub token, Slack tokens, org, etc.)
- **Key principle**: This repo must remain self-contained and deployable independently. No SaaS/billing/multi-tenant logic belongs here.

### Repo 2: `pm-platform` (separate repo, the SaaS layer)
- **What**: Landing page, billing (Stripe), onboarding, instance provisioning via Railway API
- **Deploy**: One central deployment that manages customer agent instances
- **Key principle**: This repo provisions and manages instances of `pm-agent`. It doesn't contain agent logic.

### Decision Guide: Where Does a Change Go?

| Change type | Goes in |
|---|---|
| New agent capability (tool, MCP server, prompt improvement) | `pm-agent` |
| UI feature (dashboard, chat, settings) | `pm-agent` |
| New integration (Linear, PostHog, etc.) | `pm-agent` |
| Billing, pricing, subscription management | `pm-platform` |
| Customer onboarding / provisioning | `pm-platform` |
| Landing page, marketing | `pm-platform` |
| Instance management (start/stop/update) | `pm-platform` |
| Feature flags or plan-based limits | Both — `pm-agent` checks limits, `pm-platform` sets them |

### Feature Parity Rule
Every customer instance runs the **exact same agent code**. Differentiation happens through:
- Env vars (AGENT_NAME, GITHUB_ORG, model choice, etc.)
- Settings in the DB (configured via the agent's Settings page)
- Plan-based feature flags (future — stored as env vars set by platform)

### Current Instance (Batuhan's)
- Railway project: `f3d86f92-d0e4-4763-9ac9-655ad95054ba`
- Service: `6dee8bbf-a0b2-4e79-9345-5b1b7bea25f6`
- This instance is NOT special — it's just a deployment of `pm-agent` with Batuhan's env vars
- Do NOT add Batuhan-specific logic to the codebase

## Tech Stack
- **Runtime**: Bun
- **Framework**: Hono (web server)
- **DB**: SQLite via Drizzle ORM (each instance has its own DB)
- **Agent**: Claude Agent SDK (`@anthropic-ai/claude-agent-sdk`)
- **LLM routing**: OpenRouter (default model: `google/gemini-3-flash-preview`)
- **MCP servers**: GitHub, Knowledge, Scheduler, Slack, Visualization, PostHog, Dashboard, Sandbox + remote MCP
- **Deploy**: Railway (one instance per customer)

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

## Common Pitfalls
- **Config drift between web and Slack**: Both entry points build their own `AgentConfig`. When adding a new MCP server or tool, update BOTH `routes.ts` and `bot.ts`. Consider refactoring into a shared `buildAgentConfig()` function.
- **Hardcoded models**: All model references should use `process.env.AGENT_MODEL || "google/gemini-3-flash-preview"`. Never hardcode a specific model.
- **System prompt**: `buildSystemPrompt()` in `system-prompt.ts` is the single source. Slack wraps it with `buildSlackSystemPrompt()` which strips visualization and adds Slack formatting rules.
