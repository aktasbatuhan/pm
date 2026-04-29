"""
Dash PM API Server — serves brief, workspace, and chat endpoints.
Run: python server.py (port 3001)
Next.js dev server proxies /api/* here.
"""

import asyncio
import contextvars
import json
import logging
import os
import queue
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
_project_env = Path(__file__).parent / ".env"
if _project_env.exists():
    load_dotenv(dotenv_path=_project_env)

from fastapi import Depends, FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse, HTMLResponse
from starlette.middleware.cors import CORSMiddleware

import sqlite3
from kai_env import kai_home
from workspace_context import load_workspace_context
from backend.db.postgres_client import get_pool, is_postgres_enabled
from backend.tenant_auth import build_tenant_context, get_current_tenant, is_tenant_scoped_path
from backend.tenant_context import reset_current_tenant, set_current_tenant
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
CREATE TABLE IF NOT EXISTS github_installations (
    installation_id TEXT PRIMARY KEY,
    account_login TEXT NOT NULL,
    account_type TEXT,
    repo_selection TEXT,
    cached_token TEXT,
    cached_token_expires_at REAL,
    installed_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    purpose TEXT NOT NULL,
    created_at REAL NOT NULL
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
import httpx

logger = logging.getLogger(__name__)

app = FastAPI(title="Dash PM API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def tenant_context_middleware(request: Request, call_next):
    """Resolve per-request tenant context for tenant-scoped API paths."""
    # Let CORS preflight pass through; browsers don't include the bearer
    # token on OPTIONS, and CORSMiddleware downstream produces the
    # appropriate Access-Control-Allow-* response.
    if request.method == "OPTIONS":
        return await call_next(request)
    if not is_tenant_scoped_path(request.url.path):
        return await call_next(request)

    try:
        tenant_context = build_tenant_context(request)
    except Exception as exc:
        from fastapi import HTTPException

        if isinstance(exc, HTTPException):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        raise
    request.state.tenant_context = tenant_context

    # Expose request tenant context to tool paths that execute within this request.
    os.environ["KAI_TENANT_ID"] = tenant_context.tenant_id
    os.environ["HERMES_TENANT_ID"] = tenant_context.tenant_id
    os.environ["KAI_USER_ID"] = tenant_context.user_id
    os.environ["KAI_TENANT_ROLE"] = tenant_context.role

    token = set_current_tenant(tenant_context)
    try:
        return await call_next(request)
    finally:
        reset_current_tenant(token)


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


# ── Auth v2 (Postgres + JWT, multi-tenant) ─────────────────────────────

def _verify_password(stored_hash: str, plaintext: str) -> bool:
    """Verify password against stored hash. Supports legacy SHA256 (raw hex)
    and modern argon2id ($argon2id$...). Returns True on match."""
    if not stored_hash or not plaintext:
        return False
    if stored_hash.startswith("$argon2"):
        try:
            from argon2 import PasswordHasher
            PasswordHasher().verify(stored_hash, plaintext)
            return True
        except Exception:
            return False
    return _hash_password(plaintext) == stored_hash


@app.post("/api/auth/v2/signin")
async def auth_v2_signin(request: Request):
    """Email + password signin. Returns JWT and tenant list."""
    if not is_postgres_enabled():
        return JSONResponse({"error": "Postgres auth not enabled"}, status_code=503)
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not email or not password:
        return JSONResponse({"error": "email and password required"}, status_code=400)

    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, password_hash, display_name FROM users WHERE email = %s",
                (email,),
            )
            user = cur.fetchone()
            if not user or not _verify_password(user["password_hash"] or "", password):
                return JSONResponse({"error": "Invalid email or password"}, status_code=401)
            user_id = str(user["id"])

            cur.execute(
                """
                SELECT t.id, t.slug, t.name, m.role, m.is_default
                  FROM tenant_memberships m
                  JOIN tenants t ON t.id = m.tenant_id
                 WHERE m.user_id = %s
                 ORDER BY m.is_default DESC, t.created_at ASC
                """,
                (user_id,),
            )
            memberships = cur.fetchall()

    if not memberships:
        return JSONResponse({"error": "No tenant memberships"}, status_code=403)

    from backend.tenant_auth import issue_jwt
    token = issue_jwt(user_id)
    return {
        "token": token,
        "user": {
            "id": user_id,
            "email": email,
            "display_name": user["display_name"],
        },
        "tenants": [
            {
                "id": str(m["id"]),
                "slug": m["slug"],
                "name": m["name"],
                "role": m["role"],
                "is_default": m["is_default"],
            }
            for m in memberships
        ],
    }


@app.get("/api/auth/v2/me")
def auth_v2_me(request: Request):
    """Return current user + memberships, given a valid JWT."""
    if not is_postgres_enabled():
        return JSONResponse({"error": "Postgres auth not enabled"}, status_code=503)
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse({"error": "Missing bearer token"}, status_code=401)
    token = auth_header.split(" ", 1)[1].strip()
    from backend.tenant_auth import decode_jwt
    try:
        payload = decode_jwt(token)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=401)
    user_id = payload["sub"]

    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, display_name FROM users WHERE id = %s",
                (user_id,),
            )
            user = cur.fetchone()
            if not user:
                return JSONResponse({"error": "User not found"}, status_code=404)
            cur.execute(
                """
                SELECT t.id, t.slug, t.name, m.role, m.is_default
                  FROM tenant_memberships m
                  JOIN tenants t ON t.id = m.tenant_id
                 WHERE m.user_id = %s
                 ORDER BY m.is_default DESC, t.created_at ASC
                """,
                (user_id,),
            )
            memberships = cur.fetchall()

    return {
        "user": {
            "id": str(user["id"]),
            "email": user["email"],
            "display_name": user["display_name"],
        },
        "tenants": [
            {
                "id": str(m["id"]),
                "slug": m["slug"],
                "name": m["name"],
                "role": m["role"],
                "is_default": m["is_default"],
            }
            for m in memberships
        ],
    }


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
            action_items TEXT DEFAULT '[]',
            last_evaluated_at REAL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS goal_snapshots (
            id TEXT PRIMARY KEY,
            goal_id TEXT NOT NULL,
            progress INTEGER DEFAULT 0,
            trajectory TEXT,
            action_items TEXT DEFAULT '[]',
            brief_id TEXT,
            notes TEXT,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_goal_snapshots_goal ON goal_snapshots(goal_id, created_at DESC);
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
        CREATE TABLE IF NOT EXISTS kpis (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            unit TEXT,
            direction TEXT DEFAULT 'higher',   -- higher | lower
            target_value REAL,
            current_value REAL,
            previous_value REAL,
            measurement_plan TEXT DEFAULT '',  -- agent-authored plan describing how to measure
            measurement_status TEXT DEFAULT 'pending',  -- pending | configured | failed
            measurement_error TEXT,            -- reason if configuration failed
            cron_job_id TEXT,
            status TEXT DEFAULT 'active',      -- active | paused | archived
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            last_measured_at REAL
        );
        CREATE TABLE IF NOT EXISTS kpi_values (
            id TEXT PRIMARY KEY,
            kpi_id TEXT NOT NULL,
            value REAL NOT NULL,
            source TEXT,
            notes TEXT,
            recorded_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_kpi_values_kpi ON kpi_values(kpi_id, recorded_at DESC);
        CREATE TABLE IF NOT EXISTS kpi_flags (
            id TEXT PRIMARY KEY,
            kpi_id TEXT NOT NULL,
            kind TEXT NOT NULL,                -- risk | opportunity
            title TEXT NOT NULL,
            description TEXT,
            references_json TEXT DEFAULT '[]',
            brief_id TEXT,
            status TEXT DEFAULT 'open',        -- open | resolved | dismissed
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_kpi_flags_kpi ON kpi_flags(kpi_id, status, created_at DESC);
    """)
    # Migrations for goals (action_items, last_evaluated_at)
    for col, ddl in (
        ("action_items", "ALTER TABLE goals ADD COLUMN action_items TEXT DEFAULT '[]'"),
        ("last_evaluated_at", "ALTER TABLE goals ADD COLUMN last_evaluated_at REAL"),
    ):
        try:
            db.execute(f"SELECT {col} FROM goals LIMIT 0")
        except Exception:
            try:
                db.execute(ddl)
                db.commit()
            except Exception:
                pass
    return db

_ensure_pm_tables()


def _ws_id():
    return os.environ.get("KAI_WORKSPACE_ID") or os.environ.get("HERMES_WORKSPACE_ID") or "default"


def _enrich_references(refs, github_ctx=None):
    """Backfill missing URLs on stored references using blueprint github context."""
    if not refs:
        return refs
    if github_ctx is None:
        try:
            from tools.pm_brief_tools import _get_github_context
            github_ctx = _get_github_context()
        except Exception:
            github_ctx = ("", {})
    default_org, repo_map = github_ctx
    enriched = []
    for r in refs:
        if not isinstance(r, dict):
            enriched.append(r)
            continue
        url = r.get("url") or ""
        if not url:
            title = r.get("title") or ""
            if "#" in title:
                repo_part, _, num = title.rpartition("#")
                repo_part = repo_part.strip()
                num = num.strip()
                if num.isdigit() and repo_part:
                    if "/" in repo_part:
                        owner, repo = repo_part.split("/", 1)
                    else:
                        repo = repo_part
                        owner = repo_map.get(repo.lower()) or default_org
                    if owner and repo:
                        r = {**r, "url": f"https://github.com/{owner}/{repo}/issues/{num}"}
        enriched.append(r)
    return enriched


def _shape_brief_response(row: dict, items: list[dict]) -> dict:
    headline = (row.get("headline") or "").strip()
    if not headline:
        for line in (row.get("summary") or "").split("\n"):
            stripped = line.strip().lstrip("#").lstrip("-").strip()
            if len(stripped) > 20 and not stripped.startswith("```"):
                headline = stripped[:120]
                break
    try:
        suggested_prompts = json.loads(row.get("suggested_prompts") or "[]")
    except (json.JSONDecodeError, TypeError):
        suggested_prompts = []
    return {
        "id": row["id"],
        "headline": headline,
        "summary": row["summary"],
        "data_sources": row.get("data_sources"),
        "created_at": row["created_at"],
        "suggested_prompts": suggested_prompts,
        "action_items": items,
    }


def _shape_action_for_response(item: dict) -> dict:
    """Convert a Postgres or SQLite action row into the response shape."""
    out = dict(item)
    refs = out.get("references")
    if refs is None:
        try:
            refs = json.loads(out.get("references_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            refs = []
    out["references"] = _enrich_references(refs)
    out.pop("references_json", None)
    return out


@app.get("/api/brief/latest")
def brief_latest(tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        brief = repos.get_latest_brief(tenant.tenant_id)
        if not brief:
            return {"brief": None}
        actions = repos.list_brief_actions(tenant.tenant_id, brief_id=brief["id"])
        items = [_shape_action_for_response(a) for a in actions]
        return {"brief": _shape_brief_response(brief, items)}

    db = _get_db()
    row = db.execute("SELECT * FROM briefs ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        return {"brief": None}
    actions = db.execute(
        "SELECT * FROM brief_actions WHERE brief_id = ? ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'in-progress' THEN 1 ELSE 2 END, created_at",
        (row["id"],)
    ).fetchall()
    items = [_shape_action_for_response(dict(a)) for a in actions]
    return {"brief": _shape_brief_response(dict(row), items)}


@app.get("/api/brief/{brief_id}")
def get_brief(brief_id: str, tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        brief = repos.get_brief(tenant.tenant_id, brief_id)
        if not brief:
            return JSONResponse({"error": "Not found"}, status_code=404)
        actions = repos.list_brief_actions(tenant.tenant_id, brief_id=brief_id)
        items = [_shape_action_for_response(a) for a in actions]
        return {"brief": _shape_brief_response(brief, items)}

    db = _get_db()
    row = db.execute("SELECT * FROM briefs WHERE id = ?", (brief_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "Not found"}, status_code=404)
    actions = db.execute(
        "SELECT * FROM brief_actions WHERE brief_id = ? ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'in-progress' THEN 1 ELSE 2 END, created_at",
        (brief_id,)
    ).fetchall()
    items = [_shape_action_for_response(dict(a)) for a in actions]
    return {"brief": _shape_brief_response(dict(row), items)}


@app.get("/api/briefs")
def list_briefs(limit: int = 20, tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        rows = repos.list_briefs(tenant.tenant_id, limit=limit)
    else:
        db = _get_db()
        sqlite_rows = db.execute("SELECT * FROM briefs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        rows = []
        for r in sqlite_rows:
            d = dict(r)
            ac = db.execute("SELECT COUNT(*) as c FROM brief_actions WHERE brief_id = ?", (d["id"],)).fetchone()
            pc = db.execute("SELECT COUNT(*) as c FROM brief_actions WHERE brief_id = ? AND status = 'pending'", (d["id"],)).fetchone()
            d["action_count"] = ac["c"] if ac else 0
            d["pending_count"] = pc["c"] if pc else 0
            rows.append(d)

    briefs = []
    for r in rows:
        headline = (r.get("headline") or "").strip()
        if not headline:
            for line in (r.get("summary") or "").split("\n"):
                stripped = line.strip().lstrip("#").lstrip("-").strip()
                if len(stripped) > 20 and not stripped.startswith("```"):
                    headline = stripped[:120]
                    break
        briefs.append({
            "id": r["id"],
            "headline": headline,
            "data_sources": r.get("data_sources"),
            "created_at": r["created_at"],
            "action_count": r.get("action_count", 0),
            "pending_count": r.get("pending_count", 0),
        })
    return {"briefs": briefs}


@app.get("/api/brief/actions")
def brief_actions(status: str = "pending", tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        actions = repos.list_brief_actions(
            tenant.tenant_id,
            status=None if status == "all" else status,
        )
        return {"actions": actions[:50]}

    db = _get_db()
    if status == "all":
        rows = db.execute("SELECT * FROM brief_actions ORDER BY created_at DESC LIMIT 50").fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM brief_actions WHERE status = ? ORDER BY created_at DESC LIMIT 50", (status,)
        ).fetchall()
    return {"actions": [dict(r) for r in rows]}


@app.post("/api/brief/actions/{action_id}")
async def brief_action_update(action_id: str, request: Request, tenant=Depends(get_current_tenant)):
    body = await request.json()
    new_status = body.get("status", "resolved")

    if is_postgres_enabled():
        from backend import repos
        ok = repos.update_brief_action(tenant.tenant_id, action_id, status=new_status)
        if not ok:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return {"ok": True, "action_id": action_id, "status": new_status}

    db = _get_db()
    row = db.execute("SELECT * FROM brief_actions WHERE id = ?", (action_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "Not found"}, status_code=404)
    db.execute("UPDATE brief_actions SET status = ?, updated_at = ? WHERE id = ?",
               (new_status, time.time(), action_id))
    db.commit()
    return {"ok": True, "action_id": action_id, "status": new_status}


@app.post("/api/brief/actions/{action_id}/create-issue")
async def brief_action_create_issue(action_id: str, request: Request):
    """Convert an action item into a GitHub issue. Body: {repo, title?, body?}."""
    data = await request.json()
    repo = (data.get("repo") or "").strip()
    if "/" not in repo:
        return JSONResponse({"error": "repo must be 'owner/name'"}, status_code=400)

    db = _get_db()
    row = db.execute("SELECT * FROM brief_actions WHERE id = ?", (action_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "Not found"}, status_code=404)

    title = (data.get("title") or row["title"]).strip()
    if not title:
        return JSONResponse({"error": "title required"}, status_code=400)

    # Compose an issue body that preserves the action's description + references.
    desc = (data.get("body") or row["description"] or "").strip()
    refs_body = ""
    try:
        existing_refs = json.loads(row["references_json"] or "[]")
    except Exception:
        existing_refs = []
    if existing_refs:
        lines = []
        for r in existing_refs:
            t = r.get("title") or r.get("url") or ""
            u = r.get("url") or ""
            lines.append(f"- {t}" + (f" — {u}" if u else ""))
        refs_body = "\n\n**Related:**\n" + "\n".join(lines)
    issue_body = f"{desc}{refs_body}\n\n_Filed from Dash brief action `{action_id}`._"

    # Mint/refresh a fresh installation token just in case.
    _refresh_github_token_env()
    from tools.pm_github_tools import github_create_issue
    raw = github_create_issue(repo=repo, title=title, body=issue_body)
    try:
        result = json.loads(raw)
    except Exception:
        return JSONResponse({"error": "invalid tool response", "raw": raw}, status_code=500)

    if not result.get("ok"):
        return JSONResponse(result, status_code=403 if result.get("error") == "permission_denied" else 502)

    # Append the new issue to the action's references and mark it in-progress.
    new_ref = {
        "type": "issue",
        "url": result.get("url", ""),
        "title": f"{repo}#{result.get('number')}",
    }
    existing_refs.append(new_ref)
    db.execute(
        "UPDATE brief_actions SET references_json = ?, status = 'in-progress', updated_at = ? WHERE id = ?",
        (json.dumps(existing_refs), time.time(), action_id),
    )
    db.commit()
    return {"ok": True, "issue_url": result.get("url"), "number": result.get("number"), "action_id": action_id}


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
def get_onboarding_profile(tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        return repos.get_onboarding_profile(tenant.tenant_id)
    db = _get_integrations_db()
    rows = db.execute("SELECT key, value FROM onboarding_profile").fetchall()
    return {r["key"]: r["value"] for r in rows}


@app.post("/api/onboarding/profile")
async def save_onboarding_profile(request: Request, tenant=Depends(get_current_tenant)):
    body = await request.json()
    if is_postgres_enabled():
        from backend import repos
        repos.save_onboarding_profile(tenant.tenant_id, body)
        return {"ok": True}
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
def list_integrations(tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        items = repos.list_integrations(tenant.tenant_id)
        for it in items:
            it["credentials"] = "••••" + str(it.get("credentials") or "")[-4:]
        return {"integrations": items}

    db = _get_integrations_db()
    rows = db.execute("SELECT * FROM integrations ORDER BY connected_at DESC").fetchall()
    items = []
    for r in rows:
        item = dict(r)
        item["credentials"] = "••••" + str(item.get("credentials", ""))[-4:]
        items.append(item)
    return {"integrations": items}


@app.post("/api/integrations/{platform}")
async def connect_integration(platform: str, request: Request, tenant=Depends(get_current_tenant)):
    body = await request.json()
    auth_type = body.get("auth_type", "token")
    credentials = body.get("credentials", "")
    display_name = body.get("display_name", platform)
    if not credentials:
        return JSONResponse({"error": "credentials required"}, status_code=400)

    valid, message = _validate_integration(platform, auth_type, credentials)
    status = "connected" if valid else "invalid"

    if is_postgres_enabled():
        from backend import repos
        repos.upsert_integration(
            tenant.tenant_id, platform=platform, auth_type=auth_type,
            credentials=credentials, status=status, display_name=display_name,
        )
    else:
        db = _get_integrations_db()
        now = time.time()
        db.execute(
            "INSERT INTO integrations (platform, auth_type, credentials, status, display_name, connected_at, last_verified) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(platform) DO UPDATE SET auth_type=excluded.auth_type, credentials=excluded.credentials, "
            "status=excluded.status, display_name=excluded.display_name, connected_at=excluded.connected_at, last_verified=excluded.last_verified",
            (platform, auth_type, credentials, status, display_name, now, now),
        )
        db.commit()

    if valid:
        _inject_credential(platform, credentials)
    return {"ok": valid, "status": status, "message": message}


@app.delete("/api/integrations/{platform}")
def disconnect_integration(platform: str, tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        repos.delete_integration(tenant.tenant_id, platform)
        return {"ok": True}
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

    if platform == "sentry":
        try:
            req = urllib.request.Request(
                "https://sentry.io/api/0/",
                headers={"Authorization": f"Bearer {credentials}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return True, "Sentry auth valid"
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return False, "Sentry auth failed: invalid token"
            return True, "Sentry connected"
        except Exception as e:
            return False, f"Sentry connection error: {e}"

    if platform == "stripe":
        try:
            req = urllib.request.Request(
                "https://api.stripe.com/v1/balance",
                headers={"Authorization": f"Bearer {credentials}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return True, "Stripe connected"
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return False, "Stripe auth failed: invalid key"
            return True, "Stripe connected"
        except Exception as e:
            return False, f"Stripe connection error: {e}"

    if platform == "notion":
        try:
            req = urllib.request.Request(
                "https://api.notion.com/v1/users/me",
                headers={
                    "Authorization": f"Bearer {credentials}",
                    "Notion-Version": "2022-06-28",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                name = data.get("name", "unknown")
                return True, f"Connected as {name}"
        except urllib.error.HTTPError as e:
            return False, f"Notion auth failed: {e.code}"
        except Exception as e:
            return False, f"Notion connection error: {e}"

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
        "sentry": "SENTRY_AUTH_TOKEN",
        "stripe": "STRIPE_API_KEY",
        "notion": "NOTION_API_KEY",
        "figma": "FIGMA_ACCESS_TOKEN",
        "slack": "SLACK_BOT_TOKEN",
    }
    env_var = env_map.get(platform)
    if env_var:
        os.environ[env_var] = credentials


# ── GitHub App integration ─────────────────────────────────────────────

from github_app_auth import (
    github_app_config as _github_app_config,
    generate_app_jwt as _generate_github_app_jwt,
    get_installation_token as _get_github_installation_token,
    refresh_github_token_env as _refresh_github_token_env,
)


@app.get("/api/integrations/github/debug")
def github_app_debug():
    """Diagnostic: shows whether the server process has a live GitHub token."""
    cfg = _github_app_config()
    db = _get_integrations_db()
    row = db.execute(
        "SELECT installation_id, cached_token_expires_at FROM github_installations "
        "ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    token_present = bool(os.environ.get("GITHUB_TOKEN"))
    token_prefix = (os.environ.get("GITHUB_TOKEN") or "")[:8]
    # Try a fresh refresh and report the outcome
    refresh_ok = False
    try:
        refresh_ok = _refresh_github_token_env()
    except Exception as e:
        refresh_ok = False
    # Bonus: run `env | grep GITHUB` in a subprocess just like the agent would,
    # to confirm env propagates through the shell that terminal_tool uses.
    import subprocess as _sp
    try:
        out = _sp.run(
            ["bash", "-lic", "env | grep -E '^(GITHUB|GH_)' | sed -E 's/=(.{8}).*/=\\1…/'"],
            capture_output=True, text=True, timeout=10,
        )
        subproc_env = out.stdout.strip() or "(none)"
    except Exception as e:
        subproc_env = f"error: {e}"
    # Actually exercise `gh api` like the skill tells the agent to do.
    gh_api_test = {}
    for label, cmd in [
        ("gh_version", "gh --version | head -1"),
        ("gh_auth_status", "gh auth status 2>&1"),
        ("gh_api_user", "gh api /user 2>&1 | head -c 200"),
        ("gh_api_installation_repos", "gh api /installation/repositories 2>&1 | head -c 400"),
    ]:
        try:
            r = _sp.run(["bash", "-lic", cmd], capture_output=True, text=True, timeout=20)
            gh_api_test[label] = {"rc": r.returncode, "out": (r.stdout or r.stderr or "").strip()[:500]}
        except Exception as e:
            gh_api_test[label] = {"rc": -1, "out": f"error: {e}"}
    # Check $KAI_HOME/skills on disk so we can confirm sync_skills actually ran.
    skills_dir = kai_home() / "skills"
    skills_info = {
        "kai_home": str(kai_home()),
        "skills_dir_exists": skills_dir.exists(),
        "skill_count": 0,
        "pm_skills_present": [],
    }
    if skills_dir.exists():
        try:
            all_skills = list(skills_dir.rglob("SKILL.md"))
            skills_info["skill_count"] = len(all_skills)
            pm_wanted = ["pm-brief/daily-brief", "pm-kpi/kpi-configure",
                         "pm-kpi/kpi-refresh", "pm-onboarding/self-onboard"]
            for name in pm_wanted:
                p = skills_dir / name / "SKILL.md"
                if p.exists():
                    skills_info["pm_skills_present"].append(name)
        except Exception as e:
            skills_info["error"] = str(e)
    return {
        "config_present": bool(cfg),
        "installation_row": dict(row) if row else None,
        "env_token_present_before": token_present,
        "env_token_prefix_before": token_prefix,
        "refresh_ok": refresh_ok,
        "env_token_present_after": bool(os.environ.get("GITHUB_TOKEN")),
        "env_token_prefix_after": (os.environ.get("GITHUB_TOKEN") or "")[:8],
        "subprocess_github_env": subproc_env,
        "gh_api_test": gh_api_test,
        "skills": skills_info,
        "tool_availability": _tool_availability_snapshot(),
    }


def _tool_availability_snapshot():
    """Report which of the PM-critical tools are currently registered."""
    try:
        from model_tools import get_tool_definitions
        tools = get_tool_definitions(quiet_mode=True)
        names = sorted({t["function"]["name"] for t in tools})
        critical = ["terminal", "process", "execute_code", "skills_list", "skill_view",
                    "brief_store", "workspace_get_blueprint", "platforms_list",
                    "platforms_check", "kpi_list", "goal_list"]
        return {
            "total_registered": len(names),
            "critical_present": {n: (n in names) for n in critical},
            "github_mcp_tools": [n for n in names if n.startswith("mcp-github-") or "github" in n.lower()][:10],
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/integrations/github/app-status")
def github_app_status(tenant=Depends(get_current_tenant)):
    """Expose whether the GitHub App is configured (so the UI can pick install-flow vs PAT-fallback)."""
    cfg = _github_app_config()
    if not cfg:
        return {"configured": False}
    inst = None
    if is_postgres_enabled():
        from backend import repos
        inst = repos.get_github_installation(tenant.tenant_id)
    else:
        db = _get_integrations_db()
        row = db.execute(
            "SELECT installation_id, account_login, account_type, repo_selection, installed_at, updated_at "
            "FROM github_installations ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        inst = dict(row) if row else None
    permissions = {}
    if inst:
        # Query live installation permissions so the UI knows whether write
        # operations (create issue, comment) are available.
        try:
            import urllib.request
            app_jwt = _generate_github_app_jwt(cfg)
            req = urllib.request.Request(
                f"https://api.github.com/app/installations/{inst['installation_id']}",
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "Dash-PM",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            permissions = data.get("permissions") or {}
        except Exception as e:
            logger.warning("Failed to fetch installation permissions: %s", e)
    # If the App isn't installed here, fall back to checking for any token
    # (PAT or app installation token minted at startup). Prod runs this path.
    has_token = bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN"))
    can_write = permissions.get("issues") == "write" if inst else has_token
    return {
        "configured": True,
        "slug": cfg["slug"],
        "installation": inst,
        "permissions": permissions,
        "has_token": has_token,
        "can_write_issues": can_write,
    }


@app.get("/api/integrations/github/install")
def github_app_install_redirect(tenant=Depends(get_current_tenant)):
    """Start the GitHub App install flow.

    Returns a JSON {url, state} payload AND sets an HttpOnly cookie carrying
    the same state. The cookie is the resilient channel — we use it in the
    callback when GitHub strips/loses the query param (which it does when
    the user navigates between accounts or when they hit the public app
    page rather than /installations/new).

    The URL we return is /installations/new with a state query param, but
    even if GitHub redirects mid-flow and the param is dropped, the
    cookie-based state lets the callback still attribute the install to
    the correct tenant.
    """
    cfg = _github_app_config()
    if not cfg:
        return JSONResponse({"error": "GitHub App not configured"}, status_code=503)

    state = secrets.token_urlsafe(24)
    if is_postgres_enabled():
        from backend import repos
        repos.store_oauth_state(state, tenant_id=tenant.tenant_id, purpose="github_app_install")
    else:
        db = _get_integrations_db()
        db.execute(
            "INSERT OR REPLACE INTO oauth_states (state, purpose, created_at) VALUES (?, 'github_app_install', ?)",
            (state, time.time()),
        )
        db.execute("DELETE FROM oauth_states WHERE created_at < ?", (time.time() - 600,))
        db.commit()

    import urllib.parse as _p
    url = f"https://github.com/apps/{cfg['slug']}/installations/new?state={_p.quote(state)}"
    response = JSONResponse({"url": url})
    # Cookie carries the state through GitHub's roundtrip even if the user
    # switches accounts or GitHub redirects in a way that drops the param.
    # SameSite=Lax: top-level navigations from github.com back to our domain
    # carry the cookie. Path scoped to the github callback so it doesn't
    # leak into other endpoints.
    response.set_cookie(
        key="dash_gh_install_state",
        value=state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=True,
        path="/api/integrations/github",
    )
    return response


@app.get("/api/integrations/github/callback")
def github_app_install_callback(
    request: Request,
    installation_id: Optional[str] = None,
    setup_action: Optional[str] = None,
    state: Optional[str] = None,
    code: Optional[str] = None,
):
    """GitHub redirects here after the user installs the App."""
    cfg = _github_app_config()
    if not cfg:
        return HTMLResponse("<p>GitHub App not configured on the server.</p>", status_code=503)

    if not installation_id:
        return HTMLResponse("<p>Missing installation_id. Did you cancel the install?</p>", status_code=400)

    # State recovery: GitHub may strip our state query param when the user
    # switches accounts or follows certain redirect paths. Fall back to the
    # HttpOnly cookie we set in the install endpoint.
    effective_state = state or request.cookies.get("dash_gh_install_state") or ""

    initiating_tenant_id: Optional[str] = None
    if is_postgres_enabled():
        from backend import repos
        if effective_state:
            consumed = repos.consume_oauth_state(effective_state)
            if consumed:
                initiating_tenant_id = consumed.get("tenant_id")
        if not initiating_tenant_id:
            return HTMLResponse(
                "<p>Install state expired or missing. Please retry the install from Dash so we can attribute it to your workspace.</p>",
                status_code=400,
            )
    else:
        db = _get_integrations_db()
        if effective_state:
            srow = db.execute("SELECT state FROM oauth_states WHERE state = ?", (effective_state,)).fetchone()
            if srow:
                db.execute("DELETE FROM oauth_states WHERE state = ?", (effective_state,))
                db.commit()

    # Call GitHub as the App to fetch installation details
    import urllib.request
    try:
        app_jwt = _generate_github_app_jwt(cfg)
        req = urllib.request.Request(
            f"https://api.github.com/app/installations/{installation_id}",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "Dash-PM",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            install = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error("Failed to fetch GitHub installation %s: %s", installation_id, e)
        return HTMLResponse(f"<p>Installed, but could not fetch installation details: {e}</p>", status_code=500)

    account = install.get("account") or {}
    account_login = account.get("login") or ""
    account_type = account.get("type") or ""
    repo_selection = install.get("repository_selection") or "selected"
    now = time.time()

    if is_postgres_enabled() and initiating_tenant_id:
        from backend import repos
        repos.upsert_github_installation(
            initiating_tenant_id,
            installation_id=str(installation_id),
            account_login=account_login,
            account_type=account_type,
            repo_selection=repo_selection,
        )
        repos.upsert_integration(
            initiating_tenant_id, platform="github", auth_type="github_app",
            credentials=str(installation_id), status="connected",
            display_name=account_login or "github",
        )
        _refresh_github_token_env(tenant_id=initiating_tenant_id)
    else:
        db = _get_integrations_db()
        db.execute(
            "INSERT INTO github_installations (installation_id, account_login, account_type, repo_selection, installed_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(installation_id) DO UPDATE SET account_login = excluded.account_login, "
            "account_type = excluded.account_type, repo_selection = excluded.repo_selection, updated_at = excluded.updated_at",
            (str(installation_id), account_login, account_type, repo_selection, now, now),
        )
        db.execute(
            "INSERT INTO integrations (platform, auth_type, credentials, status, display_name, connected_at, last_verified) "
            "VALUES ('github', 'github_app', ?, 'connected', ?, ?, ?) "
            "ON CONFLICT(platform) DO UPDATE SET auth_type = 'github_app', credentials = excluded.credentials, "
            "status = 'connected', display_name = excluded.display_name, connected_at = excluded.connected_at, "
            "last_verified = excluded.last_verified",
            (str(installation_id), account_login or "github", now, now),
        )
        db.commit()
        _refresh_github_token_env()

    # If the popup was blocked and the user landed in the main tab, we still
    # want to take them back to the dashboard. DASH_FRONTEND_URL is set per
    # instance (prod vs demo) so each backend knows its counterpart frontend.
    frontend_url = (os.environ.get("DASH_FRONTEND_URL") or "").rstrip("/")
    fallback_target = (frontend_url + "/dashboard") if frontend_url else "/dashboard"
    # Return a page that closes itself + pings the opener if it was a popup,
    # otherwise redirects to the frontend dashboard.
    html = f"""
    <!doctype html>
    <html><head><title>GitHub Connected</title>
    <style>body{{font-family:system-ui;padding:40px;text-align:center;color:#333}}</style>
    </head><body>
    <h2>✓ GitHub connected</h2>
    <p style="color:#666">Taking you back to Dash…</p>
    <script>
      var opened_as_popup = false;
      try {{
        if (window.opener && !window.opener.closed) {{
          window.opener.postMessage({{type:'github-app-installed'}}, '*');
          opened_as_popup = true;
          setTimeout(function(){{ window.close(); }}, 800);
        }}
      }} catch(e) {{}}
      // Same-tab fallback: redirect to the frontend so the user isn't stranded
      // on the Railway domain. Fires even if we tried window.close() — closing
      // a non-popup tab is silently blocked, so the redirect still runs.
      setTimeout(function(){{
        if (!opened_as_popup || !window.closed) {{
          window.location.replace({json.dumps(fallback_target)});
        }}
      }}, 1400);
    </script>
    </body></html>
    """
    response = HTMLResponse(html)
    # Clear the install-state cookie so it doesn't bleed into a later install
    # attempt by the same browser.
    response.delete_cookie(
        key="dash_gh_install_state",
        path="/api/integrations/github",
    )
    return response


@app.get("/api/integrations/github/repos")
def github_list_repos_endpoint(tenant=Depends(get_current_tenant)):
    """Proxy /installation/repositories for the frontend repo picker."""
    _refresh_github_token_env(tenant_id=tenant.tenant_id if is_postgres_enabled() else None)
    from tools.pm_github_tools import github_list_repos
    import json as _json
    try:
        parsed = _json.loads(github_list_repos())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    if parsed.get("error"):
        return JSONResponse(parsed, status_code=502)
    return parsed


@app.delete("/api/integrations/github/app")
def github_app_disconnect(tenant=Depends(get_current_tenant)):
    """Remove the stored installation. The user should also uninstall on GitHub.com."""
    if is_postgres_enabled():
        from backend import repos
        repos.delete_github_installation(tenant.tenant_id)
        repos.delete_integration(tenant.tenant_id, "github")
    else:
        db = _get_integrations_db()
        row = db.execute(
            "SELECT installation_id FROM github_installations ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if row:
            db.execute("DELETE FROM github_installations WHERE installation_id = ?", (row["installation_id"],))
        db.execute("DELETE FROM integrations WHERE platform = 'github' AND auth_type = 'github_app'")
        db.commit()
    os.environ.pop("GITHUB_TOKEN", None)
    os.environ.pop("GITHUB_PERSONAL_ACCESS_TOKEN", None)
    cfg = _github_app_config()
    uninstall_url = (
        f"https://github.com/settings/installations" if cfg else None
    )
    return {"ok": True, "uninstall_hint": uninstall_url}


# ── Changelog endpoints ────────────────────────────────────────────────

@app.get("/api/changelogs")
def list_changelogs(limit: int = 10, tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        return {"changelogs": repos.list_changelogs(tenant.tenant_id, limit=limit)}
    db = _ensure_pm_tables()
    rows = db.execute("SELECT * FROM changelogs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return {"changelogs": [dict(r) for r in rows]}


@app.get("/api/changelogs/latest")
def latest_changelog(tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        return {"changelog": repos.get_latest_changelog(tenant.tenant_id)}
    db = _ensure_pm_tables()
    row = db.execute("SELECT * FROM changelogs ORDER BY created_at DESC LIMIT 1").fetchone()
    return {"changelog": dict(row) if row else None}


@app.post("/api/changelogs")
async def create_changelog(request: Request, tenant=Depends(get_current_tenant)):
    body = await request.json()
    changelog_id = str(uuid.uuid4())[:8]
    now = time.time()
    if is_postgres_enabled():
        from backend import repos
        repos.create_changelog(
            tenant.tenant_id, changelog_id=changelog_id,
            content=body.get("content", ""),
            period_start=body.get("period_start", now - 604800),
            period_end=body.get("period_end", now),
            pr_count=body.get("pr_count", 0),
        )
        return {"ok": True, "id": changelog_id}
    db = _ensure_pm_tables()
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
def list_goals(status: str = "active", tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        return {"goals": repos.list_goals(tenant.tenant_id, status=status)}

    db = _ensure_pm_tables()
    if status == "all":
        rows = db.execute("SELECT * FROM goals ORDER BY created_at DESC").fetchall()
    else:
        rows = db.execute("SELECT * FROM goals WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
    goals = []
    for r in rows:
        g = dict(r)
        for field in ("related_items", "action_items"):
            try:
                g[field] = json.loads(g.get(field) or "[]")
            except (json.JSONDecodeError, TypeError):
                g[field] = []
        goals.append(g)
    return {"goals": goals}


@app.get("/api/goals/{goal_id}/history")
def goal_history(goal_id: str, limit: int = 20, tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        return {"snapshots": repos.goal_history(tenant.tenant_id, goal_id, limit=limit)}

    db = _ensure_pm_tables()
    rows = db.execute(
        "SELECT * FROM goal_snapshots WHERE goal_id = ? ORDER BY created_at DESC LIMIT ?",
        (goal_id, limit),
    ).fetchall()
    snapshots = []
    for r in rows:
        s = dict(r)
        try:
            s["action_items"] = json.loads(s.get("action_items") or "[]")
        except (json.JSONDecodeError, TypeError):
            s["action_items"] = []
        snapshots.append(s)
    return {"snapshots": snapshots}


@app.post("/api/goals")
async def create_goal(request: Request, tenant=Depends(get_current_tenant)):
    body = await request.json()
    goal_id = str(uuid.uuid4())[:8]

    if is_postgres_enabled():
        from backend import repos
        repos.create_goal(
            tenant.tenant_id, goal_id=goal_id,
            title=body.get("title", ""), description=body.get("description", ""),
            target_date=body.get("target_date", ""),
        )
        return {"ok": True, "id": goal_id}

    db = _ensure_pm_tables()
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
async def update_goal(goal_id: str, request: Request, tenant=Depends(get_current_tenant)):
    body = await request.json()

    if is_postgres_enabled():
        from backend import repos
        ok = repos.update_goal(tenant.tenant_id, goal_id, body)
        if not ok:
            # Could be either "not found" or "no fields to update"; treat as success
            # if the goal exists, 404 if not.
            existing = next((g for g in repos.list_goals(tenant.tenant_id, status="all") if g["id"] == goal_id), None)
            if not existing:
                return JSONResponse({"error": "Not found"}, status_code=404)
        return {"ok": True}

    db = _ensure_pm_tables()
    row = db.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "Not found"}, status_code=404)
    updates, params = [], []
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
def delete_goal(goal_id: str, tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        repos.delete_goal(tenant.tenant_id, goal_id)
        return {"ok": True}
    db = _ensure_pm_tables()
    db.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    db.commit()
    return {"ok": True}


# ── KPI endpoints ──────────────────────────────────────────────────────

def _kpi_row_to_dict(r, include_history: bool = False, include_flags: bool = False, db=None):
    k = dict(r)
    if include_history and db is not None:
        rows = db.execute(
            "SELECT id, value, source, notes, recorded_at FROM kpi_values WHERE kpi_id = ? "
            "ORDER BY recorded_at DESC LIMIT 60",
            (k["id"],),
        ).fetchall()
        k["history"] = [dict(h) for h in rows]
    if include_flags and db is not None:
        rows = db.execute(
            "SELECT * FROM kpi_flags WHERE kpi_id = ? AND status = 'open' ORDER BY created_at DESC",
            (k["id"],),
        ).fetchall()
        flags = []
        for f in rows:
            fd = dict(f)
            try:
                fd["references"] = json.loads(fd.get("references_json") or "[]")
            except (json.JSONDecodeError, TypeError):
                fd["references"] = []
            fd.pop("references_json", None)
            flags.append(fd)
        k["flags"] = flags
    return k


@app.get("/api/kpis")
def list_kpis(status: str = "active", tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        return {"kpis": repos.list_kpis(tenant.tenant_id, status=status)}

    db = _ensure_pm_tables()
    if status == "all":
        rows = db.execute("SELECT * FROM kpis ORDER BY created_at DESC").fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM kpis WHERE status = ? ORDER BY created_at DESC", (status,)
        ).fetchall()
    kpis = [_kpi_row_to_dict(r, include_history=True, include_flags=True, db=db) for r in rows]
    return {"kpis": kpis}


@app.get("/api/kpis/{kpi_id}")
def get_kpi(kpi_id: str, tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        kpi = repos.get_kpi(tenant.tenant_id, kpi_id)
        if not kpi:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return {"kpi": kpi}

    db = _ensure_pm_tables()
    row = db.execute("SELECT * FROM kpis WHERE id = ?", (kpi_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"kpi": _kpi_row_to_dict(row, include_history=True, include_flags=True, db=db)}


@app.post("/api/kpis")
async def create_kpi(request: Request, tenant=Depends(get_current_tenant)):
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    kpi_id = str(uuid.uuid4())[:8]
    direction = body.get("direction") or "higher"
    if direction not in ("higher", "lower"):
        direction = "higher"
    target = body.get("target_value")
    try:
        target = float(target) if target not in (None, "") else None
    except (TypeError, ValueError):
        target = None

    if is_postgres_enabled():
        from backend import repos
        repos.create_kpi(
            tenant.tenant_id, kpi_id=kpi_id, name=name,
            description=body.get("description", ""), unit=body.get("unit", ""),
            direction=direction, target_value=target,
        )
    else:
        db = _ensure_pm_tables()
        now = time.time()
        db.execute(
            "INSERT INTO kpis (id, name, description, unit, direction, target_value, "
            "measurement_plan, measurement_status, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, '', 'pending', 'active', ?, ?)",
            (kpi_id, name, body.get("description", ""), body.get("unit", ""), direction, target, now, now),
        )
        db.commit()

    _trigger_kpi_configure(kpi_id, name, body.get("description", ""))
    return {"ok": True, "id": kpi_id}


@app.patch("/api/kpis/{kpi_id}")
async def update_kpi(kpi_id: str, request: Request, tenant=Depends(get_current_tenant)):
    body = await request.json()

    if is_postgres_enabled():
        from backend import repos
        kpi = repos.get_kpi(tenant.tenant_id, kpi_id)
        if not kpi:
            return JSONResponse({"error": "Not found"}, status_code=404)
        repos.update_kpi(tenant.tenant_id, kpi_id, body)
        return {"ok": True}

    db = _ensure_pm_tables()
    row = db.execute("SELECT * FROM kpis WHERE id = ?", (kpi_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "Not found"}, status_code=404)
    updates, params = [], []
    allowed = ("name", "description", "unit", "direction", "target_value",
               "status", "measurement_plan", "measurement_status", "measurement_error")
    for field in allowed:
        if field in body:
            updates.append(f"{field} = ?")
            params.append(body[field])
    if updates:
        updates.append("updated_at = ?")
        params.append(time.time())
        params.append(kpi_id)
        db.execute(f"UPDATE kpis SET {', '.join(updates)} WHERE id = ?", params)
        db.commit()
    return {"ok": True}


@app.delete("/api/kpis/{kpi_id}")
def delete_kpi(kpi_id: str, tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        repos.delete_kpi(tenant.tenant_id, kpi_id)
        return {"ok": True}
    db = _ensure_pm_tables()
    db.execute("DELETE FROM kpi_values WHERE kpi_id = ?", (kpi_id,))
    db.execute("DELETE FROM kpi_flags WHERE kpi_id = ?", (kpi_id,))
    db.execute("DELETE FROM kpis WHERE id = ?", (kpi_id,))
    db.commit()
    return {"ok": True}


@app.post("/api/kpis/{kpi_id}/refresh")
def refresh_kpi(kpi_id: str, tenant=Depends(get_current_tenant)):
    """Manually trigger a KPI measurement refresh."""
    if is_postgres_enabled():
        from backend import repos
        kpi = repos.get_kpi(tenant.tenant_id, kpi_id)
        if not kpi:
            return JSONResponse({"error": "Not found"}, status_code=404)
        _trigger_kpi_refresh(kpi_id, kpi["name"], kpi.get("measurement_plan") or "")
        return {"ok": True, "message": "Refresh triggered"}

    db = _ensure_pm_tables()
    row = db.execute("SELECT * FROM kpis WHERE id = ?", (kpi_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "Not found"}, status_code=404)
    _trigger_kpi_refresh(kpi_id, row["name"], row["measurement_plan"])
    return {"ok": True, "message": "Refresh triggered"}


@app.post("/api/kpis/flags/{flag_id}")
async def update_kpi_flag(flag_id: str, request: Request, tenant=Depends(get_current_tenant)):
    body = await request.json()
    new_status = body.get("status", "resolved")

    if is_postgres_enabled():
        from backend import repos
        repos.update_kpi_flag_status(tenant.tenant_id, flag_id, new_status)
        return {"ok": True, "status": new_status}

    db = _ensure_pm_tables()
    db.execute(
        "UPDATE kpi_flags SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, time.time(), flag_id),
    )
    db.commit()
    return {"ok": True, "status": new_status}


def _trigger_kpi_configure(kpi_id: str, name: str, description: str):
    prompt = (
        f"Configure KPI '{name}' (id: {kpi_id}).\n"
        f"Description: {description or '(none)'}\n\n"
        "Load the pm-kpi/kpi-configure skill with skill_view and follow it exactly. "
        "Inspect connected platforms with platforms_list, decide the best measurement approach, "
        "store the plan with kpi_set_measurement_plan, then record the first value with kpi_record_value. "
        "Finally, schedule a recurring refresh via schedule_cronjob."
    )
    triggerBackgroundTask(prompt, f"kpi-configure-{kpi_id}-{int(time.time())}")


def _trigger_kpi_refresh(kpi_id: str, name: str, plan: str):
    prompt = (
        f"Refresh measurement for KPI '{name}' (id: {kpi_id}).\n"
        f"Measurement plan:\n{plan or '(no plan yet — read the KPI and re-configure if needed)'}\n\n"
        "Load the pm-kpi/kpi-refresh skill with skill_view and follow it exactly. "
        "Execute the plan, call kpi_record_value with the new value, and if movement is notable, "
        "call kpi_flag to raise a risk or opportunity."
    )
    triggerBackgroundTask(prompt, f"kpi-refresh-{kpi_id}-{int(time.time())}")


# ── Team pulse endpoints ───────────────────────────────────────────────

@app.get("/api/team/pulse")
def get_team_pulse(tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        return {"members": repos.list_team_pulse(tenant.tenant_id)}
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


def _resolve_model() -> str:
    """Resolve current model: config.yaml `model.default` > env > fallback.

    config.yaml is authoritative so the UI-level model selector persists and
    is visible to both the chat path and the cron scheduler.
    """
    try:
        import yaml
        cfg_path = kai_home() / "config.yaml"
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            m = cfg.get("model")
            if isinstance(m, str) and m.strip():
                return m.strip()
            if isinstance(m, dict):
                v = m.get("default")
                if isinstance(v, str) and v.strip():
                    return v.strip()
    except Exception:
        pass
    return (
        os.environ.get("DASH_MODEL")
        or os.environ.get("KAI_MODEL")
        or os.environ.get("HERMES_MODEL")
        or "anthropic/claude-opus-4.7"
    )


def triggerBackgroundTask(message: str, thread_id: str, tenant_context=None):
    """Internal helper — fires an agent task as a system session."""
    import threading as _threading
    # Capture the tenant from the calling request so the spawned agent has
    # it available even though ContextVars don't cross thread boundaries.
    if tenant_context is None:
        from backend.tenant_context import get_current_tenant
        tenant_context = get_current_tenant()
    def _run():
        if tenant_context is not None:
            from backend.tenant_context import set_current_tenant
            set_current_tenant(tenant_context)
        try:
            _refresh_github_token_env()
            from run_agent import AIAgent
            from model_tools import ensure_mcp_discovered
            ensure_mcp_discovered()
            model = _resolve_model()
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
            agent.tenant_context = tenant_context
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
def list_report_templates(tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        return {"templates": repos.list_report_templates(tenant.tenant_id)}
    db = _ensure_pm_tables()
    rows = db.execute("SELECT * FROM report_templates ORDER BY updated_at DESC").fetchall()
    templates = []
    for r in rows:
        t = dict(r)
        try:
            t["resources"] = json.loads(t.get("resources") or "{}")
        except (json.JSONDecodeError, TypeError):
            t["resources"] = {}
        count = db.execute("SELECT COUNT(*) as c FROM reports WHERE template_id = ?", (t["id"],)).fetchone()
        t["report_count"] = count["c"] if count else 0
        templates.append(t)
    return {"templates": templates}


@app.get("/api/reports/templates/{template_id}")
def get_report_template(template_id: str, tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        t = repos.get_report_template(tenant.tenant_id, template_id)
        if not t:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return {"template": t}
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
async def create_report_template(request: Request, tenant=Depends(get_current_tenant)):
    body = await request.json()
    template_id = str(uuid.uuid4())[:8]
    resources = body.get("resources", {})
    if not isinstance(resources, dict):
        resources = {}
    schedule = body.get("schedule", "none")

    if is_postgres_enabled():
        from backend import repos
        repos.create_report_template(
            tenant.tenant_id, template_id=template_id,
            name=body.get("name", "Untitled template"),
            body=body.get("body", ""), resources=resources, schedule=schedule,
        )
    else:
        db = _ensure_pm_tables()
        now = time.time()
        db.execute(
            "INSERT INTO report_templates (id, name, body, resources, schedule, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (template_id, body.get("name", "Untitled template"), body.get("body", ""),
             json.dumps(resources), schedule, now, now),
        )
        db.commit()

    if schedule and schedule != "none":
        _schedule_template_cron(template_id)
    return {"ok": True, "id": template_id}


@app.patch("/api/reports/templates/{template_id}")
async def update_report_template(template_id: str, request: Request, tenant=Depends(get_current_tenant)):
    body = await request.json()

    if is_postgres_enabled():
        from backend import repos
        if not repos.get_report_template(tenant.tenant_id, template_id):
            return JSONResponse({"error": "Not found"}, status_code=404)
        repos.update_report_template(tenant.tenant_id, template_id, body)
    else:
        db = _ensure_pm_tables()
        row = db.execute("SELECT * FROM report_templates WHERE id = ?", (template_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "Not found"}, status_code=404)
        updates, params = [], []
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

    if "schedule" in body:
        _unschedule_template_cron(template_id)
        if body["schedule"] and body["schedule"] != "none":
            _schedule_template_cron(template_id)
    return {"ok": True}


@app.delete("/api/reports/templates/{template_id}")
def delete_report_template(template_id: str, tenant=Depends(get_current_tenant)):
    _unschedule_template_cron(template_id)
    if is_postgres_enabled():
        from backend import repos
        repos.delete_report_template(tenant.tenant_id, template_id)
        return {"ok": True}
    db = _ensure_pm_tables()
    db.execute("DELETE FROM reports WHERE template_id = ?", (template_id,))
    db.execute("DELETE FROM report_templates WHERE id = ?", (template_id,))
    db.commit()
    return {"ok": True}


@app.post("/api/reports/templates/{template_id}/generate")
def generate_report(template_id: str, tenant=Depends(get_current_tenant)):
    """Fire agent to generate a report from the template."""
    template: Optional[dict] = None
    if is_postgres_enabled():
        from backend import repos
        template = repos.get_report_template(tenant.tenant_id, template_id)
    if not template:
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
def list_reports(template_id: str = "", limit: int = 20, tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        return {"reports": repos.list_reports(tenant.tenant_id, template_id=template_id or None, limit=limit)}
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
def delete_report(report_id: str, tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        repos.delete_report(tenant.tenant_id, report_id)
        return {"ok": True}
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


# ── Settings: model selection ──────────────────────────────────────────

MODEL_OPTIONS = [
    {"id": "anthropic/claude-opus-4.7", "label": "Claude Opus 4.7", "family": "anthropic"},
    {"id": "anthropic/claude-sonnet-4.6", "label": "Claude Sonnet 4.6", "family": "anthropic"},
    {"id": "minimax/minimax-m2.7", "label": "MiniMax M2.7", "family": "minimax"},
    {"id": "openai/gpt-5", "label": "GPT-5", "family": "openai"},
    {"id": "openai/gpt-5-mini", "label": "GPT-5 mini", "family": "openai"},
    {"id": "openai/gpt-5.4", "label": "GPT-5.4", "family": "openai"},
    {"id": "openai/gpt-5.5", "label": "GPT-5.5", "family": "openai"},
    {"id": "moonshotai/kimi-k2.6", "label": "Kimi K2.6", "family": "moonshotai"},
    {"id": "deepseek/deepseek-v4-flash", "label": "DeepSeek V4 Flash", "family": "deepseek"},
]


def _write_model_to_config(model: str):
    """Persist model selection to config.yaml (authoritative for both chat + cron)."""
    import yaml
    cfg_path = kai_home() / "config.yaml"
    cfg = {}
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    m = cfg.get("model")
    if isinstance(m, dict):
        m["default"] = model
        cfg["model"] = m
    else:
        cfg["model"] = {"default": model}
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)


@app.get("/api/settings/model")
def get_model_setting():
    return {"current": _resolve_model(), "options": MODEL_OPTIONS}


@app.post("/api/settings/model")
async def set_model_setting(request: Request):
    body = await request.json()
    model = (body.get("model") or "").strip()
    if not model:
        return JSONResponse({"error": "model required"}, status_code=400)
    try:
        _write_model_to_config(model)
    except Exception as e:
        logger.error("Failed to write model setting: %s", e, exc_info=True)
        return JSONResponse({"error": f"Failed to save: {e}"}, status_code=500)
    return {"ok": True, "current": model}


# ── MCP server management ──────────────────────────────────────────────

def _load_config_yaml() -> dict:
    import yaml
    cfg_path = kai_home() / "config.yaml"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _write_config_yaml(cfg: dict):
    import yaml
    cfg_path = kai_home() / "config.yaml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, default_flow_style=False)


def _mcp_transport(spec: dict) -> str:
    if "command" in spec:
        return "stdio"
    if "url" in spec:
        return "http"
    return "unknown"


@app.get("/api/mcp/servers")
def list_mcp_servers():
    cfg = _load_config_yaml()
    servers = cfg.get("mcp_servers") or {}
    out = []
    for name, spec in servers.items():
        if not isinstance(spec, dict):
            continue
        out.append({
            "name": name,
            "transport": _mcp_transport(spec),
            "command": spec.get("command"),
            "args": spec.get("args") or [],
            "env": spec.get("env") or {},
            "url": spec.get("url"),
            "headers": spec.get("headers") or {},
            "timeout": spec.get("timeout"),
        })
    return {"servers": out}


@app.post("/api/mcp/servers")
async def create_mcp_server(request: Request):
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        return JSONResponse(
            {"error": "name required (alphanumeric, hyphens, underscores only)"},
            status_code=400,
        )
    transport = body.get("transport") or ("stdio" if body.get("command") else "http")

    spec: dict = {}
    if transport == "stdio":
        command = (body.get("command") or "").strip()
        if not command:
            return JSONResponse({"error": "command required for stdio transport"}, status_code=400)
        spec["command"] = command
        args = body.get("args")
        if isinstance(args, list):
            spec["args"] = args
        elif isinstance(args, str) and args.strip():
            spec["args"] = [a for a in args.strip().split() if a]
        env = body.get("env")
        if isinstance(env, dict) and env:
            spec["env"] = {str(k): str(v) for k, v in env.items()}
    else:  # http
        url = (body.get("url") or "").strip()
        if not url:
            return JSONResponse({"error": "url required for http transport"}, status_code=400)
        spec["url"] = url
        headers = body.get("headers")
        if isinstance(headers, dict) and headers:
            spec["headers"] = {str(k): str(v) for k, v in headers.items()}

    timeout = body.get("timeout")
    if timeout is not None:
        try:
            spec["timeout"] = int(timeout)
        except (TypeError, ValueError):
            pass

    try:
        cfg = _load_config_yaml()
        servers = cfg.get("mcp_servers") or {}
        if not isinstance(servers, dict):
            servers = {}
        servers[name] = spec
        cfg["mcp_servers"] = servers
        _write_config_yaml(cfg)
    except Exception as e:
        logger.error("Failed to write MCP server config: %s", e, exc_info=True)
        return JSONResponse({"error": f"Failed to save: {e}"}, status_code=500)

    return {
        "ok": True,
        "name": name,
        "note": "Server added. Rediscovery happens on the next agent run.",
    }


@app.delete("/api/mcp/servers/{name}")
def delete_mcp_server(name: str):
    try:
        cfg = _load_config_yaml()
        servers = cfg.get("mcp_servers") or {}
        if not isinstance(servers, dict) or name not in servers:
            return JSONResponse({"error": "Not found"}, status_code=404)
        del servers[name]
        cfg["mcp_servers"] = servers
        _write_config_yaml(cfg)
    except Exception as e:
        logger.error("Failed to delete MCP server: %s", e, exc_info=True)
        return JSONResponse({"error": f"Failed: {e}"}, status_code=500)
    return {"ok": True}


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
    try:
        job = create_job(prompt=prompt, schedule=schedule, name=name or None, deliver="local")
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.error("Failed to create schedule: %s", e, exc_info=True)
        return JSONResponse({"error": f"Failed to create routine: {e}"}, status_code=500)
    return {"ok": True, "job": job}


@app.patch("/api/schedules/{job_id}")
async def update_schedule(job_id: str, request: Request):
    body = await request.json()
    from cron.jobs import update_job
    # Whitelist fields — prompt, name, enabled are user-editable; everything else
    # (schedule, repeat, run times) is computed and should not be overwritten here.
    allowed = {"name", "prompt", "enabled"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return JSONResponse({"error": "No updatable fields provided"}, status_code=400)
    updated = update_job(job_id, updates)
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
def list_signal_sources(tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        return {"sources": repos.list_signal_sources(tenant.tenant_id)}
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
async def create_signal_source(request: Request, tenant=Depends(get_current_tenant)):
    body = await request.json()
    source_id = str(uuid.uuid4())[:8]
    if is_postgres_enabled():
        from backend import repos
        repos.create_signal_source(
            tenant.tenant_id, source_id=source_id,
            name=(body.get("name", "").strip() or "Untitled source"),
            source_type=body.get("type", "exa"),
            config=body.get("config", {}) or {},
            filter=body.get("filter", ""),
        )
        return {"ok": True, "id": source_id}
    db = _ensure_pm_tables()
    now = time.time()
    db.execute(
        "INSERT INTO signal_sources (id, name, type, config, filter, enabled, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
        (source_id, body.get("name", "").strip() or "Untitled source",
         body.get("type", "exa"), json.dumps(body.get("config", {})),
         body.get("filter", ""), now),
    )
    db.commit()
    return {"ok": True, "id": source_id}


@app.patch("/api/signals/sources/{source_id}")
async def update_signal_source(source_id: str, request: Request, tenant=Depends(get_current_tenant)):
    body = await request.json()
    if is_postgres_enabled():
        from backend import repos
        repos.update_signal_source(tenant.tenant_id, source_id, body)
        return {"ok": True}
    db = _ensure_pm_tables()
    updates, params = [], []
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
def delete_signal_source(source_id: str, tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        repos.delete_signal_source(tenant.tenant_id, source_id)
        return {"ok": True}
    db = _ensure_pm_tables()
    db.execute("DELETE FROM signals WHERE source_id = ?", (source_id,))
    db.execute("DELETE FROM signal_sources WHERE id = ?", (source_id,))
    db.commit()
    return {"ok": True}


@app.get("/api/signals")
def list_signals(status: str = "all", limit: int = 50, tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        return {"signals": repos.list_signals(tenant.tenant_id, status=status, limit=limit)}
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
async def update_signal_status(signal_id: str, request: Request, tenant=Depends(get_current_tenant)):
    body = await request.json()
    new_status = body.get("status", "read")
    if is_postgres_enabled():
        from backend import repos
        repos.update_signal_status(tenant.tenant_id, signal_id, new_status)
        return {"ok": True}
    db = _ensure_pm_tables()
    db.execute("UPDATE signals SET status = ? WHERE id = ?", (new_status, signal_id))
    db.commit()
    return {"ok": True}


@app.post("/api/signals/sources/{source_id}/fetch")
def fetch_signal_source(source_id: str, tenant=Depends(get_current_tenant)):
    """Trigger a fetch for a specific source (or all if id='all')."""
    import threading as _threading
    tenant_id = tenant.tenant_id if is_postgres_enabled() else None

    def _run_postgres():
        from backend import repos
        sources = repos.list_signal_sources(tenant_id)
        if source_id != "all":
            sources = [s for s in sources if s["id"] == source_id]
        sources = [s for s in sources if s["enabled"]] if source_id == "all" else sources

        for src in sources:
            try:
                from signal_fetcher import fetch_source
                items = fetch_source(src["type"], src["config"], src.get("filter") or "")
            except Exception as e:
                logger.exception("Fetch failed for %s: %s", src["id"], e)
                continue

            for item in items:
                sig_id = str(uuid.uuid4())[:12]
                repos.insert_signal(
                    tenant_id, signal_id=sig_id, source_id=src["id"],
                    title=(item.get("title") or "")[:500],
                    body=(item.get("body") or "")[:5000],
                    url=item.get("url") or "",
                    author=(item.get("author") or "")[:200],
                    relevance_score=item.get("relevance_score") or 0,
                    metadata=item.get("metadata") or {},
                    external_created_at=item.get("external_created_at"),
                )
            repos.update_source_last_fetched(tenant_id, src["id"])
            logger.info("Fetched %d signals for source %s", len(items), src["id"])

    def _run_sqlite():
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
                if item.get("url"):
                    exists = db.execute("SELECT id FROM signals WHERE url = ?", (item["url"],)).fetchone()
                    if exists:
                        continue
                sig_id = str(uuid.uuid4())[:12]
                db.execute(
                    "INSERT INTO signals (id, source_id, title, body, url, author, metadata, external_created_at, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (sig_id, src["id"], item.get("title", "")[:500], item.get("body", "")[:5000],
                     item.get("url", ""), item.get("author", "")[:200],
                     json.dumps(item.get("metadata", {})),
                     item.get("external_created_at", now), now),
                )
            db.execute("UPDATE signal_sources SET last_fetched_at = ? WHERE id = ?", (now, src["id"]))
            db.commit()
            logger.info("Fetched %d signals for source %s", len(items), src["id"])

    _threading.Thread(target=(_run_postgres if tenant_id else _run_sqlite), daemon=True).start()
    return {"ok": True, "message": "Fetch started in background"}


# ── Session endpoints ───────────────────────────────────────────────────

def _get_session_db():
    from kai_state import SessionDB
    return SessionDB()


@app.get("/api/sessions")
def list_sessions(limit: int = 20, offset: int = 0, tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        sessions = repos.list_sessions(tenant.tenant_id, source="web", limit=limit, offset=offset)
        if not sessions:
            sessions = repos.list_sessions(tenant.tenant_id, source=None, limit=limit, offset=offset)
        return {"sessions": sessions}

    db = _get_session_db()
    sessions = db.list_sessions_rich(source="web", limit=limit, offset=offset)
    if not sessions:
        sessions = db.list_sessions_rich(limit=limit, offset=offset)
    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        session = repos.get_session(tenant.tenant_id, session_id)
        if not session:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        messages = repos.get_session_messages(tenant.tenant_id, session_id)
        display_messages = [
            {"id": m["id"], "role": m["role"], "content": m["content"]}
            for m in messages
            if m["role"] in ("user", "assistant") and m.get("content")
        ]
        return {"session": session, "messages": display_messages}

    db = _get_session_db()
    session = db.get_session(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    messages = db.get_messages(session_id)
    display_messages = []
    for msg in messages:
        if msg["role"] == "user" and msg.get("content"):
            display_messages.append({"id": msg["id"], "role": "user", "content": msg["content"]})
        elif msg["role"] == "assistant" and msg.get("content"):
            display_messages.append({"id": msg["id"], "role": "assistant", "content": msg["content"]})
    return {"session": session, "messages": display_messages}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        ok = repos.delete_session(tenant.tenant_id, session_id)
    else:
        db = _get_session_db()
        ok = db.delete_session(session_id)
    return {"ok": ok}


# ── Workspace endpoint ─────────────────────────────────────────────────

# ── Fleet supervisor (issue lifecycle orchestration) ───────────────────

@app.post("/api/fleet/observe")
async def fleet_observe(request: Request, tenant=Depends(get_current_tenant)):
    """Run the observer + evolver. Autonomous workflow changes get applied
    (new revision authored by 'dash'); propose-only changes get filed as
    brief actions tagged 'workflow-proposal'."""
    if not is_postgres_enabled():
        return JSONResponse({"error": "Observer requires Postgres"}, status_code=503)
    if not _refresh_github_token_env(tenant_id=tenant.tenant_id):
        return JSONResponse(
            {"error": "No GitHub installation for this tenant."}, status_code=400,
        )
    token = os.environ.get("GITHUB_TOKEN", "")

    from tools.pm_github_tools import github_list_repos
    try:
        data = json.loads(github_list_repos())
        repos_list = [r["full_name"] for r in data.get("repos", []) if r.get("full_name")]
    except Exception as e:
        return JSONResponse({"error": f"Couldn't list repos: {e}"}, status_code=502)

    # Resolve active workflow
    from agent_fleet import workflow as wf_module
    from backend import repos as pg_repos
    active = pg_repos.get_active_workflow(tenant.tenant_id)
    if active:
        try:
            workflow_obj = wf_module.parse_workflow(active["body"])
            workflow_text = active["body"]
        except Exception as e:
            return JSONResponse({"error": f"Active workflow won't parse: {e}"}, status_code=500)
    else:
        workflow_obj = wf_module.default_workflow()
        workflow_text = wf_module.DEFAULT_WORKFLOW_TEXT

    # Gather signals
    from agent_fleet.observer import gather_signals
    signals = gather_signals(workflow=workflow_obj, repos_list=repos_list, token=token)

    # Build evolver context with persistence injection
    def _save_revision(*, tenant_id, name, body, author, rationale, based_on_signals):
        return pg_repos.save_workflow_revision(
            tenant_id, name=name, body=body, author=author,
            rationale=rationale, based_on_signals=based_on_signals,
        )

    def _file_proposal(tenant_id: str, signal) -> Optional[str]:
        # File the proposal as a pending brief_action so it shows up in the brief.
        action_id = uuid.uuid4().hex[:8]
        change = signal.suggested_change or {}
        title = f"Workflow proposal: {signal.kind}"
        description = (
            f"{signal.rationale}\n\n"
            f"Suggested change: `{change.get('section')}.{change.get('field')}`: "
            f"`{change.get('from')}` → `{change.get('to')}`"
        )
        try:
            with pg_repos.get_pool().connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO brief_actions
                               (id, tenant_id, brief_id, category, title, description,
                                priority, status, references_json)
                           VALUES (%s, %s, NULL, 'workflow-proposal', %s, %s, 'medium',
                                   'pending', %s)""",
                        (action_id, tenant_id, title, description, json.dumps([])),
                    )
            return action_id
        except Exception:
            logger.exception("failed to file workflow proposal as brief_action")
            return None

    from agent_fleet.evolver import EvolverContext, evolve
    ctx = EvolverContext(
        tenant_id=tenant.tenant_id,
        workflow=workflow_obj,
        workflow_text=workflow_text,
        save_revision=_save_revision,
        file_proposal=_file_proposal,
    )
    decisions = evolve(ctx=ctx, signals=signals)

    return {
        "ok": True,
        "signals_count": len(signals),
        "decisions": [d.to_dict() for d in decisions],
        "summary": {
            "applied": sum(1 for d in decisions if d.outcome == "applied"),
            "proposed": sum(1 for d in decisions if d.outcome == "proposed"),
            "skipped": sum(1 for d in decisions if d.outcome == "skipped"),
        },
    }


@app.get("/api/fleet/delegations")
def fleet_list_delegations(tenant=Depends(get_current_tenant)):
    """List all Dash-tagged GitHub issues across the tenant's repos with
    enough state for a UI panel to render badges + 'Refile' buttons."""
    if not is_postgres_enabled():
        return JSONResponse({"error": "Fleet listing requires Postgres"}, status_code=503)

    if not _refresh_github_token_env(tenant_id=tenant.tenant_id):
        return {"ok": True, "repos": [], "delegations": [],
                "summary": "No GitHub installation for this tenant."}
    token = os.environ.get("GITHUB_TOKEN", "")

    from tools.pm_github_tools import github_list_repos
    try:
        data = json.loads(github_list_repos())
        repos_list = [r["full_name"] for r in data.get("repos", []) if r.get("full_name")]
    except Exception as e:
        return JSONResponse({"error": f"Couldn't list repos: {e}"}, status_code=502)

    from agent_fleet.supervisor import (
        _DASH_REFILED_MARKER, _DASH_STALLED_MARKER, _DASH_REVIEW_MARKER,
        _list_issue_comments,
    )
    from agent_fleet.watcher import watch_repo_delegations

    delegations = []
    for repo in repos_list:
        try:
            results = watch_repo_delegations(repo, token)
        except Exception as e:
            logger.warning("watch_repo_delegations failed for %s: %s", repo, e)
            continue
        for r in results:
            # Refile-eligible = stalled marker present AND no refile yet.
            issue_comments = _list_issue_comments(repo, r.issue_number, token)
            has_stalled = any(_DASH_STALLED_MARKER in (c.get("body") or "") for c in issue_comments)
            has_refiled = any(_DASH_REFILED_MARKER in (c.get("body") or "") for c in issue_comments)
            review_present = False
            if r.pr_number:
                pr_comments = _list_issue_comments(repo, r.pr_number, token)
                review_present = any(_DASH_REVIEW_MARKER in (c.get("body") or "") for c in pr_comments)

            delegations.append({
                "repo": repo,
                "issue_number": r.issue_number,
                "task_id": r.task_id,
                "agent_id": r.agent_id,
                "status": r.status,
                "pr_number": r.pr_number,
                "url": f"https://github.com/{repo}/issues/{r.issue_number}",
                "review_verdict": r.review.verdict if r.review else None,
                "has_dash_review": review_present,
                "has_stalled_marker": has_stalled,
                "has_refiled_marker": has_refiled,
                "refile_eligible": has_stalled and not has_refiled,
            })

    return {
        "ok": True,
        "repos": repos_list,
        "delegations": delegations,
        "summary": f"{len(delegations)} delegations across {len(repos_list)} repos",
    }


@app.post("/api/fleet/refile")
async def fleet_refile(request: Request, tenant=Depends(get_current_tenant)):
    """Refile a stalled Dash delegation to the next agent in the fallback chain.
    Body: { repo: 'owner/name', issue_number: <n>, agent_id?: '...' }
    The optional agent_id forces a specific target instead of the chain."""
    if not is_postgres_enabled():
        return JSONResponse({"error": "Refile requires Postgres"}, status_code=503)

    body = await request.json()
    repo = (body.get("repo") or "").strip()
    issue_number = body.get("issue_number")
    target_agent_id = (body.get("agent_id") or "").strip() or None

    if "/" not in repo:
        return JSONResponse({"error": "repo must be 'owner/name'"}, status_code=400)
    if not isinstance(issue_number, int) or issue_number < 1:
        return JSONResponse({"error": "issue_number is required"}, status_code=400)

    if not _refresh_github_token_env(tenant_id=tenant.tenant_id):
        return JSONResponse(
            {"error": "No GitHub installation for this tenant. Connect GitHub first."},
            status_code=400,
        )
    token = os.environ.get("GITHUB_TOKEN", "")

    # Resolve active workflow (for fallback chain)
    from agent_fleet import workflow as wf_module
    from backend import repos as pg_repos
    active = pg_repos.get_active_workflow(tenant.tenant_id)
    if active:
        try:
            workflow_obj = wf_module.parse_workflow(active["body"])
        except Exception as e:
            return JSONResponse({"error": f"Active workflow won't parse: {e}"}, status_code=500)
    else:
        workflow_obj = wf_module.default_workflow()

    from agent_fleet.supervisor import refile_delegation
    rf = refile_delegation(
        repo=repo, issue_number=issue_number, token=token,
        workflow=workflow_obj, target_agent_id=target_agent_id,
    )
    if not rf.ok:
        return JSONResponse({"ok": False, "error": rf.error}, status_code=400)
    return {
        "ok": True,
        "new_issue_number": rf.new_issue_number,
        "new_issue_url": rf.new_issue_url,
        "new_agent_id": rf.new_agent_id,
        "closed_issue_number": issue_number,
    }


@app.post("/api/fleet/supervise")
async def fleet_supervise(request: Request, tenant=Depends(get_current_tenant)):
    """Run the fleet supervisor for this tenant against all repos accessible
    to the tenant's GitHub installation. Body (optional):
        { "repos": ["owner/name", ...] }   # restrict to a subset
    """
    if not is_postgres_enabled():
        return JSONResponse({"error": "Supervisor requires Postgres"}, status_code=503)

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    repos_override = body.get("repos") if isinstance(body, dict) else None

    # Refresh tenant-scoped GitHub token
    if not _refresh_github_token_env(tenant_id=tenant.tenant_id):
        return JSONResponse(
            {"error": "No GitHub installation for this tenant. Connect GitHub first."},
            status_code=400,
        )
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return JSONResponse(
            {"error": "Failed to mint installation token"}, status_code=500,
        )

    # Resolve repos list
    if repos_override and isinstance(repos_override, list):
        repos_list = [str(r) for r in repos_override if isinstance(r, str) and "/" in r]
    else:
        from tools.pm_github_tools import github_list_repos
        try:
            data = json.loads(github_list_repos())
            repos_list = [r["full_name"] for r in data.get("repos", []) if r.get("full_name")]
        except Exception as e:
            return JSONResponse(
                {"error": f"Couldn't list repos for installation: {e}"}, status_code=502,
            )

    if not repos_list:
        return {"ok": True, "repos_scanned": 0, "delegations_seen": 0,
                "actions": [], "summary": "No repos accessible to this installation."}

    # Resolve active workflow
    from agent_fleet import workflow as wf_module
    from backend import repos as pg_repos
    active = pg_repos.get_active_workflow(tenant.tenant_id)
    if active:
        try:
            workflow_obj = wf_module.parse_workflow(active["body"])
            wf_revision = active["revision"]
        except Exception as e:
            return JSONResponse(
                {"error": f"Active workflow won't parse: {e}"}, status_code=500,
            )
    else:
        workflow_obj = wf_module.default_workflow()
        wf_revision = 0

    from agent_fleet.supervisor import run_supervisor
    report = run_supervisor(
        tenant_id=tenant.tenant_id,
        repos_list=repos_list,
        token=token,
        workflow=workflow_obj,
        workflow_revision=wf_revision,
    )

    return {
        "ok": True,
        "tenant_id": report.tenant_id,
        "workflow_revision": report.workflow_revision,
        "repos_scanned": report.repos_scanned,
        "delegations_seen": report.delegations_seen,
        "by_kind": report.by_kind(),
        "actions": [
            {
                "repo": a.repo, "issue_number": a.issue_number,
                "kind": a.kind, "detail": a.detail, "error": a.error,
            }
            for a in report.actions
        ],
    }


# ── Workflow contract (issue lifecycle) ────────────────────────────────

@app.get("/api/workflow")
def workflow_get_active(tenant=Depends(get_current_tenant)):
    """Return the active workflow for this tenant (or the default if none saved)."""
    if not is_postgres_enabled():
        return JSONResponse({"error": "Workflows require Postgres"}, status_code=503)
    from agent_fleet.workflow import (
        DEFAULT_WORKFLOW_TEXT, default_workflow, parse_workflow,
    )
    from backend import repos

    active = repos.get_active_workflow(tenant.tenant_id)
    if active:
        try:
            wf = parse_workflow(active["body"])
            parsed = wf.to_dict()
        except Exception as e:
            parsed = {"error": f"Active workflow won't parse: {e}"}
        return {
            "revision": active["revision"],
            "name": active["name"],
            "body": active["body"],
            "rationale": active["rationale"],
            "author": active["author"],
            "based_on_signals": active["based_on_signals"],
            "created_at": active["created_at"],
            "is_default": False,
            "parsed": parsed,
        }

    # No tenant-specific revision yet — return the shipped default.
    wf = default_workflow()
    return {
        "revision": 0,
        "name": wf.name,
        "body": DEFAULT_WORKFLOW_TEXT,
        "rationale": "Dash default; no tenant-specific revision yet",
        "author": "dash",
        "based_on_signals": None,
        "created_at": None,
        "is_default": True,
        "parsed": wf.to_dict(),
    }


@app.put("/api/workflow")
async def workflow_save(request: Request, tenant=Depends(get_current_tenant)):
    """Save a new workflow revision. Body: { body: <markdown+yaml>, rationale?: str }."""
    if not is_postgres_enabled():
        return JSONResponse({"error": "Workflows require Postgres"}, status_code=503)

    body = await request.json()
    text = (body.get("body") or "").strip()
    rationale = (body.get("rationale") or "").strip() or None
    if not text:
        return JSONResponse({"error": "body required"}, status_code=400)

    # Parse before saving so we never persist a malformed workflow.
    from agent_fleet.workflow import parse_workflow, WorkflowParseError
    try:
        wf = parse_workflow(text)
    except WorkflowParseError as e:
        return JSONResponse({"error": f"Invalid workflow: {e}"}, status_code=400)

    from backend import repos
    rev = repos.save_workflow_revision(
        tenant.tenant_id,
        name=wf.name,
        body=text,
        author=tenant.user_id,
        rationale=rationale,
    )
    return {"ok": True, "revision": rev, "name": wf.name}


@app.get("/api/workflow/revisions")
def workflow_list_revisions(limit: int = 20, tenant=Depends(get_current_tenant)):
    if not is_postgres_enabled():
        return JSONResponse({"error": "Workflows require Postgres"}, status_code=503)
    from backend import repos
    return {"revisions": repos.list_workflow_revisions(tenant.tenant_id, limit=limit)}


@app.get("/api/workflow/revisions/{revision}")
def workflow_get_revision(revision: int, tenant=Depends(get_current_tenant)):
    if not is_postgres_enabled():
        return JSONResponse({"error": "Workflows require Postgres"}, status_code=503)
    from backend import repos
    rev = repos.get_workflow_revision(tenant.tenant_id, revision)
    if not rev:
        return JSONResponse({"error": "Revision not found"}, status_code=404)
    return rev


@app.get("/api/workspace/status")
def workspace_status(tenant=Depends(get_current_tenant)):
    if is_postgres_enabled():
        from backend import repos
        try:
            meta = repos.get_workspace_meta(tenant.tenant_id)
            bp = repos.get_workspace_blueprint(tenant.tenant_id)
            learnings = repos.list_workspace_learnings(tenant.tenant_id, limit=50)
            onboarding = (meta or {}).get("onboarding_status") or "not_started"
            return {
                "onboarding": onboarding,
                "blueprint": bp,
                "learnings_count": len(learnings),
                "learnings": learnings,
            }
        except Exception as e:
            return {"error": str(e)}

    try:
        ctx = load_workspace_context(workspace_id=tenant.tenant_id)
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
            "learnings": learnings,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/tenant/context")
def tenant_context_debug(tenant=Depends(get_current_tenant)):
    return {"user_id": tenant.user_id, "tenant_id": tenant.tenant_id, "role": tenant.role}


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    message = body.get("message", "").strip()
    thread_id = body.get("threadId") or str(uuid.uuid4())[:12]
    source = body.get("source", "web")  # "web" for user chats, "system" for background tasks

    if not message:
        return JSONResponse({"error": "message required"}, status_code=400)

    # The agent runs in a worker thread. ContextVars don't auto-propagate
    # across thread boundaries, so we snapshot the *active* context AND
    # carry the resolved tenant explicitly via request.state — the latter
    # is the canonical Starlette-safe channel and survives any middleware
    # quirk that would leave the ContextVar empty in the endpoint context.
    request_ctx = contextvars.copy_context()
    tenant_for_thread = getattr(request.state, "tenant_context", None)

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
        # Belt-and-suspenders: explicitly re-set the ContextVar inside the
        # worker thread, regardless of what copy_context() captured. Some
        # middleware arrangements leave the ContextVar empty by the time
        # copy_context() runs in the endpoint, so trust request.state.
        # ContextVar is per-thread, so concurrent requests don't collide.
        if tenant_for_thread is not None:
            from backend.tenant_context import set_current_tenant
            set_current_tenant(tenant_for_thread)

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

            _refresh_github_token_env()
            model = _resolve_model()
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
            # Inject tenant explicitly into the agent's tool dispatch — the
            # ContextVar fallback isn't reliable across the worker-thread
            # boundary in production, so we plumb it through kwargs.
            agent.tenant_context = tenant_for_thread

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

    threading.Thread(target=request_ctx.run, args=(run_agent,), daemon=True).start()

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

_cron_health = {
    "started_at": None,
    "last_tick_at": None,
    "last_error": None,
    "ticks": 0,
    "jobs_run": 0,
}


def _start_cron_ticker():
    """Run the cron scheduler tick loop in a background thread."""
    import traceback

    def ticker():
        _cron_health["started_at"] = time.time()
        while True:
            try:
                from cron.scheduler import tick
                executed = tick(verbose=False) or 0
                _cron_health["last_tick_at"] = time.time()
                _cron_health["ticks"] += 1
                _cron_health["jobs_run"] += executed
                _cron_health["last_error"] = None
            except Exception as e:
                _cron_health["last_error"] = str(e)
                logger.error("Cron tick error: %s\n%s", e, traceback.format_exc())
            time.sleep(60)  # Check every 60 seconds

    t = threading.Thread(target=ticker, daemon=True)
    t.start()
    logger.info("Cron ticker started (60s interval)")


@app.on_event("startup")
def on_startup():
    # Seed bundled skills/ from /app/skills into $KAI_HOME/skills so the agent
    # can find pm-brief, pm-kpi, pm-onboarding, etc. on a fresh volume.
    try:
        from tools.skills_sync import sync_skills
        result = sync_skills(quiet=True)
        logger.info("Skills sync: %s", result.get("summary") if isinstance(result, dict) else "done")
    except Exception as e:
        logger.warning("Skills sync on startup failed: %s", e)
    try:
        if _refresh_github_token_env():
            logger.info("GitHub App token refreshed on startup")
    except Exception as e:
        logger.warning("GitHub App token refresh on startup failed: %s", e)
    _start_cron_ticker()


@app.get("/api/cron/status")
def cron_status():
    """Diagnostic: cron ticker health + scheduled jobs summary."""
    from cron.jobs import list_jobs
    jobs = list_jobs(include_disabled=True)
    return {
        "ticker": _cron_health,
        "now": time.time(),
        "job_count": len(jobs),
        "jobs": [
            {
                "id": j.get("id"),
                "name": j.get("name"),
                "enabled": j.get("enabled"),
                "schedule_display": j.get("schedule_display"),
                "next_run_at": j.get("next_run_at"),
                "last_run_at": j.get("last_run_at"),
                "last_status": j.get("last_status"),
                "last_error": j.get("last_error"),
            }
            for j in jobs
        ],
    }


@app.get("/api/health/postgres")
def postgres_health():
    """Diagnostic: ping Neon and report latency."""
    if not is_postgres_enabled():
        return {"ok": False, "enabled": False}
    started_at = time.perf_counter()
    try:
        with get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        return {"ok": True, "enabled": True, "latency_ms": latency_ms}
    except Exception as exc:
        return JSONResponse({"ok": False, "enabled": True, "error": str(exc)}, status_code=503)


@app.post("/api/cron/run/{job_id}")
def cron_run_now(job_id: str, request: Request):
    """Manually trigger a cron job immediately (bypasses schedule)."""
    from cron.jobs import get_job, update_job
    from kai_time import now as _kai_now
    job = get_job(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    tenant_for_thread = getattr(request.state, "tenant_context", None)

    def _run():
        if tenant_for_thread is not None:
            from backend.tenant_context import set_current_tenant
            set_current_tenant(tenant_for_thread)
        from cron.scheduler import run_job
        from cron.jobs import mark_job_run, save_job_output
        try:
            success, output, final_response, error = run_job(job)
            save_job_output(job["id"], output)
            mark_job_run(job["id"], success, error)
        except Exception as e:
            logger.exception("Manual cron run failed")
            mark_job_run(job["id"], False, str(e))

    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "message": f"Job '{job.get('name')}' triggered"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", os.environ.get("API_PORT", 3001)))
    print(f"Dash PM API server on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
