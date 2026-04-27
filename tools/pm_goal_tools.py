"""
PM Goal tools — let the agent track goal progress during briefs.

The agent uses these during a daily brief to:
  1. List active goals
  2. Evaluate each (reading live data from GitHub/PostHog/etc.)
  3. Write back progress %, trajectory, and 1-3 action items per goal
  4. Snapshots are stored so we can chart goal progress over time
"""

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

from kai_env import kai_home
from backend.db.postgres_client import is_postgres_enabled
from backend.tenant_context import require_tenant_context
from tools.registry import registry


_DB_PATH = kai_home() / "integrations.db"


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=10.0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    # Ensure tables — mirrors server._ensure_pm_tables so the agent can run
    # standalone (e.g. cron) without the HTTP server booting first.
    db.executescript("""
        CREATE TABLE IF NOT EXISTS goals (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
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
            tenant_id TEXT NOT NULL DEFAULT 'default',
            goal_id TEXT NOT NULL,
            progress INTEGER DEFAULT 0,
            trajectory TEXT,
            action_items TEXT DEFAULT '[]',
            brief_id TEXT,
            notes TEXT,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_goal_snapshots_goal ON goal_snapshots(goal_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_goals_tenant ON goals(tenant_id, created_at DESC);
    """)
    for col, ddl in (
        ("tenant_id", "ALTER TABLE goals ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'"),
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
    try:
        db.execute("SELECT tenant_id FROM goal_snapshots LIMIT 0")
    except Exception:
        try:
            db.execute("ALTER TABLE goal_snapshots ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")
            db.commit()
        except Exception:
            pass
    return db


# =============================================================================
# Tool: goal_list
# =============================================================================

def goal_list(status: str = "active", **kwargs) -> str:
    tenant = require_tenant_context(kwargs=kwargs, consumer="goal_list")
    if is_postgres_enabled():
        from backend import repos
        goals = repos.list_goals(tenant.tenant_id, status=status)
        return json.dumps({"count": len(goals), "goals": goals})

    db = _db()
    if status == "all":
        rows = db.execute("SELECT * FROM goals WHERE tenant_id = ? ORDER BY created_at DESC", (tenant.tenant_id,)).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM goals WHERE tenant_id = ? AND status = ? ORDER BY created_at DESC", (tenant.tenant_id, status)
        ).fetchall()
    goals = []
    for r in rows:
        g = dict(r)
        for field in ("related_items", "action_items"):
            try:
                g[field] = json.loads(g.get(field) or "[]")
            except (json.JSONDecodeError, TypeError):
                g[field] = []
        goals.append(g)
    return json.dumps({"count": len(goals), "goals": goals})


GOAL_LIST_SCHEMA = {
    "name": "goal_list",
    "description": "List goals. Use during daily brief to find goals that need progress evaluation.",
    "parameters": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["active", "completed", "paused", "missed", "all"],
                "description": "Filter by status (default: active)",
            }
        },
    },
}


# =============================================================================
# Tool: goal_get
# =============================================================================

def goal_get(goal_id: str, include_history: bool = False, **kwargs) -> str:
    tenant = require_tenant_context(kwargs=kwargs, consumer="goal_get")
    if is_postgres_enabled():
        from backend import repos
        g = repos.get_goal(tenant.tenant_id, goal_id)
        if not g:
            return json.dumps({"error": f"Goal {goal_id} not found."})
        if include_history:
            g["history"] = repos.goal_history(tenant.tenant_id, goal_id, limit=10)
        return json.dumps(g)

    db = _db()
    row = db.execute("SELECT * FROM goals WHERE id = ? AND tenant_id = ?", (goal_id, tenant.tenant_id)).fetchone()
    if not row:
        return json.dumps({"error": f"Goal {goal_id} not found."})
    g = dict(row)
    for field in ("related_items", "action_items"):
        try:
            g[field] = json.loads(g.get(field) or "[]")
        except (json.JSONDecodeError, TypeError):
            g[field] = []
    if include_history:
        hist_rows = db.execute(
            "SELECT * FROM goal_snapshots WHERE goal_id = ? AND tenant_id = ? ORDER BY created_at DESC LIMIT 10",
            (goal_id, tenant.tenant_id),
        ).fetchall()
        history = []
        for h in hist_rows:
            hd = dict(h)
            try:
                hd["action_items"] = json.loads(hd.get("action_items") or "[]")
            except (json.JSONDecodeError, TypeError):
                hd["action_items"] = []
            history.append(hd)
        g["history"] = history
    return json.dumps(g)


GOAL_GET_SCHEMA = {
    "name": "goal_get",
    "description": "Get a specific goal, optionally with its recent progress history.",
    "parameters": {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "The goal ID"},
            "include_history": {
                "type": "boolean",
                "description": "Include the last 10 progress snapshots",
            },
        },
        "required": ["goal_id"],
    },
}


# =============================================================================
# Tool: goal_update_progress
# =============================================================================

def goal_update_progress(
    goal_id: str,
    progress: int,
    trajectory: str = "",
    action_items: str = "[]",
    brief_id: str = "",
    notes: str = "",
    **kwargs,
) -> str:
    """Update a goal's progress and write a snapshot for trajectory tracking."""
    tenant = require_tenant_context(kwargs=kwargs, consumer="goal_update_progress")

    try:
        items = json.loads(action_items) if isinstance(action_items, str) else action_items
        if not isinstance(items, list):
            items = []
    except json.JSONDecodeError:
        return json.dumps({"error": "action_items must be valid JSON array"})

    progress = max(0, min(100, int(progress)))
    snapshot_id = uuid.uuid4().hex[:12]

    if is_postgres_enabled():
        from backend import repos
        ok = repos.update_goal_progress(
            tenant.tenant_id, goal_id, progress=progress, trajectory=trajectory,
            action_items=items, snapshot_id=snapshot_id,
            brief_id=brief_id or None, notes=notes or None,
        )
        if not ok:
            return json.dumps({"error": f"Goal {goal_id} not found."})
        return json.dumps({"ok": True, "goal_id": goal_id, "progress": progress,
                           "snapshot_id": snapshot_id, "action_items_count": len(items)})

    db = _db()
    row = db.execute("SELECT * FROM goals WHERE id = ? AND tenant_id = ?", (goal_id, tenant.tenant_id)).fetchone()
    if not row:
        return json.dumps({"error": f"Goal {goal_id} not found."})

    now = time.time()
    db.execute(
        "UPDATE goals SET progress = ?, trajectory = ?, action_items = ?, last_evaluated_at = ?, updated_at = ? WHERE id = ? AND tenant_id = ?",
        (progress, trajectory, json.dumps(items), now, now, goal_id, tenant.tenant_id),
    )
    db.execute(
        "INSERT INTO goal_snapshots (id, tenant_id, goal_id, progress, trajectory, action_items, brief_id, notes, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (snapshot_id, tenant.tenant_id, goal_id, progress, trajectory, json.dumps(items), brief_id or None, notes or None, now),
    )
    db.commit()
    return json.dumps({
        "ok": True, "goal_id": goal_id, "progress": progress,
        "snapshot_id": snapshot_id, "action_items_count": len(items),
    })


GOAL_UPDATE_PROGRESS_SCHEMA = {
    "name": "goal_update_progress",
    "description": (
        "Update a goal's progress percentage, trajectory, and action items. "
        "Call this for each active goal during a daily brief after reviewing recent "
        "activity (PRs, metrics, team progress). A snapshot is stored for trajectory charting."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "The goal ID"},
            "progress": {
                "type": "integer",
                "description": "Progress 0-100 based on observable evidence.",
            },
            "trajectory": {
                "type": "string",
                "description": "One-line status: 'on-track', 'at-risk', 'behind', 'ahead', 'stalled'",
            },
            "action_items": {
                "type": "string",
                "description": (
                    'JSON array of action items specific to this goal. Each: '
                    '{"title": "...", "description": "...", "priority": "critical|high|medium|low", '
                    '"references": [{"type":"issue|pr|link","url":"...","title":"..."}]}. '
                    "Use 1-3 items that would move this goal forward meaningfully."
                ),
            },
            "brief_id": {
                "type": "string",
                "description": "Optional brief ID if this update is part of a brief run.",
            },
            "notes": {
                "type": "string",
                "description": "Optional short note explaining what changed since last evaluation.",
            },
        },
        "required": ["goal_id", "progress"],
    },
}


# =============================================================================
# Registry
# =============================================================================

registry.register(
    name="goal_list",
    toolset="pm-goals",
    schema=GOAL_LIST_SCHEMA,
    handler=lambda args, **kw: goal_list(status=args.get("status", "active"), **kw),
)

registry.register(
    name="goal_get",
    toolset="pm-goals",
    schema=GOAL_GET_SCHEMA,
    handler=lambda args, **kw: goal_get(
        goal_id=args.get("goal_id", ""),
        include_history=bool(args.get("include_history", False)),
        **kw,
    ),
)

registry.register(
    name="goal_update_progress",
    toolset="pm-goals",
    schema=GOAL_UPDATE_PROGRESS_SCHEMA,
    handler=lambda args, **kw: goal_update_progress(
        goal_id=args.get("goal_id", ""),
        progress=int(args.get("progress", 0)),
        trajectory=args.get("trajectory", ""),
        action_items=args.get("action_items", "[]"),
        brief_id=args.get("brief_id", ""),
        notes=args.get("notes", ""),
        **kw,
    ),
)
