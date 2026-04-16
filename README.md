# Dash PM

**An autonomous product management agent that delivers daily briefs, surfaces action items, and connects signals across your tools.**

Built on the [Hermes Agent](https://github.com/NousResearch/hermes-agent) framework by Nous Research.

---

## What is Dash?

Dash is an AI PM agent that connects to GitHub, Linear, PostHog, Slack, and other tools your team uses. It handles:

- **Daily briefs**: Structured summaries of what happened, what matters, and what to do next — delivered every 6 hours
- **Cross-domain synthesis**: Connecting code activity, analytics, team dynamics, and market signals into insights no single tool can see
- **Proactive risk detection**: Flagging blockers, stale work, team issues, and product problems before they escalate
- **Action items**: Prioritized, categorized, linked to source data — resolve them inline or dive deeper in chat

You talk to it like a senior PM. It does the analysis.

## How it works

1. Connect your platforms (GitHub, Linear, PostHog, Slack)
2. Dash scans your organization and builds a workspace blueprint
3. Every 6 hours, Dash produces a daily brief with charts, metrics, and action items
4. Chat with Dash anytime for deeper analysis — sprint reviews, risk assessments, feature prioritization
5. Action items from briefs link to chat sessions for execution

## Quick Start

```bash
# Clone
git clone https://github.com/your-org/dash-pm.git
cd dash-pm

# Set up
cp .env.example .env  # Add your API keys
source .venv/bin/activate
pip install -r requirements.txt

# Run CLI
python cli.py

# Run web dashboard
python server.py &          # API on :3001
cd web && npm run dev        # Frontend on :3000
```

## Architecture

```
dash-pm/
├── server.py              # FastAPI API server (briefs, chat, sessions)
├── run_agent.py           # AIAgent core (model-agnostic, tool-calling)
├── agent/                 # Agent internals (prompts, compression, display)
├── tools/                 # Self-registering tool modules
│   ├── pm_brief_tools.py      # Daily brief store/retrieve
│   ├── pm_workspace_tools.py  # Blueprint, learnings, onboarding
│   ├── pm_platform_tools.py   # Platform discovery
│   └── pm_image_tools.py      # Cover image generation (fal.ai)
├── skills/                # SKILL.md instruction documents
│   ├── pm-brief/              # Daily brief generation
│   ├── pm-onboarding/         # Workspace self-onboarding
│   └── pm-analysis/           # Sprint review, risk, prioritization
├── web/                   # Next.js frontend (shadcn/ui + ElevenLabs UI)
├── gateway/               # Multi-platform messaging (Slack, Discord, etc.)
├── cron/                  # Scheduled task execution
└── workspace_context.py   # Shared state (SQLite)
```

## Platform Connections

Configure in `cli-config.yaml`:
- **GitHub**: via `gh` CLI or MCP server
- **Linear**: via MCP server (HTTP)
- **PostHog**: via MCP server (stdio)
- **Slack**: via gateway adapter

## License

See LICENSE file.
