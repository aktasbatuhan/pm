#!/usr/bin/env python3
"""
Backfill agent sessions + messages from each Railway instance's state.db
into Neon Postgres, tagged with the right tenant_id.

Usage:
    DATABASE_URL_DIRECT=postgresql://... \
    python scripts/backfill_sessions_to_neon.py \
        --demo /tmp/dash-backfill/demo/state.db \
        --prod /Users/.../backups/dash-api-2026-04-25/state.db

Idempotent — uses ON CONFLICT DO NOTHING for sessions and skips
messages that already exist for that (session_id, timestamp, role).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg


def ts_to_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def get_tenant_id(pg, slug: str) -> str:
    with pg.cursor() as cur:
        cur.execute("SELECT id FROM tenants WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if not row:
            sys.exit(f"Tenant '{slug}' not found in Neon")
        return str(row[0])


def migrate_state_db(pg, sqlite_path: str, tenant_id: str, label: str):
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row

    sess_inserted = 0
    msg_inserted = 0
    skipped_orphan_messages = 0

    sessions = src.execute("SELECT * FROM sessions").fetchall()
    valid_session_ids = {s["id"] for s in sessions}

    with pg.cursor() as cur:
        # Sessions first (no FK on parent_session_id since we set ON DELETE SET NULL)
        for s in sessions:
            try:
                config_json = json.dumps(json.loads(s["model_config"])) if s["model_config"] else None
            except (json.JSONDecodeError, TypeError):
                config_json = None
            parent_id = s["parent_session_id"] if s["parent_session_id"] in valid_session_ids else None
            cur.execute(
                """
                INSERT INTO agent_sessions
                    (id, tenant_id, source, user_id, model, model_config, system_prompt,
                     parent_session_id, title, started_at, ended_at, end_reason,
                     message_count, tool_call_count, input_tokens, output_tokens)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    s["id"], tenant_id, s["source"], s["user_id"], s["model"], config_json,
                    s["system_prompt"], parent_id, s["title"],
                    ts_to_dt(s["started_at"]) or datetime.now(timezone.utc),
                    ts_to_dt(s["ended_at"]),
                    s["end_reason"], s["message_count"] or 0, s["tool_call_count"] or 0,
                    s["input_tokens"] or 0, s["output_tokens"] or 0,
                ),
            )
            sess_inserted += cur.rowcount

        # Messages
        msgs = src.execute("SELECT * FROM messages ORDER BY id").fetchall()
        for m in msgs:
            if m["session_id"] not in valid_session_ids:
                skipped_orphan_messages += 1
                continue
            try:
                tool_calls = json.dumps(json.loads(m["tool_calls"])) if m["tool_calls"] else None
            except (json.JSONDecodeError, TypeError):
                tool_calls = None
            ts = ts_to_dt(m["timestamp"]) or datetime.now(timezone.utc)
            # Skip duplicate (session_id, role, timestamp, content) on rerun
            cur.execute(
                """
                SELECT 1 FROM agent_messages
                 WHERE session_id = %s AND role = %s AND timestamp = %s
                """,
                (m["session_id"], m["role"], ts),
            )
            if cur.fetchone():
                continue
            cur.execute(
                """
                INSERT INTO agent_messages
                    (tenant_id, session_id, role, content, tool_call_id, tool_calls,
                     tool_name, timestamp, token_count, finish_reason)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    tenant_id, m["session_id"], m["role"], m["content"],
                    m["tool_call_id"], tool_calls, m["tool_name"], ts,
                    m["token_count"], m["finish_reason"],
                ),
            )
            msg_inserted += 1

    pg.commit()
    src.close()
    print(f"[{label}] tenant={tenant_id}")
    print(f"  sessions: +{sess_inserted}")
    print(f"  messages: +{msg_inserted}")
    if skipped_orphan_messages:
        print(f"  skipped {skipped_orphan_messages} orphan messages (session not in DB)")


def main():
    parser = argparse.ArgumentParser(description="Backfill state.db -> Neon")
    parser.add_argument("--demo", required=True, help="Path to demo state.db")
    parser.add_argument("--prod", required=True, help="Path to prod backup state.db")
    args = parser.parse_args()

    db_url = os.getenv("DATABASE_URL_DIRECT") or os.getenv("DATABASE_URL")
    if not db_url:
        sys.exit("DATABASE_URL_DIRECT or DATABASE_URL must be set")

    for p in (args.demo, args.prod):
        if not os.path.exists(p):
            sys.exit(f"Missing {p}")

    with psycopg.connect(db_url) as pg:
        demo_tenant = get_tenant_id(pg, "aktasbatuhan-demo")
        prod_tenant = get_tenant_id(pg, "aktasbatuhan-prod")
        print(f"demo_tenant={demo_tenant}  prod_tenant={prod_tenant}\n")
        migrate_state_db(pg, args.demo, demo_tenant, "demo")
        migrate_state_db(pg, args.prod, prod_tenant, "prod")


if __name__ == "__main__":
    main()
