"""Per-tenant repository functions backed by Neon Postgres.

These return SQLite-shaped dicts (timestamps as unix floats, action_items as
JSON strings, etc.) so existing endpoint code can stay mostly unchanged when
swapping from SQLite to Postgres.

Convention: every function takes ``tenant_id`` as its first arg and only
returns rows belonging to that tenant.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from backend.db.postgres_client import get_pool


def _ts(value: Any) -> Optional[float]:
    """timestamptz → unix float (None-safe)."""
    if value is None:
        return None
    try:
        return value.timestamp()
    except AttributeError:
        return float(value) if value is not None else None


def _shape_brief(row: dict) -> dict:
    return {
        "id": row["id"],
        "tenant_id": str(row["tenant_id"]),
        "summary": row["summary"],
        "headline": row.get("headline") or "",
        "action_items": json.dumps(row["action_items"]) if isinstance(row["action_items"], (list, dict)) else (row["action_items"] or "[]"),
        "suggested_prompts": json.dumps(row["suggested_prompts"]) if isinstance(row["suggested_prompts"], (list, dict)) else (row["suggested_prompts"] or "[]"),
        "data_sources": row.get("data_sources") or "",
        "cover_url": row.get("cover_url") or "",
        "created_at": _ts(row["created_at"]),
    }


def _shape_action(row: dict) -> dict:
    refs = row.get("references_json") or []
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except json.JSONDecodeError:
            refs = []
    return {
        "id": row["id"],
        "tenant_id": str(row["tenant_id"]),
        "brief_id": row["brief_id"],
        "category": row["category"],
        "title": row["title"],
        "description": row["description"],
        "priority": row["priority"],
        "status": row["status"],
        "chat_session_id": row.get("chat_session_id"),
        "references": refs,
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
    }


# ---------------------------------------------------------------------------
# Briefs
# ---------------------------------------------------------------------------

def list_briefs(tenant_id: str, limit: int = 20) -> list[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT b.*,
                       (SELECT count(*) FROM brief_actions a WHERE a.brief_id = b.id) AS action_count,
                       (SELECT count(*) FROM brief_actions a WHERE a.brief_id = b.id AND a.status = 'pending') AS pending_count
                  FROM briefs b
                 WHERE b.tenant_id = %s
                 ORDER BY b.created_at DESC
                 LIMIT %s
                """,
                (tenant_id, limit),
            )
            rows = cur.fetchall()
    out = []
    for r in rows:
        d = _shape_brief(r)
        d["action_count"] = r["action_count"]
        d["pending_count"] = r["pending_count"]
        out.append(d)
    return out


def get_brief(tenant_id: str, brief_id: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM briefs WHERE tenant_id = %s AND id = %s",
                (tenant_id, brief_id),
            )
            row = cur.fetchone()
    return _shape_brief(row) if row else None


def get_latest_brief(tenant_id: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM briefs WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 1",
                (tenant_id,),
            )
            row = cur.fetchone()
    return _shape_brief(row) if row else None


def list_brief_actions(tenant_id: str, brief_id: Optional[str] = None,
                       status: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM brief_actions WHERE tenant_id = %s"
    args: list[Any] = [tenant_id]
    if brief_id:
        sql += " AND brief_id = %s"
        args.append(brief_id)
    if status:
        sql += " AND status = %s"
        args.append(status)
    sql += " ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'in-progress' THEN 1 ELSE 2 END, created_at"

    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()
    return [_shape_action(r) for r in rows]


def update_brief_action(tenant_id: str, action_id: str, *, status: Optional[str] = None,
                        chat_session_id: Optional[str] = None) -> bool:
    sets = []
    args: list[Any] = []
    if status is not None:
        sets.append("status = %s")
        args.append(status)
    if chat_session_id is not None:
        sets.append("chat_session_id = %s")
        args.append(chat_session_id)
    if not sets:
        return False
    args.extend([tenant_id, action_id])
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE brief_actions SET {', '.join(sets)} WHERE tenant_id = %s AND id = %s",
                args,
            )
            return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

def get_workspace_meta(tenant_id: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM workspace_meta WHERE tenant_id = %s",
                (tenant_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "tenant_id": str(row["tenant_id"]),
        "onboarding_status": row["onboarding_status"],
        "onboarding_phase": row["onboarding_phase"],
        "onboarded_at": _ts(row["onboarded_at"]),
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
    }


def get_workspace_blueprint(tenant_id: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM workspace_blueprint WHERE tenant_id = %s",
                (tenant_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "summary": row["summary"] or "",
        "data": row["data"] or {},
        "updated_at": _ts(row["updated_at"]),
    }


def list_workspace_learnings(tenant_id: str, limit: int = 50) -> list[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, category, content, source_thread, created_at
                  FROM workspace_learnings
                 WHERE tenant_id = %s
                 ORDER BY created_at DESC
                 LIMIT %s
                """,
                (tenant_id, limit),
            )
            rows = cur.fetchall()
    return [
        {
            "id": r["id"],
            "category": r["category"],
            "content": r["content"],
            "source_thread": r["source_thread"],
            "created_at": _ts(r["created_at"]),
        }
        for r in rows
    ]
