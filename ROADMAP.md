# PM Agent — Roadmap

## Shipped
- [x] Chat with GitHub integration (issues, projects, sprint analysis)
- [x] Knowledge base — agent can read/write knowledge files via MCP tools
- [x] Knowledge Hub UI — browse, edit, create, delete knowledge files from web
- [x] Delete chat sessions from web UI
- [x] Configurable agent model via `AGENT_MODEL` env var
- [x] OpenRouter support as LLM backend

---

## Architecture References
- [Agent SDK Hosting](https://platform.claude.com/docs/en/agent-sdk/hosting) — Pattern 3 (Hybrid Sessions) fits us: container hydrated with history via SDK session resumption, spins down when idle
- [Agent SDK Secure Deployment](https://platform.claude.com/docs/en/agent-sdk/secure-deployment) — Proxy pattern for credentials, container hardening, MCP-as-auth-boundary
- [OpenClaw](https://github.com/openclaw/openclaw) — Reference for gateway architecture, multi-channel output, cron+wake triggers, daemon mode, session pruning

---

## Next Up

### 1. Agent Self-Managed Runtime
Let the agent control its own schedule. No rigid cron — the agent sets timers, sleeps, wakes on triggers. Inspired by OpenClaw's cron + wake trigger pattern.

Key pieces:
- **Persistent background loop** — a daemon process (systemd/launchd or Docker entrypoint) that stays alive, checks a `jobs` table for due tasks
- **Agent MCP tools**: `set_reminder(time, prompt)`, `set_recurring(interval, prompt)`, `cancel_job(id)`, `list_jobs()`
- **Self-directed scheduling** — agent decides "check sprint health in 4 hours" or "every morning at 9am, run standup"
- **Job execution** — when a job fires, spin up a `chat()` call with the job's prompt, route output to the configured channel
- **Session pruning** — long-running agents accumulate context; prune old messages to prevent unbounded growth (OpenClaw pattern)
- Jobs table in SQLite: `id`, `type` (once/recurring), `next_run_at`, `interval`, `prompt`, `output_channel`, `status`, `created_at`
- Follows **Pattern 2 (Long-Running Sessions)** from SDK hosting docs — persistent container, multiple agent processes on demand

### 2. Notification Channels (Slack / Email)
Output channels so the autonomous agent has a mouth. Without this, proactive mode is useless.
- **Slack**: incoming webhook (simplest — just a `SLACK_WEBHOOK_URL` in `.env`). New MCP server `slack.ts` with `send_message` tool so the agent can push updates during conversations or scheduled jobs
- **Email**: secondary channel (SMTP or SendGrid), useful for daily digest
- **Channel routing**: job output goes to configured channel. Agent decides what's worth notifying vs. what to just log
- Follows OpenClaw's multi-channel pattern — each channel is a pluggable adapter

### 3. Auth
Required before leaving localhost. Ref: [Secure Deployment](https://platform.claude.com/docs/en/agent-sdk/secure-deployment).
- Simple token or password gate on all Hono API routes (middleware)
- Session cookie after login, configurable via `AUTH_TOKEN` env var
- Protect web UI and API equally
- API key option for programmatic access (webhook callbacks, integrations)
- For cloud: credentials never in container — use proxy pattern from secure deployment docs (proxy outside container injects `GITHUB_TOKEN`, `OPENROUTER_API_KEY`)

### 4. Deployment Config
Containerized deployment following SDK hosting patterns.
- **Dockerfile**: Bun runtime, copy source + knowledge dir, expose port
- **docker-compose**: volume mounts for SQLite (`pm-agent.db`) + `knowledge/` persistence
- **Credential proxy**: container runs with `--network none`, credentials injected via proxy outside container (secure deployment pattern)
- **Health check**: already have `/api/health`
- **Daemon mode**: entrypoint runs both web server + background job loop
- **Resource baseline**: 1GiB RAM, 5GiB disk, 1 CPU (from SDK hosting docs)
- Target platforms: Railway, Fly.io, or simple VPS with Docker

---

## Ideas (not prioritized)
- Webhook listener — react to GitHub events in real-time (push, PR opened, issue labeled) via GitHub webhooks
- Multi-channel input — Telegram, Discord, WhatsApp as input channels (OpenClaw pattern)
- Multi-user support — separate sessions/knowledge per user
- Agent memory across sessions — long-term memory beyond knowledge files, session pruning strategies
- Voice interface — talk to your PM agent
- Dashboard view — visual sprint board / charts in the web UI
- Skills platform — pluggable skill modules for different PM workflows (OpenClaw pattern)
