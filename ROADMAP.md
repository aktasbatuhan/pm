# PM Agent — Roadmap

## Shipped
- [x] Chat with GitHub integration (issues, projects, sprint analysis)
- [x] Knowledge base — agent can read/write knowledge files via MCP tools
- [x] Knowledge Hub UI — browse, edit, create, delete knowledge files from web
- [x] Delete chat sessions from web UI
- [x] Configurable agent model via `AGENT_MODEL` env var
- [x] OpenRouter support as LLM backend
- [x] Self-managed runtime — scheduler MCP tools (`schedule_job`, `list_jobs`, `cancel_job`), background job loop, jobs DB table
- [x] Slack notifications — `slack_send_message` MCP tool via incoming webhook
- [x] Auth — token-based middleware, session cookies, login page, Bearer token for API
- [x] Deployment — Dockerfile, docker-compose, Railway (live at `pm-production-e983.up.railway.app`)
- [x] Persistent volume at `/data` for DB + knowledge files
- [x] Onboarding banner — auto-detects empty knowledge base, prompts setup
- [x] Bloomberg Terminal UI — dark aesthetic, amber accents, all-monospace, data-dense layout

---

## Architecture References
- [Agent SDK Hosting](https://platform.claude.com/docs/en/agent-sdk/hosting) — Pattern 3 (Hybrid Sessions) fits us: container hydrated with history via SDK session resumption, spins down when idle
- [Agent SDK Secure Deployment](https://platform.claude.com/docs/en/agent-sdk/secure-deployment) — Proxy pattern for credentials, container hardening, MCP-as-auth-boundary
- [OpenClaw](https://github.com/openclaw/openclaw) — Reference for gateway architecture, multi-channel output, cron+wake triggers, daemon mode, session pruning

---

## Next Up

### 1. Email Notifications
Secondary output channel (SMTP or SendGrid) for daily digest and scheduled reports.

### 2. GitHub Webhook Listener
React to GitHub events in real-time (push, PR opened, issue labeled) — the agent can analyze changes as they happen instead of polling.

### 3. Session Pruning
Long-running agents accumulate context. Prune old messages to prevent unbounded growth (OpenClaw pattern).

### 4. Dashboard View
Visual sprint board / charts in the web UI — progress bars, burndown, team workload.

---

## Ideas (not prioritized)
- Multi-channel input — Telegram, Discord, WhatsApp as input channels (OpenClaw pattern)
- Multi-user support — separate sessions/knowledge per user
- Agent memory across sessions — long-term memory beyond knowledge files
- Voice interface — talk to your PM agent
- Skills platform — pluggable skill modules for different PM workflows (OpenClaw pattern)
