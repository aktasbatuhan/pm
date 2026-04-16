# Kai Agent — Architecture Map

> Last updated: 2026-03-27

---

## 1. The Core Problem

A human employee has **one mind** with consolidated context, but works across **many threads** (Slack DMs, email, meetings, code reviews). The mind synthesizes everything — context from a Slack thread informs a code review, a meeting decision changes how they approach an email.

Kai Agent today is the inverse: **many minds, each with isolated context**.

```
HUMAN EMPLOYEE                         KAI AGENT (TODAY)
┌─────────────────────────┐            ┌─────────────────────────┐
│       ONE MIND          │            │     NO SHARED MIND      │
│  (consolidated context) │            │                         │
│                         │            │  ┌─────┐ ┌─────┐ ┌───┐ │
│   ┌──┐ ┌──┐ ┌──┐ ┌──┐  │            │  │Brain│ │Brain│ │Toy│ │
│   │  │ │  │ │  │ │  │  │            │  │  1  │ │  2  │ │ 3 │ │
│   └──┘ └──┘ └──┘ └──┘  │            │  └──┬──┘ └──┬──┘ └─┬─┘ │
│   Slack Email Code  Mtg │            │     │       │      │   │
└─────────────────────────┘            └─────┼───────┼──────┼───┘
                                             │       │      │
Each thread feeds the                  Slack  Lifecycle Web Chat
same mind. Context                     (full   (full    (raw LLM,
flows freely.                          agent)  agent)   no tools,
                                                        no memory)
                                       ZERO shared context between them.
```

---

## 2. Current State — What Exists

### 2.1 Three Entry Points, Three Isolated Worlds

```
                         ┌──────────────────────────────────────────┐
                         │              KAI BACKEND                 │
                         │            (Bun / Hono)                  │
                         │                                          │
                         │  MongoDB ──── E2B API ──── JWT mgmt     │
                         └─────┬──────────┬──────────────┬─────────┘
                               │          │              │
              ┌────────────────┼──────────┼──────────────┼──────────────┐
              │                │          │              │               │
              ▼                ▼          ▼              ▼               │
     ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐       │
     │  FRONTEND   │  │   SLACK      │  │     LIFECYCLE        │       │
     │  (Next.js)  │  │   GATEWAY    │  │     RUNNER           │       │
     │             │  │              │  │                      │       │
     │ POST /chat ─┼──┼──────┐      │  │  Runs on cron        │       │
     └─────────────┘  │      │      │  │  (every 24h)         │       │
              │       │      │      │  │                      │       │
              ▼       │      ▼      │  └──────────┬───────────┘       │
     ┌─────────────┐  │  ┌──────┐   │             │                   │
     │ E2B SANDBOX │  │  │ AI   │   │        ┌────▼─────┐            │
     │             │  │  │Agent │   │        │ AIAgent  │            │
     │ kai_chat_   │  │  │(real)│   │        │ (real)   │            │
     │ server.py   │  │  └──┬───┘   │        └────┬─────┘            │
     │             │  │     │       │             │                   │
     │ RAW LLM    │  │  ┌──▼────┐  │        ┌────▼──────┐           │
     │ urllib call │  │  │32 MCP │  │        │ 32 MCP    │           │
     │ NO tools   │  │  │tools  │  │        │ tools     │           │
     │ NO memory  │  │  │Skills │  │        │ Skills    │           │
     │ NO MCP     │  │  │Memory │  │        │ Memory    │           │
     │ dict{}     │  │  │SQLite │  │        │ SQLite    │           │
     │ sessions   │  │  └───────┘  │        └───────────┘           │
     └─────────────┘  └────────────┘                                 │
                                                                      │
     SESSION KEY:      SESSION KEY:          SESSION KEY:             │
     web_{timestamp}   slack:dm:{channel}    lifecycle_{workspace}    │
     (in-memory,       (SQLite, persistent)  (SQLite, persistent)    │
      lost on restart)                                                │
                                                                      │
     SHARED STATE: ────────────── NONE ───────────────────────────────┘
```

### 2.2 Web Chat — The Fake Brain

`deploy/e2b-template/kai_chat_server.py` — 182 lines, self-contained HTTP server baked into the E2B image.

```
Frontend                    E2B Sandbox (:8080)
   │                              │
   │  POST /chat                  │
   │  {message, threadId}         │
   │─────────────────────────────►│
   │                              │
   │                    ┌─────────▼──────────┐
   │                    │ SESSIONS = {}      │  ◄── Python dict, in-memory
   │                    │                    │
   │                    │ history = SESSIONS  │
   │                    │   [threadId]       │
   │                    │                    │
   │                    │ llm_messages = [   │
   │                    │   {system: HARD-   │  ◄── 15-line hardcoded prompt
   │                    │    CODED_PROMPT},  │
   │                    │   ...history,      │
   │                    │   {user: message}  │
   │                    │ ]                  │
   │                    │                    │
   │                    │ urllib.request     │
   │                    │   .urlopen(        │  ◄── Raw HTTP to OpenRouter
   │                    │     openrouter,    │      No SDK, no retry, no stream
   │                    │     llm_messages   │
   │                    │   )               │
   │                    └─────────┬──────────┘
   │                              │
   │  {response, threadId}        │
   │◄─────────────────────────────│
   │                              │
```

**What's missing:** Tools, MCP, skills, memory, session persistence, context compression, streaming, error recovery. It's a demo placeholder.

### 2.3 Slack Chat — The Real Brain

```
Slack WebSocket
      │
      ▼
┌───────────────────────────────────────────────────────────────┐
│  GATEWAY  (gateway/run.py)                                    │
│                                                               │
│  1. SlackAdapter normalizes message                           │
│     ├── Strip bot mentions                                    │
│     ├── Download attachments (images/audio/docs)              │
│     └── Build SessionSource{platform, chat_id, user_id}      │
│                                                               │
│  2. Authorization check                                       │
│     ├── SLACK_ALLOW_ALL_USERS / allowlist                     │
│     └── Pairing code flow for DMs                             │
│                                                               │
│  3. Session management                                        │
│     ├── Key: "agent:main:slack:dm:{channel_id}"               │
│     ├── Load from SQLite (or create new)                      │
│     ├── Check reset policy (idle timeout / daily)             │
│     └── Load transcript history                               │
│                                                               │
│  4. Context compression (if history > 85% of context window)  │
│     ├── Summarize middle turns via Gemini Flash               │
│     └── Rewrite transcript                                    │
│                                                               │
│  5. Enrich message                                            │
│     ├── Vision analysis on images                             │
│     ├── Transcribe audio                                      │
│     └── Inline document content                               │
│                                                               │
│  6. Build AIAgent                                             │
│     ├── model: from config.yaml                               │
│     ├── enabled_toolsets: ["hermes-slack"]                     │
│     ├── ephemeral_system_prompt: session context               │
│     ├── session_id: for memory persistence                    │
│     ├── prefill_messages: conversation history                │
│     └── platform: "slack"                                     │
│                                                               │
│  7. agent.run_conversation(message, history)                  │
│     ├── System prompt = identity + memory + skills + context  │
│     ├── Tool loop (MCP, terminal, file, web, delegate...)     │
│     └── Returns response text + tool results                  │
│                                                               │
│  8. Deliver response                                          │
│     ├── chat_postMessage to Slack                             │
│     ├── Upload media (images, docs)                           │
│     └── Mirror to transcript (SQLite)                         │
└───────────────────────────────────────────────────────────────┘
```

### 2.4 Lifecycle Runner — The Autonomous Brain

```
┌──────────────────────────────────────────────────────────────────────┐
│  LIFECYCLE  (lifecycle/runner.py)                                     │
│                                                                      │
│  Triggered by cron (every 24h) or manual CLI                         │
│  Runs as independent process, NOT inside the gateway                 │
│                                                                      │
│  6-PHASE STATE MACHINE (persisted to kai-backend):                   │
│                                                                      │
│  ┌───────┐    ┌───────────┐    ┌─────────┐    ┌─────────────────┐   │
│  │ SCAN  │───►│ BUILD     │───►│PROPOSE  │───►│AWAIT            │   │
│  │       │    │ BLUEPRINT │    │(5-10    │    │APPROVAL         │   │
│  │Fetch  │    │           │    │tasks)   │    │(poll backend    │   │
│  │integr-│    │LLM analy- │    │         │    │ every 30s,      │   │
│  │ations │    │zes repos, │    │Priori-  │    │ 3h timeout)     │   │
│  │data   │    │PRs, issues│    │tized by │    │                 │   │
│  │       │    │sprints,CI │    │impact   │    │User approves/   │   │
│  │       │    │           │    │         │    │rejects via UI   │   │
│  └───────┘    └───────────┘    └─────────┘    └────────┬────────┘   │
│                                                         │            │
│                                                         ▼            │
│                ┌───────────┐    ┌─────────────────────────────┐      │
│                │  REPORT   │◄───│ EXECUTE                     │      │
│                │           │    │                             │      │
│                │Markdown   │    │ For each approved task:     │      │
│                │summary    │    │  security_scan → recommend  │      │
│                │submitted  │    │  evolution → recommend      │      │
│                │to backend │    │  investigate → LLM analysis │      │
│                │           │    │  report → generate findings │      │
│                └───────────┘    └─────────────────────────────┘      │
│                                                                      │
│  Session ID: lifecycle_{workspace}_{timestamp}                       │
│  Shares NOTHING with Slack or web sessions                           │
│  Blueprint versioned on backend, but not accessible to other brains  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Self-Learning & Scheduled Work — How They Work

### 3.1 Memory System (Per-Session, Not Global)

```
┌─────────────────────────────────────────────────────────────┐
│  MEMORY LAYERS                                               │
│                                                              │
│  Layer 1: CURATED FILES (persistent across sessions)         │
│  ┌────────────────────┐  ┌────────────────────┐             │
│  │ ~/.hermes/MEMORY.md│  │ ~/.hermes/USER.md  │             │
│  │                    │  │                    │             │
│  │ 2,200 char limit   │  │ 1,375 char limit   │             │
│  │ Agent's notes:     │  │ User profile:      │             │
│  │ - env facts        │  │ - name, role       │             │
│  │ - project patterns │  │ - timezone         │             │
│  │ - tool quirks      │  │ - coding style     │             │
│  │ - lessons learned  │  │ - preferences      │             │
│  └────────┬───────────┘  └────────┬───────────┘             │
│           │                       │                          │
│           ▼                       ▼                          │
│  ┌─────────────────────────────────────────────┐            │
│  │ FROZEN SNAPSHOT (loaded once at session start)│           │
│  │ Injected into system prompt, never changes    │           │
│  │ mid-session (preserves prefix cache)          │           │
│  └─────────────────────────────────────────────┘            │
│                                                              │
│  Layer 2: SESSION TRANSCRIPTS (per session, SQLite)          │
│  ┌──────────────────────────────────────────┐               │
│  │ sessions table + messages table           │               │
│  │ FTS5 full-text search across all history  │               │
│  │ Each session has unique key:              │               │
│  │   "agent:main:slack:dm:C12345"            │               │
│  │   "lifecycle_ws123_20260327"              │               │
│  │   (web sessions: not even stored)         │               │
│  └──────────────────────────────────────────┘               │
│                                                              │
│  Layer 3: SKILLS (reusable workflow documents)               │
│  ┌──────────────────────────────────────────┐               │
│  │ ~/.hermes/skills/{category}/{name}/       │               │
│  │   SKILL.md      — instructions            │               │
│  │   references/   — supporting docs         │               │
│  │   templates/    — output templates        │               │
│  │                                           │               │
│  │ Agent prompted to save skills after       │               │
│  │ complex tasks (5+ tool calls)             │               │
│  └──────────────────────────────────────────┘               │
│                                                              │
│  Layer 4: SESSION SEARCH (cross-session recall)              │
│  ┌──────────────────────────────────────────┐               │
│  │ FTS5 query across ALL past sessions       │               │
│  │ Top 3-5 sessions loaded, truncated to     │               │
│  │ ~100k chars, summarized by Gemini Flash   │               │
│  │                                           │               │
│  │ Triggered by: "remember when...",         │               │
│  │ "we did this before", "last time"         │               │
│  └──────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Memory Flush — The Self-Learning Trigger

```
DURING A SESSION:

  turn 1 ─► turn 2 ─► ... ─► turn N
                                │
                    ┌───────────┼───────────────────────┐
                    │           │                       │
                    │     TRIGGER EVENTS:               │
                    │     • Context hits 85%            │
                    │     • Session reset               │
                    │     • CLI exit                    │
                    │     • /compress command           │
                    │                                   │
                    ▼                                   │
          ┌─────────────────┐                          │
          │  flush_memories  │                          │
          │                 │                          │
          │ Inject synthetic│                          │
          │ user message:   │                          │
          │ "Save anything  │                          │
          │  worth          │                          │
          │  remembering"   │                          │
          │                 │                          │
          │ One LLM turn    │                          │
          │ with memory     │                          │
          │ tool access     │                          │
          │       │         │                          │
          │       ▼         │                          │
          │ Agent decides   │                          │
          │ what to write   │                          │
          │ to MEMORY.md    │                          │
          │ and USER.md     │                          │
          │                 │                          │
          │ Atomic write    │                          │
          │ to disk         │                          │
          └─────────────────┘                          │
                                                       │
  BUT: This only captures what ONE session learned.    │
  Other sessions don't see it until THEIR next start.  │
  And the web chat brain never sees it at all.         │
  ─────────────────────────────────────────────────────┘
```

### 3.3 Cron System — Scheduled Task Execution

```
┌──────────────────────────────────────────────────────────────┐
│  CRON ENGINE  (cron/)                                         │
│                                                               │
│  Storage: ~/.hermes/cron/jobs.json (file-locked)              │
│  Ticker: gateway background thread, every 60s                 │
│                                                               │
│  SCHEDULE TYPES:                                              │
│  ┌──────────────┬───────────────────┬────────────────┐       │
│  │ One-shot     │ Recurring         │ Cron expr      │       │
│  │ "30m", "2h"  │ "every 30m"       │ "0 9 * * *"    │       │
│  │ "2026-03-28  │ "every 1d"        │ (5-field)      │       │
│  │  T14:00:00"  │                   │                │       │
│  └──────────────┴───────────────────┴────────────────┘       │
│                                                               │
│  EXECUTION FLOW:                                              │
│                                                               │
│  tick() ──► get_due_jobs() ──► for each job:                  │
│                                     │                         │
│                    ┌────────────────▼────────────────┐        │
│                    │  run_job(job)                    │        │
│                    │                                 │        │
│                    │  1. Load fresh .env + config    │        │
│                    │  2. Create AIAgent              │        │
│                    │     (ISOLATED session,          │        │
│                    │      NO conversation history,   │        │
│                    │      prompt must be             │        │
│                    │      self-contained)            │        │
│                    │  3. agent.run_conversation(     │        │
│                    │       job["prompt"])            │        │
│                    │  4. Capture output              │        │
│                    │  5. Save to cron/output/        │        │
│                    └────────────────┬────────────────┘        │
│                                     │                         │
│                    ┌────────────────▼────────────────┐        │
│                    │  _deliver_result()               │        │
│                    │                                 │        │
│                    │  Target: "origin" → source chat │        │
│                    │          "slack"  → home channel│        │
│                    │          "local"  → file only   │        │
│                    │          "slack:C123" → specific│        │
│                    └─────────────────────────────────┘        │
│                                                               │
│  CRITICAL CONSTRAINT:                                         │
│  Each cron job runs with ZERO context from any session.       │
│  The prompt is the ONLY input. No memory injection,           │
│  no conversation history, no awareness of other jobs.         │
└──────────────────────────────────────────────────────────────┘
```

### 3.4 Lifecycle ↔ Cron Integration

```
register_lifecycle_cron(workspace_id, "every 24h")
        │
        ▼
┌───────────────────┐         ┌──────────────────────────┐
│  CRON JOB         │  tick   │  LIFECYCLE RUNNER         │
│                   │────────►│                          │
│  prompt:          │         │  python -m lifecycle     │
│  "python -m       │         │    {workspace_id}        │
│   lifecycle       │         │    --once                │
│   {workspace_id}  │         │                          │
│   --once"         │         │  Runs 6-phase state      │
│                   │         │  machine (scan →          │
│  schedule:        │         │  blueprint → propose →    │
│  "every 24h"      │         │  approve → execute →     │
│                   │         │  report)                  │
└───────────────────┘         │                          │
                              │  Persists state to       │
                              │  kai-backend (resumable)  │
                              └──────────────────────────┘
```

---

## 4. Target Architecture — Unified Mind

### 4.1 Why NOT a Separate Broker Process

A living broker service (persistent process managing all AI sessions) is wrong here:

- **AIAgent is already stateless between turns.** The gateway creates a fresh AIAgent per message. `run_conversation()` builds its world from scratch each time: load memory, build system prompt, call LLM. That's a feature — any entry point can spin up an agent and die.
- **Single point of failure.** Broker dies → everything dies. Currently each thread is independent.
- **Unnecessary network hops.** Asking "what do other threads know?" before every turn is just a function call against shared storage, not an RPC.
- **The injection point already exists.** `_build_system_prompt()` (line 1424) assembles layers in order. `ephemeral_system_prompt` (line 3490) adds per-call context. We just need to feed them shared data.

### 4.2 The Answer: Shared Context Layer + Workspace-Aware Prompt Assembly

No new process. Just two function calls wrapping the existing `run_conversation`:

```
BEFORE:                                    AFTER:
─────────────────────────                  ──────────────────────────────────

gateway._run_agent():                      gateway._run_agent():
  agent = AIAgent(...)                       ctx = workspace_context.load(ws_id)
  result = agent.run_conversation(msg)       agent = AIAgent(...)
  deliver(result)                            result = agent.run_conversation(
                                               msg,
                                               system_message=ctx.to_prompt()
                                             )
                                             workspace_context.post_turn(
                                               ws_id, thread_id, result
                                             )
                                             deliver(result)

cron/scheduler.py run_job():               cron/scheduler.py run_job():
  agent = AIAgent(...)                       ctx = workspace_context.load(ws_id)
  agent.run_conversation(prompt)             agent = AIAgent(...)
                                             agent.run_conversation(
                                               prompt,
                                               system_message=ctx.to_prompt()
                                             )
                                             workspace_context.post_turn(...)

lifecycle/runner.py:                       lifecycle/runner.py:
  agent = _create_agent(session_id)          ctx = workspace_context.load(ws_id)
  # ... 6-phase loop ...                     agent = _create_agent(session_id)
                                             # ... 6-phase loop ...
                                             workspace_context.update_blueprint(
                                               ws_id, blueprint
                                             )
```

### 4.3 Workspace Context — The Shared Layer

```
┌──────────────────────────────────────────────────────────────────────┐
│  WORKSPACE CONTEXT  (new module: workspace_context.py)               │
│                                                                      │
│  Storage: SQLite table(s) in the existing SessionDB                  │
│  OR: ~/.hermes/workspace/{workspace_id}/                             │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                                                                 │ │
│  │  BLUEPRINT (written by lifecycle, read by all)                  │ │
│  │  ┌───────────────────────────────────────────────────────────┐  │ │
│  │  │ Latest workspace snapshot from lifecycle's scan phase:    │  │ │
│  │  │ - repos, tech stack, health scores                       │  │ │
│  │  │ - open issues, stale PRs, CI status                      │  │ │
│  │  │ - last scan results (high-sev vulns, evolution status)   │  │ │
│  │  │ - team members, active sprints                           │  │ │
│  │  │                                                          │  │ │
│  │  │ Updated: every lifecycle cycle (typically daily)          │  │ │
│  │  │ Format: structured JSON, summarized to ~2K tokens        │  │ │
│  │  │         for system prompt injection                      │  │ │
│  │  └───────────────────────────────────────────────────────────┘  │ │
│  │                                                                 │ │
│  │  THREAD INDEX (written by all threads, read by all)             │ │
│  │  ┌───────────────────────────────────────────────────────────┐  │ │
│  │  │ thread_id       │ platform │ last_active │ summary        │  │ │
│  │  │─────────────────┼──────────┼─────────────┼───────────────│  │ │
│  │  │ slack:dm:C123   │ slack    │ 10min ago   │ "Discussing   │  │ │
│  │  │                 │          │             │  auth refactor │  │ │
│  │  │                 │          │             │  for repo X"   │  │ │
│  │  │─────────────────┼──────────┼─────────────┼───────────────│  │ │
│  │  │ web:sess:42     │ web      │ 2min ago    │ "User onboard-│  │ │
│  │  │                 │          │             │  ing, connected│  │ │
│  │  │                 │          │             │  GitHub"       │  │ │
│  │  │─────────────────┼──────────┼─────────────┼───────────────│  │ │
│  │  │ lifecycle:ws1   │ auto     │ 6h ago      │ "Nightly scan │  │ │
│  │  │                 │          │             │  found 2 high- │  │ │
│  │  │                 │          │             │  sev vulns"    │  │ │
│  │  │─────────────────┼──────────┼─────────────┼───────────────│  │ │
│  │  │ cron:dep-check  │ auto     │ 1h ago      │ "All deps     │  │ │
│  │  │                 │          │             │  up to date"   │  │ │
│  │  └───────────────────────────────────────────────────────────┘  │ │
│  │                                                                 │ │
│  │  Summary is 1-2 sentences per thread. Written by post_turn().   │ │
│  │  NOT the full conversation — just "what's the latest?"          │ │
│  │                                                                 │ │
│  │  LEARNINGS (written by all threads, read by all)                │ │
│  │  ┌───────────────────────────────────────────────────────────┐  │ │
│  │  │ Replaces MEMORY.md (2,200 chars) with structured entries │  │ │
│  │  │                                                          │  │ │
│  │  │ Each entry:                                              │  │ │
│  │  │   { source_thread, timestamp, category, content }        │  │ │
│  │  │                                                          │  │ │
│  │  │ Categories:                                              │  │ │
│  │  │   user_pref    — "Alice prefers PRs under 200 lines"     │  │ │
│  │  │   codebase     — "Repo X uses custom auth middleware"    │  │ │
│  │  │   tool_quirk   — "Jira API rate-limits at 50 req/min"   │  │ │
│  │  │   scan_finding — "CVE-2026-1234 in repo Y, patched"     │  │ │
│  │  │   workflow     — "Team does Friday deploys, not Monday"  │  │ │
│  │  │                                                          │  │ │
│  │  │ Bounded: max ~100 entries, oldest auto-evicted           │  │ │
│  │  │ Summarized to ~1.5K tokens for system prompt injection   │  │ │
│  │  └───────────────────────────────────────────────────────────┘  │ │
│  │                                                                 │ │
│  │  PENDING WORK (written by lifecycle/cron, read by all)          │ │
│  │  ┌───────────────────────────────────────────────────────────┐  │ │
│  │  │ Approved tasks, open questions, blocked items             │  │ │
│  │  │ { id, type, status, description, linked_thread }         │  │ │
│  │  │                                                          │  │ │
│  │  │ When Slack user asks "what's on your plate?" —            │  │ │
│  │  │ the agent reads this, not a separate backend call.       │  │ │
│  │  └───────────────────────────────────────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.4 How It Plugs Into run_conversation — Exact Code Path

The workspace context injects through `system_message` (the parameter that becomes
part of `_build_system_prompt`, line 1455) and `ephemeral_system_prompt` (injected
at API-call time, line 3490). No changes needed inside AIAgent itself.

```
run_conversation(user_message, system_message, conversation_history)
      │
      │  Line 3320: if self._cached_system_prompt is None:
      │  Line 3336:     self._cached_system_prompt = self._build_system_prompt(system_message)
      │                       │
      │                       ▼
      │              _build_system_prompt() assembles (line 1424):
      │                1. DEFAULT_AGENT_IDENTITY
      │                2. Tool guidance (memory, session_search, skills)
      │                3. system_message  ◄──── THIS IS WHERE WORKSPACE CONTEXT GOES
      │                   │
      │                   │  Contains:
      │                   │  ┌─────────────────────────────────────────────┐
      │                   │  │ ## Workspace Context                       │
      │                   │  │                                            │
      │                   │  │ ### Blueprint                              │
      │                   │  │ 3 repos, 2 with passing CI, 1 failing...  │
      │                   │  │ Last scan: 2 high-sev vulns in repo X...  │
      │                   │  │                                            │
      │                   │  │ ### Other Active Threads                   │
      │                   │  │ - Slack DM with Alice (10min ago):         │
      │                   │  │   discussing auth refactor for repo X      │
      │                   │  │ - Lifecycle (6h ago):                      │
      │                   │  │   nightly scan complete, 2 vulns found     │
      │                   │  │                                            │
      │                   │  │ ### Learnings                              │
      │                   │  │ - Alice prefers PRs under 200 lines        │
      │                   │  │ - Repo X uses custom auth middleware       │
      │                   │  │ - Team does Friday deploys                 │
      │                   │  │                                            │
      │                   │  │ ### Pending Work                           │
      │                   │  │ - [approved] Scan repo Y for CVE-2026-XX  │
      │                   │  │ - [blocked] Need Alice's input on auth     │
      │                   │  └─────────────────────────────────────────────┘
      │                   │
      │                4. Memory snapshot (MEMORY.md, USER.md)
      │                5. Skills index
      │                6. Context files (AGENTS.md)
      │                7. Timestamp
      │                8. Platform hint
      │
      │  Line 3490: ephemeral_system_prompt appended at API-call time
      │             (platform-specific session context, as today)
      │
      ▼
   LLM sees: identity + workspace context + memory + skills + thread history
   Kai now knows what ALL threads have been doing.
```

### 4.5 Post-Turn: Writing Back

After `run_conversation` returns, the caller (gateway, cron, lifecycle) writes back:

```
result = agent.run_conversation(msg, system_message=ctx.to_prompt())
    │
    ▼
workspace_context.post_turn(workspace_id, thread_id, result)
    │
    ├── 1. UPDATE THREAD SUMMARY
    │      Extract last assistant message, compress to 1-2 sentences
    │      Write to thread_index: {thread_id, platform, last_active, summary}
    │      This is CHEAP — no LLM call needed for short summaries.
    │      For long tool-heavy turns: one fast LLM call (haiku/flash).
    │
    ├── 2. EXTRACT LEARNINGS (optional, not every turn)
    │      Only when the agent used tools that produced new info:
    │      - Security scan completed → scan_finding
    │      - User stated a preference → user_pref
    │      - Discovered a codebase pattern → codebase
    │      Heuristic: did this turn contain tool_calls? Was it >3 turns?
    │      If yes: one fast LLM call to extract structured learnings.
    │      If no: skip (most casual chat turns produce nothing).
    │
    └── 3. UPDATE PENDING WORK
           If the agent completed or made progress on a pending item,
           mark it. This is just a status field update, no LLM call.
```

### 4.6 Full Picture

```
┌───────────────────────────────────────────────────────────────────────────┐
│                                                                           │
│   WORKSPACE CONTEXT (SQLite / file-based, shared across all threads)      │
│   ┌──────────┐ ┌──────────────┐ ┌──────────┐ ┌──────────────┐           │
│   │Blueprint │ │Thread Index  │ │Learnings │ │Pending Work  │           │
│   │(daily)   │ │(per turn)    │ │(organic) │ │(lifecycle)   │           │
│   └────┬─────┘ └──────┬───────┘ └────┬─────┘ └──────┬───────┘           │
│        │              │              │              │                     │
│        └──────────────┴──────────────┴──────────────┘                     │
│                              │                                            │
│                    ctx.to_prompt()                                        │
│                    (read at session start,                                │
│                     ~3-4K tokens total)                                   │
│                              │                                            │
│              ┌───────────────┼───────────────┐                            │
│              │               │               │                            │
│              ▼               ▼               ▼                            │
│     ┌──────────────┐ ┌────────────┐ ┌──────────────┐                     │
│     │ WEB / SLACK  │ │ LIFECYCLE  │ │   CRON JOB   │                     │
│     │              │ │            │ │              │                     │
│     │ AIAgent      │ │ AIAgent    │ │ AIAgent      │                     │
│     │  system_msg  │ │  system_msg│ │  system_msg  │                     │
│     │  = ctx       │ │  = ctx     │ │  = ctx       │                     │
│     │              │ │            │ │              │                     │
│     │ Thread's own │ │ Lifecycle  │ │ Job's own    │                     │
│     │ chat history │ │ phases     │ │ prompt       │                     │
│     └──────┬───────┘ └─────┬──────┘ └──────┬───────┘                     │
│            │               │               │                             │
│            ▼               ▼               ▼                             │
│     post_turn()      update_blueprint()   post_turn()                    │
│     - thread summary - full blueprint     - thread summary               │
│     - learnings      - pending work       - learnings                    │
│     - pending work                                                       │
│                                                                           │
│   ALL threads read the same context. ALL threads write back.              │
│   No broker process. No new service. Just shared storage + 2 functions.   │
└───────────────────────────────────────────────────────────────────────────┘
```

### 4.7 What Changes From Today

```
TODAY                                     TARGET
─────────────────────────────────────     ───────────────────────────────────────
Web chat = raw LLM call                  Web chat = real AIAgent (same as Slack)
kai_chat_server.py = 182-line toy        DELETED. Sandbox runs the real agent.
Sessions = per-thread, isolated           Workspace context = shared read/write
Memory = MEMORY.md (2,200 chars)         Learnings table (structured, bounded)
Blueprint = lifecycle-only, backend      Blueprint = local copy, all threads see
Cron jobs = zero context                  Cron jobs = workspace-aware via ctx
Lifecycle writes to backend only         Lifecycle also writes local blueprint
Slack doesn't know about lifecycle       Slack sees lifecycle summary in ctx
No cross-thread awareness                Thread index shows sibling activity
flush_memories = per-session             post_turn = writes to shared context
Honcho = optional external service       Replaced by workspace context layer
```

### 4.8 Token Budget

The workspace context injected into `system_message` must be bounded:

```
Component          Target       Notes
─────────────────  ───────────  ────────────────────────────────────────
Blueprint summary  ~1,000 tok   Condensed from full JSON by lifecycle
Thread index       ~500 tok     1-2 sentences * ~5 active threads
Learnings          ~1,500 tok   ~20 most relevant entries
Pending work       ~500 tok     Active items only
─────────────────  ───────────  ────────────────────────────────────────
TOTAL              ~3,500 tok   <3% of 128K context window

For comparison, the existing system prompt is already ~2-4K tokens
(identity + memory + skills + context files). This roughly doubles it.
Still well within prefix-cache-friendly territory.
```

---

## 5. Summary — Current vs Target

```
┌────────────────────────┬──────────────────────┬──────────────────────────────┐
│                        │ CURRENT              │ TARGET                       │
├────────────────────────┼──────────────────────┼──────────────────────────────┤
│ Web chat               │ Fake (raw LLM)       │ Real AIAgent, same as Slack  │
│ Shared context         │ None                 │ Workspace context (SQLite)   │
│ Cross-thread awareness │ None                 │ Thread index in system prompt│
│ Memory model           │ MEMORY.md (tiny)     │ Structured learnings table   │
│ Lifecycle results      │ Trapped in backend   │ Blueprint in shared context  │
│ Cron job context       │ Zero (prompt only)   │ Full workspace context       │
│ New processes          │ N/A                  │ None — just functions         │
│ AIAgent changes        │ N/A                  │ None — uses existing params   │
│ Token overhead         │ N/A                  │ ~3.5K tokens in system prompt│
│ "One mind" feeling     │ No                   │ Yes                          │
└────────────────────────┴──────────────────────┴──────────────────────────────┘
```

---

## 6. Implementation Status

### Done (workspace context layer)

| File | Change |
|------|--------|
| `workspace_context.py` (new) | Shared SQLite storage: blueprint, thread_index, learnings, pending_work. `load()`, `to_system_prompt()`, `post_turn_update()`. |
| `gateway/run.py` | `_run_agent()` loads workspace context before `run_conversation`, writes thread summary after. |
| `cron/scheduler.py` | `run_job()` loads workspace context into `system_message`, writes back after. |
| `lifecycle/runner.py` | All `_ask_agent()` calls pass workspace context. Blueprint, proposals, and execution results written to shared store. |
| `deploy/e2b-template/kai_chat_server.py` | Replaced toy urllib chat with real AIAgent + tools + MCP + workspace context. Same HTTP contract. |

### Next: Unified Onboarding Flow

The workspace context layer is the foundation. The next step is the onboarding lifecycle:

1. **Agent provisioned** → fresh workspace, empty context
2. **Onboarding flow** → agent walks user through connecting integrations (GitHub, Slack, Jira, Linear)
3. **First blueprint** → agent scans integrations, builds initial workspace context
4. **Lifecycle starts** → daily cycle registered, autonomous work begins
5. **Every session** → reads full workspace context, Kai knows everything from day one
6. **Conflict resolution** → if user asks something that contradicts lifecycle tasks, agent flags the conflict, resolves it, and adjusts pending work accordingly
