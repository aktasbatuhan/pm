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


def insert_brief(tenant_id: str, *, brief_id: str, summary: str, headline: str,
                 action_items: list, data_sources: str = "",
                 suggested_prompts: Optional[list] = None) -> None:
    """Insert a brief and its action items atomically. action_items: list of
    dicts with title/description/category/priority/references."""
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO briefs (id, tenant_id, summary, headline, action_items,
                                       suggested_prompts, data_sources)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (brief_id, tenant_id, summary, headline,
                 json.dumps(action_items or []),
                 json.dumps(suggested_prompts or []),
                 data_sources),
            )
            for item in (action_items or []):
                action_id = item.get("id") or __import__("uuid").uuid4().hex[:8]
                cur.execute(
                    """INSERT INTO brief_actions
                           (id, tenant_id, brief_id, category, title, description,
                            priority, status, references_json)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,'pending',%s)""",
                    (action_id, tenant_id, brief_id,
                     item.get("category", "risk"),
                     item.get("title", ""),
                     item.get("description", ""),
                     item.get("priority", "medium"),
                     json.dumps(item.get("references", []))),
                )


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


def get_goal(tenant_id: str, goal_id: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM goals WHERE tenant_id = %s AND id = %s",
                (tenant_id, goal_id),
            )
            row = cur.fetchone()
    return _shape_goal(row) if row else None


def update_goal_progress(tenant_id: str, goal_id: str, *, progress: int,
                         trajectory: str, action_items: list,
                         snapshot_id: str, brief_id: Optional[str],
                         notes: Optional[str]) -> bool:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE goals
                      SET progress = %s, trajectory = %s, action_items = %s,
                          last_evaluated_at = NOW()
                    WHERE tenant_id = %s AND id = %s""",
                (progress, trajectory, json.dumps(action_items), tenant_id, goal_id),
            )
            if cur.rowcount == 0:
                return False
            cur.execute(
                """INSERT INTO goal_snapshots
                       (id, tenant_id, goal_id, progress, trajectory, action_items, brief_id, notes)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (snapshot_id, tenant_id, goal_id, progress, trajectory,
                 json.dumps(action_items), brief_id or None, notes or None),
            )
    return True


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


def kpi_record_value(tenant_id: str, kpi_id: str, *, value_id: str, value: float,
                     source: Optional[str], notes: Optional[str]) -> Optional[dict]:
    """Record a new value, update kpis.current_value/previous_value. Returns prior current_value."""
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT current_value FROM kpis WHERE tenant_id = %s AND id = %s",
                (tenant_id, kpi_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            prev = row["current_value"]
            cur.execute(
                """INSERT INTO kpi_values (id, tenant_id, kpi_id, value, source, notes, recorded_at)
                   VALUES (%s,%s,%s,%s,%s,%s, NOW())""",
                (value_id, tenant_id, kpi_id, value, source or None, notes or None),
            )
            cur.execute(
                """UPDATE kpis
                      SET previous_value = current_value,
                          current_value = %s,
                          last_measured_at = NOW(),
                          measurement_status = 'configured',
                          measurement_error = NULL
                    WHERE tenant_id = %s AND id = %s""",
                (value, tenant_id, kpi_id),
            )
    return {"previous": prev}


def kpi_set_measurement_plan(tenant_id: str, kpi_id: str, *, plan: str,
                              status: str, error: Optional[str]) -> bool:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE kpis
                      SET measurement_plan = %s,
                          measurement_status = %s,
                          measurement_error = %s
                    WHERE tenant_id = %s AND id = %s""",
                (plan, status, error or None, tenant_id, kpi_id),
            )
            return cur.rowcount > 0


def kpi_create_flag(tenant_id: str, *, flag_id: str, kpi_id: str, kind: str,
                    title: str, description: Optional[str],
                    references: list, brief_id: Optional[str]) -> bool:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM kpis WHERE tenant_id = %s AND id = %s",
                (tenant_id, kpi_id),
            )
            if not cur.fetchone():
                return False
            cur.execute(
                """INSERT INTO kpi_flags
                       (id, tenant_id, kpi_id, kind, title, description,
                        references_json, brief_id, status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'open')""",
                (flag_id, tenant_id, kpi_id, kind, title, description or None,
                 json.dumps(references or []), brief_id or None),
            )
    return True


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


# ---------------------------------------------------------------------------
# Workflow contract (per-tenant, revisioned)
# ---------------------------------------------------------------------------

def get_active_workflow(tenant_id: str) -> Optional[dict]:
    """Return the active workflow revision for a tenant, or None if never set."""
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT revision, name, body, rationale, author, based_on_signals,
                          created_at
                     FROM tenant_workflows
                    WHERE tenant_id = %s AND is_active = TRUE""",
                (tenant_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "revision": row["revision"],
        "name": row["name"],
        "body": row["body"],
        "rationale": row["rationale"],
        "author": row["author"],
        "based_on_signals": row["based_on_signals"],
        "created_at": _ts(row["created_at"]),
    }


def list_workflow_revisions(tenant_id: str, limit: int = 20) -> list[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT revision, name, rationale, author, is_active, created_at
                     FROM tenant_workflows
                    WHERE tenant_id = %s
                 ORDER BY revision DESC
                    LIMIT %s""",
                (tenant_id, limit),
            )
            rows = cur.fetchall()
    return [
        {
            "revision": r["revision"],
            "name": r["name"],
            "rationale": r["rationale"],
            "author": r["author"],
            "is_active": r["is_active"],
            "created_at": _ts(r["created_at"]),
        }
        for r in rows
    ]


def get_workflow_revision(tenant_id: str, revision: int) -> Optional[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT revision, name, body, rationale, author, based_on_signals,
                          is_active, created_at
                     FROM tenant_workflows
                    WHERE tenant_id = %s AND revision = %s""",
                (tenant_id, revision),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "revision": row["revision"],
        "name": row["name"],
        "body": row["body"],
        "rationale": row["rationale"],
        "author": row["author"],
        "based_on_signals": row["based_on_signals"],
        "is_active": row["is_active"],
        "created_at": _ts(row["created_at"]),
    }


def save_workflow_revision(tenant_id: str, *, name: str, body: str, author: str,
                           rationale: Optional[str] = None,
                           based_on_signals: Optional[list] = None) -> int:
    """Atomically save a new revision and mark it active.

    Returns the new revision number. Caller is responsible for parsing/validating
    the body before calling.
    """
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            # next revision number
            cur.execute(
                "SELECT COALESCE(MAX(revision), 0) AS r FROM tenant_workflows WHERE tenant_id = %s",
                (tenant_id,),
            )
            next_rev = (cur.fetchone()["r"] or 0) + 1

            # deactivate current active (if any)
            cur.execute(
                "UPDATE tenant_workflows SET is_active = FALSE WHERE tenant_id = %s AND is_active = TRUE",
                (tenant_id,),
            )

            # insert new active revision
            signals = json.dumps(based_on_signals) if based_on_signals else None
            cur.execute(
                """INSERT INTO tenant_workflows
                       (tenant_id, revision, name, body, rationale, author,
                        is_active, based_on_signals)
                   VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s)""",
                (tenant_id, next_rev, name, body, rationale, author, signals),
            )
    return next_rev


def store_oauth_state(state: str, *, tenant_id: Optional[str], purpose: str) -> None:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO oauth_states (state, tenant_id, purpose)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (state) DO UPDATE
                       SET tenant_id = EXCLUDED.tenant_id,
                           purpose = EXCLUDED.purpose,
                           created_at = NOW()""",
                (state, tenant_id, purpose),
            )
            cur.execute("DELETE FROM oauth_states WHERE created_at < NOW() - INTERVAL '10 minutes'")


def consume_oauth_state(state: str) -> Optional[dict]:
    """Return the state row (with tenant_id) and delete it. Returns None if not found."""
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT tenant_id, purpose FROM oauth_states WHERE state = %s", (state,))
            row = cur.fetchone()
            if not row:
                return None
            cur.execute("DELETE FROM oauth_states WHERE state = %s", (state,))
            return {
                "tenant_id": str(row["tenant_id"]) if row["tenant_id"] else None,
                "purpose": row["purpose"],
            }


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

# ---------------------------------------------------------------------------
# Signal sources + signals
# ---------------------------------------------------------------------------

def list_signal_sources(tenant_id: str) -> list[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM signal_sources WHERE tenant_id = %s ORDER BY created_at DESC",
                (tenant_id,),
            )
            rows = cur.fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "type": r["type"],
            "config": r["config"] or {},
            "filter": r["filter"],
            "enabled": bool(r["enabled"]),
            "last_fetched_at": _ts(r["last_fetched_at"]),
            "created_at": _ts(r["created_at"]),
        }
        for r in rows
    ]


def create_signal_source(tenant_id: str, *, source_id: str, name: str,
                         source_type: str, config: dict, filter: Optional[str]) -> None:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO signal_sources
                       (id, tenant_id, name, type, config, filter, enabled)
                   VALUES (%s,%s,%s,%s,%s,%s, TRUE)""",
                (source_id, tenant_id, name, source_type, json.dumps(config or {}), filter),
            )


def update_signal_source(tenant_id: str, source_id: str, fields: dict) -> bool:
    allowed = {"name", "type", "config", "filter", "enabled"}
    sets, args = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "config" and isinstance(v, dict):
            v = json.dumps(v)
        if k == "enabled":
            v = bool(v)
        sets.append(f"{k} = %s")
        args.append(v)
    if not sets:
        return False
    args.extend([tenant_id, source_id])
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE signal_sources SET {', '.join(sets)} WHERE tenant_id = %s AND id = %s",
                args,
            )
            return cur.rowcount > 0


def delete_signal_source(tenant_id: str, source_id: str) -> bool:
    # signals cascade via FK on source_id (ON DELETE CASCADE)
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM signal_sources WHERE tenant_id = %s AND id = %s",
                (tenant_id, source_id),
            )
            return cur.rowcount > 0


def list_signals(tenant_id: str, status: str = "all", limit: int = 50) -> list[dict]:
    sql = """
        SELECT s.*, src.name AS source_name, src.type AS source_type
          FROM signals s
          JOIN signal_sources src ON s.source_id = src.id
         WHERE s.tenant_id = %s
    """
    args: list[Any] = [tenant_id]
    if status and status != "all":
        sql += " AND s.status = %s"
        args.append(status)
    sql += " ORDER BY s.external_created_at DESC NULLS LAST, s.created_at DESC LIMIT %s"
    args.append(limit)
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()
    return [
        {
            "id": r["id"], "source_id": r["source_id"],
            "title": r["title"], "body": r["body"], "url": r["url"], "author": r["author"],
            "relevance_score": r["relevance_score"] or 0,
            "status": r["status"],
            "metadata": r["metadata"] or {},
            "external_created_at": _ts(r["external_created_at"]),
            "created_at": _ts(r["created_at"]),
            "source_name": r["source_name"], "source_type": r["source_type"],
        }
        for r in rows
    ]


def update_signal_status(tenant_id: str, signal_id: str, status: str) -> bool:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE signals SET status = %s WHERE tenant_id = %s AND id = %s",
                (status, tenant_id, signal_id),
            )
            return cur.rowcount > 0


def insert_signal(tenant_id: str, *, signal_id: str, source_id: str, title: Optional[str],
                  body: Optional[str], url: Optional[str], author: Optional[str],
                  relevance_score: float, metadata: dict,
                  external_created_at: Optional[float]) -> bool:
    """Insert a fetched signal. Returns False if duplicate URL within source."""
    ext_ts = None
    if external_created_at is not None:
        ext_ts = datetime.fromtimestamp(external_created_at, tz=timezone.utc)
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            if url:
                cur.execute(
                    "SELECT 1 FROM signals WHERE tenant_id = %s AND source_id = %s AND url = %s",
                    (tenant_id, source_id, url),
                )
                if cur.fetchone():
                    return False
            cur.execute(
                """INSERT INTO signals
                       (id, tenant_id, source_id, title, body, url, author,
                        relevance_score, status, metadata, external_created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'new',%s,%s)
                   ON CONFLICT (id) DO NOTHING""",
                (signal_id, tenant_id, source_id, title, body, url, author,
                 relevance_score, json.dumps(metadata or {}), ext_ts),
            )
            return cur.rowcount > 0


def update_source_last_fetched(tenant_id: str, source_id: str) -> None:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE signal_sources SET last_fetched_at = NOW() WHERE tenant_id = %s AND id = %s",
                (tenant_id, source_id),
            )


# ---------------------------------------------------------------------------
# Report templates + reports
# ---------------------------------------------------------------------------

def _shape_template(row: dict, report_count: int = 0) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "body": row["body"],
        "resources": row["resources"] or {},
        "schedule": row["schedule"],
        "cron_job_id": row["cron_job_id"],
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "report_count": report_count,
    }


def list_report_templates(tenant_id: str) -> list[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT t.*, (SELECT count(*) FROM reports r WHERE r.template_id = t.id) AS rc
                     FROM report_templates t
                    WHERE t.tenant_id = %s
                 ORDER BY t.updated_at DESC""",
                (tenant_id,),
            )
            return [_shape_template(r, r["rc"]) for r in cur.fetchall()]


def get_report_template(tenant_id: str, template_id: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM report_templates WHERE tenant_id = %s AND id = %s",
                (tenant_id, template_id),
            )
            row = cur.fetchone()
    return _shape_template(row) if row else None


def create_report_template(tenant_id: str, *, template_id: str, name: str, body: str,
                           resources: dict, schedule: str = "none") -> None:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO report_templates
                       (id, tenant_id, name, body, resources, schedule)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (template_id, tenant_id, name, body, json.dumps(resources or {}), schedule),
            )


def update_report_template(tenant_id: str, template_id: str, fields: dict) -> bool:
    allowed = {"name", "body", "resources", "schedule", "cron_job_id"}
    sets, args = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "resources" and isinstance(v, dict):
            v = json.dumps(v)
        sets.append(f"{k} = %s")
        args.append(v)
    if not sets:
        return False
    args.extend([tenant_id, template_id])
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE report_templates SET {', '.join(sets)} WHERE tenant_id = %s AND id = %s",
                args,
            )
            return cur.rowcount > 0


def delete_report_template(tenant_id: str, template_id: str) -> bool:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM report_templates WHERE tenant_id = %s AND id = %s",
                (tenant_id, template_id),
            )
            return cur.rowcount > 0


def list_reports(tenant_id: str, template_id: Optional[str] = None, limit: int = 20) -> list[dict]:
    sql = "SELECT * FROM reports WHERE tenant_id = %s"
    args: list[Any] = [tenant_id]
    if template_id:
        sql += " AND template_id = %s"
        args.append(template_id)
    sql += " ORDER BY created_at DESC LIMIT %s"
    args.append(limit)
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return [
                {"id": r["id"], "template_id": r["template_id"],
                 "content": r["content"], "created_at": _ts(r["created_at"])}
                for r in cur.fetchall()
            ]


def delete_report(tenant_id: str, report_id: str) -> bool:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM reports WHERE tenant_id = %s AND id = %s",
                (tenant_id, report_id),
            )
            return cur.rowcount > 0


def insert_report(tenant_id: str, *, report_id: str, template_id: str, content: str) -> None:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO reports (id, tenant_id, template_id, content) VALUES (%s,%s,%s,%s)",
                (report_id, tenant_id, template_id, content),
            )


# ---------------------------------------------------------------------------
# Team pulse + changelogs
# ---------------------------------------------------------------------------

def list_team_pulse(tenant_id: str) -> list[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM team_pulse
                    WHERE tenant_id = %s
                 ORDER BY prs_merged DESC""",
                (tenant_id,),
            )
            rows = cur.fetchall()
    return [
        {
            "id": r["id"], "member_name": r["member_name"], "github_handle": r["github_handle"],
            "prs_merged": r["prs_merged"] or 0, "reviews_done": r["reviews_done"] or 0,
            "days_since_active": r["days_since_active"] or 0,
            "flags": r["flags"] or [],
            "period": r["period"],
            "created_at": _ts(r["created_at"]),
        }
        for r in rows
    ]


def list_changelogs(tenant_id: str, limit: int = 10) -> list[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM changelogs WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s",
                (tenant_id, limit),
            )
            return [_shape_changelog(r) for r in cur.fetchall()]


def get_latest_changelog(tenant_id: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM changelogs WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 1",
                (tenant_id,),
            )
            row = cur.fetchone()
    return _shape_changelog(row) if row else None


def _shape_changelog(row: dict) -> dict:
    return {
        "id": row["id"], "content": row["content"],
        "period_start": _ts(row["period_start"]),
        "period_end": _ts(row["period_end"]),
        "pr_count": row["pr_count"] or 0,
        "created_at": _ts(row["created_at"]),
    }


def create_changelog(tenant_id: str, *, changelog_id: str, content: str,
                     period_start: Optional[float], period_end: Optional[float],
                     pr_count: int = 0) -> None:
    ps = datetime.fromtimestamp(period_start, tz=timezone.utc) if period_start else None
    pe = datetime.fromtimestamp(period_end, tz=timezone.utc) if period_end else None
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO changelogs
                       (id, tenant_id, content, period_start, period_end, pr_count)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (changelog_id, tenant_id, content, ps, pe, pr_count),
            )


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
