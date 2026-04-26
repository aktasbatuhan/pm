#!/usr/bin/env python3
"""Backfill bucket #3 tables (signals, reports, team_pulse, changelogs) from
each Railway instance's integrations.db into Neon Postgres."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg


def ts(value: Any) -> Optional[datetime]:
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
            sys.exit(f"Tenant '{slug}' not found")
        return str(row[0])


def jload(s):
    try:
        return json.dumps(json.loads(s)) if s else "{}"
    except (json.JSONDecodeError, TypeError):
        return "{}"


def migrate(pg, sqlite_path: str, tenant_id: str, label: str):
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    counts = {}

    with pg.cursor() as cur:
        # signal_sources
        n = 0
        for r in src.execute("SELECT * FROM signal_sources").fetchall():
            cur.execute(
                """INSERT INTO signal_sources
                       (id, tenant_id, name, type, config, filter, enabled, last_fetched_at, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO NOTHING""",
                (
                    r["id"], tenant_id, r["name"], r["type"], jload(r["config"]),
                    r["filter"], bool(r["enabled"]),
                    ts(r["last_fetched_at"]),
                    ts(r["created_at"]) or datetime.now(timezone.utc),
                ),
            )
            n += cur.rowcount
        counts["signal_sources"] = n

        # signals
        n = 0
        for r in src.execute("SELECT * FROM signals").fetchall():
            cur.execute(
                """INSERT INTO signals
                       (id, tenant_id, source_id, title, body, url, author,
                        relevance_score, status, metadata, external_created_at, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO NOTHING""",
                (
                    r["id"], tenant_id, r["source_id"], r["title"], r["body"],
                    r["url"], r["author"], r["relevance_score"] or 0, r["status"],
                    jload(r["metadata"]), ts(r["external_created_at"]),
                    ts(r["created_at"]) or datetime.now(timezone.utc),
                ),
            )
            n += cur.rowcount
        counts["signals"] = n

        # report_templates
        n = 0
        for r in src.execute("SELECT * FROM report_templates").fetchall():
            cur.execute(
                """INSERT INTO report_templates
                       (id, tenant_id, name, body, resources, schedule, cron_job_id, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO NOTHING""",
                (
                    r["id"], tenant_id, r["name"], r["body"], jload(r["resources"]),
                    r["schedule"], r["cron_job_id"],
                    ts(r["created_at"]) or datetime.now(timezone.utc),
                    ts(r["updated_at"]) or datetime.now(timezone.utc),
                ),
            )
            n += cur.rowcount
        counts["report_templates"] = n

        # reports
        n = 0
        for r in src.execute("SELECT * FROM reports").fetchall():
            cur.execute(
                """INSERT INTO reports (id, tenant_id, template_id, content, created_at)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO NOTHING""",
                (
                    r["id"], tenant_id, r["template_id"], r["content"],
                    ts(r["created_at"]) or datetime.now(timezone.utc),
                ),
            )
            n += cur.rowcount
        counts["reports"] = n

        # team_pulse
        n = 0
        for r in src.execute("SELECT * FROM team_pulse").fetchall():
            try:
                flags = json.dumps(json.loads(r["flags"])) if r["flags"] else "[]"
            except (json.JSONDecodeError, TypeError):
                flags = "[]"
            cur.execute(
                """INSERT INTO team_pulse
                       (id, tenant_id, member_name, github_handle, prs_merged,
                        reviews_done, days_since_active, flags, period, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO NOTHING""",
                (
                    r["id"], tenant_id, r["member_name"], r["github_handle"],
                    r["prs_merged"] or 0, r["reviews_done"] or 0,
                    r["days_since_active"] or 0, flags, r["period"],
                    ts(r["created_at"]) or datetime.now(timezone.utc),
                ),
            )
            n += cur.rowcount
        counts["team_pulse"] = n

        # changelogs
        n = 0
        for r in src.execute("SELECT * FROM changelogs").fetchall():
            cur.execute(
                """INSERT INTO changelogs
                       (id, tenant_id, content, period_start, period_end, pr_count, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO NOTHING""",
                (
                    r["id"], tenant_id, r["content"],
                    ts(r["period_start"]), ts(r["period_end"]),
                    r["pr_count"] or 0,
                    ts(r["created_at"]) or datetime.now(timezone.utc),
                ),
            )
            n += cur.rowcount
        counts["changelogs"] = n

    pg.commit()
    src.close()
    print(f"[{label}] tenant={tenant_id}")
    for k, v in counts.items():
        if v: print(f"  {k}: +{v}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--demo", required=True)
    p.add_argument("--prod", required=True)
    args = p.parse_args()
    db_url = os.getenv("DATABASE_URL_DIRECT") or os.getenv("DATABASE_URL")
    if not db_url:
        sys.exit("DATABASE_URL_DIRECT or DATABASE_URL must be set")
    with psycopg.connect(db_url) as pg:
        demo_t = get_tenant_id(pg, "aktasbatuhan-demo")
        prod_t = get_tenant_id(pg, "aktasbatuhan-prod")
        migrate(pg, args.demo, demo_t, "demo")
        migrate(pg, args.prod, prod_t, "prod")


if __name__ == "__main__":
    main()
