"""
PM KPI tools — let the agent autonomously configure, measure, and flag KPIs.

KPIs differ from goals: they are continuous metrics (WAU, conversion rate, MRR)
the agent tracks over time. The agent:
  1. Configures each KPI by writing its own measurement plan based on connected platforms
  2. Records values on a schedule
  3. Raises risk/opportunity flags only when movement is meaningful
"""

import json
import sqlite3
import time
import uuid

from kai_env import kai_home
from tools.registry import registry


_DB_PATH = kai_home() / "integrations.db"


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=10.0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS kpis (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            unit TEXT,
            direction TEXT DEFAULT 'higher',
            target_value REAL,
            current_value REAL,
            previous_value REAL,
            measurement_plan TEXT DEFAULT '',
            measurement_status TEXT DEFAULT 'pending',
            measurement_error TEXT,
            cron_job_id TEXT,
            status TEXT DEFAULT 'active',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            last_measured_at REAL
        );
        CREATE TABLE IF NOT EXISTS kpi_values (
            id TEXT PRIMARY KEY,
            kpi_id TEXT NOT NULL,
            value REAL NOT NULL,
            source TEXT,
            notes TEXT,
            recorded_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_kpi_values_kpi ON kpi_values(kpi_id, recorded_at DESC);
        CREATE TABLE IF NOT EXISTS kpi_flags (
            id TEXT PRIMARY KEY,
            kpi_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            references_json TEXT DEFAULT '[]',
            brief_id TEXT,
            status TEXT DEFAULT 'open',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_kpi_flags_kpi ON kpi_flags(kpi_id, status, created_at DESC);
    """)
    return db


def _fetch_history(db, kpi_id: str, limit: int = 30):
    rows = db.execute(
        "SELECT id, value, source, notes, recorded_at FROM kpi_values WHERE kpi_id = ? "
        "ORDER BY recorded_at DESC LIMIT ?",
        (kpi_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# =============================================================================
# Tool: kpi_list
# =============================================================================

def kpi_list(status: str = "active", **kwargs) -> str:
    db = _db()
    if status == "all":
        rows = db.execute("SELECT * FROM kpis ORDER BY created_at DESC").fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM kpis WHERE status = ? ORDER BY created_at DESC", (status,)
        ).fetchall()
    kpis = []
    for r in rows:
        k = dict(r)
        k["recent_values"] = _fetch_history(db, k["id"], limit=8)
        kpis.append(k)
    return json.dumps({"count": len(kpis), "kpis": kpis})


KPI_LIST_SCHEMA = {
    "name": "kpi_list",
    "description": "List KPIs with their current value, measurement plan, and recent data points.",
    "parameters": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["active", "paused", "archived", "all"],
            }
        },
    },
}


# =============================================================================
# Tool: kpi_get
# =============================================================================

def kpi_get(kpi_id: str, history_limit: int = 30, **kwargs) -> str:
    db = _db()
    row = db.execute("SELECT * FROM kpis WHERE id = ?", (kpi_id,)).fetchone()
    if not row:
        return json.dumps({"error": f"KPI {kpi_id} not found."})
    k = dict(row)
    k["history"] = _fetch_history(db, kpi_id, limit=history_limit)
    open_flags = db.execute(
        "SELECT * FROM kpi_flags WHERE kpi_id = ? AND status = 'open' ORDER BY created_at DESC",
        (kpi_id,),
    ).fetchall()
    k["open_flags"] = [dict(f) for f in open_flags]
    return json.dumps(k)


KPI_GET_SCHEMA = {
    "name": "kpi_get",
    "description": "Get a specific KPI with its full history and open flags.",
    "parameters": {
        "type": "object",
        "properties": {
            "kpi_id": {"type": "string"},
            "history_limit": {"type": "integer"},
        },
        "required": ["kpi_id"],
    },
}


# =============================================================================
# Tool: kpi_set_measurement_plan
# =============================================================================

def kpi_set_measurement_plan(
    kpi_id: str,
    plan: str,
    status: str = "configured",
    error: str = "",
    **kwargs,
) -> str:
    """Set or update the agent-authored measurement plan for a KPI."""
    db = _db()
    row = db.execute("SELECT * FROM kpis WHERE id = ?", (kpi_id,)).fetchone()
    if not row:
        return json.dumps({"error": f"KPI {kpi_id} not found."})
    if status not in ("configured", "failed", "pending"):
        status = "configured"
    now = time.time()
    db.execute(
        "UPDATE kpis SET measurement_plan = ?, measurement_status = ?, measurement_error = ?, updated_at = ? WHERE id = ?",
        (plan, status, error or None, now, kpi_id),
    )
    db.commit()
    return json.dumps({"ok": True, "kpi_id": kpi_id, "measurement_status": status})


KPI_SET_MEASUREMENT_PLAN_SCHEMA = {
    "name": "kpi_set_measurement_plan",
    "description": (
        "Store the measurement plan for a KPI. This plan is a short, self-contained "
        "description of which platform(s) to query, the exact query/endpoint, the window, "
        "and how to interpret the result. Set status='failed' with an error message when "
        "no available platform can measure the KPI."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "kpi_id": {"type": "string"},
            "plan": {
                "type": "string",
                "description": "The measurement plan (markdown/plain text). Include the exact query/URL.",
            },
            "status": {
                "type": "string",
                "enum": ["configured", "failed", "pending"],
            },
            "error": {
                "type": "string",
                "description": "One-line reason when status='failed' so the UI can show it.",
            },
        },
        "required": ["kpi_id", "plan"],
    },
}


# =============================================================================
# Tool: kpi_record_value
# =============================================================================

def kpi_record_value(
    kpi_id: str,
    value: float,
    source: str = "",
    notes: str = "",
    **kwargs,
) -> str:
    """Record a new measurement for a KPI. Updates current/previous values."""
    db = _db()
    row = db.execute("SELECT * FROM kpis WHERE id = ?", (kpi_id,)).fetchone()
    if not row:
        return json.dumps({"error": f"KPI {kpi_id} not found."})

    try:
        value = float(value)
    except (TypeError, ValueError):
        return json.dumps({"error": "value must be numeric"})

    now = time.time()
    vid = uuid.uuid4().hex[:12]
    db.execute(
        "INSERT INTO kpi_values (id, kpi_id, value, source, notes, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
        (vid, kpi_id, value, source or None, notes or None, now),
    )
    db.execute(
        "UPDATE kpis SET previous_value = current_value, current_value = ?, last_measured_at = ?, "
        "measurement_status = 'configured', measurement_error = NULL, updated_at = ? WHERE id = ?",
        (value, now, now, kpi_id),
    )
    db.commit()

    prev = row["current_value"]
    change_pct = None
    if prev is not None and prev != 0:
        change_pct = round((value - prev) / abs(prev) * 100, 2)
    return json.dumps({
        "ok": True,
        "kpi_id": kpi_id,
        "value": value,
        "previous": prev,
        "change_pct": change_pct,
    })


KPI_RECORD_VALUE_SCHEMA = {
    "name": "kpi_record_value",
    "description": (
        "Record a new value for a KPI. Call this every time you measure the KPI. "
        "Include a short source (e.g. 'posthog:weekly_actives') and optional notes "
        "describing any caveats or context."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "kpi_id": {"type": "string"},
            "value": {"type": "number"},
            "source": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": ["kpi_id", "value"],
    },
}


# =============================================================================
# Tool: kpi_flag
# =============================================================================

def kpi_flag(
    kpi_id: str,
    kind: str,
    title: str,
    description: str = "",
    references: str = "[]",
    brief_id: str = "",
    **kwargs,
) -> str:
    """Raise a risk or opportunity flag on a KPI.

    Rule: only flag when movement or an external signal is *actually* worth the
    user's attention. No flag is better than a noisy flag.
    """
    if kind not in ("risk", "opportunity"):
        return json.dumps({"error": "kind must be 'risk' or 'opportunity'"})

    db = _db()
    row = db.execute("SELECT id FROM kpis WHERE id = ?", (kpi_id,)).fetchone()
    if not row:
        return json.dumps({"error": f"KPI {kpi_id} not found."})

    try:
        refs = json.loads(references) if isinstance(references, str) else references
        if not isinstance(refs, list):
            refs = []
    except json.JSONDecodeError:
        refs = []

    flag_id = uuid.uuid4().hex[:12]
    now = time.time()
    db.execute(
        "INSERT INTO kpi_flags (id, kpi_id, kind, title, description, references_json, "
        "brief_id, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
        (flag_id, kpi_id, kind, title, description or None,
         json.dumps(refs), brief_id or None, now, now),
    )
    db.commit()
    return json.dumps({"ok": True, "flag_id": flag_id, "kind": kind})


KPI_FLAG_SCHEMA = {
    "name": "kpi_flag",
    "description": (
        "Raise a risk or opportunity flag on a KPI. Only call this when the signal is "
        "clearly worth the user's attention — not every movement deserves a flag. "
        "A risk is something that could harm the KPI; an opportunity is a lever you "
        "spotted that could boost it. Silence is the correct answer when the KPI is "
        "moving normally."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "kpi_id": {"type": "string"},
            "kind": {"type": "string", "enum": ["risk", "opportunity"]},
            "title": {"type": "string"},
            "description": {
                "type": "string",
                "description": "What you observed + why it matters for this KPI + what action it implies.",
            },
            "references": {
                "type": "string",
                "description": 'JSON array of references: [{"type":"issue|pr|link","url":"...","title":"..."}]',
            },
            "brief_id": {
                "type": "string",
                "description": "Brief ID if this flag is raised during a brief run.",
            },
        },
        "required": ["kpi_id", "kind", "title"],
    },
}


# =============================================================================
# Registry
# =============================================================================

registry.register(
    name="kpi_list",
    toolset="pm-kpis",
    schema=KPI_LIST_SCHEMA,
    handler=lambda args, **kw: kpi_list(status=args.get("status", "active")),
)

registry.register(
    name="kpi_get",
    toolset="pm-kpis",
    schema=KPI_GET_SCHEMA,
    handler=lambda args, **kw: kpi_get(
        kpi_id=args.get("kpi_id", ""),
        history_limit=int(args.get("history_limit", 30)),
    ),
)

registry.register(
    name="kpi_set_measurement_plan",
    toolset="pm-kpis",
    schema=KPI_SET_MEASUREMENT_PLAN_SCHEMA,
    handler=lambda args, **kw: kpi_set_measurement_plan(
        kpi_id=args.get("kpi_id", ""),
        plan=args.get("plan", ""),
        status=args.get("status", "configured"),
        error=args.get("error", ""),
    ),
)

registry.register(
    name="kpi_record_value",
    toolset="pm-kpis",
    schema=KPI_RECORD_VALUE_SCHEMA,
    handler=lambda args, **kw: kpi_record_value(
        kpi_id=args.get("kpi_id", ""),
        value=args.get("value"),
        source=args.get("source", ""),
        notes=args.get("notes", ""),
    ),
)

registry.register(
    name="kpi_flag",
    toolset="pm-kpis",
    schema=KPI_FLAG_SCHEMA,
    handler=lambda args, **kw: kpi_flag(
        kpi_id=args.get("kpi_id", ""),
        kind=args.get("kind", ""),
        title=args.get("title", ""),
        description=args.get("description", ""),
        references=args.get("references", "[]"),
        brief_id=args.get("brief_id", ""),
    ),
)
