#!/usr/bin/env python3
"""
Kai Agent Chat Server — HTTP server for E2B sandbox.

Handles /chat and /health endpoints. Unlike the previous version, this uses
a real AIAgent with full tool/MCP/memory support and shared workspace context.

API contract (unchanged from previous version):
  POST /chat  {message, threadId}  → {response, threadId, toolsUsed}
  GET  /health                     → {status: "ok", agent: "kai"}
"""
import atexit
import json
import logging
import os
import signal
import sys
import time
import traceback
import http.server
from pathlib import Path

from kai_env import kai_home, get_env

# ---------------------------------------------------------------------------
# Environment setup — all config comes from env vars injected by backend
# ---------------------------------------------------------------------------

HERMES_HOME = kai_home()
AGENT_ID = os.getenv("AGENT_ID", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("kai")

# Add agent code to path — in E2B sandbox layout:
#   /home/user/kai_chat_server.py  (this file)
#   /home/user/kai-agent/          (agent code, copied by Dockerfile)
_project_root = Path(__file__).parent / "kai-agent"
if _project_root.exists():
    sys.path.insert(0, str(_project_root))

# ---------------------------------------------------------------------------
# Secrets — fetched from backend on startup and on /secrets-updated notify
# ---------------------------------------------------------------------------

_backend_client = None


def _get_backend_client():
    global _backend_client
    if _backend_client is None:
        try:
            from lifecycle.client import KaiBackendClient
            _backend_client = KaiBackendClient()
        except Exception as e:
            log.warning("Failed to init backend client: %s", e)
    return _backend_client


def load_secrets():
    """Fetch secrets from backend and inject into os.environ."""
    if not AGENT_ID:
        log.debug("No AGENT_ID, skipping secrets fetch")
        return
    client = _get_backend_client()
    if not client:
        return
    secrets = client.fetch_secrets(AGENT_ID)
    for key, value in secrets.items():
        os.environ[key] = value
    if secrets:
        log.info("Loaded %d secrets into environment", len(secrets))


# ---------------------------------------------------------------------------
# Chat system prompt — instructs the agent to behave as a user-facing assistant
# ---------------------------------------------------------------------------

CHAT_SYSTEM_PROMPT = """You are Dash, an autonomous PM agent that manages product teams. You deliver daily briefs, surface action items, and connect signals across tools like GitHub, Linear, and PostHog.

## RESPONSE RULES
- Never expose internal details: no database errors, stack traces, file paths, env vars, or infrastructure specifics.
- If something fails internally, say "I ran into an issue" — never show raw error messages.
- Never mention MongoDB, Redis, FastAPI, E2B, sandbox internals, or backend architecture.
- Respond conversationally, concisely, and actionably — like a knowledgeable colleague.

## HOW TO DO SECURITY SCANS
You have access to a full security scanning infrastructure via MCP tools. NEVER do manual security analysis (grepping for vulnerabilities, reading source files to find bugs). Instead:

1. **Always use the proper scan tools**: `start_security_scan`, `list_scan_tiers`, `get_security_scan_details`, etc.
2. **Scans cost credits**. Before proposing a scan:
   - Check credits with `check_workspace_credits`
   - Tell the user the estimated cost and what tier you recommend
   - Wait for user confirmation before calling `start_security_scan`
3. **For autonomous/daily cycles**: Create a lifecycle action (type: "security_scan") with `lifecycle_actions_create` and let the user approve it from the dashboard. **Always include actionConfig with tierId**:
   - First call `list_scan_tiers` to get available tiers
   - Pick the most appropriate tier (usually the first/default one)
   - Set `actionConfig: { tierId: "<tier_id>" }` when creating the action
   - Also set `repoId` and `repoName` so the scan knows which repo to target
4. **After a scan completes**: Use `list_vulnerabilities` and the vulnerability-triage skill to analyze findings, then create GitHub/Jira issues for verified vulnerabilities.
5. **Monitor running scans** with `get_security_scan_details` and `get_scan_progress_logs` — share progress updates with the user.

## HOW TO DO CODE EVOLUTIONS
Evolutions use AI to optimize code (make it faster, use less memory, etc.). They are cheaper than scans.

1. Use `start_evolutionary_coding` with proper scopes (file path + line range) and config.
2. You can start evolutions directly when the user asks — no approval gate needed.
3. Before starting: analyze the target code with `browse_repository_files` / `read_repository_files` to choose good scopes and understand what to optimize.
4. Check if evaluators exist with `list_code_evaluators`. Create one with `create_ai_evaluator` if needed.
5. Monitor with `get_code_generation_progress` and `get_evolution_iterations`.
6. Report results: show before/after metrics, explain what changed, note trade-offs.

## WHAT YOU CAN DO
- **Security scans**: Find real vulnerabilities with execution-based verification (zero false positives)
- **Code evolution**: Optimize code for performance, memory, gas efficiency with benchmarks
- **Vulnerability triage**: Research and contextualize findings with CVE references and fix guidance
- **Pattern detection**: Spot systemic risks (commit velocity anomalies, code drift, dependency risks)
- **Issue creation**: File GitHub issues or Jira tickets directly for findings
- **Workspace management**: Add/remove repos, check billing, manage integrations

## VISUALIZATIONS & CHARTS
When presenting data that benefits from visualization (scan results, trends, comparisons, distributions), output a chart using a fenced code block with the `chart` language tag:

```chart
{
  "type": "bar",
  "title": "Vulnerabilities by Severity",
  "xKey": "severity",
  "yKeys": ["count"],
  "data": [
    {"severity": "Critical", "count": 3},
    {"severity": "High", "count": 7},
    {"severity": "Medium", "count": 12},
    {"severity": "Low", "count": 5}
  ]
}
```

Supported chart types: "bar", "line", "area", "pie".
- For bar/line/area: use `xKey` for the x-axis field and `yKeys` for one or more numeric fields.
- For pie: use `nameKey` and `valueKey`.
- Always include a descriptive `title`.
- Use charts for: severity distributions, scan trends over time, credit usage, code quality metrics, evolution fitness progress.
- Keep data concise (max ~20 data points) for readability.

## STATUS REPORTS & BRIEFINGS
When the user asks for a status report, workspace summary, or "what's going on":
1. Load the `workspace-report` skill via `skill_view`
2. Follow the skill steps to gather data and generate the report
3. Save the briefing via `save_workspace_briefing` so it appears on the dashboard
4. Present the report to the user in chat with charts when relevant

## WHAT YOU SHOULD NOT DO
- Do not manually grep source code looking for vulnerabilities — use the scan infrastructure
- Do not analyze the kai-agent's own source code — that's not the user's codebase
- Do not run pip install, bandit, semgrep, or other local tools — the scan executor handles this properly
- Do not propose actions without explaining the cost/benefit to the user
"""

# ---------------------------------------------------------------------------
# Session store — SQLite-backed via SessionDB for persistence across restarts
# ---------------------------------------------------------------------------

_session_db = None
_sessions_history = {}  # thread_id → list of message dicts


def _get_session_db():
    """Lazy-init the session DB."""
    global _session_db
    if _session_db is None:
        try:
            from kai_state import SessionDB
            _session_db = SessionDB()
        except Exception as e:
            log.warning("SessionDB init failed, using in-memory sessions: %s", e)
    return _session_db


# ---------------------------------------------------------------------------
# Agent creation
# ---------------------------------------------------------------------------

def _create_agent(session_id: str, token_callback=None, tool_progress_callback=None):
    """Create a real AIAgent with full capabilities."""
    from run_agent import AIAgent

    model = os.getenv("LLM_MODEL") or get_env("KAI_MODEL") or "anthropic/claude-opus-4-6"

    # Load config
    cfg = {}
    try:
        import yaml
        cfg_path = HERMES_HOME / "config.yaml"
        if cfg_path.exists():
            with open(cfg_path) as f:
                cfg = yaml.safe_load(f) or {}
            model_cfg = cfg.get("model", {})
            if isinstance(model_cfg, str):
                model = model_cfg
            elif isinstance(model_cfg, dict):
                model = model_cfg.get("default", model)
    except Exception as e:
        log.warning("Config load failed: %s", e)

    # Resolve provider
    try:
        from kai_cli.runtime_provider import resolve_runtime_provider
        runtime = resolve_runtime_provider(requested=get_env("KAI_INFERENCE_PROVIDER"))
    except Exception:
        # Fallback to OpenRouter direct
        runtime = {
            "api_key": os.getenv("OPENROUTER_API_KEY", ""),
            "base_url": "https://openrouter.ai/api/v1",
            "provider": "openrouter",
            "api_mode": "chat_completions",
        }

    max_iterations = cfg.get("agent", {}).get("max_turns") or 30  # Lower for web chat

    # Create state reporter for backend telemetry
    _state_reporter = None
    try:
        from agent.state_reporter import StateReporter
        _state_reporter = StateReporter()
        _state_reporter.start()
    except Exception:
        pass  # StateReporter is optional

    return AIAgent(
        model=model,
        api_key=runtime.get("api_key"),
        base_url=runtime.get("base_url"),
        provider=runtime.get("provider"),
        api_mode=runtime.get("api_mode"),
        max_iterations=max_iterations,
        quiet_mode=True,
        session_id=session_id,
        session_db=_get_session_db(),
        platform="web",
        token_callback=token_callback,
        tool_progress_callback=tool_progress_callback,
        state_reporter=_state_reporter,
    )


# ---------------------------------------------------------------------------
# Auth — verify Basic auth from backend using BACKEND_INTERNAL_AUTH_SECRET
# ---------------------------------------------------------------------------

_SANDBOX_AUTH_SECRET = os.getenv("BACKEND_INTERNAL_AUTH_SECRET", "")
_JWT_SECRET = os.getenv("JWT_SECRET", "")


def _verify_backend_auth(headers) -> bool:
    """Verify Basic auth header matches the sandbox auth secret."""
    if not _SANDBOX_AUTH_SECRET:
        return False
    auth = headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    import base64
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        _, secret = decoded.split(":", 1)
        return secret == _SANDBOX_AUTH_SECRET
    except Exception:
        return False


def _verify_chat_token(headers) -> bool:
    """Verify Bearer JWT token for direct client-to-sandbox chat requests."""
    if not _JWT_SECRET:
        return True  # No secret configured — skip auth (dev mode)
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    token = auth[7:]
    try:
        import jwt
        payload = jwt.decode(token, _JWT_SECRET, algorithms=["HS256"], options={"require": ["exp", "iss"]})
        return payload.get("iss") == "chat-session"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class ChatHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self._json_response(200, {"status": "ok", "agent": "kai"})
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_POST(self):
        if self.path == "/secrets-updated":
            if not _verify_backend_auth(self.headers):
                self._json_response(401, {"error": "Unauthorized"})
                return
            try:
                load_secrets()
                self._json_response(200, {"ok": True})
            except Exception as e:
                log.error("Failed to reload secrets: %s", e)
                self._json_response(500, {"error": str(e)[:200]})
            return

        if self.path == "/chat/stream":
            if not _verify_chat_token(self.headers):
                self._json_response(401, {"error": "Invalid or expired chat session token"})
                return
            self._handle_chat_stream()
            return

        if self.path == "/event":
            if not _verify_backend_auth(self.headers):
                self._json_response(401, {"error": "Unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}
                _ensure_event_processor()
                _event_queue.put(body)
                self._json_response(200, {"ok": True})
            except Exception as e:
                self._json_response(500, {"error": str(e)[:200]})
            return

        if self.path == "/chat":
            if not _verify_chat_token(self.headers):
                self._json_response(401, {"error": "Invalid or expired chat session token"})
                return
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}

            message = body.get("message", "")
            thread_id = body.get("threadId", "")

            if not message:
                self._json_response(400, {"error": "message required"})
                return

            try:
                session_key = thread_id or f"web_{int(time.time())}"

                # Load workspace context
                ws_prompt = None
                ws_status = None
                try:
                    from workspace_context_bridge import fetch_workspace_status, build_workspace_status_prompt, update_workspace_status
                    ws_status = fetch_workspace_status()
                    ws_prompt = build_workspace_status_prompt(ws_status) if ws_status else None
                except Exception as e:
                    log.debug("Workspace context load failed: %s", e)

                user_msg = message

                # Load or init conversation history for this thread
                if session_key not in _sessions_history:
                    _sessions_history[session_key] = []
                history = _sessions_history[session_key]

                # Create agent and run
                full_system = CHAT_SYSTEM_PROMPT + ("\n\n" + ws_prompt if ws_prompt else "")
                agent = _create_agent(session_key)
                result = agent.run_conversation(
                    user_msg,
                    system_message=full_system,
                    conversation_history=history if history else None,
                )

                response_text = result.get("final_response", "")
                if not response_text:
                    response_text = "(No response generated)"

                # Extract tool names used
                tools_used = []
                for msg in result.get("messages", []):
                    if msg.get("role") == "assistant" and msg.get("tool_calls"):
                        for tc in msg["tool_calls"]:
                            name = tc.get("function", {}).get("name", "")
                            if name and name not in tools_used:
                                tools_used.append(name)

                # Update conversation history from agent result
                _sessions_history[session_key] = result.get("messages", [])


                self._json_response(200, {
                    "response": response_text,
                    "threadId": session_key,
                    "toolsUsed": tools_used,
                })

            except Exception as e:
                log.error("Chat error: %s", e)
                traceback.print_exc()
                self._json_response(500, {"error": str(e)[:500]})
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_chat_stream(self):
        """SSE streaming endpoint — tokens arrive in real-time."""
        import queue
        import threading as _threading

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        message = body.get("message", "")
        thread_id = body.get("threadId", "")

        if not message:
            self._json_response(400, {"error": "message required"})
            return

        # SSE response headers
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        event_queue = queue.Queue()

        def token_cb(text):
            event_queue.put({"type": "text", "content": text})

        def tool_cb(name, preview, _args):
            event_queue.put({"type": "tool", "name": name, "preview": preview or ""})

        session_key = thread_id or f"web_{int(time.time())}"

        # Load workspace context
        ws_prompt = None
        try:
            from workspace_context_bridge import fetch_workspace_status, build_workspace_status_prompt
            ws_status = fetch_workspace_status()
            ws_prompt = build_workspace_status_prompt(ws_status) if ws_status else None
        except Exception:
            pass

        if session_key not in _sessions_history:
            _sessions_history[session_key] = []
        history = _sessions_history[session_key]

        result_holder = {"result": None, "error": None}

        full_system = CHAT_SYSTEM_PROMPT + ("\n\n" + ws_prompt if ws_prompt else "")

        def run_agent():
            try:
                agent = _create_agent(session_key, token_callback=token_cb, tool_progress_callback=tool_cb)
                result_holder["result"] = agent.run_conversation(
                    message,
                    system_message=full_system,
                    conversation_history=history if history else None,
                )
            except Exception as e:
                result_holder["error"] = e
            finally:
                event_queue.put(None)  # sentinel

        agent_thread = _threading.Thread(target=run_agent, daemon=True)
        agent_thread.start()

        def write_sse(data):
            try:
                self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
                self.wfile.flush()
            except Exception:
                pass

        # Drain the queue and write SSE events
        while True:
            try:
                event = event_queue.get(timeout=5)
            except queue.Empty:
                # Heartbeat to keep connection alive
                write_sse({"type": "heartbeat"})
                continue

            if event is None:
                break
            write_sse(event)

        # Final done event
        result = result_holder.get("result") or {}
        error = result_holder.get("error")

        if error:
            write_sse({"type": "error", "error": str(error)[:500]})
        else:
            response_text = result.get("final_response", "") or "(No response generated)"
            tools_used = []
            for msg in result.get("messages", []):
                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        name = tc.get("function", {}).get("name", "")
                        if name and name not in tools_used:
                            tools_used.append(name)

            _sessions_history[session_key] = result.get("messages", [])

            write_sse({
                "type": "done",
                "response": response_text,
                "threadId": session_key,
                "toolsUsed": tools_used,
            })

    def _json_response(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass


def _start_cron_ticker():
    """Start a background thread that ticks the cron scheduler every 60 seconds.

    This allows the agent to run scheduled jobs (daily lifecycle check-in, etc.)
    autonomously inside the sandbox without depending on an external trigger.
    """
    import threading

    def _ticker():
        while True:
            try:
                time.sleep(60)
                from cron.scheduler import tick
                tick(verbose=False)
            except Exception as e:
                log.debug("Cron tick error: %s", e)

    t = threading.Thread(target=_ticker, daemon=True, name="cron-ticker")
    t.start()
    log.info("Cron ticker started (60s interval)")


def _seed_default_cron_jobs():
    """Create default cron jobs on first startup (if none exist)."""
    try:
        from cron.jobs import load_jobs, create_job
        existing = load_jobs()
        if existing:
            log.info("Cron jobs already exist (%d), skipping seed", len(existing))
            return

        create_job(
            prompt="Review the workspace status. Scan connected repos for security vulnerabilities and code quality issues. Create task cards for any findings. Send a brief daily summary.",
            schedule="0 9 * * *",
            name="Daily workspace health check",
        )
        create_job(
            prompt="Run a comprehensive security and code quality analysis on all connected repositories. Create detailed task cards with priority levels for each finding. Include recommendations.",
            schedule="0 10 * * 1",
            name="Weekly deep scan",
        )
        log.info("Seeded 2 default cron jobs (daily health + weekly scan)")
    except Exception as e:
        log.warning("Failed to seed default cron jobs: %s", e)


# ---------------------------------------------------------------------------
# Event handling — receives webhook events from backend
# ---------------------------------------------------------------------------

_event_queue = None
_event_thread = None


def _process_event_queue():
    """Sequential event processor to avoid concurrent agent runs."""
    import queue as _q
    while True:
        event = _event_queue.get()
        if event is None:
            break
        try:
            event_type = event.get("event", "unknown")
            payload = event.get("payload", {})
            prompt = _build_event_prompt(event_type, payload)
            if prompt:
                session_key = f"event_{event_type}_{int(time.time())}"
                agent = _create_agent(session_key)
                agent.run_conversation(prompt)
                log.info("Processed %s event", event_type)
        except Exception as e:
            log.error("Event processing error: %s", e)


def _build_event_prompt(event_type: str, payload: dict) -> str:
    """Convert a GitHub webhook event into an agent prompt."""
    repo = payload.get("repository", {}).get("full_name", "unknown")

    if event_type == "push":
        ref = payload.get("ref", "")
        pusher = payload.get("pusher", {}).get("name", "unknown")
        commits = payload.get("commits", [])
        commit_summaries = "\n".join(
            f"- {c.get('message', '').split(chr(10))[0]}" for c in commits[:10]
        )
        return (
            f"New commits pushed to {repo} on {ref} by {pusher}.\n\n"
            f"Commits:\n{commit_summaries}\n\n"
            "Review the changes and determine if any action is needed. "
            "Create task cards for anything significant."
        )

    if event_type == "pull_request":
        action = payload.get("action", "")
        pr = payload.get("pull_request", {})
        number = pr.get("number", "?")
        title = pr.get("title", "")
        user = pr.get("user", {}).get("login", "unknown")
        body = (pr.get("body", "") or "")[:500]
        return (
            f"PR #{number} '{title}' was {action} on {repo} by {user}.\n\n"
            f"Description: {body}\n\n"
            "Review the PR and provide feedback. Create a task card if action is needed."
        )

    if event_type == "issues":
        action = payload.get("action", "")
        issue = payload.get("issue", {})
        number = issue.get("number", "?")
        title = issue.get("title", "")
        user = issue.get("user", {}).get("login", "unknown")
        body = (issue.get("body", "") or "")[:500]
        return (
            f"Issue #{number} '{title}' was {action} on {repo} by {user}.\n\n"
            f"Body: {body}\n\n"
            "Analyze this issue and determine if any action is needed. "
            "Create a task card to track it."
        )

    return ""


def _ensure_event_processor():
    """Start the event processor thread if not already running."""
    import queue as _q
    import threading as _t
    global _event_queue, _event_thread
    if _event_queue is None:
        _event_queue = _q.Queue()
        _event_thread = _t.Thread(target=_process_event_queue, daemon=True, name="event-processor")
        _event_thread.start()
        log.info("Event processor started")


def _on_shutdown(reason="destroyed"):
    """Notify backend that this agent sandbox is shutting down."""
    agent_id = os.getenv("AGENT_ID")
    if not agent_id:
        return
    try:
        from lifecycle.client import KaiBackendClient
        client = KaiBackendClient()
        client.finalize_agent(agent_id, reason)
    except Exception as e:
        log.warning("Failed to finalize agent on shutdown: %s", e)


class ThreadingChatServer(http.server.ThreadingHTTPServer):
    """Threaded HTTP server so long-running /chat requests don't block /health or new requests."""
    daemon_threads = True


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = ThreadingChatServer(("0.0.0.0", port), ChatHandler)

    # Register shutdown hooks to finalize agent on exit
    atexit.register(lambda: _on_shutdown("destroyed"))
    signal.signal(signal.SIGTERM, lambda *_: (_on_shutdown("destroyed"), sys.exit(0)))

    # Fetch user-managed secrets from backend and load into os.environ
    try:
        load_secrets()
    except Exception as e:
        log.warning("Initial secrets load failed: %s", e)

    # Start cron ticker so the agent can run scheduled jobs autonomously
    try:
        _start_cron_ticker()
    except Exception as e:
        log.warning("Cron ticker failed to start: %s", e)

    # Seed default cron jobs on first startup (daily health check, weekly scan)
    try:
        _seed_default_cron_jobs()
    except Exception as e:
        log.warning("Cron seed failed: %s", e)

    # Run the daily health check immediately on first startup (background thread)
    try:
        import threading as _t
        def _initial_health_check():
            time.sleep(5)  # brief delay for server to be fully ready
            try:
                session_key = f"startup_{int(time.time())}"
                agent = _create_agent(session_key)
                agent.run_conversation(
                    "Review the workspace status. Scan connected repos for security vulnerabilities "
                    "and code quality issues. Create task cards for any findings. Send a brief summary."
                )
                log.info("Initial health check completed")
            except Exception as e:
                log.warning("Initial health check failed: %s", e)
        _t.Thread(target=_initial_health_check, daemon=True, name="initial-health-check").start()
        log.info("Initial health check scheduled")
    except Exception as e:
        log.warning("Failed to schedule initial health check: %s", e)

    # Start event processor for GitHub webhook events
    try:
        _ensure_event_processor()
    except Exception as e:
        log.warning("Event processor failed to start: %s", e)

    log.info("Kai chat server (real agent) on port %d", port)
    server.serve_forever()
