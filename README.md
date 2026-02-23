# Dash — Cursor for Product Managers

AI agents can build it. Dash figures out *what* to build.

An open-source AI agent that joins your product team and handles the discovery and coordination layer — sprint planning, risk detection, status tracking, effort estimation, and proactive alerts. Coding agents handle implementation. Dash handles everything around it.

Built with the [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview). Read the story behind it: [Move Your Business to Where the Code Is](https://batuhanaktas.substack.com).

## Features

- **Sprint Intelligence** — Automated standups, sprint health checks, completion forecasting, risk detection
- **Effort Estimation** — Fibonacci-scale estimates grounded in actual codebase analysis
- **Live Dashboard** — Agent-generated charts, tables, and stat cards with auto-refresh
- **Slack Bot** — Bi-directional chat via Socket Mode, proactive alerts, thread-based conversations
- **Scheduled Jobs** — Daily standups, weekly digests, custom recurring reports
- **Knowledge System** — Auto-generates and maintains context about your repos and architecture
- **Product Analytics** — PostHog integration for usage data alongside engineering progress
- **Visualizations** — Chart.js charts and Mermaid diagrams rendered inline in chat
- **Sandbox** — Clone repos, run scripts, generate and share files
- **GitHub Project v2** — Full support for custom fields, iterations, dynamic field discovery
- **Code Review** — Read PR diffs, post reviews, approve or request changes
- **Multi-Model** — OpenRouter support with model selection per conversation (Gemini, Claude, etc.)

## Quick Start

```bash
git clone https://github.com/aktasbatuhan/pm.git
cd pm

bun install

# Interactive setup — connects GitHub, generates knowledge base
bun run setup

# Start web UI
bun run web

# Or start terminal UI
bun run start
```

## Configuration

The setup wizard handles this, but you can also create a `.env` file manually:

```env
# LLM Backend (pick one)
OPENROUTER_API_KEY=sk-or-v1-...     # Recommended
# ANTHROPIC_API_KEY=sk-ant-...      # Alternative

# Agent
AGENT_NAME=Dash
AGENT_MODEL=google/gemini-3-flash-preview

# GitHub (required)
GITHUB_TOKEN=ghp_...
GITHUB_ORG=your-org
GITHUB_PROJECT_NUMBER=1

# Slack (optional)
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_DEFAULT_CHANNEL=#general

# Auth (optional — leave empty for local dev)
AUTH_TOKEN=
```

**GitHub Token** needs these scopes: `repo`, `read:org`, `project`

## Usage

### Web UI

```bash
bun run web
```

Opens at `http://localhost:3000` with:
- Dashboard with sprint health, charts, and metrics
- Streaming chat drawer with markdown, inline charts, and file downloads
- Knowledge hub for browsing and editing the agent's context
- Settings, team management, and setup wizard

### Terminal

```bash
bun run start
```

Slash commands: `/standup`, `/analyze`, `/estimate #123`, `/review`, `/alerts`, `/digest`

### Slack

Configure `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN`, then the bot joins automatically. DM it or @mention in channels.

### Docker

```bash
docker compose up
```

Persists data (DB + knowledge) to a named volume at `/data`.

## Architecture

```
                    ┌─────────────┐
                    │  Web UI     │
                    │  Slack Bot  │──── User input
                    │  Terminal   │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Agent Core │──── Claude Agent SDK
                    │  (chat())   │     System prompt + knowledge
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────▼────┐ ┌────▼─────┐ ┌────▼─────┐
        │ GitHub   │ │ Slack    │ │ PostHog  │
        │ GraphQL  │ │ Bot API  │ │ HogQL    │
        │ + gh CLI │ │          │ │          │
        └──────────┘ └──────────┘ └──────────┘
              │
        ┌─────▼────┐ ┌──────────┐ ┌──────────┐
        │ Scheduler│ │ Sandbox  │ │ Viz      │
        │ (cron)   │ │ (bash)   │ │ Chart.js │
        └──────────┘ └──────────┘ └──────────┘
```

- **Runtime**: Bun
- **Agent**: Claude Agent SDK with MCP tool servers
- **Web**: Hono + vanilla HTML/CSS/JS
- **Database**: SQLite via Drizzle ORM
- **LLM**: OpenRouter (default) or Anthropic direct

## Project Structure

```
pm/
├── src/
│   ├── index.ts                # Entry point (web | tui | setup)
│   ├── agent/
│   │   ├── core.ts             # Shared chat() function
│   │   ├── system-prompt.ts    # System prompt builder
│   │   ├── permissions.ts      # Tool approval (read=auto, write=confirm)
│   │   └── sandbox.ts          # Command safety checks
│   ├── tools/
│   │   ├── github.ts           # GitHub GraphQL + gh CLI
│   │   ├── dashboard.ts        # Dashboard widget CRUD
│   │   ├── knowledge.ts        # Knowledge file CRUD
│   │   ├── scheduler.ts        # Job scheduling
│   │   ├── slack.ts            # Slack messaging
│   │   ├── posthog.ts          # PostHog analytics
│   │   ├── sandbox.ts          # Shell execution + file I/O
│   │   ├── visualization.ts    # Chart.js + Mermaid rendering
│   │   └── remote.ts           # Remote MCP servers (Exa, Linear)
│   ├── slack/
│   │   ├── bot.ts              # Slack Socket Mode bot
│   │   └── formatter.ts        # Markdown → Slack mrkdwn
│   ├── scheduler/
│   │   └── loop.ts             # Background job execution
│   ├── knowledge/
│   │   ├── generator.ts        # Auto-generate repo knowledge
│   │   └── loader.ts           # Load knowledge into prompt
│   ├── setup/
│   │   └── onboarding.ts       # Interactive setup wizard
│   ├── db/
│   │   ├── schema.ts           # SQLite schema (Drizzle)
│   │   └── index.ts            # DB init + migrations
│   ├── tui/                    # Terminal chat interface
│   └── web/
│       ├── server.ts           # Hono server
│       ├── routes.ts           # API routes (SSE, sessions, dashboard)
│       └── public/             # Frontend (HTML/CSS/JS)
├── knowledge/
│   ├── skills.md               # Core PM knowledge (committed)
│   └── repos/                  # Auto-generated per repo on setup
├── Dockerfile
├── docker-compose.yml
└── package.json
```

## Requirements

- [Bun](https://bun.sh) v1.0+
- [GitHub personal access token](https://github.com/settings/tokens) with `repo`, `read:org`, `project` scopes
- An LLM API key — [OpenRouter](https://openrouter.ai) (recommended) or [Anthropic](https://console.anthropic.com)

## License

MIT
