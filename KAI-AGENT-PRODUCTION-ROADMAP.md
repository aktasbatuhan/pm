# Kai Agent: Current State & Production Roadmap

> Last updated: 2026-03-24

## Overview

Kai Agent is an always-on AI team member that lives inside an E2B sandbox. It onboards itself into your organization by connecting to your tools (GitHub, Slack, Jira, Linear), builds context about your codebase and workflows, and then operates autonomously: deciding what to work on each day, confirming with the team, and executing. Think of it as hiring a new engineer who never sleeps.

The long-term vision is similar to [Dimension](https://dimension.dev/): Kai reviews your business context daily, proposes a work plan, gets approval, and executes. Not a chatbot you prompt, but a colleague who shows up with ideas.

---

## 1. What We Have Today

### Architecture

```
                    ┌─────────────────────┐
                    │   Kai Frontend       │
                    │   (Next.js 16)       │
                    └──────┬──────────────┘
                           │ REST API
                           ▼
                    ┌─────────────────────┐
                    │   Kai Backend        │
                    │   (Bun/Hono)         │
                    │                      │
                    │  - MongoDB (agents)  │
                    │  - E2B v2 API        │
                    │  - JWT management    │
                    └──────┬──────────────┘
                           │ E2B REST API
                           ▼
                    ┌─────────────────────┐
                    │   E2B Sandbox        │
                    │   (Custom Template)  │
                    │                      │
                    │  - Python 3.11       │
                    │  - Chat server :8080 │
                    │  - OpenRouter LLM    │
                    │  - Kai skills        │
                    └─────────────────────┘
```

### E2B Template (Built & Working)

- **Template ID**: `v0gtez6yu5vhp4kw50cm` (alias: `kai-agent`)
- **Base**: Python 3.11 with git, curl, Node.js, npm, all Python deps, Kai skills
- **Start command**: `python3 /home/user/kai_chat_server.py` on port 8080
- **Chat server**: `/chat` and `/health` endpoints, OpenRouter LLM (`anthropic/claude-opus-4-6`)
- **Secrets**: Reads from `/home/user/.kai-agent/.env`, reloads per request

**Key files:**
| File | Purpose |
|------|---------|
| `e2b_template.py` | Template definition (SDK v2 builder) |
| `e2b_build.py` | Build script (`python e2b_build.py`) |
| `deploy/e2b-template/kai_chat_server.py` | HTTP chat server baked into template |
| `deploy/e2b-template/default-config.yaml` | MCP server config |

### Backend Routes (kai-backend)

All under `/api/v1/workspaces/{workspaceId}/agents/`:

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| POST | `/provision` | Working | Create sandbox, inject secrets, return 201 |
| GET | `/status` | Working | Get agent status |
| POST | `/pause` | Working | Pause sandbox via E2B API |
| POST | `/resume` | Working | Resume sandbox, re-inject secrets |
| POST | `/chat` | Working | Proxy message to sandbox chat server |
| DELETE | `/destroy` | Working | Kill sandbox, soft-delete |
| PUT | `/secrets` | Working | Update secrets, sync to sandbox |
| GET | `/secrets` | Working | Get secret keys (values masked) |
| GET | `/activities` | Working | Activity feed with pagination |
| POST | `/activities` | Working | Record activity (for agent to call) |
| POST | `/refresh-jwt` | Working | Refresh agent JWT |
| GET | `/lookup` | Working | Find agent by Slack team ID |

**Shared E2B module**: `src/lib/e2b.ts` consolidates all sandbox operations.

### Frontend (kai-frontend)

- **Agent page**: Thin wrapper (`page.tsx`) + content component (`agent-page-content.tsx`)
- **Chat component**: `agent-chat.tsx` with localStorage persistence, auto-onboard
- **PostHog tracking**: Page view, provision, pause, resume, chat, secrets, Slack connect
- **Optimistic updates**: Pause/resume mutations with rollback

### What Works End-to-End

1. User visits Agent page, clicks "Provision Agent"
2. E2B sandbox created, secrets injected, chat server health-checked
3. Chat auto-sends `__onboard__` message, Kai introduces itself
4. User can chat, pause, resume, manage secrets
5. Secrets synced to sandbox without restart

---

## 2. What's Next

### This Week

**Agent provisioning + chat via Kai Frontend + Slack (nice to have)**
- [ ] Stabilize the provision > chat > pause > resume flow end-to-end
- [ ] Streaming chat responses (SSE from sandbox to frontend)
- [ ] Error recovery: retry secret injection, actionable error states in UI
- [ ] Slack integration: deploy Cloudflare Worker, wire Slack OAuth, handle message dispatch
- [ ] Process supervisor inside sandbox (replace kill/nohup with supervisord)

**Secret management & sandbox lifecycle**
- [ ] Health check cron: detect dead sandboxes, auto-update status
- [ ] Auto-reprovision dead sandboxes on next interaction (with same secrets)
- [ ] Encrypt secrets at rest in MongoDB
- [ ] Proper secret rotation (JWT refresh cron)

**Self-onboarding: context building via integrations**
- [ ] After provisioning, Kai walks the user through connecting integrations (GitHub, Slack, Jira, Linear)
- [ ] Kai pulls repo structure, recent PRs, open issues, team members
- [ ] Builds a workspace context document that persists across sessions
- [ ] Learns the team's priorities, codebase patterns, and active workstreams

### Next Week

**Autonomous work**
- [ ] Kai reviews workspace context daily and proposes a work plan (what to scan, what to improve, what to research)
- [ ] User approves, modifies, or rejects the plan via chat or a dedicated UI
- [ ] Kai executes approved tasks inside the sandbox, reports results
- [ ] Work scheduling: configurable frequency, time windows, notification preferences

**Proper UI for agent todo list & activity feed**
- [ ] Agent todo list: pending tasks, in-progress, completed
- [ ] Activity feed with real entries (agent POSTs activities as it works)
- [ ] Task detail view: what Kai did, tools used, results, artifacts

**New skills**
- [ ] The team has specifics on new skills to add (hygiene, dependency analysis, and others)

### Long Term Vision

Kai operates like a real team member:

1. **Onboards itself**: Connects to your tools, reads your repos, understands your workflows, learns your team's conventions
2. **Plans its day**: Reviews open issues, recent changes, security alerts, dependency updates. Proposes a daily work plan
3. **Gets approval**: Presents the plan to the team lead via Slack or the Kai UI. Waits for confirmation before executing
4. **Executes autonomously**: Runs security scans, analyzes code, creates PRs, updates documentation, monitors for regressions
5. **Reports back**: Posts results to Slack, updates the activity feed, flags anything that needs human attention
6. **Learns over time**: Builds persistent memory about the codebase, team preferences, and what types of work get approved vs rejected

The goal is not a chatbot you have to prompt. It's a colleague who shows up every morning with a plan.

---

## 3. Environment Setup

### Prerequisites
- E2B API key (Pro plan recommended)
- OpenRouter API key (for LLM access)
- MongoDB instance
- Node.js 20+, Python 3.11+, Bun

### Build the E2B Template
```bash
cd ~/Development/prod/hermes-agent
E2B_API_KEY=e2b_xxx python e2b_build.py kai-agent
# Returns template ID — set as E2B_TEMPLATE in backend env
```

### Run Backend Locally
```bash
cd ~/Development/prod/kai-backend
# Ensure .env has:
#   E2B_API_KEY=e2b_xxx
#   E2B_TEMPLATE=v0gtez6yu5vhp4kw50cm
bun run dev
```

### Run Frontend Locally
```bash
cd ~/Development/prod/kai-frontend
# .env.local should have:
#   NEXT_PUBLIC_API_URL=http://localhost:3001
bun run dev
```

### Test Sandbox Manually
```bash
cd ~/Development/prod/hermes-agent/deploy
E2B_API_KEY=e2b_xxx python test_e2b.py
```

---

## 4. Key Technical Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Sandbox provider | E2B v2 | Fastest cold start (~2s), pause/resume, SDK builder API |
| LLM provider | OpenRouter | Single API for multiple models, easy model switching |
| Chat protocol | HTTP sync (moving to SSE) | Sync was simplest to ship, SSE needed for real-time |
| Secret injection | .env file + restart | E2B start command can't inherit runtime env vars |
| Chat persistence | localStorage (moving to MongoDB) | Quick to ship, server-side needed for cross-device |
| Process management | kill/nohup (moving to supervisord) | Works but fragile, supervisor is the production answer |

---

## 5. Known Issues

| Issue | Impact | Current Workaround |
|-------|--------|--------------------|
| Sandbox dies after 24h | Agent goes offline silently | Manual reprovision |
| No streaming | Slow UX for long responses | 90s timeout, loading indicator |
| Secrets in plaintext DB | Security risk | Backend is behind auth |
| Chat history lost on sandbox restart | Context lost | localStorage cache |
| No rate limiting | Potential abuse | Auth required for all endpoints |
| Template builds are manual | Slow iteration | `python e2b_build.py` from CLI |

---

## 6. Repository Map

```
kai-agent (kai-agent branch) — github.com/aktasbatuhan/kai-agent
├── e2b_template.py              # Template definition (run from repo root)
├── e2b_build.py                 # Build script
├── deploy/
│   ├── e2b-template/
│   │   ├── kai_chat_server.py   # Chat server (baked into template)
│   │   ├── default-config.yaml  # MCP config
│   │   ├── build.py             # Alternative build script
│   │   └── template.py          # Alternative template def
│   ├── worker/                  # Cloudflare Worker (Slack proxy)
│   ├── agent_entrypoint.py      # Sandbox entry for Slack messages
│   ├── provisioner.py           # Standalone provisioner script
│   └── test_e2b.py              # CLI test script
├── skills/
│   ├── kai-security/            # Security scanning skills
│   ├── kai-research/            # Research skills
│   ├── kai-evolve/              # Code evolution skills
│   └── kai-ops/                 # Operations skills
└── agent/                       # Core agent logic (from Hermes)

kai-backend (feature/kai-agent branch)
├── src/lib/e2b.ts               # Shared E2B helpers
├── src/routes/workspace/agents/
│   ├── index.ts                 # Main agent routes
│   ├── secrets.ts               # Secret management
│   ├── activities.ts            # Activity feed
│   └── slack-oauth.ts           # Slack OAuth flow
└── src/models/workspaces/
    ├── agent.ts                 # Agent model
    └── agent-activity.ts        # Activity model

kai-frontend (feature/kai-agent branch)
├── app/(app)/workspace/[workspace]/agent/
│   ├── page.tsx                 # Thin wrapper (use(params), PostHog)
│   ├── agent-page-content.tsx   # Main page component
│   └── agent-chat.tsx           # Chat component
├── lib/api/agent.ts             # API client
└── lib/posthog/events.ts        # Tracking events (AGENT_*)
```
