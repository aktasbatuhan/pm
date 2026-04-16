"""
DEPRECATED: This module is being replaced by server-side workspace context
accessed via MCP tools (workspace_status, workspace_blueprint_get, etc.).
See workspace_context_bridge.py for the new entry point integration.

The WorkspaceContext class is still used by storage/factory.py for the
local backend mode. Do not add new callers.

Old description:
Workspace Context — shared state layer across all agent threads.
Storage: SQLite tables in ~/.kai-agent/workspace.db.
    ...
    ctx.update_thread(thread_id, platform, summary)
    ctx.add_learning(category, content, source_thread)
"""

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from kai_env import kai_home, get_env

logger = logging.getLogger(__name__)

_kai_home = kai_home()
DEFAULT_WS_DB_PATH = _kai_home / "workspace.db"

# Bounds
MAX_LEARNINGS = 100
MAX_THREAD_SUMMARY_CHARS = 200
BLUEPRINT_SUMMARY_MAX_CHARS = 4000
LEARNINGS_PROMPT_MAX_CHARS = 3000
THREAD_INDEX_PROMPT_MAX_CHARS = 1500
PENDING_WORK_PROMPT_MAX_CHARS = 1500

WORKSPACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_meta (
    workspace_id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    onboarding_status TEXT NOT NULL DEFAULT 'not_started',
    onboarding_phase TEXT,
    onboarded_at REAL
);

CREATE TABLE IF NOT EXISTS blueprint (
    workspace_id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    summary TEXT NOT NULL,
    updated_at REAL NOT NULL,
    updated_by TEXT
);

CREATE TABLE IF NOT EXISTS thread_index (
    thread_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    last_active REAL NOT NULL,
    summary TEXT NOT NULL,
    user_id TEXT
);

CREATE TABLE IF NOT EXISTS learnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    source_thread TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_work (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    description TEXT NOT NULL,
    linked_thread TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_thread_workspace ON thread_index(workspace_id);
CREATE INDEX IF NOT EXISTS idx_thread_active ON thread_index(last_active DESC);
CREATE INDEX IF NOT EXISTS idx_learnings_workspace ON learnings(workspace_id);
CREATE INDEX IF NOT EXISTS idx_learnings_created ON learnings(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pending_workspace ON pending_work(workspace_id);
CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_work(status);
"""


class WorkspaceContext:
    """
    Shared workspace context that all agent threads read and write.

    NOT a service — just a data access layer around a SQLite database.
    Thread-safe via WAL mode (multiple readers, single writer).
    """

    def __init__(self, workspace_id: str, db_path: Path = None):
        self.workspace_id = workspace_id
        self.db_path = Path(db_path) if db_path else DEFAULT_WS_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=10.0,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(WORKSPACE_SCHEMA)

        # Ensure workspace record exists
        now = time.time()
        self._conn.execute(
            "INSERT OR IGNORE INTO workspace_meta (workspace_id, created_at, updated_at) VALUES (?, ?, ?)",
            (workspace_id, now, now),
        )
        self._conn.commit()

    # ── Reads ──────────────────────────────────────────────────────────

    def get_blueprint(self) -> Optional[Dict[str, Any]]:
        """Get the latest workspace blueprint, or None if not yet built."""
        row = self._conn.execute(
            "SELECT data, summary, updated_at FROM blueprint WHERE workspace_id = ?",
            (self.workspace_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "data": json.loads(row["data"]),
            "summary": row["summary"],
            "updated_at": row["updated_at"],
        }

    def get_threads(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent active threads for this workspace."""
        rows = self._conn.execute(
            "SELECT thread_id, platform, last_active, summary, user_id "
            "FROM thread_index WHERE workspace_id = ? ORDER BY last_active DESC LIMIT ?",
            (self.workspace_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_learnings(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Get recent learnings, newest first."""
        rows = self._conn.execute(
            "SELECT id, category, content, source_thread, created_at "
            "FROM learnings WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
            (self.workspace_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_pending_work(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Get pending/in-progress work items."""
        if active_only:
            rows = self._conn.execute(
                "SELECT id, type, status, description, linked_thread, updated_at "
                "FROM pending_work WHERE workspace_id = ? AND status IN ('pending', 'in_progress', 'approved', 'blocked') "
                "ORDER BY updated_at DESC",
                (self.workspace_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, type, status, description, linked_thread, updated_at "
                "FROM pending_work WHERE workspace_id = ? ORDER BY updated_at DESC LIMIT 20",
                (self.workspace_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Writes ─────────────────────────────────────────────────────────

    def update_blueprint(self, data: Dict[str, Any], summary: str, updated_by: str = "lifecycle") -> None:
        """Write or replace the workspace blueprint."""
        now = time.time()
        self._conn.execute(
            "INSERT INTO blueprint (workspace_id, data, summary, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(workspace_id) DO UPDATE SET data=excluded.data, summary=excluded.summary, "
            "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            (self.workspace_id, json.dumps(data), summary[:BLUEPRINT_SUMMARY_MAX_CHARS], now, updated_by),
        )
        self._touch()
        self._conn.commit()

    def update_thread(self, thread_id: str, platform: str, summary: str, user_id: str = None) -> None:
        """Update or create a thread entry in the index."""
        now = time.time()
        self._conn.execute(
            "INSERT INTO thread_index (thread_id, workspace_id, platform, last_active, summary, user_id) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(thread_id) DO UPDATE SET last_active=excluded.last_active, "
            "summary=excluded.summary, platform=excluded.platform, user_id=excluded.user_id",
            (thread_id, self.workspace_id, platform, now, summary[:MAX_THREAD_SUMMARY_CHARS], user_id),
        )
        self._touch()
        self._conn.commit()

    def add_learning(self, category: str, content: str, source_thread: str = None) -> None:
        """Add a learning entry. Auto-evicts oldest if over MAX_LEARNINGS."""
        now = time.time()
        self._conn.execute(
            "INSERT INTO learnings (workspace_id, category, content, source_thread, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (self.workspace_id, category, content, source_thread, now),
        )
        # Evict oldest beyond limit
        self._conn.execute(
            "DELETE FROM learnings WHERE workspace_id = ? AND id NOT IN "
            "(SELECT id FROM learnings WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?)",
            (self.workspace_id, self.workspace_id, MAX_LEARNINGS),
        )
        self._touch()
        self._conn.commit()

    def add_pending_work(self, work_id: str, work_type: str, description: str, linked_thread: str = None) -> None:
        """Add a pending work item (from lifecycle proposals, cron, etc.)."""
        now = time.time()
        self._conn.execute(
            "INSERT INTO pending_work (id, workspace_id, type, status, description, linked_thread, created_at, updated_at) "
            "VALUES (?, ?, ?, 'pending', ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET description=excluded.description, updated_at=excluded.updated_at",
            (work_id, self.workspace_id, work_type, description, linked_thread, now, now),
        )
        self._touch()
        self._conn.commit()

    def update_pending_work_status(self, work_id: str, status: str) -> None:
        """Update status of a work item (pending, in_progress, approved, blocked, completed, rejected)."""
        now = time.time()
        self._conn.execute(
            "UPDATE pending_work SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, work_id),
        )
        self._conn.commit()

    # ── Onboarding state ─────────────────────────────────────────────

    def get_onboarding_status(self) -> str:
        """Get onboarding status: not_started, in_progress, completed."""
        row = self._conn.execute(
            "SELECT onboarding_status FROM workspace_meta WHERE workspace_id = ?",
            (self.workspace_id,),
        ).fetchone()
        return row["onboarding_status"] if row else "not_started"

    def set_onboarding_status(self, status: str, phase: str = None) -> None:
        """Update onboarding status and optionally the current phase."""
        now = time.time()
        if status == "completed":
            self._conn.execute(
                "UPDATE workspace_meta SET onboarding_status = ?, onboarding_phase = ?, onboarded_at = ?, updated_at = ? "
                "WHERE workspace_id = ?",
                (status, phase, now, now, self.workspace_id),
            )
        else:
            self._conn.execute(
                "UPDATE workspace_meta SET onboarding_status = ?, onboarding_phase = ?, updated_at = ? "
                "WHERE workspace_id = ?",
                (status, phase, now, self.workspace_id),
            )
        self._conn.commit()

    def is_onboarded(self) -> bool:
        """Check if workspace has completed onboarding."""
        return self.get_onboarding_status() == "completed"

    def needs_onboarding(self) -> bool:
        """Check if workspace needs onboarding (not started or in progress)."""
        return self.get_onboarding_status() != "completed"

    # ── System prompt rendering ────────────────────────────────────────

    def to_system_prompt(self, current_thread_id: str = None) -> str:
        """
        Render the workspace context as a string for injection into system_message.

        Excludes the current thread from the sibling thread list (you don't need
        to tell yourself what you're currently doing).

        Target: ~3-4K tokens total.
        """
        parts = []

        parts.append("## Workspace Context\n")
        parts.append(
            "You have a shared workspace context that persists across all your conversations "
            "(web chat, Slack, lifecycle, cron jobs). Use it to stay coherent across threads. "
            "Information below reflects the latest state.\n"
        )

        # Blueprint
        bp = self.get_blueprint()
        if bp:
            _age = _format_age(bp["updated_at"])
            parts.append(f"### Workspace Blueprint (updated {_age})\n{bp['summary']}\n")

        # Sibling threads
        threads = self.get_threads(limit=8)
        sibling_threads = [t for t in threads if t["thread_id"] != current_thread_id]
        if sibling_threads:
            lines = ["### Other Active Threads"]
            for t in sibling_threads[:6]:
                age = _format_age(t["last_active"])
                user = f" (user: {t['user_id']})" if t.get("user_id") else ""
                lines.append(f"- **{t['platform']}** ({age}){user}: {t['summary']}")
            thread_block = "\n".join(lines)
            if len(thread_block) > THREAD_INDEX_PROMPT_MAX_CHARS:
                thread_block = thread_block[:THREAD_INDEX_PROMPT_MAX_CHARS] + "..."
            parts.append(thread_block + "\n")

        # Learnings
        learnings = self.get_learnings(limit=20)
        if learnings:
            lines = ["### What I Know"]
            for l in learnings:
                lines.append(f"- [{l['category']}] {l['content']}")
            learnings_block = "\n".join(lines)
            if len(learnings_block) > LEARNINGS_PROMPT_MAX_CHARS:
                learnings_block = learnings_block[:LEARNINGS_PROMPT_MAX_CHARS] + "..."
            parts.append(learnings_block + "\n")

        # Pending work
        pending = self.get_pending_work()
        if pending:
            lines = ["### Pending Work"]
            for w in pending:
                lines.append(f"- [{w['status']}] ({w['type']}) {w['description']}")
            pending_block = "\n".join(lines)
            if len(pending_block) > PENDING_WORK_PROMPT_MAX_CHARS:
                pending_block = pending_block[:PENDING_WORK_PROMPT_MAX_CHARS] + "..."
            parts.append(pending_block + "\n")

        result = "\n".join(parts).strip()

        # Fresh workspace — trigger onboarding
        if self.needs_onboarding() and not bp and not learnings:
            onboarding_status = self.get_onboarding_status()
            if onboarding_status == "not_started":
                result = (
                    "## Workspace Context\n\n"
                    "This is a fresh workspace. No blueprint, no history, no learnings.\n\n"
                    "**You must onboard.** Load the self-onboard skill immediately:\n"
                    "1. Call `skill_view` with name `pm-onboarding/self-onboard` to load the onboarding workflow.\n"
                    "2. Follow the skill instructions — introduce yourself, explore the workspace, share findings, build context.\n"
                    "3. Do NOT ask permission to explore. You are a new engineer on your first day — open the code and look around.\n\n"
                    "Start now. Your first action should be calling skill_view, then immediately calling list_my_workspaces and list_repositories."
                )
            elif onboarding_status == "in_progress":
                result = (
                    "## Workspace Context\n\n"
                    "Onboarding is in progress. Continue where you left off.\n"
                    "Load the self-onboard skill with `skill_view` name `pm-onboarding/self-onboard` if you need to review the flow.\n"
                    "Pick up from the last phase — check what repos and integrations are already connected."
                )

        return result

    # ── Helpers ─────────────────────────────────────────────────────────

    def _touch(self):
        """Update workspace modified timestamp."""
        self._conn.execute(
            "UPDATE workspace_meta SET updated_at = ? WHERE workspace_id = ?",
            (time.time(), self.workspace_id),
        )

    def close(self):
        """Close the database connection."""
        try:
            self._conn.close()
        except Exception:
            pass


def _format_age(timestamp: float) -> str:
    """Format a timestamp as human-readable relative age."""
    delta = time.time() - timestamp
    if delta < 60:
        return "just now"
    if delta < 3600:
        m = int(delta / 60)
        return f"{m}min ago"
    if delta < 86400:
        h = int(delta / 3600)
        return f"{h}h ago"
    d = int(delta / 86400)
    return f"{d}d ago"


def load_workspace_context(workspace_id: str = None, db_path: Path = None) -> WorkspaceContext:
    """
    Load workspace context for the given workspace ID.

    If workspace_id is not provided, reads from HERMES_WORKSPACE_ID env var,
    falling back to "default".
    """
    ws_id = workspace_id or get_env("KAI_WORKSPACE_ID", "default")
    return WorkspaceContext(ws_id, db_path=db_path)


def post_turn_update(
    ctx: WorkspaceContext,
    thread_id: str,
    platform: str,
    result: Dict[str, Any],
    user_id: str = None,
) -> None:
    """
    Post-turn hook: update shared workspace context after a run_conversation completes.

    Extracts a thread summary from the final response and writes it back.
    This is intentionally simple — no LLM call, just truncation of the last response.
    For long/complex turns, the caller can provide a better summary.
    """
    final_response = result.get("final_response", "")

    # Simple summary: first sentence or first 200 chars of the response
    summary = _extract_summary(final_response)
    if summary:
        ctx.update_thread(thread_id, platform, summary, user_id=user_id)


def _extract_summary(text: str) -> str:
    """Extract a short summary from a response — first meaningful sentence."""
    if not text:
        return ""
    # Strip markdown formatting
    clean = text.strip().replace("**", "").replace("##", "").replace("- ", "")
    # Take first line or first sentence
    for sep in ["\n", ". ", "! ", "? "]:
        idx = clean.find(sep)
        if 0 < idx < 200:
            return clean[:idx + 1].strip()
    return clean[:200].strip()
