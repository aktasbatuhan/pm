# Backend Handoff: Kai Agent Architecture Changes

kai-agent repo has been restructured. This doc tells the backend team what changed, what's needed, and what's deprecated.
> Note: The agent runtime is now maintained by the Kai team. All references to "Hermes" in env vars, paths, and config are being migrated to "Kai" equivalents. Both names may coexist during the transition.

---

## TL;DR

We replaced the rigid lifecycle state machine with a shared workspace context layer and skill-driven autonomous work. The agent now has a single mind across all threads (web chat, Slack, cron, lifecycle). This impacts the backend in four ways:

1. **Activity feed is replaced by lifecycle actions + events** — richer, editable by users, drives the agent's decision-making
2. **Lifecycle backend API (`/internal/v1/lifecycle/...`) is deprecated** — cycle state moves to the new actions system
3. **Chat server in the sandbox now runs a real agent** — same HTTP contract, but fundamentally different behavior (slower, richer, makes MCP calls back to backend)
4. **Onboarding flow changed** — `__onboard__` trigger now runs an interactive multi-turn exploration, not a canned intro

---

## 1. What's Deprecated

### Activity Feed (`workspace_agent_activities` collection)

**Current state:** Agent posts activity summaries (`POST /agents/activities`), frontend reads them (`GET /agents/activities`). Simple append-only log with `summary`, `type`, `toolsUsed`.

**Why it's being replaced:** The activity feed is write-only from the agent's perspective — it posts and forgets. The agent never reads it back. Users can't edit or influence it. It's a display artifact, not a working data structure.

**Replaced by:** Lifecycle actions + action events (see section 2). These are read-write from both the agent and the user, with a full event log that the agent reasons about. The event log IS the activity feed — query `status=completed` actions and their events to see what Kai has been doing.

**Migration:** The `workspace_agent_activities` collection and its routes can be removed once the new actions system is live. No data migration needed — the old activities are display-only and don't feed into any decision-making.

### Lifecycle Internal API (`/internal/v1/lifecycle/...`)

**Current state:** The agent's lifecycle runner calls these internal (no-auth) endpoints:

| Endpoint | Purpose |
|----------|---------|
| `GET /lifecycle/{workspaceId}/scan` | Aggregate integration data |
| `POST /lifecycle/{workspaceId}/cycles/start` | Start a new cycle |
| `PATCH /lifecycle/{workspaceId}/cycles/{cycleId}` | Update cycle status |
| `GET /lifecycle/{workspaceId}/cycles/current` | Get active cycle |
| `POST /lifecycle/{workspaceId}/cycles/{cycleId}/propose` | Submit task proposal |
| `GET /lifecycle/{workspaceId}/cycles/{cycleId}/approval` | Poll for approval |
| `GET /lifecycle/{workspaceId}/cycles/{cycleId}/tasks` | List cycle tasks |
| `PATCH /lifecycle/{workspaceId}/cycles/{cycleId}/tasks/{taskId}` | Update task |
| `GET /lifecycle/{workspaceId}/blueprint` | Get blueprint |
| `POST /lifecycle/{workspaceId}/blueprint` | Push blueprint |
| `POST /lifecycle/{workspaceId}/cycles/{cycleId}/report` | Submit report |

**Why it's being replaced:** The lifecycle is no longer a rigid state machine. The agent decides what to work on based on signals (git activity, scan results, user requests), not a fixed scan → blueprint → propose → approve → execute → report pipeline. The cycle/phase model doesn't fit anymore.

**What stays useful:** The integration scan endpoint (`GET /lifecycle/{workspaceId}/scan`) is still valuable — it aggregates data from GitHub, Linear, Jira. Keep this, but expose it as an MCP tool so the agent can call it directly.

**Migration:** These endpoints can be removed after the new actions system is live. The MongoDB collections for cycles, proposals, and blueprints can be archived.

---

## 2. What's New: Lifecycle Actions & Events

### The Concept

Lifecycle actions replace both the activity feed and the cycle task system. An action is a unit of work the agent plans to do (or has done). Users can see, edit, add, and remove actions from the frontend. Every mutation is logged as an event so the agent understands what changed and why.

### MongoDB Collections

#### `lifecycle_actions`

```typescript
{
  _id: ObjectId,
  workspaceId: ObjectId,          // ref: workspaces

  // What
  type: string,                   // "security_scan" | "evolution" | "investigate" | "report" | "recommend" | "custom"
  title: string,                  // "Scan kai-frontend for vulnerabilities"
  description: string,            // Detailed description of what and why
  priority: string,               // "critical" | "high" | "medium" | "low"
  status: string,                 // "proposed" | "approved" | "in_progress" | "completed" | "rejected" | "deferred"

  // Context
  reasoning: string?,             // Why this action was created (agent's reasoning or user's note)
  linkedItems: [{                 // References to external items
    platform: string,             // "github" | "linear" | "jira" | "kai"
    externalId: string,
    url: string?,
    title: string?,
  }]?,

  // Results (filled after execution)
  result: {
    summary: string?,
    findings: string?,
    recommendations: string[]?,
    artifactIds: string[]?,       // References to scan IDs, evolution IDs, etc.
  }?,

  // Metadata
  createdBy: string,              // "agent" | "user:{userId}"
  assignedTo: string?,            // "agent" | "user:{userId}" — who should execute this
  cycleTag: string?,              // Optional grouping tag, e.g. "2026-03-27" for daily grouping

  createdAt: Date,
  updatedAt: Date,
  completedAt: Date?,
}
```

**Indexes:**
- `{ workspaceId: 1, status: 1, createdAt: -1 }` — active actions for a workspace
- `{ workspaceId: 1, cycleTag: 1 }` — group by daily cycle
- `{ workspaceId: 1, createdAt: -1 }` — chronological listing

#### `lifecycle_action_events`

Append-only log. Every mutation to an action creates an event.

```typescript
{
  _id: ObjectId,
  actionId: ObjectId,             // ref: lifecycle_actions
  workspaceId: ObjectId,          // ref: workspaces (denormalized for queries)

  eventType: string,              // "created" | "updated" | "status_changed" | "removed" | "completed"
  actor: string,                  // "agent" | "user:{userId}"

  // What changed
  changes: {                      // Only the fields that changed (diff, not snapshot)
    [field: string]: {
      before: any,
      after: any,
    }
  }?,

  reason: string?,                // Why this change was made (optional, human or agent explanation)

  createdAt: Date,
}
```

**Indexes:**
- `{ workspaceId: 1, createdAt: -1 }` — recent events for agent context
- `{ actionId: 1, createdAt: -1 }` — event history for a specific action

### API Endpoints

All under `/api/v1/workspaces/{workspaceId}/agents/actions/`.

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| **GET** | `/actions` | workspace | List actions (filterable by status, type, cycleTag) |
| **POST** | `/actions` | workspace | Create an action (from frontend or agent) |
| **GET** | `/actions/{actionId}` | workspace | Get single action with full details |
| **PATCH** | `/actions/{actionId}` | workspace | Update action (status, priority, description, etc.) |
| **DELETE** | `/actions/{actionId}` | workspace | Remove action (soft delete — creates a "removed" event) |
| **GET** | `/actions/events` | workspace | List recent events across all actions (for agent context) |
| **GET** | `/actions/{actionId}/events` | workspace | Events for a specific action |

#### Query Parameters

**`GET /actions`:**
- `status` — filter: `proposed`, `approved`, `in_progress`, `completed`, `rejected`, `deferred` (comma-separated for multiple)
- `type` — filter by action type
- `cycleTag` — filter by cycle grouping
- `limit` — default 20, max 100
- `offset` — pagination offset

**`GET /actions/events`:**
- `since` — ISO timestamp, return events after this time (default: 48 hours ago)
- `limit` — default 50, max 200

#### Create Action Body

```json
{
  "type": "security_scan",
  "title": "Scan kai-frontend for vulnerabilities",
  "description": "kai-frontend hasn't been scanned in 3 weeks and has had 12 commits since last scan.",
  "priority": "high",
  "reasoning": "Overdue scan on active repo with significant changes.",
  "linkedItems": [
    { "platform": "github", "externalId": "firstbatchxyz/kai-frontend", "url": "https://github.com/..." }
  ],
  "createdBy": "agent",
  "cycleTag": "2026-03-27"
}
```

#### Update Action Body

Any subset of mutable fields:

```json
{
  "status": "approved",
  "priority": "critical",
  "reason": "User escalated priority after noticing auth changes"
}
```

Every PATCH creates an event in `lifecycle_action_events` automatically. The `reason` field is optional but encouraged — it's what the agent reads to understand user intent.

#### Event Auto-Creation

The backend should automatically create events for every mutation:

```typescript
// On PATCH /actions/{actionId}
const changes = {};
for (const [key, value] of Object.entries(updateBody)) {
  if (key === 'reason') continue;
  if (action[key] !== value) {
    changes[key] = { before: action[key], after: value };
  }
}

await ActionEventModel.create({
  actionId,
  workspaceId,
  eventType: updateBody.status ? 'status_changed' : 'updated',
  actor: isAgentRequest ? 'agent' : `user:${userId}`,
  changes,
  reason: updateBody.reason,
});
```

### MCP Tool Exposure (Recommended)

These endpoints should also be exposed via the Kai MCP server so the agent can call them directly as tools during conversations:

- `list_lifecycle_actions(workspaceId, status?, limit?)` — see what's planned
- `create_lifecycle_action(workspaceId, type, title, description, priority, reasoning)` — propose work
- `update_lifecycle_action(actionId, status?, priority?, reason?)` — update progress
- `list_lifecycle_events(workspaceId, since?)` — see what changed recently

This is cleaner than HTTP helpers because it goes through the same MCP tool system as everything else (security scans, repo browsing, etc.).

---

## 3. Chat Server: Now a Real Agent

### What Changed

The E2B sandbox's `kai_chat_server.py` was a 182-line placeholder that made raw `urllib` calls to OpenRouter. No tools, no MCP, no memory. It has been replaced with a full Kai Agent:

- Full AIAgent with tools, MCP, memory, skills
- Shared workspace context (reads before each turn, writes after)
- Session persistence across messages within the same sandbox

### HTTP Contract (Unchanged)

- `POST /chat` with `{message, threadId}` → `{response, threadId, toolsUsed}`
- `GET /health` → `{status: "ok", agent: "kai"}`

### What's Different for the Backend

**Response times are fundamentally different.** The old server responded in 2-5 seconds (single LLM call). The new agent uses tools — it reads repos, runs scans, queries workspace state. A typical turn takes 10-60 seconds. Complex tasks (onboarding, scans) can take 60-120 seconds.

**Impact on `POST /agents/chat` proxy:**
- The current 90-second `AbortSignal.timeout` in the chat route may not be enough for complex turns
- **Recommended:** Switch to SSE streaming. The agent can stream partial responses and tool progress. This is already on the roadmap and would dramatically improve the web chat UX
- **Minimum:** Increase timeout to 180 seconds

**The agent makes MCP calls back to the backend during chat turns.** When a user sends a message, the agent may call `start_security_scan`, `list_repositories`, `list_vulnerabilities_by_repo`, etc. via MCP. This means a single `POST /agents/chat` request can trigger multiple Kai backend API calls underneath.

**Impact:**
- Rate limiting should account for agent-initiated requests (authenticated via JWT, same as before)
- Backend logging will show MCP tool calls interleaved with the chat request — this is expected behavior, not abuse
- If rate limits exist per-JWT, they may need to be raised for agent JWTs

**`toolsUsed` field now has real data.** Previously always `[]`. Now contains actual tool names the agent invoked during the turn (e.g. `["list_repositories", "browse_repository_files", "start_security_scan"]`). The frontend can use this to show what the agent did.

---

## 4. Onboarding Flow Changed

### What the Frontend Sends (Unchanged)

After provisioning, the frontend sends `POST /agents/chat` with `{message: "__onboard__"}`. This is the same as before.

### What Happens Now (Different)

**Before:** The chat server returned a canned 200-word intro in 2-3 seconds. No tool calls, no real exploration.

**Now:** The agent enters a full interactive onboarding flow:
1. Loads the self-onboard skill
2. Calls `list_my_workspaces`, `list_repositories`, `get_workspace_details` to explore
3. Reads repo files (README, package.json) to understand the tech stack
4. Shares findings as it discovers them
5. Asks follow-up questions based on what it found
6. Optionally runs a first security scan
7. Builds workspace context for all future conversations

**Impact on the frontend:**
- First response takes 30-60 seconds instead of 2-3 seconds
- The response is much richer — contains specific findings about the workspace
- The frontend needs a loading state that doesn't feel broken during this time
- **Recommended:** Implement SSE streaming so the user sees the agent's progress in real-time (tool calls, partial text). Without streaming, users will see a 30-60 second spinner and think it's broken.

### After Onboarding

Once onboarding completes, the agent transitions to autonomous daily work via the lifecycle skill. It will create lifecycle actions (proposed tasks) that appear in the new actions system. The user can approve, reject, or modify these from the frontend.

---

## 5. Environment Variables

### Sandbox Env Vars

The backend injects these during provisioning (in `buildEnvContent`):

| Var | Status | Notes |
|-----|--------|-------|
| `KAI_JWT_TOKEN` | Keep | Agent auth for MCP |
| `KAI_WORKSPACE_ID` | Keep | Workspace scoping. Agent also reads `KAI_WORKSPACE_ID` for workspace context |
| `KAI_BACKEND_URL` | Keep | Backend base URL |
| `OPENROUTER_API_KEY` | Keep | LLM provider |
| `FIRECRAWL_API_KEY` | Keep | Web research |
| `LLM_MODEL` | Keep | Model selection |
| `SLACK_BOT_TOKEN` | Keep | Slack integration |

**No new env vars required from backend.** The agent reads `KAI_WORKSPACE_ID` (already set) for workspace context scoping.

**Naming migration note:** The agent runtime historically used `HERMES_*` env var names (from the Hermes fork). These are being migrated to `KAI_*` equivalents. The agent reads both during transition. The backend only needs to set `KAI_*` vars — no `HERMES_*` vars needed.

---

## 6. Chat Server Code Injection

The backend's provision route currently injects the latest `kai_chat_server.py` into the sandbox:

```typescript
const chatServerPath = resolve(process.cwd(), "../hermes-agent/deploy/e2b-template/kai_chat_server.py");
const chatServerCode = readFileSync(chatServerPath, "utf-8");
await injectChatServerCode(sandboxId, chatServerCode);
```

**This path needs updating.** The repo has moved from `hermes-agent` to `kai-agent`. The new path:

```typescript
const chatServerPath = resolve(process.cwd(), "../kai-agent/deploy/e2b-template/kai_chat_server.py");
```

**Important:** The new chat server imports from the kai-agent package (`from run_agent import AIAgent`, `from workspace_context import ...`). These must be installed in the E2B template. The template build already handles this — but if the backend is injecting code without rebuilding the template, ensure the sandbox has the full kai-agent package installed, not just the chat server file.

---

## 7. Migration Plan

### Phase 1: Backend builds new actions system 
- Create `lifecycle_actions` and `lifecycle_action_events` collections
- Add CRUD + events endpoints under `/agents/actions/`
- Auto-create events on every mutation
- Keep existing activity feed and lifecycle API running in parallel
- Update chat server path from `hermes-agent` to `kai-agent`

### Phase 2: Backend exposes actions as MCP tools 
- Add lifecycle action tools to Kai MCP server
- Expose integration scan as MCP tool (keep `GET /lifecycle/{workspaceId}/scan`)

### Phase 3: Agent switches to new system 
- Agent reads/writes lifecycle actions via MCP tools
- Cron triggers the lifecycle skill, which creates/updates actions
- Workspace context caches action summary for system prompt injection

### Phase 4: Frontend switches 
- Replace activity feed component with actions list
- Add action editing (approve, reject, reprioritize, add, remove)
- Show event log per action (audit trail)

### Phase 5: Chat UX improvements
- Implement SSE streaming for `POST /agents/chat`
- Show tool progress during long turns
- Better loading states for onboarding

### Phase 6: Deprecate old system 
- Remove activity feed endpoints and collection
- Remove lifecycle internal API endpoints
- Archive cycle/blueprint/proposal collections

---

## 8. Summary of All Backend Changes Needed

| Priority | Task | Effort | Blocks |
|----------|------|--------|--------|
| **P0** | Create `lifecycle_actions` collection + CRUD routes | 1-2 days | Frontend actions UI |
| **P0** | Create `lifecycle_action_events` collection + auto-event creation | 1 day | Agent context |
| **P0** | `GET /actions/events?since=` endpoint for agent context | 0.5 day | Agent lifecycle skill |
| **P0** | Update chat server path: `hermes-agent` → `kai-agent` | 0.5 hour | Provisioning |
| **P1** | Expose lifecycle actions as MCP tools on Kai MCP server | 1 day | Agent direct tool access |
| **P1** | Expose integration scan as MCP tool | 0.5 day | Agent lifecycle skill |
| **P1** | New MCP tool: `list_github_user_repos(workspaceId)` — list ALL repos from user's GitHub (not just workspace-connected). Use stored OAuth token to call GitHub API `GET /user/repos` + `GET /orgs/{org}/repos`. Agent needs this for onboarding — it must see the full org to understand the codebase, not just manually-added repos. | 1 day | Onboarding |
| **P1** | Increase chat proxy timeout to 180s (or implement SSE) | 1-2 days | Web chat UX |
| **P2** | Account for agent-initiated MCP calls in rate limiting | 0.5 day | Production stability |
| **P3** | Remove deprecated activity feed routes + collection | 0.5 day | Cleanup |
| **P3** | Remove deprecated lifecycle internal API | 0.5 day | Cleanup |

**Total: ~7-9 days of backend work**, mostly parallelizable with agent-side and frontend development. P0 items block other teams and should start immediately.

---

## 9. Workspace Context API (NEW)

The agent's workspace memory is moving from local SQLite to backend MongoDB, exposed as MCP tools. This replaces the agent's `workspace_context.py` module and makes the agent's knowledge visible to the frontend and editable by users.

### MongoDB Collections

**`workspace_context_status`** — one doc per workspace
```json
{ "workspaceId": "ws_abc", "onboardingStatus": "completed", "onboardingPhase": "complete", "updatedAt": "..." }
```

**`workspace_blueprints`** — one doc per workspace
```json
{ "workspaceId": "ws_abc", "summary": "text <4000 chars", "data": {}, "updatedAt": "...", "updatedBy": "agent" }
```

**`workspace_learnings`** — append-only, one doc per learning
```json
{ "workspaceId": "ws_abc", "category": "security", "content": "...", "sourceThread": "cli:abc", "createdAt": "..." }
```

**`workspace_threads`** — one doc per thread (upsert by threadId)
```json
{ "workspaceId": "ws_abc", "threadId": "slack:C04xyz", "platform": "slack", "summary": "...", "userId": "u_123", "lastActive": "..." }
```

**`workspace_pending_work`** — one doc per work item (upsert by workId)
```json
{ "workspaceId": "ws_abc", "workId": "fix_jwt", "type": "security_fix", "status": "approved", "description": "...", "linkedThread": "...", "updatedAt": "..." }
```

### REST Routes

All under `/api/v1/workspaces/:workspaceId/agents/context/`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/context/status` | Onboarding status + summary counts |
| PATCH | `/context/status` | Update onboarding status |
| GET | `/context/blueprint` | Full blueprint |
| PUT | `/context/blueprint` | Write/replace blueprint |
| GET | `/context/learnings?category=&limit=30` | List learnings |
| POST | `/context/learnings` | Add a learning |
| GET | `/context/threads?platform=&limit=10` | List thread summaries |
| PUT | `/context/threads/:threadId` | Upsert thread summary |
| GET | `/context/pending-work?status=&limit=20` | List pending work |
| PUT | `/context/pending-work/:workId` | Upsert pending work item |

### MCP Tools (10 new tools)

Register in `src/mcp/tools/workspace-context.ts` following the same pattern as `lifecycle.ts`:

**Read tools:** `workspace_status`, `workspace_blueprint_get`, `workspace_learnings_list`, `workspace_threads_list`, `workspace_pending_work_list`

**Write tools:** `workspace_status_update`, `workspace_blueprint_update`, `workspace_learnings_add`, `workspace_threads_update`, `workspace_pending_work_upsert`

Each tool maps 1:1 to a REST route above using `callApiAsTool()`.

### Priority

| Priority | Task | Effort |
|----------|------|--------|
| **P0** | Create 5 MongoDB collections + indexes | 0.5 day |
| **P0** | Create REST routes (10 endpoints) | 1-2 days |
| **P0** | Register 10 MCP tools in workspace-context.ts | 1 day |
| **P1** | Frontend: render agent learnings + blueprint (read-only) | 1-2 days |
| **P2** | Frontend: allow users to edit/delete learnings, approve/reject pending work | 2-3 days |
