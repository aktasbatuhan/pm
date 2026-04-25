#!/usr/bin/env python3
"""
Backfill SQLite data from both Railway instances into Neon Postgres.

Usage:
    DATABASE_URL_DIRECT=postgresql://... \
    OPERATOR_EMAIL=batuhan@dria.co \
    python scripts/backfill_to_neon.py \
        --demo /tmp/dash-backfill/demo \
        --prod /tmp/dash-backfill/prod

Idempotent — re-running is safe; uses ON CONFLICT DO NOTHING for inserts.
Creates two tenants ('aktasbatuhan-demo', 'aktasbatuhan-prod') and one user
linked to both as owner. Demo is set as the default tenant.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psycopg


def ts_to_dt(value: Any) -> Optional[datetime]:
    """Convert a SQLite REAL unix timestamp to UTC datetime."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def load_sqlite(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    return db


def ensure_user(pg, email: str, password_hash: Optional[str], display_name: str) -> str:
    """Create or fetch user; return user_id."""
    with pg.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
        if row:
            return str(row[0])
        user_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO users (id, email, password_hash, display_name) VALUES (%s, %s, %s, %s)",
            (user_id, email, password_hash, display_name),
        )
        return user_id


def ensure_tenant(pg, slug: str, name: str, created_by: str) -> str:
    """Create or fetch tenant by slug; return tenant_id."""
    with pg.cursor() as cur:
        cur.execute("SELECT id FROM tenants WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if row:
            return str(row[0])
        tenant_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO tenants (id, slug, name, created_by) VALUES (%s, %s, %s, %s)",
            (tenant_id, slug, name, created_by),
        )
        return tenant_id


def ensure_membership(pg, tenant_id: str, user_id: str, role: str, is_default: bool):
    with pg.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenant_memberships (tenant_id, user_id, role, is_default)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tenant_id, user_id) DO UPDATE
                SET role = EXCLUDED.role, is_default = EXCLUDED.is_default
            """,
            (tenant_id, user_id, role, is_default),
        )


def get_password_hash(integrations_db: sqlite3.Connection) -> Optional[str]:
    try:
        row = integrations_db.execute(
            "SELECT value FROM auth WHERE key = 'password_hash'"
        ).fetchone()
        return row["value"] if row else None
    except sqlite3.OperationalError:
        return None


# --- Per-table migrations ---------------------------------------------------

def migrate_workspace_meta(pg, sqlite_db, tenant_id: str):
    row = sqlite_db.execute("SELECT * FROM workspace_meta LIMIT 1").fetchone()
    if not row:
        return 0
    with pg.cursor() as cur:
        cur.execute(
            """
            INSERT INTO workspace_meta (tenant_id, onboarding_status, onboarding_phase, onboarded_at, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id) DO UPDATE SET
                onboarding_status = EXCLUDED.onboarding_status,
                onboarding_phase  = EXCLUDED.onboarding_phase,
                onboarded_at      = EXCLUDED.onboarded_at,
                updated_at        = EXCLUDED.updated_at
            """,
            (
                tenant_id,
                row["onboarding_status"],
                row["onboarding_phase"],
                ts_to_dt(row["onboarded_at"]),
                ts_to_dt(row["created_at"]) or datetime.now(timezone.utc),
                ts_to_dt(row["updated_at"]) or datetime.now(timezone.utc),
            ),
        )
    return 1


def migrate_blueprint(pg, sqlite_db, tenant_id: str):
    row = sqlite_db.execute("SELECT * FROM blueprint LIMIT 1").fetchone()
    if not row:
        return 0
    try:
        data = json.loads(row["data"]) if row["data"] else {}
    except json.JSONDecodeError:
        data = {"_raw": row["data"]}
    with pg.cursor() as cur:
        cur.execute(
            """
            INSERT INTO workspace_blueprint (tenant_id, data, summary, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id) DO UPDATE SET
                data       = EXCLUDED.data,
                summary    = EXCLUDED.summary,
                updated_by = EXCLUDED.updated_by,
                updated_at = EXCLUDED.updated_at
            """,
            (tenant_id, json.dumps(data), row["summary"] or "", row["updated_by"],
             ts_to_dt(row["updated_at"]) or datetime.now(timezone.utc)),
        )
    return 1


def migrate_learnings(pg, sqlite_db, tenant_id: str):
    rows = sqlite_db.execute("SELECT * FROM learnings ORDER BY id").fetchall()
    inserted = 0
    with pg.cursor() as cur:
        for r in rows:
            cur.execute(
                """
                INSERT INTO workspace_learnings (tenant_id, category, content, source_thread, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (tenant_id, r["category"], r["content"], r["source_thread"],
                 ts_to_dt(r["created_at"]) or datetime.now(timezone.utc)),
            )
            inserted += 1
    return inserted


def migrate_briefs(pg, sqlite_db, tenant_id: str):
    rows = sqlite_db.execute("SELECT * FROM briefs ORDER BY created_at").fetchall()
    inserted = 0
    with pg.cursor() as cur:
        for r in rows:
            try:
                action_items = json.loads(r["action_items"]) if r["action_items"] else []
            except json.JSONDecodeError:
                action_items = []
            try:
                suggested = json.loads(r["suggested_prompts"]) if r["suggested_prompts"] else []
            except (json.JSONDecodeError, IndexError, KeyError):
                suggested = []
            cur.execute(
                """
                INSERT INTO briefs (id, tenant_id, summary, headline, action_items,
                                    suggested_prompts, data_sources, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    r["id"], tenant_id, r["summary"], r["headline"] or "",
                    json.dumps(action_items), json.dumps(suggested),
                    r["data_sources"], ts_to_dt(r["created_at"]) or datetime.now(timezone.utc),
                ),
            )
            inserted += cur.rowcount
    return inserted


def migrate_brief_actions(pg, sqlite_db, tenant_id: str):
    rows = sqlite_db.execute("SELECT * FROM brief_actions ORDER BY created_at").fetchall()
    inserted = 0
    with pg.cursor() as cur:
        for r in rows:
            try:
                refs = json.loads(r["references_json"]) if r["references_json"] else []
            except json.JSONDecodeError:
                refs = []
            cur.execute(
                """
                INSERT INTO brief_actions (id, tenant_id, brief_id, category, title, description,
                                           priority, status, chat_session_id, references_json,
                                           created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    r["id"], tenant_id, r["brief_id"], r["category"], r["title"], r["description"],
                    r["priority"], r["status"], r["chat_session_id"], json.dumps(refs),
                    ts_to_dt(r["created_at"]) or datetime.now(timezone.utc),
                    ts_to_dt(r["updated_at"]) or datetime.now(timezone.utc),
                ),
            )
            inserted += cur.rowcount
    return inserted


def migrate_goals(pg, sqlite_db, tenant_id: str):
    try:
        rows = sqlite_db.execute("SELECT * FROM goals").fetchall()
    except sqlite3.OperationalError:
        return 0
    inserted = 0
    with pg.cursor() as cur:
        for r in rows:
            cur.execute(
                """
                INSERT INTO goals (id, tenant_id, title, description, target_date, status, progress,
                                   trajectory, related_items, action_items, last_evaluated_at,
                                   created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    r["id"], tenant_id, r["title"], r["description"], r["target_date"], r["status"],
                    r["progress"], r["trajectory"], r["related_items"] or "[]",
                    r["action_items"] or "[]", ts_to_dt(r["last_evaluated_at"]),
                    ts_to_dt(r["created_at"]) or datetime.now(timezone.utc),
                    ts_to_dt(r["updated_at"]) or datetime.now(timezone.utc),
                ),
            )
            inserted += cur.rowcount
    return inserted


def migrate_goal_snapshots(pg, sqlite_db, tenant_id: str):
    try:
        rows = sqlite_db.execute("SELECT * FROM goal_snapshots").fetchall()
    except sqlite3.OperationalError:
        return 0
    inserted = 0
    with pg.cursor() as cur:
        for r in rows:
            cur.execute(
                """
                INSERT INTO goal_snapshots (id, tenant_id, goal_id, progress, trajectory,
                                            action_items, brief_id, notes, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    r["id"], tenant_id, r["goal_id"], r["progress"], r["trajectory"],
                    r["action_items"] or "[]", r["brief_id"], r["notes"],
                    ts_to_dt(r["created_at"]) or datetime.now(timezone.utc),
                ),
            )
            inserted += cur.rowcount
    return inserted


def migrate_kpis(pg, sqlite_db, tenant_id: str):
    try:
        rows = sqlite_db.execute("SELECT * FROM kpis").fetchall()
    except sqlite3.OperationalError:
        return 0
    inserted = 0
    with pg.cursor() as cur:
        for r in rows:
            cur.execute(
                """
                INSERT INTO kpis (id, tenant_id, name, description, unit, direction, target_value,
                                  current_value, previous_value, measurement_plan, measurement_status,
                                  measurement_error, cron_job_id, status,
                                  created_at, updated_at, last_measured_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    r["id"], tenant_id, r["name"], r["description"], r["unit"], r["direction"],
                    r["target_value"], r["current_value"], r["previous_value"],
                    r["measurement_plan"], r["measurement_status"], r["measurement_error"],
                    r["cron_job_id"], r["status"],
                    ts_to_dt(r["created_at"]) or datetime.now(timezone.utc),
                    ts_to_dt(r["updated_at"]) or datetime.now(timezone.utc),
                    ts_to_dt(r["last_measured_at"]),
                ),
            )
            inserted += cur.rowcount
    return inserted


def migrate_kpi_values(pg, sqlite_db, tenant_id: str):
    try:
        rows = sqlite_db.execute("SELECT * FROM kpi_values").fetchall()
    except sqlite3.OperationalError:
        return 0
    inserted = 0
    with pg.cursor() as cur:
        for r in rows:
            cur.execute(
                """
                INSERT INTO kpi_values (id, tenant_id, kpi_id, value, source, notes, recorded_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    r["id"], tenant_id, r["kpi_id"], r["value"], r["source"], r["notes"],
                    ts_to_dt(r["recorded_at"]) or datetime.now(timezone.utc),
                ),
            )
            inserted += cur.rowcount
    return inserted


def migrate_kpi_flags(pg, sqlite_db, tenant_id: str):
    try:
        rows = sqlite_db.execute("SELECT * FROM kpi_flags").fetchall()
    except sqlite3.OperationalError:
        return 0
    inserted = 0
    with pg.cursor() as cur:
        for r in rows:
            try:
                refs = json.loads(r["references_json"]) if r["references_json"] else []
            except json.JSONDecodeError:
                refs = []
            cur.execute(
                """
                INSERT INTO kpi_flags (id, tenant_id, kpi_id, kind, title, description,
                                       references_json, brief_id, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    r["id"], tenant_id, r["kpi_id"], r["kind"], r["title"], r["description"],
                    json.dumps(refs), r["brief_id"], r["status"],
                    ts_to_dt(r["created_at"]) or datetime.now(timezone.utc),
                    ts_to_dt(r["updated_at"]) or datetime.now(timezone.utc),
                ),
            )
            inserted += cur.rowcount
    return inserted


def migrate_integrations(pg, sqlite_db, tenant_id: str):
    rows = sqlite_db.execute("SELECT * FROM integrations").fetchall()
    inserted = 0
    with pg.cursor() as cur:
        for r in rows:
            cur.execute(
                """
                INSERT INTO integration_connections (tenant_id, platform, auth_type, credentials,
                                                     status, display_name, connected_at, last_verified)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, platform) DO NOTHING
                """,
                (
                    tenant_id, r["platform"], r["auth_type"], r["credentials"], r["status"],
                    r["display_name"], ts_to_dt(r["connected_at"]), ts_to_dt(r["last_verified"]),
                ),
            )
            inserted += cur.rowcount
    return inserted


def migrate_github_installations(pg, sqlite_db, tenant_id: str):
    try:
        rows = sqlite_db.execute("SELECT * FROM github_installations").fetchall()
    except sqlite3.OperationalError:
        return 0
    inserted = 0
    with pg.cursor() as cur:
        for r in rows:
            cur.execute(
                """
                INSERT INTO integration_github_installations
                    (installation_id, tenant_id, account_login, account_type, repo_selection,
                     cached_token, cached_token_expires_at, installed_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (installation_id) DO UPDATE SET
                    tenant_id     = EXCLUDED.tenant_id,
                    account_login = EXCLUDED.account_login,
                    updated_at    = EXCLUDED.updated_at
                """,
                (
                    r["installation_id"], tenant_id, r["account_login"], r["account_type"],
                    r["repo_selection"], r["cached_token"],
                    ts_to_dt(r["cached_token_expires_at"]),
                    ts_to_dt(r["installed_at"]) or datetime.now(timezone.utc),
                    ts_to_dt(r["updated_at"]) or datetime.now(timezone.utc),
                ),
            )
            inserted += cur.rowcount
    return inserted


def migrate_onboarding_profile(pg, sqlite_db, tenant_id: str):
    rows = sqlite_db.execute("SELECT * FROM onboarding_profile").fetchall()
    inserted = 0
    with pg.cursor() as cur:
        for r in rows:
            cur.execute(
                """
                INSERT INTO tenant_onboarding_profile (tenant_id, key, value)
                VALUES (%s, %s, %s)
                ON CONFLICT (tenant_id, key) DO UPDATE SET value = EXCLUDED.value
                """,
                (tenant_id, r["key"], r["value"]),
            )
            inserted += cur.rowcount
    return inserted


# --- Driver -----------------------------------------------------------------

def migrate_one(pg, sqlite_dir: Path, tenant_id: str, label: str):
    workspace = load_sqlite(sqlite_dir / "workspace.db")
    integrations = load_sqlite(sqlite_dir / "integrations.db")

    summary = {}
    summary["workspace_meta"] = migrate_workspace_meta(pg, workspace, tenant_id)
    summary["blueprint"] = migrate_blueprint(pg, workspace, tenant_id)
    summary["learnings"] = migrate_learnings(pg, workspace, tenant_id)
    summary["briefs"] = migrate_briefs(pg, workspace, tenant_id)
    summary["brief_actions"] = migrate_brief_actions(pg, workspace, tenant_id)
    summary["goals"] = migrate_goals(pg, integrations, tenant_id)
    summary["goal_snapshots"] = migrate_goal_snapshots(pg, integrations, tenant_id)
    summary["kpis"] = migrate_kpis(pg, integrations, tenant_id)
    summary["kpi_values"] = migrate_kpi_values(pg, integrations, tenant_id)
    summary["kpi_flags"] = migrate_kpi_flags(pg, integrations, tenant_id)
    summary["integrations"] = migrate_integrations(pg, integrations, tenant_id)
    summary["github_installations"] = migrate_github_installations(pg, integrations, tenant_id)
    summary["onboarding_profile"] = migrate_onboarding_profile(pg, integrations, tenant_id)
    pg.commit()

    print(f"[{label}] tenant={tenant_id}")
    for k, v in summary.items():
        if v:
            print(f"  {k}: +{v}")


def main():
    parser = argparse.ArgumentParser(description="Backfill SQLite -> Neon Postgres")
    parser.add_argument("--demo", required=True, help="Path to demo SQLite dir (workspace.db, integrations.db)")
    parser.add_argument("--prod", required=True, help="Path to prod SQLite dir")
    parser.add_argument("--operator-email", default=os.getenv("OPERATOR_EMAIL", "batuhan@dria.co"))
    parser.add_argument("--operator-name", default="Batuhan")
    args = parser.parse_args()

    db_url = os.getenv("DATABASE_URL_DIRECT") or os.getenv("DATABASE_URL")
    if not db_url:
        sys.exit("DATABASE_URL_DIRECT or DATABASE_URL must be set")

    demo_dir = Path(args.demo)
    prod_dir = Path(args.prod)
    for d in (demo_dir, prod_dir):
        for f in ("workspace.db", "integrations.db"):
            if not (d / f).exists():
                sys.exit(f"Missing {d / f}")

    # Pick a password hash to bring forward (prod wins; user can reset if needed).
    prod_integrations = load_sqlite(prod_dir / "integrations.db")
    pwd_hash = get_password_hash(prod_integrations)
    prod_integrations.close()

    with psycopg.connect(db_url) as pg:
        user_id = ensure_user(pg, args.operator_email, pwd_hash, args.operator_name)
        demo_tenant = ensure_tenant(pg, "aktasbatuhan-demo", "Dash Demo", user_id)
        prod_tenant = ensure_tenant(pg, "aktasbatuhan-prod", "Dash Prod", user_id)
        ensure_membership(pg, demo_tenant, user_id, "owner", is_default=True)
        ensure_membership(pg, prod_tenant, user_id, "owner", is_default=False)
        pg.commit()

        print(f"user_id={user_id} email={args.operator_email}")
        print(f"demo_tenant={demo_tenant}  prod_tenant={prod_tenant}")
        print()

        migrate_one(pg, demo_dir, demo_tenant, "demo")
        migrate_one(pg, prod_dir, prod_tenant, "prod")


if __name__ == "__main__":
    main()
