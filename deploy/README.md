# Kai Agent Deployment

## Architecture

```
Slack @kai mention
       ↓
Cloudflare Worker (always on, free tier)
  ├─ Verify Slack signature
  └─ Call Kai backend /agents/lookup + /agents/wake
       ↓
Kai Backend (production.kai-backend.dria.co)
  ├─ MongoDB: workspace → agent → sandbox mapping
  ├─ E2B API: resume sandbox, dispatch command
  ├─ JWT management: issue, refresh, inject
  └─ Credits & billing integration
       ↓
E2B Sandbox (Kai Agent)
  ├─ Pre-installed via custom template
  ├─ JWT + API keys in env vars
  ├─ Calls Kai MCP for security & evolve tools
  ├─ Posts results back to Slack
  └─ Auto-pauses after idle timeout
```

## Components

### 1. Kai Backend (kai-backend repo)

New endpoints under `/api/v1/workspaces/{id}/agents/`:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/agents/provision` | Create E2B sandbox, inject credentials, pause |
| GET | `/agents/status` | Current agent status |
| POST | `/agents/wake` | Resume sandbox + dispatch message |
| POST | `/agents/refresh-jwt` | Refresh expired JWT |
| DELETE | `/agents/destroy` | Kill sandbox, soft-delete |
| GET | `/agents/lookup?slackTeamId=` | Route Slack events to workspace |

**Files added:**
- `src/models/workspaces/agent.ts` - Agent model (Mongoose + Zod)
- `src/routes/workspace/agents/index.ts` - All agent API routes

### 2. Cloudflare Worker (deploy/worker/)

Thin proxy. No state, no KV, no E2B calls. Just:
1. Verify Slack signature
2. Call backend `/agents/lookup` to find the workspace
3. Call backend `/agents/wake` to dispatch the message
4. Return 200 within Slack's 3s limit

```bash
cd deploy/worker
npm install
wrangler secret put KAI_SERVICE_TOKEN
wrangler secret put SLACK_SIGNING_SECRET
npm run deploy
```

### 3. E2B Template (deploy/e2b-template/)

Custom template with Kai Agent pre-installed:
- Python 3.11, Node.js 20
- All agent dependencies
- Default config pointing to Kai MCP
- Skills directory linked

```bash
cd deploy/e2b-template
e2b template build --name kai-agent
```

### 4. Agent Entrypoint (deploy/agent_entrypoint.py)

Runs inside the E2B sandbox when a message arrives:
1. Receives message + Slack context as args
2. Posts "Analyzing..." to Slack
3. Runs full Kai Agent query (MCP tools, research, etc.)
4. Posts response back to Slack

## Provisioning Flow

```
User enables Kai Agent in workspace settings
  → Frontend calls POST /api/v1/workspaces/{id}/agents/provision
  → Backend generates JWT for user
  → Backend creates E2B sandbox with JWT + API keys
  → Backend pauses sandbox (ready for on-demand wake)
  → Backend stores agent record in MongoDB
  → Agent is now reachable via @kai in Slack
```

## Message Flow

```
User: @kai scan my repos for vulnerabilities
  → Slack sends event to Cloudflare Worker
  → Worker calls GET /agents/lookup?slackTeamId=T0123
  → Backend returns { workspaceId, sandboxId }
  → Worker calls POST /workspaces/{id}/agents/wake
  → Backend resumes E2B sandbox (0.6s)
  → Backend dispatches agent_entrypoint.py with message
  → Agent runs Kai MCP tools (scan, analyze, report)
  → Agent posts results to Slack channel
  → Sandbox auto-pauses after 5 min idle
```

## JWT Lifecycle

| Event | JWT Duration | Trigger |
|-------|-------------|---------|
| Provision | 7 days | User enables agent |
| Refresh | 7 days | Cron (every 6 days) or manual |
| Wake | Uses existing JWT | Slack event |

Backend cron job should call `/agents/refresh-jwt` for all active agents
every 6 days (before the 7-day expiry).

## Cost

| Component | Cost |
|-----------|------|
| Cloudflare Worker | Free (100k req/day) |
| E2B Pro | $150/month base |
| Per agent (30 min active/day) | ~$2-3/month |
| 50 agents | ~$250-300/month |
