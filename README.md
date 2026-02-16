# PM Agent

An open-source AI project management agent built on the [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview). Connects to your GitHub Projects and helps with sprint analysis, status tracking, effort estimation, and planning.

Built as Episode 1 of the [Open Source Agent Series](https://batuhanaktas.substack.com).

## Features

- **Sprint Analysis** — Automated standup reports, sprint health checks, risk detection
- **Effort Estimation** — Fibonacci-scale estimates with reasoning, breakdown, and risk analysis
- **Deep Context** — Reads issue comments, PRs, repo structure for accurate analysis
- **GitHub Project v2** — Full support for custom fields, iterations, and project board views
- **Write Operations** — Create issues, update status, add comments (with approval)
- **Session Persistence** — Resume conversations with full context
- **Two Interfaces** — Terminal (TUI) and web dashboard with Palantir-inspired dark theme

## Quick Start

```bash
# Clone
git clone https://github.com/yourusername/pm-agent.git
cd pm-agent

# Install
bun install

# Setup (interactive — connects GitHub, generates knowledge)
bun run setup

# Start TUI
bun run start

# Or start web UI
bun run web
```

## Configuration

Create a `.env` file (or run `bun run setup`):

```env
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...
GITHUB_ORG=your-org
GITHUB_PROJECT_NUMBER=1
```

**GitHub Token** needs these scopes:
- `repo` (read/write issues, PRs)
- `read:org` (list organizations)
- `project` (read/write GitHub Projects)

## Usage

### TUI

```bash
bun run start
```

Supports slash commands:
- `/standup` — Daily sprint standup report
- `/analyze` — Deep sprint analysis with recommendations
- `/estimate #123` — Estimate effort for a specific issue

### Web UI

```bash
bun run web
```

Opens at `http://localhost:3000` with:
- Streaming chat with markdown rendering
- Session sidebar for conversation history
- Quick action buttons for common workflows

## Architecture

```
Claude Agent SDK (query) → MCP Tools → GitHub API
                         ↓
                    Knowledge Layer (skills.md + generated repo knowledge)
                         ↓
                    SQLite (chat history, sessions)
```

- **Agent Core**: Claude Agent SDK `query()` with streaming
- **Tools**: Custom MCP server wrapping GitHub REST + GraphQL APIs
- **Knowledge**: Markdown files composed into system prompt
- **Persistence**: SQLite via Drizzle ORM
- **Web**: Hono HTTP server with vanilla HTML/CSS/JS frontend

## Project Structure

```
pm-agent/
├── src/
│   ├── index.ts              # CLI entry point (tui | web | setup)
│   ├── agent/
│   │   ├── core.ts           # Agent SDK wrapper, streaming
│   │   ├── system-prompt.ts  # Compose system prompt from knowledge
│   │   └── permissions.ts    # Tool approval handler
│   ├── tools/
│   │   ├── github.ts         # GitHub MCP tools (read + write)
│   │   └── index.ts          # Tool aggregator
│   ├── knowledge/
│   │   ├── generator.ts      # Auto-generate repo knowledge
│   │   └── loader.ts         # Load knowledge files at runtime
│   ├── setup/
│   │   └── onboarding.ts     # Interactive setup wizard
│   ├── db/
│   │   ├── schema.ts         # SQLite schema (Drizzle)
│   │   └── index.ts          # Database init
│   ├── tui/
│   │   ├── index.ts          # Terminal chat interface
│   │   └── renderer.ts       # Stream rendering
│   └── web/
│       ├── server.ts         # Hono HTTP server
│       ├── routes.ts         # API routes (SSE streaming)
│       └── public/           # Frontend (HTML/CSS/JS)
├── knowledge/
│   ├── skills.md             # Core PM knowledge (committed)
│   ├── company.md            # Auto-generated on setup
│   └── repos/                # Auto-generated per repo
├── .claude/commands/         # Slash command templates
├── .env.example
└── package.json
```

## Requirements

- [Bun](https://bun.sh) v1.0+
- [Anthropic API key](https://console.anthropic.com)
- [GitHub personal access token](https://github.com/settings/tokens)

## License

MIT
