"""Mirror chat session writes from SQLite (kai_state) into Neon Postgres.

When DATABASE_URL is set and a tenant is in scope (via KAI_TENANT_ID env or
the contextvar), every create_session/append_message in kai_state.py also
inserts a row into agent_sessions / agent_messages tagged with the tenant.
This is a dual-write: SQLite remains the agent runtime's source of truth,
Postgres is what the API serves.

Failures in the Postgres write are logged but do not block the SQLite path —
chat must keep working even if Neon is briefly unavailable.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from backend.db.postgres_client import get_pool, is_postgres_enabled
from backend.tenant_context import get_current_tenant

logger = logging.getLogger(__name__)


def _resolve_tenant_id() -> Optional[str]:
    """Look up the active tenant: contextvar first, then env (set by middleware)."""
    ctx = get_current_tenant()
    if ctx and ctx.tenant_id and ctx.tenant_id != "default":
        return ctx.tenant_id
    env_tid = os.getenv("KAI_TENANT_ID", "").strip()
    if env_tid and env_tid != "default":
        return env_tid
    return None


def sync_session(
    *,
    session_id: str,
    source: str,
    user_id: Optional[str],
    model: Optional[str],
    model_config: Optional[dict],
    system_prompt: Optional[str],
    parent_session_id: Optional[str],
) -> None:
    if not is_postgres_enabled():
        return
    tenant_id = _resolve_tenant_id()
    if not tenant_id:
        return
    try:
        with get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_sessions
                        (id, tenant_id, source, user_id, model, model_config,
                         system_prompt, parent_session_id, started_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s, NOW())
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        session_id, tenant_id, source, user_id, model,
                        json.dumps(model_config) if model_config else None,
                        system_prompt, parent_session_id,
                    ),
                )
    except Exception as e:
        logger.warning("session_sync.sync_session failed for %s: %s", session_id, e)


def sync_message(
    *,
    session_id: str,
    role: str,
    content: Optional[str],
    tool_call_id: Optional[str],
    tool_calls: Any,
    tool_name: Optional[str],
    token_count: Optional[int],
    finish_reason: Optional[str],
) -> None:
    if not is_postgres_enabled():
        return
    tenant_id = _resolve_tenant_id()
    if not tenant_id:
        return
    try:
        ts = datetime.now(timezone.utc)
        num_tool_calls = 0
        if tool_calls is not None:
            num_tool_calls = len(tool_calls) if isinstance(tool_calls, list) else 1
        with get_pool().connection() as conn:
            with conn.cursor() as cur:
                # Insert message
                cur.execute(
                    """
                    INSERT INTO agent_messages
                        (tenant_id, session_id, role, content, tool_call_id,
                         tool_calls, tool_name, timestamp, token_count, finish_reason)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        tenant_id, session_id, role, content, tool_call_id,
                        json.dumps(tool_calls) if tool_calls else None,
                        tool_name, ts, token_count, finish_reason,
                    ),
                )
                # Bump session counters
                if num_tool_calls > 0:
                    cur.execute(
                        """UPDATE agent_sessions
                              SET message_count = message_count + 1,
                                  tool_call_count = tool_call_count + %s
                            WHERE id = %s AND tenant_id = %s""",
                        (num_tool_calls, session_id, tenant_id),
                    )
                else:
                    cur.execute(
                        """UPDATE agent_sessions
                              SET message_count = message_count + 1
                            WHERE id = %s AND tenant_id = %s""",
                        (session_id, tenant_id),
                    )
    except Exception as e:
        logger.warning("session_sync.sync_message failed for %s: %s", session_id, e)


def sync_session_title(session_id: str, title: Optional[str]) -> None:
    if not is_postgres_enabled() or not title:
        return
    tenant_id = _resolve_tenant_id()
    if not tenant_id:
        return
    try:
        with get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE agent_sessions SET title = %s WHERE id = %s AND tenant_id = %s",
                    (title, session_id, tenant_id),
                )
    except Exception as e:
        logger.warning("session_sync.sync_session_title failed: %s", e)


def sync_session_end(session_id: str, end_reason: Optional[str]) -> None:
    if not is_postgres_enabled():
        return
    tenant_id = _resolve_tenant_id()
    if not tenant_id:
        return
    try:
        with get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE agent_sessions
                          SET ended_at = NOW(), end_reason = %s
                        WHERE id = %s AND tenant_id = %s""",
                    (end_reason, session_id, tenant_id),
                )
    except Exception as e:
        logger.warning("session_sync.sync_session_end failed: %s", e)
