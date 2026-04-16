"""
PM Report tools — store generated reports linked to a template.
"""

import json
import os
import sqlite3
import time
import uuid

from kai_env import kai_home
from tools.registry import registry

_kai_home = kai_home()
_DB_PATH = _kai_home / "integrations.db"


def _get_db():
    db = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=10.0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    # Table should already exist from server.py _ensure_pm_tables
    return db


def report_save(template_id: str, content: str, **kwargs) -> str:
    """Store a generated report linked to a template."""
    if not template_id or not content:
        return json.dumps({"error": "template_id and content are required"})
    db = _get_db()
    # Verify template exists
    row = db.execute("SELECT id, name FROM report_templates WHERE id = ?", (template_id,)).fetchone()
    if not row:
        return json.dumps({"error": f"Template {template_id} not found"})
    report_id = str(uuid.uuid4())[:12]
    now = time.time()
    db.execute(
        "INSERT INTO reports (id, template_id, content, created_at) VALUES (?, ?, ?, ?)",
        (report_id, template_id, content, now),
    )
    db.commit()
    return json.dumps({
        "success": True,
        "report_id": report_id,
        "template_name": row["name"],
        "message": f"Report saved for template {row['name']}"
    })


REPORT_SAVE_SCHEMA = {
    "name": "report_save",
    "description": "Save a generated report for a specific template. Use this after producing the report content according to a template's structure.",
    "parameters": {
        "type": "object",
        "properties": {
            "template_id": {
                "type": "string",
                "description": "The template ID this report was generated for"
            },
            "content": {
                "type": "string",
                "description": "The full rendered report content in markdown"
            }
        },
        "required": ["template_id", "content"]
    }
}


registry.register(
    name="report_save",
    toolset="pm-reports",
    schema=REPORT_SAVE_SCHEMA,
    handler=lambda args, **kw: report_save(
        template_id=args.get("template_id", ""),
        content=args.get("content", "")),
)
