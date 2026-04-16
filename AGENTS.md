# Dash PM Agent - Development Guide

Dash is an autonomous PM agent that manages product teams. It connects to your GitHub, Linear, PostHog, and other platforms, then provides daily briefs with action items and on-demand chat for product management.

Built on the Hermes Agent framework by Nous Research.

## Development Environment

```bash
source .venv/bin/activate  # ALWAYS activate before running Python
```

## Project Structure

```
pm-agent-v2/
├── run_agent.py          # AIAgent class - core conversation loop
├── model_tools.py        # Tool orchestration, discovery, dispatch
├── toolsets.py           # Toolset definitions, _PM_CORE_TOOLS list
├── cli.py                # CLI orchestrator
├── agent/                # Agent internals
│   ├── prompt_builder.py     # System prompt assembly (Dash PM identity)
│   ├── context_compressor.py # Auto context compression
│   ├── prompt_caching.py     # Prompt caching
│   ├── display.py            # Spinner, tool preview formatting
│   └── skill_commands.py     # Skill slash commands
├── tools/                # Tool implementations (self-registering)
│   ├── registry.py       # Central tool registry
│   ├── pm_brief_tools.py # Daily brief store/retrieve/action items
│   ├── terminal_tool.py  # Terminal orchestration
│   ├── file_tools.py     # File operations
│   ├── web_tools.py      # Web search/extract
│   ├── mcp_tool.py       # MCP client (GitHub, Linear, PostHog)
│   ├── delegate_tool.py  # Subagent delegation
│   └── ...
├── skills/               # Skill documents
│   ├── pm-brief/         # Daily brief workflow
│   ├── pm-onboarding/    # Self-onboarding for new workspaces
│   ├── pm-analysis/      # Sprint review, risk assessment, prioritization
│   ├── pm-communication/ # Stakeholder updates
│   ├── productivity/     # Google Workspace, Notion
│   └── software-development/ # GitHub, code analysis
├── gateway/              # Messaging gateway (Slack, Discord, Telegram)
├── cron/                 # Scheduled task execution (daily briefs)
├── workspace_context.py  # Shared workspace state (blueprint, learnings, briefs)
└── cli-config.yaml       # Configuration including MCP servers
```

## Running

```bash
# CLI mode
python cli.py

# Slack gateway
python -m gateway.run --platform slack

# With specific model
python cli.py --model openai/gpt-5.4
```

## Core Product Features

1. **Daily Brief**: Scheduled every 6h via cron. Analyzes all connected platforms, produces structured brief with action items.
2. **Chat**: On-demand conversation with full workspace context (blueprint, learnings, previous briefs).
3. **Action Items**: Briefs surface prioritized action items. Users act on them via chat threads.

## Adding a New Tool

1. Create `tools/your_tool.py`
2. Define schema (OpenAI function format: `{name, description, parameters}`)
3. Register with `registry.register(name, toolset, schema, handler)`
4. Add to `_discover_tools()` in `model_tools.py`
5. Add tool name to `_PM_CORE_TOOLS` in `toolsets.py` (if default-enabled)

## Adding a New Skill

1. Create `skills/category/skill-name/SKILL.md`
2. Add YAML frontmatter: name, description, version, metadata
3. The agent discovers it automatically via `skills_list`

## Platform Connections (MCP)

Edit `cli-config.yaml` to add MCP servers:
- GitHub: auto-discovers repos, issues, PRs, project boards
- Linear: cycles, issues, team workload
- PostHog: analytics, funnels, user behavior

MCP tools are auto-discovered at startup. No code changes needed.
