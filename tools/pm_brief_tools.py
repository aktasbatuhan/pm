"""
PM Brief tools — store, retrieve, and manage daily briefs and action items.

These tools power the daily brief workflow. The agent produces briefs via the
pm-brief/daily-brief skill, stores them here, and users interact with action
items to start contextual chat sessions.
"""

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

from kai_env import kai_home

_kai_home = kai_home()
_DB_PATH = _kai_home / "workspace.db"


import re as _re


def _extract_references(text: str) -> list:
    """Auto-extract GitHub PRs, issues, and URLs from action item text."""
    refs = []
    seen = set()

    # GitHub issue/PR patterns: org/repo#123 or repo #123
    for m in _re.finditer(r'([\w.-]+/[\w.-]+)[# ]+#?(\d+)', text):
        repo, num = m.group(1), m.group(2)
        url = f"https://github.com/{repo}/issues/{num}"
        if url not in seen:
            refs.append({"type": "issue", "url": url, "title": f"{repo}#{num}"})
            seen.add(url)

    # Standalone issue refs: repo-name #123 or repo-name issue #123
    for m in _re.finditer(r'([\w-]+)\s+(?:issue\s+)?#(\d+)', text):
        repo, num = m.group(1), m.group(2)
        key = f"{repo}#{num}"
        if key not in seen:
            refs.append({"type": "issue", "url": "", "title": key})
            seen.add(key)

    # Explicit URLs
    for m in _re.finditer(r'https?://[^\s<>"\')\]]+', text):
        url = m.group(0).rstrip(".,;:")
        if url not in seen:
            ref_type = "pr" if "/pull/" in url else "issue" if "/issues/" in url else "link"
            refs.append({"type": ref_type, "url": url, "title": url.split("/")[-1]})
            seen.add(url)

    return refs


def _get_db():
    """Get a connection to the workspace database."""
    db = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=10.0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    # Ensure tables exist
    db.executescript("""
        CREATE TABLE IF NOT EXISTS briefs (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL DEFAULT 'default',
            summary TEXT NOT NULL,
            action_items TEXT NOT NULL,
            data_sources TEXT,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS brief_actions (
            id TEXT PRIMARY KEY,
            brief_id TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'pending',
            chat_session_id TEXT,
            references_json TEXT DEFAULT '[]',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_briefs_created ON briefs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_actions_brief ON brief_actions(brief_id);
        CREATE INDEX IF NOT EXISTS idx_actions_status ON brief_actions(status);
    """)
    # Migration: add suggested_prompts column if missing
    try:
        db.execute("SELECT suggested_prompts FROM briefs LIMIT 0")
    except Exception:
        try:
            db.execute("ALTER TABLE briefs ADD COLUMN suggested_prompts TEXT DEFAULT '[]'")
            db.commit()
        except Exception:
            pass
    # Migration: add references_json column if missing
    try:
        db.execute("SELECT references_json FROM brief_actions LIMIT 0")
    except Exception:
        try:
            db.execute("ALTER TABLE brief_actions ADD COLUMN references_json TEXT DEFAULT '[]'")
            db.commit()
        except Exception:
            pass
    return db


# =============================================================================
# Tool: brief_store
# =============================================================================

def brief_store(summary: str, action_items: str, data_sources: str = "", suggested_prompts: str = "", **kwargs) -> str:
    """Store a completed brief with its action items."""
    db = _get_db()
    brief_id = str(uuid.uuid4())[:8]
    now = time.time()

    # Parse action items JSON
    try:
        items = json.loads(action_items) if isinstance(action_items, str) else action_items
    except json.JSONDecodeError:
        return json.dumps({"error": "action_items must be valid JSON array"})

    # Parse suggested prompts
    try:
        prompts = json.loads(suggested_prompts) if suggested_prompts else []
    except json.JSONDecodeError:
        prompts = []

    # Store brief
    db.execute(
        "INSERT INTO briefs (id, summary, action_items, data_sources, suggested_prompts, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (brief_id, summary, json.dumps(items), data_sources, json.dumps(prompts), now)
    )

    # Store individual action items
    for item in items:
        action_id = str(uuid.uuid4())[:8]
        # Extract references: explicit from agent, or auto-detect from text
        refs = item.get("references", [])
        if not refs:
            refs = _extract_references(item.get("title", "") + " " + item.get("description", ""))
        db.execute(
            "INSERT INTO brief_actions (id, brief_id, category, title, description, priority, status, references_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
            (action_id, brief_id, item.get("category", "risk"), item.get("title", ""),
             item.get("description", ""), item.get("priority", "medium"),
             json.dumps(refs), now, now)
        )

    db.commit()
    return json.dumps({
        "success": True,
        "brief_id": brief_id,
        "action_items_count": len(items),
        "message": f"Brief stored with {len(items)} action items."
    })


BRIEF_STORE_SCHEMA = {
    "name": "brief_store",
    "description": "Store a completed daily brief with structured action items. Call this after producing a brief to persist it.",
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "The full brief markdown content"
            },
            "action_items": {
                "type": "string",
                "description": 'JSON array of action items. Each: {"category": "pain-point|next-feature|stakeholder-update|risk|team", "title": "...", "description": "...", "priority": "critical|high|medium|low", "references": [{"type": "issue|pr|link|email", "url": "...", "title": "..."}]}. References are optional; if omitted, they are auto-extracted from the description text.'
            },
            "data_sources": {
                "type": "string",
                "description": "Comma-separated list of data sources checked (e.g. 'github,posthog,linear')"
            },
            "suggested_prompts": {
                "type": "string",
                "description": "JSON array of 3-5 follow-up questions the user might ask based on this brief. Each should be specific and actionable, referencing real data from the brief. E.g. [\"Why is Sprint 59 behind schedule?\", \"Investigate the JWT secret exposure in kai-backend #278\", \"Draft a stakeholder update on the pricing launch\"]"
            }
        },
        "required": ["summary", "action_items"]
    }
}


# =============================================================================
# Tool: brief_get_latest
# =============================================================================

def brief_get_latest(**kwargs) -> str:
    """Get the most recent brief."""
    db = _get_db()
    row = db.execute("SELECT * FROM briefs ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        return json.dumps({"message": "No briefs stored yet."})

    actions = db.execute(
        "SELECT * FROM brief_actions WHERE brief_id = ? ORDER BY created_at",
        (row["id"],)
    ).fetchall()

    return json.dumps({
        "brief_id": row["id"],
        "summary": row["summary"],
        "action_items": [dict(a) for a in actions],
        "data_sources": row["data_sources"],
        "created_at": row["created_at"]
    })


BRIEF_GET_LATEST_SCHEMA = {
    "name": "brief_get_latest",
    "description": "Get the most recent daily brief with its action items. Use this to compare against current state when producing a new brief.",
    "parameters": {"type": "object", "properties": {}}
}


# =============================================================================
# Tool: brief_get_action_items
# =============================================================================

def brief_get_action_items(status: str = "pending", **kwargs) -> str:
    """Get action items filtered by status."""
    db = _get_db()
    if status == "all":
        rows = db.execute("SELECT * FROM brief_actions ORDER BY created_at DESC LIMIT 20").fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM brief_actions WHERE status = ? ORDER BY created_at DESC LIMIT 20",
            (status,)
        ).fetchall()

    if not rows:
        return json.dumps({"message": f"No {status} action items.", "items": []})

    return json.dumps({
        "count": len(rows),
        "items": [dict(r) for r in rows]
    })


BRIEF_GET_ACTION_ITEMS_SCHEMA = {
    "name": "brief_get_action_items",
    "description": "Get action items from recent briefs. Defaults to pending items. Use 'all' to see everything.",
    "parameters": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["pending", "in-progress", "resolved", "dismissed", "all"],
                "description": "Filter by status (default: pending)"
            }
        }
    }
}


# =============================================================================
# Tool: brief_resolve_action
# =============================================================================

def brief_resolve_action(action_id: str, status: str = "resolved", **kwargs) -> str:
    """Update an action item's status."""
    db = _get_db()
    row = db.execute("SELECT * FROM brief_actions WHERE id = ?", (action_id,)).fetchone()
    if not row:
        return json.dumps({"error": f"Action item {action_id} not found."})

    db.execute(
        "UPDATE brief_actions SET status = ?, updated_at = ? WHERE id = ?",
        (status, time.time(), action_id)
    )
    db.commit()
    return json.dumps({"success": True, "action_id": action_id, "new_status": status})


BRIEF_RESOLVE_ACTION_SCHEMA = {
    "name": "brief_resolve_action",
    "description": "Update an action item's status (e.g., mark as resolved or in-progress).",
    "parameters": {
        "type": "object",
        "properties": {
            "action_id": {
                "type": "string",
                "description": "The action item ID"
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in-progress", "resolved", "dismissed"],
                "description": "New status (default: resolved)"
            }
        },
        "required": ["action_id"]
    }
}


# =============================================================================
# Registry
# =============================================================================

from tools.registry import registry

registry.register(
    name="brief_store",
    toolset="pm-brief",
    schema=BRIEF_STORE_SCHEMA,
    handler=lambda args, **kw: brief_store(
        summary=args.get("summary", ""),
        action_items=args.get("action_items", "[]"),
        data_sources=args.get("data_sources", ""),
        suggested_prompts=args.get("suggested_prompts", "[]")),
)

registry.register(
    name="brief_get_latest",
    toolset="pm-brief",
    schema=BRIEF_GET_LATEST_SCHEMA,
    handler=lambda args, **kw: brief_get_latest(),
)

registry.register(
    name="brief_get_action_items",
    toolset="pm-brief",
    schema=BRIEF_GET_ACTION_ITEMS_SCHEMA,
    handler=lambda args, **kw: brief_get_action_items(
        status=args.get("status", "pending")),
)

registry.register(
    name="brief_resolve_action",
    toolset="pm-brief",
    schema=BRIEF_RESOLVE_ACTION_SCHEMA,
    handler=lambda args, **kw: brief_resolve_action(
        action_id=args.get("action_id", ""),
        status=args.get("status", "resolved")),
)
