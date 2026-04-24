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
from backend.tenant_context import require_tenant_context

_kai_home = kai_home()
_DB_PATH = _kai_home / "workspace.db"


import re as _re


def _get_github_context() -> tuple:
    """Get GitHub org + known repos from workspace blueprint.

    Returns (default_org, repo_to_owner_map). Best-effort; empty on failure.
    """
    default_org = ""
    repo_map = {}
    try:
        from workspace_context import WorkspaceContext
        ws = WorkspaceContext()
        bp = ws.get_blueprint()
        if not bp:
            return default_org, repo_map
        data = bp.get("data") or {}
        for key in ("github_owner", "github_org", "org", "organization", "owner"):
            val = data.get(key)
            if isinstance(val, str) and val:
                default_org = val
                break
        gh = data.get("github") or {}
        if isinstance(gh, dict) and not default_org:
            for key in ("owner", "org", "organization"):
                val = gh.get(key)
                if isinstance(val, str) and val:
                    default_org = val
                    break
        # Build repo → owner map from repos list
        for repos_field in (data.get("repos"), data.get("repositories"), gh.get("repos") if isinstance(gh, dict) else None):
            if not repos_field:
                continue
            if isinstance(repos_field, list):
                for r in repos_field:
                    if isinstance(r, str) and "/" in r:
                        owner, name = r.split("/", 1)
                        repo_map[name.lower()] = owner
                    elif isinstance(r, dict):
                        name = r.get("name") or r.get("repo") or ""
                        owner = r.get("owner") or r.get("org") or default_org
                        if name and owner:
                            if "/" in name:
                                o, n = name.split("/", 1)
                                repo_map[n.lower()] = o
                            else:
                                repo_map[name.lower()] = owner
    except Exception:
        pass
    return default_org, repo_map


def _extract_references(text: str) -> list:
    """Auto-extract GitHub PRs, issues, and URLs from action item text."""
    refs = []
    seen = set()
    default_org, repo_map = _get_github_context()

    # Explicit URLs first (so we don't double-capture)
    for m in _re.finditer(r'https?://[^\s<>"\')\]]+', text):
        url = m.group(0).rstrip(".,;:")
        if url not in seen:
            ref_type = "pr" if "/pull/" in url else "issue" if "/issues/" in url else "link"
            title = url.split("/")[-1] or url
            refs.append({"type": ref_type, "url": url, "title": title})
            seen.add(url)

    # GitHub fully-qualified refs: org/repo#123
    for m in _re.finditer(r'([\w.-]+)/([\w.-]+)#(\d+)', text):
        owner, repo, num = m.group(1), m.group(2), m.group(3)
        url = f"https://github.com/{owner}/{repo}/issues/{num}"
        if url not in seen:
            refs.append({"type": "issue", "url": url, "title": f"{repo}#{num}"})
            seen.add(url)

    # Standalone issue refs: repo-name#123 or repo-name #123 or repo-name issue #123
    for m in _re.finditer(r'(?<![\w/])([A-Za-z][\w.-]{1,40})\s*(?:issue\s+|PR\s+)?#(\d+)', text):
        repo, num = m.group(1), m.group(2)
        # Skip common false positives
        if repo.lower() in {"issue", "pr", "pull", "ticket"}:
            continue
        key = f"{repo}#{num}"
        if key in seen:
            continue
        owner = repo_map.get(repo.lower()) or default_org
        if owner:
            url = f"https://github.com/{owner}/{repo}/issues/{num}"
            if url not in seen:
                refs.append({"type": "issue", "url": url, "title": key})
                seen.add(url)
                seen.add(key)
        else:
            refs.append({"type": "issue", "url": "", "title": key})
            seen.add(key)

    return refs


def _get_db():
    """Get a connection to the workspace database."""
    db = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=10.0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    # Create tables (without the tenant_id index — that comes after the ALTER
    # migration so legacy DBs that predate the column don't crash here).
    db.executescript("""
        CREATE TABLE IF NOT EXISTS briefs (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            workspace_id TEXT NOT NULL DEFAULT 'default',
            summary TEXT NOT NULL,
            action_items TEXT NOT NULL,
            data_sources TEXT,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS brief_actions (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
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
    for table in ("briefs", "brief_actions"):
        try:
            db.execute(f"SELECT tenant_id FROM {table} LIMIT 0")
        except Exception:
            try:
                db.execute(f"ALTER TABLE {table} ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")
                db.commit()
            except Exception:
                pass
    # Tenant index must be created AFTER the ALTER migration.
    try:
        db.execute("CREATE INDEX IF NOT EXISTS idx_briefs_tenant ON briefs(tenant_id, created_at DESC)")
        db.commit()
    except Exception:
        pass
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
    # Migration: add headline column if missing
    try:
        db.execute("SELECT headline FROM briefs LIMIT 0")
    except Exception:
        try:
            db.execute("ALTER TABLE briefs ADD COLUMN headline TEXT DEFAULT ''")
            db.commit()
        except Exception:
            pass
    return db


def _normalize_action_items(action_items):
    """Parse and normalize brief action items into a consistent list of dicts."""
    try:
        parsed_items = json.loads(action_items) if isinstance(action_items, str) else action_items
    except json.JSONDecodeError:
        return None, "action_items must be valid JSON array"

    if not isinstance(parsed_items, list):
        return None, "action_items must be valid JSON array"

    normalized_items = []
    for item in parsed_items:
        item_data = item if isinstance(item, dict) else {}
        title = item_data.get("title", "")
        description = item_data.get("description", "")
        refs = item_data.get("references", [])
        if not isinstance(refs, list):
            refs = []
        if not refs:
            refs = _extract_references(f"{title} {description}")

        normalized_items.append({
            "category": item_data.get("category", "risk"),
            "title": title,
            "description": description,
            "priority": item_data.get("priority", "medium"),
            "references": refs,
        })

    return normalized_items, None


# =============================================================================
# Tool: brief_store
# =============================================================================

def brief_store(summary: str, action_items: str, headline: str = "", data_sources: str = "", suggested_prompts: str = "", **kwargs) -> str:
    """Store a completed brief with its action items."""
    tenant = require_tenant_context(kwargs=kwargs, consumer="brief_store")
    db = _get_db()
    brief_id = str(uuid.uuid4())[:8]
    now = time.time()

    items, error = _normalize_action_items(action_items)
    if error:
        return json.dumps({"error": error})

    # Parse suggested prompts
    try:
        prompts = json.loads(suggested_prompts) if suggested_prompts else []
    except json.JSONDecodeError:
        prompts = []

    # Store brief
    db.execute(
        "INSERT INTO briefs (id, tenant_id, workspace_id, summary, action_items, data_sources, suggested_prompts, headline, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (brief_id, tenant.tenant_id, tenant.tenant_id, summary, json.dumps(items), data_sources, json.dumps(prompts), headline or "", now)
    )

    # Store individual action items
    for item in items:
        action_id = str(uuid.uuid4())[:8]
        db.execute(
            "INSERT INTO brief_actions (id, tenant_id, brief_id, category, title, description, priority, status, references_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
            (action_id, tenant.tenant_id, brief_id, item.get("category", "risk"), item.get("title", ""),
             item.get("description", ""), item.get("priority", "medium"),
             json.dumps(item.get("references", [])), now, now)
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
            "headline": {
                "type": "string",
                "description": "A single-sentence headline (8-14 words) summarizing the most important thing in this brief. Written as a newspaper headline — concrete, active verb, no filler. Good: 'Signup conversion drops 14% after paywall rollout, blocking Q2 growth target.' Bad: 'Terminal tool unblocked — commit f6f674ba fixed the critical shell access blocker.' This appears as the big headline on the brief view; the summary body stays in action items and sections below.",
            },
            "summary": {
                "type": "string",
                "description": "The full brief markdown content (without duplicating the headline — the headline renders separately above)."
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
        "required": ["headline", "summary", "action_items"]
    }
}


# =============================================================================
# Tool: brief_get_latest
# =============================================================================

def brief_get_latest(**kwargs) -> str:
    """Get the most recent brief."""
    tenant = require_tenant_context(kwargs=kwargs, consumer="brief_get_latest")
    db = _get_db()
    row = db.execute("SELECT * FROM briefs WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 1", (tenant.tenant_id,)).fetchone()
    if not row:
        return json.dumps({"message": "No briefs stored yet."})

    actions = db.execute(
        "SELECT * FROM brief_actions WHERE tenant_id = ? AND brief_id = ? ORDER BY created_at",
        (tenant.tenant_id, row["id"])
    ).fetchall()

    out = {
        "brief_id": row["id"],
        "summary": row["summary"],
        "action_items": [dict(a) for a in actions],
        "data_sources": row["data_sources"],
        "created_at": row["created_at"],
    }
    try:
        out["headline"] = row["headline"] or ""
    except (IndexError, KeyError):
        out["headline"] = ""
    return json.dumps(out)


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
    tenant = require_tenant_context(kwargs=kwargs, consumer="brief_get_action_items")
    db = _get_db()
    if status == "all":
        rows = db.execute("SELECT * FROM brief_actions WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 20", (tenant.tenant_id,)).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM brief_actions WHERE tenant_id = ? AND status = ? ORDER BY created_at DESC LIMIT 20",
            (tenant.tenant_id, status)
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
    tenant = require_tenant_context(kwargs=kwargs, consumer="brief_resolve_action")
    db = _get_db()
    row = db.execute("SELECT * FROM brief_actions WHERE id = ? AND tenant_id = ?", (action_id, tenant.tenant_id)).fetchone()
    if not row:
        return json.dumps({"error": f"Action item {action_id} not found."})

    db.execute(
        "UPDATE brief_actions SET status = ?, updated_at = ? WHERE id = ? AND tenant_id = ?",
        (status, time.time(), action_id, tenant.tenant_id)
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
        headline=args.get("headline", ""),
        data_sources=args.get("data_sources", ""),
        suggested_prompts=args.get("suggested_prompts", "[]"),
        **kw),
)

registry.register(
    name="brief_get_latest",
    toolset="pm-brief",
    schema=BRIEF_GET_LATEST_SCHEMA,
    handler=lambda args, **kw: brief_get_latest(**kw),
)

registry.register(
    name="brief_get_action_items",
    toolset="pm-brief",
    schema=BRIEF_GET_ACTION_ITEMS_SCHEMA,
    handler=lambda args, **kw: brief_get_action_items(
        status=args.get("status", "pending"),
        **kw),
)

registry.register(
    name="brief_resolve_action",
    toolset="pm-brief",
    schema=BRIEF_RESOLVE_ACTION_SCHEMA,
    handler=lambda args, **kw: brief_resolve_action(
        action_id=args.get("action_id", ""),
        status=args.get("status", "resolved"),
        **kw),
)
