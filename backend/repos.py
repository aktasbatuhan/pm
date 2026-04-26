"""Per-tenant repository functions backed by Neon Postgres.

These return SQLite-shaped dicts (timestamps as unix floats, action_items as
JSON strings, etc.) so existing endpoint code can stay mostly unchanged when
swapping from SQLite to Postgres.

Convention: every function takes ``tenant_id`` as its first arg and only
returns rows belonging to that tenant.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
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


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def list_sessions(tenant_id: str, source: Optional[str] = "web",
                  limit: int = 20, offset: int = 0) -> list[dict]:
    sql = """
        SELECT id, source, user_id, model, started_at, ended_at, title,
               message_count, tool_call_count, input_tokens, output_tokens
          FROM agent_sessions
         WHERE tenant_id = %s
    """
    args: list[Any] = [tenant_id]
    if source:
        sql += " AND source = %s"
        args.append(source)
    sql += " ORDER BY started_at DESC LIMIT %s OFFSET %s"
    args.extend([limit, offset])

    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()

    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "source": r["source"],
            "user_id": r["user_id"],
            "model": r["model"],
            "started_at": _ts(r["started_at"]),
            "ended_at": _ts(r["ended_at"]),
            "title": r["title"],
            "message_count": r["message_count"] or 0,
            "tool_call_count": r["tool_call_count"] or 0,
            "input_tokens": r["input_tokens"] or 0,
            "output_tokens": r["output_tokens"] or 0,
        })
    return out


def get_session(tenant_id: str, session_id: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM agent_sessions WHERE tenant_id = %s AND id = %s",
                (tenant_id, session_id),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "source": row["source"],
        "user_id": row["user_id"],
        "model": row["model"],
        "system_prompt": row["system_prompt"],
        "title": row["title"],
        "started_at": _ts(row["started_at"]),
        "ended_at": _ts(row["ended_at"]),
        "message_count": row["message_count"] or 0,
        "tool_call_count": row["tool_call_count"] or 0,
    }


def get_session_messages(tenant_id: str, session_id: str) -> list[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, role, content, tool_call_id, tool_calls, tool_name, timestamp
                  FROM agent_messages
                 WHERE tenant_id = %s AND session_id = %s
                 ORDER BY timestamp, id
                """,
                (tenant_id, session_id),
            )
            rows = cur.fetchall()
    return [
        {
            "id": r["id"],
            "role": r["role"],
            "content": r["content"],
            "tool_call_id": r["tool_call_id"],
            "tool_calls": r["tool_calls"],
            "tool_name": r["tool_name"],
            "timestamp": _ts(r["timestamp"]),
        }
        for r in rows
    ]


def delete_session(tenant_id: str, session_id: str) -> bool:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM agent_sessions WHERE tenant_id = %s AND id = %s",
                (tenant_id, session_id),
            )
            return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------

def _shape_goal(row: dict) -> dict:
    related = row.get("related_items") or []
    actions = row.get("action_items") or []
    if isinstance(related, str):
        try: related = json.loads(related)
        except: related = []
    if isinstance(actions, str):
        try: actions = json.loads(actions)
        except: actions = []
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row.get("description"),
        "target_date": row.get("target_date"),
        "status": row.get("status"),
        "progress": row.get("progress") or 0,
        "trajectory": row.get("trajectory"),
        "related_items": related,
        "action_items": actions,
        "last_evaluated_at": _ts(row.get("last_evaluated_at")),
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
    }


def list_goals(tenant_id: str, status: Optional[str] = "active") -> list[dict]:
    sql = "SELECT * FROM goals WHERE tenant_id = %s"
    args: list[Any] = [tenant_id]
    if status and status != "all":
        sql += " AND status = %s"
        args.append(status)
    sql += " ORDER BY created_at DESC"
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return [_shape_goal(r) for r in cur.fetchall()]


def create_goal(tenant_id: str, *, goal_id: str, title: str,
                description: str = "", target_date: str = "") -> None:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO goals (id, tenant_id, title, description, target_date, status, progress)
                   VALUES (%s, %s, %s, %s, %s, 'active', 0)""",
                (goal_id, tenant_id, title, description, target_date),
            )


def update_goal(tenant_id: str, goal_id: str, fields: dict) -> bool:
    allowed = {"title", "description", "target_date", "status",
               "progress", "trajectory", "related_items"}
    sets, args = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "related_items" and isinstance(v, list):
            v = json.dumps(v)
        sets.append(f"{k} = %s")
        args.append(v)
    if not sets:
        return False
    args.extend([tenant_id, goal_id])
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE goals SET {', '.join(sets)} WHERE tenant_id = %s AND id = %s",
                args,
            )
            return cur.rowcount > 0


def delete_goal(tenant_id: str, goal_id: str) -> bool:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM goals WHERE tenant_id = %s AND id = %s",
                (tenant_id, goal_id),
            )
            return cur.rowcount > 0


def goal_history(tenant_id: str, goal_id: str, limit: int = 20) -> list[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM goal_snapshots
                    WHERE tenant_id = %s AND goal_id = %s
                    ORDER BY created_at DESC LIMIT %s""",
                (tenant_id, goal_id, limit),
            )
            rows = cur.fetchall()
    out = []
    for r in rows:
        ai = r.get("action_items") or []
        if isinstance(ai, str):
            try: ai = json.loads(ai)
            except: ai = []
        out.append({
            "id": r["id"],
            "goal_id": r["goal_id"],
            "progress": r["progress"] or 0,
            "trajectory": r["trajectory"],
            "action_items": ai,
            "brief_id": r["brief_id"],
            "notes": r["notes"],
            "created_at": _ts(r["created_at"]),
        })
    return out


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------

def _shape_kpi(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row.get("description"),
        "unit": row.get("unit"),
        "direction": row.get("direction"),
        "target_value": row.get("target_value"),
        "current_value": row.get("current_value"),
        "previous_value": row.get("previous_value"),
        "measurement_plan": row.get("measurement_plan") or "",
        "measurement_status": row.get("measurement_status"),
        "measurement_error": row.get("measurement_error"),
        "cron_job_id": row.get("cron_job_id"),
        "status": row.get("status"),
        "created_at": _ts(row.get("created_at")),
        "updated_at": _ts(row.get("updated_at")),
        "last_measured_at": _ts(row.get("last_measured_at")),
    }


def list_kpis(tenant_id: str, status: Optional[str] = "active",
              with_history: bool = True, with_flags: bool = True) -> list[dict]:
    sql = "SELECT * FROM kpis WHERE tenant_id = %s"
    args: list[Any] = [tenant_id]
    if status and status != "all":
        sql += " AND status = %s"
        args.append(status)
    sql += " ORDER BY created_at DESC"

    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            kpi_rows = cur.fetchall()
            kpis = [_shape_kpi(r) for r in kpi_rows]
            if with_history:
                for k in kpis:
                    cur.execute(
                        """SELECT id, value, source, notes, recorded_at FROM kpi_values
                            WHERE tenant_id = %s AND kpi_id = %s
                            ORDER BY recorded_at DESC LIMIT 60""",
                        (tenant_id, k["id"]),
                    )
                    k["history"] = [
                        {**dict(r), "recorded_at": _ts(r["recorded_at"])}
                        for r in cur.fetchall()
                    ]
            if with_flags:
                for k in kpis:
                    cur.execute(
                        """SELECT * FROM kpi_flags
                            WHERE tenant_id = %s AND kpi_id = %s AND status = 'open'
                            ORDER BY created_at DESC""",
                        (tenant_id, k["id"]),
                    )
                    flags = []
                    for f in cur.fetchall():
                        refs = f.get("references_json") or []
                        if isinstance(refs, str):
                            try: refs = json.loads(refs)
                            except: refs = []
                        flags.append({
                            "id": f["id"], "kpi_id": f["kpi_id"], "kind": f["kind"],
                            "title": f["title"], "description": f.get("description"),
                            "references": refs, "brief_id": f.get("brief_id"),
                            "status": f["status"],
                            "created_at": _ts(f["created_at"]),
                            "updated_at": _ts(f["updated_at"]),
                        })
                    k["flags"] = flags
    return kpis


def get_kpi(tenant_id: str, kpi_id: str) -> Optional[dict]:
    kpis = list_kpis(tenant_id, status=None, with_history=True, with_flags=True)
    return next((k for k in kpis if k["id"] == kpi_id), None)


def create_kpi(tenant_id: str, *, kpi_id: str, name: str, description: str = "",
               unit: str = "", direction: str = "higher", target_value: Optional[float] = None) -> None:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO kpis (id, tenant_id, name, description, unit, direction,
                                     target_value, measurement_plan, measurement_status, status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'','pending','active')""",
                (kpi_id, tenant_id, name, description, unit, direction, target_value),
            )


def update_kpi(tenant_id: str, kpi_id: str, fields: dict) -> bool:
    allowed = {"name", "description", "unit", "direction", "target_value",
               "status", "measurement_plan", "measurement_status", "measurement_error"}
    sets, args = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = %s")
            args.append(v)
    if not sets:
        return False
    args.extend([tenant_id, kpi_id])
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE kpis SET {', '.join(sets)} WHERE tenant_id = %s AND id = %s",
                args,
            )
            return cur.rowcount > 0


def delete_kpi(tenant_id: str, kpi_id: str) -> bool:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM kpis WHERE tenant_id = %s AND id = %s",
                (tenant_id, kpi_id),
            )
            return cur.rowcount > 0


def update_kpi_flag_status(tenant_id: str, flag_id: str, status: str) -> bool:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE kpi_flags SET status = %s WHERE tenant_id = %s AND id = %s",
                (status, tenant_id, flag_id),
            )
            return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Integration connections
# ---------------------------------------------------------------------------

def list_integrations(tenant_id: str) -> list[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT platform, auth_type, credentials, status, display_name,
                          connected_at, last_verified
                     FROM integration_connections
                    WHERE tenant_id = %s
                 ORDER BY connected_at DESC NULLS LAST""",
                (tenant_id,),
            )
            return [
                {
                    "platform": r["platform"],
                    "auth_type": r["auth_type"],
                    "credentials": r["credentials"],
                    "status": r["status"],
                    "display_name": r["display_name"],
                    "connected_at": _ts(r["connected_at"]),
                    "last_verified": _ts(r["last_verified"]),
                }
                for r in cur.fetchall()
            ]


def upsert_integration(tenant_id: str, *, platform: str, auth_type: str, credentials: str,
                       status: str, display_name: str) -> None:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO integration_connections
                       (tenant_id, platform, auth_type, credentials, status, display_name,
                        connected_at, last_verified)
                   VALUES (%s,%s,%s,%s,%s,%s, NOW(), NOW())
                   ON CONFLICT (tenant_id, platform) DO UPDATE SET
                        auth_type = EXCLUDED.auth_type,
                        credentials = EXCLUDED.credentials,
                        status = EXCLUDED.status,
                        display_name = EXCLUDED.display_name,
                        connected_at = EXCLUDED.connected_at,
                        last_verified = EXCLUDED.last_verified""",
                (tenant_id, platform, auth_type, credentials, status, display_name),
            )


def delete_integration(tenant_id: str, platform: str) -> bool:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM integration_connections WHERE tenant_id = %s AND platform = %s",
                (tenant_id, platform),
            )
            return cur.rowcount > 0


# ---------------------------------------------------------------------------
# GitHub installation
# ---------------------------------------------------------------------------

def get_github_installation(tenant_id: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM integration_github_installations
                    WHERE tenant_id = %s
                 ORDER BY installed_at DESC LIMIT 1""",
                (tenant_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "installation_id": row["installation_id"],
        "account_login": row["account_login"],
        "account_type": row["account_type"],
        "repo_selection": row["repo_selection"],
        "cached_token": row["cached_token"],
        "cached_token_expires_at": _ts(row["cached_token_expires_at"]),
        "installed_at": _ts(row["installed_at"]),
        "updated_at": _ts(row["updated_at"]),
    }


def upsert_github_installation(tenant_id: str, *, installation_id: str,
                                account_login: str, account_type: str,
                                repo_selection: str) -> None:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO integration_github_installations
                       (installation_id, tenant_id, account_login, account_type,
                        repo_selection, installed_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s, NOW(), NOW())
                   ON CONFLICT (installation_id) DO UPDATE SET
                        tenant_id = EXCLUDED.tenant_id,
                        account_login = EXCLUDED.account_login,
                        account_type = EXCLUDED.account_type,
                        repo_selection = EXCLUDED.repo_selection,
                        updated_at = NOW()""",
                (installation_id, tenant_id, account_login, account_type, repo_selection),
            )


def update_github_token(installation_id: str, token: Optional[str],
                        expires_at_unix: Optional[float]) -> None:
    expires_at = None
    if expires_at_unix is not None:
        expires_at = datetime.fromtimestamp(expires_at_unix, tz=timezone.utc)
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE integration_github_installations
                      SET cached_token = %s, cached_token_expires_at = %s, updated_at = NOW()
                    WHERE installation_id = %s""",
                (token, expires_at, installation_id),
            )


def delete_github_installation(tenant_id: str) -> bool:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM integration_github_installations WHERE tenant_id = %s",
                (tenant_id,),
            )
            return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Onboarding profile
# ---------------------------------------------------------------------------

def get_onboarding_profile(tenant_id: str) -> dict:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT key, value FROM tenant_onboarding_profile WHERE tenant_id = %s",
                (tenant_id,),
            )
            return {r["key"]: r["value"] for r in cur.fetchall()}


def save_onboarding_profile(tenant_id: str, fields: dict) -> None:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            for k, v in fields.items():
                cur.execute(
                    """INSERT INTO tenant_onboarding_profile (tenant_id, key, value)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (tenant_id, key) DO UPDATE SET value = EXCLUDED.value""",
                    (tenant_id, str(k), str(v)),
                )


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
