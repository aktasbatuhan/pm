"""
Dash PM API Server — serves brief, workspace, and chat endpoints.
Run: python server.py (port 3001)
Next.js dev server proxies /api/* here.
"""

import asyncio
import json
import logging
import os
import queue
import sys
import threading
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
_project_env = Path(__file__).parent / ".env"
if _project_env.exists():
    load_dotenv(dotenv_path=_project_env)

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from starlette.middleware.cors import CORSMiddleware

import sqlite3
from kai_env import kai_home
from workspace_context import load_workspace_context
from tools.pm_brief_tools import _get_db

# ── Integrations DB ────────────────────────────────────────────────────

_INTEGRATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS integrations (
    platform TEXT PRIMARY KEY,
    auth_type TEXT NOT NULL,
    credentials TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    display_name TEXT,
    connected_at REAL,
    last_verified REAL
);
CREATE TABLE IF NOT EXISTS onboarding_profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

def _get_integrations_db():
    home = kai_home()
    db_path = home / "integrations.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10.0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(_INTEGRATIONS_SCHEMA)
    return db

import hashlib
import secrets

logger = logging.getLogger(__name__)

app = FastAPI(title="Dash PM API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── Auth ───────────────────────────────────────────────────────────────

def _get_auth_db():
    db = _get_integrations_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS auth (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    return db


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


@app.post("/api/auth/setup")
async def auth_setup(request: Request):
    """First-time password setup. Only works if no password exists yet."""
    body = await request.json()
    password = body.get("password", "")
    if not password or len(password) < 4:
        return JSONResponse({"error": "Password must be at least 4 characters"}, status_code=400)

    db = _get_auth_db()
    existing = db.execute("SELECT value FROM auth WHERE key = 'password_hash'").fetchone()
    if existing:
        return JSONResponse({"error": "Password already set. Use /api/auth/login instead."}, status_code=409)

    token = secrets.token_hex(32)
    db.execute("INSERT INTO auth (key, value) VALUES ('password_hash', ?)", (_hash_password(password),))
    db.execute("INSERT OR REPLACE INTO auth (key, value) VALUES ('session_token', ?)", (token,))
    db.commit()
    return {"ok": True, "token": token}


@app.post("/api/auth/login")
async def auth_login(request: Request):
    """Login with password, returns session token."""
    body = await request.json()
    password = body.get("password", "")

    db = _get_auth_db()
    row = db.execute("SELECT value FROM auth WHERE key = 'password_hash'").fetchone()
    if not row:
        return JSONResponse({"error": "No password set. Use /api/auth/setup first."}, status_code=404)

    if _hash_password(password) != row["value"]:
        return JSONResponse({"error": "Wrong password"}, status_code=401)

    token = secrets.token_hex(32)
    db.execute("INSERT OR REPLACE INTO auth (key, value) VALUES ('session_token', ?)", (token,))
    db.commit()
    return {"ok": True, "token": token}


@app.get("/api/auth/check")
def auth_check(request: Request):
    """Check if a session token is valid. Also returns whether a password has been set."""
    db = _get_auth_db()
    has_password = db.execute("SELECT value FROM auth WHERE key = 'password_hash'").fetchone() is not None

    auth_header = request.headers.get("authorization", "")
    token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""

    if not has_password:
        return {"authenticated": False, "needs_setup": True}

    if not token:
        return {"authenticated": False, "needs_setup": False}

    stored = db.execute("SELECT value FROM auth WHERE key = 'session_token'").fetchone()
    valid = stored and stored["value"] == token
    return {"authenticated": valid, "needs_setup": False}

_sessions: dict = {}

# ── Changelog + Goals DB ───────────────────────────────────────────────

def _ensure_pm_tables():
    db = _get_integrations_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS changelogs (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            period_start REAL,
            period_end REAL,
            pr_count INTEGER DEFAULT 0,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS goals (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            target_date TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            progress INTEGER DEFAULT 0,
            trajectory TEXT,
            related_items TEXT DEFAULT '[]',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS team_pulse (
            id TEXT PRIMARY KEY,
            member_name TEXT NOT NULL,
            github_handle TEXT,
            prs_merged INTEGER DEFAULT 0,
            reviews_done INTEGER DEFAULT 0,
            days_since_active INTEGER DEFAULT 0,
            flags TEXT DEFAULT '[]',
            period TEXT,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS signal_sources (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            config TEXT NOT NULL DEFAULT '{}',
            filter TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_fetched_at REAL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            title TEXT,
            body TEXT,
            url TEXT,
            author TEXT,
            relevance_score REAL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'new',
            metadata TEXT DEFAULT '{}',
            external_created_at REAL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_signals_source ON signals(source_id);
        CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
        CREATE TABLE IF NOT EXISTS report_templates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            body TEXT NOT NULL,
            resources TEXT NOT NULL DEFAULT '{}',
            schedule TEXT DEFAULT 'none',
            cron_job_id TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY,
            template_id TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reports_template ON reports(template_id);
        CREATE INDEX IF NOT EXISTS idx_reports_created ON reports(created_at DESC);
    """)
    return db

_ensure_pm_tables()


def _ws_id():
    return os.environ.get("KAI_WORKSPACE_ID") or os.environ.get("HERMES_WORKSPACE_ID") or "default"


@app.get("/api/brief/latest")
def brief_latest():
    db = _get_db()
    row = db.execute("SELECT * FROM briefs ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        return {"brief": None}
    actions = db.execute(
        "SELECT * FROM brief_actions WHERE brief_id = ? ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'in-progress' THEN 1 ELSE 2 END, created_at",
        (row["id"],)
    ).fetchall()
    items = []
    for a in actions:
        item = dict(a)
        # Parse references JSON
        try:
            item["references"] = json.loads(item.get("references_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            item["references"] = []
        item.pop("references_json", None)
        items.append(item)
    # Get optional columns
    cover_url = ""
    suggested_prompts = []
    try:
        cover_url = row["cover_url"] or ""
    except (IndexError, KeyError):
        pass
    try:
        suggested_prompts = json.loads(row["suggested_prompts"] or "[]")
    except (IndexError, KeyError, json.JSONDecodeError):
        pass

    return {
        "brief": {
            "id": row["id"],
            "summary": row["summary"],
            "data_sources": row["data_sources"],
            "created_at": row["created_at"],
            "cover_url": cover_url,
            "suggested_prompts": suggested_prompts,
            "action_items": items,
        }
    }


@app.get("/api/brief/{brief_id}")
def get_brief(brief_id: str):
    db = _get_db()
    row = db.execute("SELECT * FROM briefs WHERE id = ?", (brief_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "Not found"}, status_code=404)
    actions = db.execute(
        "SELECT * FROM brief_actions WHERE brief_id = ? ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'in-progress' THEN 1 ELSE 2 END, created_at",
        (brief_id,)
    ).fetchall()
    items = []
    for a in actions:
        item = dict(a)
        try:
            item["references"] = json.loads(item.get("references_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            item["references"] = []
        item.pop("references_json", None)
        items.append(item)
    cover_url = ""
    suggested_prompts = []
    try:
        cover_url = row["cover_url"] or ""
    except (IndexError, KeyError):
        pass
    try:
        suggested_prompts = json.loads(row["suggested_prompts"] or "[]")
    except (IndexError, KeyError, json.JSONDecodeError):
        pass
    return {
        "brief": {
            "id": row["id"],
            "summary": row["summary"],
            "data_sources": row["data_sources"],
            "created_at": row["created_at"],
            "cover_url": cover_url,
            "suggested_prompts": suggested_prompts,
            "action_items": items,
        }
    }


@app.get("/api/briefs")
def list_briefs(limit: int = 20):
    db = _get_db()
    rows = db.execute("SELECT id, summary, data_sources, created_at FROM briefs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    briefs = []
    for row in rows:
        r = dict(row)
        # Count actions
        action_count = db.execute("SELECT COUNT(*) as c FROM brief_actions WHERE brief_id = ?", (r["id"],)).fetchone()
        pending_count = db.execute("SELECT COUNT(*) as c FROM brief_actions WHERE brief_id = ? AND status = 'pending'", (r["id"],)).fetchone()
        # Extract headline (first meaningful line)
        headline = ""
        for line in r["summary"].split("\n"):
            stripped = line.strip().lstrip("#").lstrip("-").strip()
            if len(stripped) > 20 and not stripped.startswith("```"):
                headline = stripped[:120]
                break
        # Get cover + prompts
        cover_url = ""
        try:
            full = db.execute("SELECT cover_url FROM briefs WHERE id = ?", (r["id"],)).fetchone()
            cover_url = full["cover_url"] or ""
        except Exception:
            pass
        briefs.append({
            "id": r["id"],
            "headline": headline,
            "data_sources": r["data_sources"],
            "created_at": r["created_at"],
            "cover_url": cover_url,
            "action_count": action_count["c"] if action_count else 0,
            "pending_count": pending_count["c"] if pending_count else 0,
        })
    return {"briefs": briefs}


@app.get("/api/brief/actions")
def brief_actions(status: str = "pending"):
    db = _get_db()
    if status == "all":
        rows = db.execute("SELECT * FROM brief_actions ORDER BY created_at DESC LIMIT 50").fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM brief_actions WHERE status = ? ORDER BY created_at DESC LIMIT 50", (status,)
        ).fetchall()
    return {"actions": [dict(r) for r in rows]}


@app.post("/api/brief/actions/{action_id}")
async def brief_action_update(action_id: str, request: Request):
    body = await request.json()
    db = _get_db()
    row = db.execute("SELECT * FROM brief_actions WHERE id = ?", (action_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "Not found"}, status_code=404)
    new_status = body.get("status", "resolved")
    db.execute("UPDATE brief_actions SET status = ?, updated_at = ? WHERE id = ?",
               (new_status, time.time(), action_id))
    db.commit()
    return {"ok": True, "action_id": action_id, "status": new_status}


# ── Waitlist ────────────────────────────────────────────────────────────

@app.post("/api/waitlist")
async def waitlist_submit(request: Request):
    body = await request.json()
    db = _get_integrations_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS waitlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT NOT NULL,
            organization TEXT,
            role TEXT,
            team_size TEXT,
            pain_point TEXT,
            submitted_at REAL NOT NULL
        )
    """)
    db.execute(
        "INSERT INTO waitlist (name, email, organization, role, team_size, pain_point, submitted_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            body.get("name", ""),
            body.get("email", ""),
            body.get("organization", ""),
            body.get("role", ""),
            body.get("team_size", ""),
            body.get("pain_point", ""),
            time.time(),
        ),
    )
    db.commit()
    logger.info(
        "Waitlist submission: %s <%s> from %s (%s, %s)",
        body.get("name", ""), body.get("email", ""), body.get("organization", ""),
        body.get("role", ""), body.get("team_size", ""),
    )
    return {"ok": True}


@app.get("/api/waitlist/list")
def waitlist_list(request: Request):
    """Admin endpoint — requires auth token."""
    db = _get_auth_db()
    auth_header = request.headers.get("authorization", "")
    token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""
    stored = db.execute("SELECT value FROM auth WHERE key = 'session_token'").fetchone()
    if not stored or stored["value"] != token:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    rows = db.execute("SELECT * FROM waitlist ORDER BY submitted_at DESC").fetchall()
    return {"waitlist": [dict(r) for r in rows]}


# ── Onboarding endpoints ───────────────────────────────────────────────

@app.get("/api/onboarding/profile")
def get_onboarding_profile():
    db = _get_integrations_db()
    rows = db.execute("SELECT key, value FROM onboarding_profile").fetchall()
    return {r["key"]: r["value"] for r in rows}


@app.post("/api/onboarding/profile")
async def save_onboarding_profile(request: Request):
    body = await request.json()
    db = _get_integrations_db()
    for key, value in body.items():
        db.execute(
            "INSERT INTO onboarding_profile (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(key), str(value)),
        )
    db.commit()
    return {"ok": True}


@app.get("/api/integrations")
def list_integrations():
    db = _get_integrations_db()
    rows = db.execute("SELECT * FROM integrations ORDER BY connected_at DESC").fetchall()
    items = []
    for r in rows:
        item = dict(r)
        # Never return raw credentials
        item["credentials"] = "••••" + str(item.get("credentials", ""))[-4:]
        items.append(item)
    return {"integrations": items}


@app.post("/api/integrations/{platform}")
async def connect_integration(platform: str, request: Request):
    body = await request.json()
    auth_type = body.get("auth_type", "token")  # token, oauth, api_key
    credentials = body.get("credentials", "")
    display_name = body.get("display_name", platform)

    if not credentials:
        return JSONResponse({"error": "credentials required"}, status_code=400)

    # Validate the credential
    valid, message = _validate_integration(platform, auth_type, credentials)

    db = _get_integrations_db()
    now = time.time()
    status = "connected" if valid else "invalid"
    db.execute(
        "INSERT INTO integrations (platform, auth_type, credentials, status, display_name, connected_at, last_verified) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(platform) DO UPDATE SET auth_type=excluded.auth_type, credentials=excluded.credentials, "
        "status=excluded.status, display_name=excluded.display_name, connected_at=excluded.connected_at, last_verified=excluded.last_verified",
        (platform, auth_type, credentials, status, display_name, now, now),
    )
    db.commit()

    # If valid, also inject into the environment for the agent to use
    if valid:
        _inject_credential(platform, credentials)

    return {"ok": valid, "status": status, "message": message}


@app.delete("/api/integrations/{platform}")
def disconnect_integration(platform: str):
    db = _get_integrations_db()
    db.execute("DELETE FROM integrations WHERE platform = ?", (platform,))
    db.commit()
    return {"ok": True}


@app.post("/api/onboarding/complete")
async def complete_onboarding(request: Request):
    """Trigger the agent scan after onboarding form is done."""
    body = await request.json()
    org = body.get("organization", "")

    # Mark workspace as in_progress
    from workspace_context_bridge import update_workspace_status
    update_workspace_status(_ws_id(), "in_progress", "scanning")

    return {"ok": True, "message": "Onboarding started. Use /api/chat to trigger the agent scan."}


def _validate_integration(platform: str, auth_type: str, credentials: str) -> tuple:
    """Validate a platform credential. Returns (valid, message)."""
    import urllib.request
    import urllib.error

    if platform == "github":
        try:
            req = urllib.request.Request(
                "https://api.github.com/user",
                headers={"Authorization": f"token {credentials}", "User-Agent": "DashPM"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                return True, f"Connected as {data.get('login', 'unknown')}"
        except urllib.error.HTTPError as e:
            return False, f"GitHub auth failed: {e.code}"
        except Exception as e:
            return False, f"GitHub connection error: {e}"

    if platform == "linear":
        try:
            req = urllib.request.Request(
                "https://api.linear.app/graphql",
                data=json.dumps({"query": "{ viewer { id name } }"}).encode(),
                headers={"Authorization": credentials, "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                name = data.get("data", {}).get("viewer", {}).get("name", "unknown")
                return True, f"Connected as {name}"
        except Exception as e:
            return False, f"Linear auth failed: {e}"

    if platform == "posthog":
        # PostHog personal API keys start with phx_
        if credentials.startswith("phx_") or credentials.startswith("phc_"):
            return True, "API key format looks valid"
        return False, "Expected PostHog API key (phx_... or phc_...)"

    if platform == "slack":
        try:
            req = urllib.request.Request(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {credentials}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                if data.get("ok"):
                    return True, f"Connected to {data.get('team', 'unknown')}"
                return False, f"Slack auth failed: {data.get('error', 'unknown')}"
        except Exception as e:
            return False, f"Slack connection error: {e}"

    # Unknown platform — accept anything
    return True, "Saved"


def _inject_credential(platform: str, credentials: str):
    """Inject a validated credential into the runtime environment."""
    env_map = {
        "github": "GITHUB_TOKEN",
        "linear": "LINEAR_API_KEY",
        "posthog": "POSTHOG_API_KEY",
        "slack": "SLACK_BOT_TOKEN",
    }
    env_var = env_map.get(platform)
    if env_var:
        os.environ[env_var] = credentials


# ── Changelog endpoints ────────────────────────────────────────────────

@app.get("/api/changelogs")
def list_changelogs(limit: int = 10):
    db = _ensure_pm_tables()
    rows = db.execute("SELECT * FROM changelogs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return {"changelogs": [dict(r) for r in rows]}


@app.get("/api/changelogs/latest")
def latest_changelog():
    db = _ensure_pm_tables()
    row = db.execute("SELECT * FROM changelogs ORDER BY created_at DESC LIMIT 1").fetchone()
    return {"changelog": dict(row) if row else None}


@app.post("/api/changelogs")
async def create_changelog(request: Request):
    body = await request.json()
    db = _ensure_pm_tables()
    changelog_id = str(uuid.uuid4())[:8]
    now = time.time()
    db.execute(
        "INSERT INTO changelogs (id, content, period_start, period_end, pr_count, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (changelog_id, body.get("content", ""), body.get("period_start", now - 604800),
         body.get("period_end", now), body.get("pr_count", 0), now),
    )
    db.commit()
    return {"ok": True, "id": changelog_id}


@app.post("/api/changelogs/generate")
def generate_changelog():
    triggerBackgroundTask(
        "Generate a changelog of what shipped recently. Use gh CLI to list merged PRs from the last 7 days across all repos. "
        "Group by feature area (not by repo). Write clean, user-facing prose — strip internal jargon, PR numbers as references. "
        "Store the result using a POST to /api/changelogs with the content, period_start, period_end, and pr_count. "
        "Actually, just use the terminal tool to call: workspace_add_learning with category 'changelog' and the full changelog content.",
        f"changelog-{int(time.time())}"
    )
    return {"ok": True, "message": "Changelog generation started"}


# ── Goals endpoints ────────────────────────────────────────────────────

@app.get("/api/goals")
def list_goals(status: str = "active"):
    db = _ensure_pm_tables()
    if status == "all":
        rows = db.execute("SELECT * FROM goals ORDER BY created_at DESC").fetchall()
    else:
        rows = db.execute("SELECT * FROM goals WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
    goals = []
    for r in rows:
        g = dict(r)
        try:
            g["related_items"] = json.loads(g.get("related_items") or "[]")
        except (json.JSONDecodeError, TypeError):
            g["related_items"] = []
        goals.append(g)
    return {"goals": goals}


@app.post("/api/goals")
async def create_goal(request: Request):
    body = await request.json()
    db = _ensure_pm_tables()
    goal_id = str(uuid.uuid4())[:8]
    now = time.time()
    db.execute(
        "INSERT INTO goals (id, title, description, target_date, status, progress, trajectory, related_items, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'active', 0, ?, '[]', ?, ?)",
        (goal_id, body.get("title", ""), body.get("description", ""),
         body.get("target_date", ""), "", now, now),
    )
    db.commit()
    return {"ok": True, "id": goal_id}


@app.patch("/api/goals/{goal_id}")
async def update_goal(goal_id: str, request: Request):
    body = await request.json()
    db = _ensure_pm_tables()
    row = db.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "Not found"}, status_code=404)
    updates = []
    params = []
    for field in ["title", "description", "target_date", "status", "progress", "trajectory", "related_items"]:
        if field in body:
            updates.append(f"{field} = ?")
            val = body[field]
            if field == "related_items" and isinstance(val, list):
                val = json.dumps(val)
            params.append(val)
    if updates:
        updates.append("updated_at = ?")
        params.append(time.time())
        params.append(goal_id)
        db.execute(f"UPDATE goals SET {', '.join(updates)} WHERE id = ?", params)
        db.commit()
    return {"ok": True}


@app.delete("/api/goals/{goal_id}")
def delete_goal(goal_id: str):
    db = _ensure_pm_tables()
    db.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    db.commit()
    return {"ok": True}


# ── Team pulse endpoints ───────────────────────────────────────────────

@app.get("/api/team/pulse")
def get_team_pulse():
    db = _ensure_pm_tables()
    rows = db.execute("SELECT * FROM team_pulse ORDER BY prs_merged DESC").fetchall()
    members = []
    for r in rows:
        m = dict(r)
        try:
            m["flags"] = json.loads(m.get("flags") or "[]")
        except (json.JSONDecodeError, TypeError):
            m["flags"] = []
        members.append(m)
    return {"members": members}


@app.post("/api/team/pulse/generate")
def generate_team_pulse():
    triggerBackgroundTask(
        "Analyze team activity for the last 7 days. Use gh CLI to check each team member in the workspace blueprint. "
        "For each person: count PRs merged, PRs reviewed, comments, and calculate days since last activity. "
        "Flag: 'quiet' if >3 days inactive, 'overloaded' if >10 PRs merged, 'bottleneck' if they have >3 PRs waiting for their review, "
        "'concentration_risk' if they own >40% of merged PRs. "
        "Save each member's data to the team_pulse table via workspace tools or terminal.",
        f"pulse-{int(time.time())}"
    )
    return {"ok": True, "message": "Team pulse analysis started"}


def triggerBackgroundTask(message: str, thread_id: str):
    """Internal helper — fires an agent task as a system session."""
    import threading as _threading
    def _run():
        try:
            from run_agent import AIAgent
            from model_tools import ensure_mcp_discovered
            ensure_mcp_discovered()
            model = os.environ.get("DASH_MODEL") or os.environ.get("KAI_MODEL") or "openai/gpt-5.4"
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
            from workspace_context_bridge import fetch_workspace_status, build_workspace_status_prompt
            ws_status = fetch_workspace_status()
            ws_prompt = build_workspace_status_prompt(ws_status) if ws_status else None
            sdb = _get_session_db()
            sdb.create_session(session_id=thread_id, source="system", model=model)
            agent = AIAgent(
                model=model, api_key=api_key, base_url=base_url, provider="openrouter",
                max_iterations=25, quiet_mode=True, platform="system",
                session_id=thread_id, ephemeral_system_prompt=ws_prompt, session_db=sdb,
            )
            agent.run_conversation(message, conversation_history=[])
        except Exception as e:
            logger.exception("Background task %s failed: %s", thread_id, e)
    _threading.Thread(target=_run, daemon=True).start()


# ── Report Templates endpoints ─────────────────────────────────────────

def _build_report_prompt(template: dict, generated_by: str = "manual") -> str:
    """Build the agent prompt to generate a report for a template."""
    resources = template.get("resources", {}) if isinstance(template.get("resources"), dict) else {}
    try:
        if isinstance(template.get("resources"), str):
            resources = json.loads(template["resources"] or "{}")
    except (json.JSONDecodeError, TypeError):
        resources = {}

    resource_instructions = []
    if resources.get("repos"):
        resource_instructions.append(f"- Repos to focus on: {', '.join(resources['repos'])}")
    if resources.get("learning_categories"):
        cats = ", ".join(resources["learning_categories"])
        resource_instructions.append(f"- Read workspace learnings with categories: {cats} using workspace_get_learnings")
    if resources.get("brief_depth"):
        depth = int(resources["brief_depth"])
        resource_instructions.append(f"- Pull the last {depth} daily briefs using brief_get_latest and brief_get_action_items")
    if resources.get("signal_sources"):
        resource_instructions.append(f"- Include recent signals from these sources: {', '.join(resources['signal_sources'])}")

    resource_block = "\n".join(resource_instructions) if resource_instructions else "- Use whatever workspace context is available"

    return (
        f"Generate a report using this template. Triggered by: {generated_by}.\n\n"
        f"Template ID: {template['id']}\n"
        f"Template name: {template['name']}\n\n"
        f"## Template content (markdown with variable placeholders)\n\n"
        f"{template['body']}\n\n"
        f"## Resources to pull\n{resource_block}\n\n"
        f"## Instructions\n"
        f"1. Read the resources above using the appropriate tools.\n"
        f"2. Replace variable placeholders in the template (like {{recent_briefs}}, {{team_activity}}, {{learnings}}, {{signals}}, {{workspace}}) with synthesized content from the actual data. Keep markdown formatting.\n"
        f"3. The final output must be ready-to-share markdown — no internal jargon, no unresolved placeholders.\n"
        f"4. Save the final content using report_save with template_id='{template['id']}' and content=<the rendered report>."
    )


@app.get("/api/reports/templates")
def list_report_templates():
    db = _ensure_pm_tables()
    rows = db.execute("SELECT * FROM report_templates ORDER BY updated_at DESC").fetchall()
    templates = []
    for r in rows:
        t = dict(r)
        try:
            t["resources"] = json.loads(t.get("resources") or "{}")
        except (json.JSONDecodeError, TypeError):
            t["resources"] = {}
        # Count reports
        count = db.execute("SELECT COUNT(*) as c FROM reports WHERE template_id = ?", (t["id"],)).fetchone()
        t["report_count"] = count["c"] if count else 0
        templates.append(t)
    return {"templates": templates}


@app.get("/api/reports/templates/{template_id}")
def get_report_template(template_id: str):
    db = _ensure_pm_tables()
    row = db.execute("SELECT * FROM report_templates WHERE id = ?", (template_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "Not found"}, status_code=404)
    t = dict(row)
    try:
        t["resources"] = json.loads(t.get("resources") or "{}")
    except (json.JSONDecodeError, TypeError):
        t["resources"] = {}
    return {"template": t}


@app.post("/api/reports/templates")
async def create_report_template(request: Request):
    body = await request.json()
    db = _ensure_pm_tables()
    template_id = str(uuid.uuid4())[:8]
    now = time.time()
    resources = body.get("resources", {})
    if not isinstance(resources, dict):
        resources = {}
    db.execute(
        "INSERT INTO report_templates (id, name, body, resources, schedule, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            template_id,
            body.get("name", "Untitled template"),
            body.get("body", ""),
            json.dumps(resources),
            body.get("schedule", "none"),
            now, now,
        ),
    )
    db.commit()
    # If a schedule is set, register a cron job
    schedule = body.get("schedule", "none")
    if schedule and schedule != "none":
        _schedule_template_cron(template_id)
    return {"ok": True, "id": template_id}


@app.patch("/api/reports/templates/{template_id}")
async def update_report_template(template_id: str, request: Request):
    body = await request.json()
    db = _ensure_pm_tables()
    row = db.execute("SELECT * FROM report_templates WHERE id = ?", (template_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "Not found"}, status_code=404)
    updates = []
    params = []
    for field in ["name", "body", "resources", "schedule"]:
        if field in body:
            updates.append(f"{field} = ?")
            val = body[field]
            if field == "resources" and isinstance(val, dict):
                val = json.dumps(val)
            params.append(val)
    if updates:
        updates.append("updated_at = ?")
        params.append(time.time())
        params.append(template_id)
        db.execute(f"UPDATE report_templates SET {', '.join(updates)} WHERE id = ?", params)
        db.commit()

    # If schedule changed, re-register cron
    if "schedule" in body:
        _unschedule_template_cron(template_id)
        if body["schedule"] and body["schedule"] != "none":
            _schedule_template_cron(template_id)

    return {"ok": True}


@app.delete("/api/reports/templates/{template_id}")
def delete_report_template(template_id: str):
    db = _ensure_pm_tables()
    _unschedule_template_cron(template_id)
    db.execute("DELETE FROM reports WHERE template_id = ?", (template_id,))
    db.execute("DELETE FROM report_templates WHERE id = ?", (template_id,))
    db.commit()
    return {"ok": True}


@app.post("/api/reports/templates/{template_id}/generate")
def generate_report(template_id: str):
    """Fire agent to generate a report from the template."""
    db = _ensure_pm_tables()
    row = db.execute("SELECT * FROM report_templates WHERE id = ?", (template_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "Template not found"}, status_code=404)
    template = dict(row)
    try:
        template["resources"] = json.loads(template.get("resources") or "{}")
    except (json.JSONDecodeError, TypeError):
        template["resources"] = {}

    prompt = _build_report_prompt(template, generated_by="manual")
    triggerBackgroundTask(prompt, f"report-{template_id}-{int(time.time())}")
    return {"ok": True, "message": "Report generation started"}


@app.get("/api/reports")
def list_reports(template_id: str = "", limit: int = 20):
    db = _ensure_pm_tables()
    if template_id:
        rows = db.execute(
            "SELECT * FROM reports WHERE template_id = ? ORDER BY created_at DESC LIMIT ?",
            (template_id, limit),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM reports ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"reports": [dict(r) for r in rows]}


@app.delete("/api/reports/{report_id}")
def delete_report(report_id: str):
    db = _ensure_pm_tables()
    db.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    db.commit()
    return {"ok": True}


def _schedule_to_cron(schedule: str) -> str:
    """Convert user-friendly schedule to cron format."""
    mapping = {
        "daily": "0 9 * * *",      # every day at 9am
        "weekly": "0 9 * * 1",     # Monday at 9am
        "monthly": "0 9 1 * *",    # 1st of month at 9am
    }
    return mapping.get(schedule, "")


def _schedule_template_cron(template_id: str):
    """Create a cron job that regenerates this template on its schedule."""
    try:
        db = _ensure_pm_tables()
        row = db.execute("SELECT * FROM report_templates WHERE id = ?", (template_id,)).fetchone()
        if not row:
            return
        template = dict(row)
        try:
            template["resources"] = json.loads(template.get("resources") or "{}")
        except (json.JSONDecodeError, TypeError):
            template["resources"] = {}

        cron_expr = _schedule_to_cron(template.get("schedule", ""))
        if not cron_expr:
            return

        prompt = _build_report_prompt(template, generated_by="scheduled")

        from cron.jobs import create_job
        job = create_job(
            prompt=prompt,
            schedule=cron_expr,
            name=f"Report: {template['name']}",
            repeat=None,   # forever
            deliver="local",
        )

        db.execute(
            "UPDATE report_templates SET cron_job_id = ? WHERE id = ?",
            (job["id"], template_id),
        )
        db.commit()
        logger.info("Scheduled cron %s for template %s", job["id"], template_id)
    except Exception as e:
        logger.exception("Failed to schedule template cron: %s", e)


def _unschedule_template_cron(template_id: str):
    """Remove the cron job linked to this template."""
    try:
        db = _ensure_pm_tables()
        row = db.execute("SELECT cron_job_id FROM report_templates WHERE id = ?", (template_id,)).fetchone()
        if not row or not row["cron_job_id"]:
            return
        from cron.jobs import remove_job
        remove_job(row["cron_job_id"])
        db.execute("UPDATE report_templates SET cron_job_id = NULL WHERE id = ?", (template_id,))
        db.commit()
    except Exception as e:
        logger.exception("Failed to unschedule template cron: %s", e)


# ── Cron Schedules endpoints ───────────────────────────────────────────

@app.get("/api/schedules")
def list_schedules():
    from cron.jobs import list_jobs
    jobs = list_jobs(include_disabled=True)
    return {"schedules": jobs}


@app.post("/api/schedules")
async def create_schedule(request: Request):
    body = await request.json()
    prompt = body.get("prompt", "").strip()
    schedule = body.get("schedule", "").strip()
    name = body.get("name", "").strip()
    if not prompt or not schedule:
        return JSONResponse({"error": "prompt and schedule required"}, status_code=400)
    from cron.jobs import create_job
    job = create_job(prompt=prompt, schedule=schedule, name=name or None, deliver="local")
    return {"ok": True, "job": job}


@app.patch("/api/schedules/{job_id}")
async def update_schedule(job_id: str, request: Request):
    body = await request.json()
    from cron.jobs import update_job
    updated = update_job(job_id, body)
    if not updated:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"ok": True}


@app.delete("/api/schedules/{job_id}")
def delete_schedule(job_id: str):
    from cron.jobs import remove_job
    ok = remove_job(job_id)
    return {"ok": ok}


# ── Signal Collector endpoints ─────────────────────────────────────────

@app.get("/api/signals/sources")
def list_signal_sources():
    db = _ensure_pm_tables()
    rows = db.execute("SELECT * FROM signal_sources ORDER BY created_at DESC").fetchall()
    sources = []
    for r in rows:
        s = dict(r)
        try:
            s["config"] = json.loads(s.get("config") or "{}")
        except (json.JSONDecodeError, TypeError):
            s["config"] = {}
        sources.append(s)
    return {"sources": sources}


@app.post("/api/signals/sources")
async def create_signal_source(request: Request):
    body = await request.json()
    db = _ensure_pm_tables()
    source_id = str(uuid.uuid4())[:8]
    now = time.time()
    db.execute(
        "INSERT INTO signal_sources (id, name, type, config, filter, enabled, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
        (
            source_id,
            body.get("name", "").strip() or "Untitled source",
            body.get("type", "exa"),
            json.dumps(body.get("config", {})),
            body.get("filter", ""),
            now,
        ),
    )
    db.commit()
    return {"ok": True, "id": source_id}


@app.patch("/api/signals/sources/{source_id}")
async def update_signal_source(source_id: str, request: Request):
    body = await request.json()
    db = _ensure_pm_tables()
    updates = []
    params = []
    for field in ["name", "type", "config", "filter", "enabled"]:
        if field in body:
            updates.append(f"{field} = ?")
            val = body[field]
            if field == "config" and isinstance(val, dict):
                val = json.dumps(val)
            if field == "enabled":
                val = 1 if val else 0
            params.append(val)
    if updates:
        params.append(source_id)
        db.execute(f"UPDATE signal_sources SET {', '.join(updates)} WHERE id = ?", params)
        db.commit()
    return {"ok": True}


@app.delete("/api/signals/sources/{source_id}")
def delete_signal_source(source_id: str):
    db = _ensure_pm_tables()
    db.execute("DELETE FROM signals WHERE source_id = ?", (source_id,))
    db.execute("DELETE FROM signal_sources WHERE id = ?", (source_id,))
    db.commit()
    return {"ok": True}


@app.get("/api/signals")
def list_signals(status: str = "all", limit: int = 50):
    db = _ensure_pm_tables()
    if status == "all":
        rows = db.execute(
            "SELECT s.*, src.name AS source_name, src.type AS source_type "
            "FROM signals s JOIN signal_sources src ON s.source_id = src.id "
            "ORDER BY s.external_created_at DESC, s.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT s.*, src.name AS source_name, src.type AS source_type "
            "FROM signals s JOIN signal_sources src ON s.source_id = src.id "
            "WHERE s.status = ? ORDER BY s.external_created_at DESC, s.created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    signals = []
    for r in rows:
        s = dict(r)
        try:
            s["metadata"] = json.loads(s.get("metadata") or "{}")
        except (json.JSONDecodeError, TypeError):
            s["metadata"] = {}
        signals.append(s)
    return {"signals": signals}


@app.post("/api/signals/{signal_id}/status")
async def update_signal_status(signal_id: str, request: Request):
    body = await request.json()
    db = _ensure_pm_tables()
    db.execute("UPDATE signals SET status = ? WHERE id = ?", (body.get("status", "read"), signal_id))
    db.commit()
    return {"ok": True}


@app.post("/api/signals/sources/{source_id}/fetch")
def fetch_signal_source(source_id: str):
    """Trigger a fetch for a specific source (or all if id='all')."""
    import threading as _threading

    def _run():
        db = _ensure_pm_tables()
        if source_id == "all":
            rows = db.execute("SELECT * FROM signal_sources WHERE enabled = 1").fetchall()
        else:
            rows = db.execute("SELECT * FROM signal_sources WHERE id = ?", (source_id,)).fetchall()

        for row in rows:
            src = dict(row)
            try:
                config = json.loads(src.get("config") or "{}")
            except (json.JSONDecodeError, TypeError):
                config = {}
            try:
                from signal_fetcher import fetch_source
                items = fetch_source(src["type"], config, src.get("filter", ""))
            except Exception as e:
                logger.exception("Fetch failed for %s: %s", src["id"], e)
                continue

            now = time.time()
            for item in items:
                # Dedupe by URL
                if item.get("url"):
                    exists = db.execute("SELECT id FROM signals WHERE url = ?", (item["url"],)).fetchone()
                    if exists:
                        continue
                sig_id = str(uuid.uuid4())[:12]
                db.execute(
                    "INSERT INTO signals (id, source_id, title, body, url, author, metadata, external_created_at, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        sig_id, src["id"],
                        item.get("title", "")[:500],
                        item.get("body", "")[:5000],
                        item.get("url", ""),
                        item.get("author", "")[:200],
                        json.dumps(item.get("metadata", {})),
                        item.get("external_created_at", now),
                        now,
                    ),
                )
            db.execute("UPDATE signal_sources SET last_fetched_at = ? WHERE id = ?", (now, src["id"]))
            db.commit()
            logger.info("Fetched %d signals for source %s", len(items), src["id"])

    _threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "message": "Fetch started in background"}


# ── Session endpoints ───────────────────────────────────────────────────

def _get_session_db():
    from kai_state import SessionDB
    return SessionDB()


@app.get("/api/sessions")
def list_sessions(limit: int = 20, offset: int = 0):
    db = _get_session_db()
    sessions = db.list_sessions_rich(source="web", limit=limit, offset=offset)
    # Also include CLI sessions if no web sessions yet
    if not sessions:
        sessions = db.list_sessions_rich(limit=limit, offset=offset)
    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    db = _get_session_db()
    session = db.get_session(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    messages = db.get_messages(session_id)
    # Filter to user + assistant content messages for display
    display_messages = []
    for msg in messages:
        if msg["role"] == "user" and msg.get("content"):
            display_messages.append({
                "id": msg["id"],
                "role": "user",
                "content": msg["content"],
            })
        elif msg["role"] == "assistant" and msg.get("content"):
            display_messages.append({
                "id": msg["id"],
                "role": "assistant",
                "content": msg["content"],
            })
    return {"session": session, "messages": display_messages}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    db = _get_session_db()
    ok = db.delete_session(session_id)
    return {"ok": ok}


# ── Workspace endpoint ─────────────────────────────────────────────────

@app.get("/api/workspace/status")
def workspace_status():
    try:
        ctx = load_workspace_context(workspace_id=_ws_id())
        bp = ctx.get_blueprint()
        learnings = ctx.get_learnings(limit=10)
        onboarding = ctx.get_onboarding_status()
        return {
            "onboarding": onboarding,
            "blueprint": {
                "summary": bp["summary"] if bp else None,
                "data": bp["data"] if bp else None,
                "updated_at": bp["updated_at"] if bp else None,
            } if bp else None,
            "learnings_count": len(learnings),
            "learnings": learnings,  # return all — frontend filters by category
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    message = body.get("message", "").strip()
    thread_id = body.get("threadId") or str(uuid.uuid4())[:12]
    source = body.get("source", "web")  # "web" for user chats, "system" for background tasks

    if not message:
        return JSONResponse({"error": "message required"}, status_code=400)

    event_queue: queue.Queue = queue.Queue()
    _tool_starts: dict = {}  # track tool start times for duration

    def token_cb(delta):
        if delta:
            event_queue.put({"type": "text", "content": delta})

    def thinking_cb(text):
        if text:
            event_queue.put({"type": "thinking", "content": text})
        else:
            event_queue.put({"type": "thinking_done"})

    def reasoning_cb(text):
        if text:
            event_queue.put({"type": "reasoning", "content": text})

    def tool_cb(name, preview, args):
        _tool_starts[name] = time.time()
        # Summarize args for display
        args_summary = ""
        if args:
            keys = list(args.keys())[:3]
            parts = []
            for k in keys:
                v = str(args[k])[:40]
                parts.append(f"{k}={v}")
            args_summary = ", ".join(parts)
        event_queue.put({
            "type": "tool_start",
            "name": name,
            "preview": preview or "",
            "args": args_summary,
        })

    def run_agent():
        try:
            from run_agent import AIAgent
            from model_tools import ensure_mcp_discovered
            ensure_mcp_discovered()

            history = _sessions.get(thread_id, [])

            # If resuming an existing session, load history from DB
            if not history:
                try:
                    sdb = _get_session_db()
                    stored = sdb.get_messages_as_conversation(thread_id)
                    if stored:
                        history = stored
                except Exception:
                    pass

            model = os.environ.get("DASH_MODEL") or os.environ.get("KAI_MODEL") or os.environ.get("HERMES_MODEL") or "openai/gpt-5.4"
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

            from workspace_context_bridge import fetch_workspace_status, build_workspace_status_prompt
            ws_status = fetch_workspace_status()
            ws_prompt = build_workspace_status_prompt(ws_status) if ws_status else None

            # Create or reuse session in DB
            sdb = _get_session_db()
            existing = sdb.get_session(thread_id)
            if not existing:
                sdb.create_session(
                    session_id=thread_id,
                    source=source,
                    model=model,
                )

            agent = AIAgent(
                model=model,
                api_key=api_key,
                base_url=base_url,
                provider="openrouter",
                max_iterations=25,
                quiet_mode=True,
                token_callback=token_cb,
                tool_progress_callback=tool_cb,
                thinking_callback=thinking_cb,
                reasoning_callback=reasoning_cb,
                platform="web",
                session_id=thread_id,
                ephemeral_system_prompt=ws_prompt,
                session_db=sdb,
            )

            result = agent.run_conversation(message, conversation_history=history)
            final = result.get("final_response", "")
            messages = result.get("messages", [])
            _sessions[thread_id] = messages

            # Auto-title from first user message
            if not existing:
                title = message[:60] + ("..." if len(message) > 60 else "")
                try:
                    sdb.set_session_title(thread_id, title)
                except Exception:
                    pass

            event_queue.put({"type": "done", "threadId": thread_id, "response": final})
        except Exception as e:
            logger.exception("Agent error")
            event_queue.put({"type": "error", "message": str(e)})

    threading.Thread(target=run_agent, daemon=True).start()

    async def event_stream():
        last_data = time.time()
        while True:
            try:
                event = event_queue.get(timeout=0.2)
                yield f"data: {json.dumps(event)}\n\n"
                last_data = time.time()
                if event.get("type") in ("done", "error"):
                    break
            except queue.Empty:
                # Send a real data event every 3s to keep CDN connections alive
                # (Railway Fastly edge drops idle SSE connections)
                now = time.time()
                if now - last_data > 3:
                    yield f"data: {{\"type\":\"heartbeat\"}}\n\n"
                    last_data = now
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx/CDN buffering
        },
    )


# ── Cron ticker (background thread) ────────────────────────────────────

def _start_cron_ticker():
    """Run the cron scheduler tick loop in a background thread."""
    import traceback

    def ticker():
        while True:
            try:
                from cron.scheduler import tick
                tick()
            except Exception as e:
                logger.error("Cron tick error: %s\n%s", e, traceback.format_exc())
            time.sleep(60)  # Check every 60 seconds

    t = threading.Thread(target=ticker, daemon=True)
    t.start()
    logger.info("Cron ticker started (60s interval)")


@app.on_event("startup")
def on_startup():
    _start_cron_ticker()


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", os.environ.get("API_PORT", 3001)))
    print(f"Dash PM API server on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
