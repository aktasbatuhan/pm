"""
MongoDB workspace context backend.

Drop-in replacement for workspace_context.WorkspaceContext — implements
the same method signatures so it satisfies WorkspaceStorageBackend protocol.

Collections:
    workspace_meta  — one document per workspace
    blueprints      — one document per workspace
    thread_index    — one document per thread
    learnings       — one document per learning entry
    pending_work    — one document per work item

Requires: pymongo >= 4.6.0
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

import pymongo
from pymongo import ASCENDING, DESCENDING

from storage.mongodb import _get_client

logger = logging.getLogger(__name__)

# Bounds (match workspace_context.py)
MAX_LEARNINGS = 100
MAX_THREAD_SUMMARY_CHARS = 200
BLUEPRINT_SUMMARY_MAX_CHARS = 4000
LEARNINGS_PROMPT_MAX_CHARS = 3000
THREAD_INDEX_PROMPT_MAX_CHARS = 1500
PENDING_WORK_PROMPT_MAX_CHARS = 1500


class MongoWorkspaceBackend:
    """
    MongoDB-backed workspace context storage.

    Thread-safe via pymongo's built-in connection pooling.
    """

    def __init__(
        self,
        workspace_id: str,
        uri: str = "mongodb://localhost:27017",
        database: str = "kai_agent",
    ):
        self.workspace_id = workspace_id
        client = _get_client(uri)
        self._db = client[database]
        self._meta = self._db["workspace_meta"]
        self._blueprints = self._db["blueprints"]
        self._threads = self._db["thread_index"]
        self._learnings = self._db["learnings"]
        self._pending = self._db["pending_work"]
        self._ensure_indexes()
        self._ensure_workspace()

    def _ensure_indexes(self):
        self._threads.create_index([("workspace_id", ASCENDING), ("last_active", DESCENDING)])
        self._learnings.create_index([("workspace_id", ASCENDING), ("created_at", DESCENDING)])
        self._pending.create_index([("workspace_id", ASCENDING), ("status", ASCENDING)])

    def _ensure_workspace(self):
        """Create workspace meta record if it doesn't exist."""
        now = time.time()
        self._meta.update_one(
            {"_id": self.workspace_id},
            {"$setOnInsert": {
                "created_at": now,
                "updated_at": now,
                "onboarding_status": "not_started",
                "onboarding_phase": None,
                "onboarded_at": None,
            }},
            upsert=True,
        )

    # ── Reads ───────────────────────────────────────────────────────

    def get_blueprint(self) -> Optional[Dict[str, Any]]:
        doc = self._blueprints.find_one({"_id": self.workspace_id})
        if not doc:
            return None
        return {
            "data": doc["data"],
            "summary": doc["summary"],
            "updated_at": doc["updated_at"],
        }

    def get_threads(self, limit: int = 10) -> List[Dict[str, Any]]:
        cursor = self._threads.find(
            {"workspace_id": self.workspace_id}
        ).sort("last_active", DESCENDING).limit(limit)
        results = []
        for doc in cursor:
            results.append({
                "thread_id": doc["_id"],
                "platform": doc["platform"],
                "last_active": doc["last_active"],
                "summary": doc["summary"],
                "user_id": doc.get("user_id"),
            })
        return results

    def get_learnings(self, limit: int = 30) -> List[Dict[str, Any]]:
        cursor = self._learnings.find(
            {"workspace_id": self.workspace_id}
        ).sort("created_at", DESCENDING).limit(limit)
        results = []
        for doc in cursor:
            results.append({
                "id": doc["_id"],
                "category": doc["category"],
                "content": doc["content"],
                "source_thread": doc.get("source_thread"),
                "created_at": doc["created_at"],
            })
        return results

    def get_pending_work(self, active_only: bool = True) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"workspace_id": self.workspace_id}
        if active_only:
            query["status"] = {"$in": ["pending", "in_progress", "approved", "blocked"]}

        cursor = self._pending.find(query).sort("updated_at", DESCENDING)
        if not active_only:
            cursor = cursor.limit(20)

        results = []
        for doc in cursor:
            results.append({
                "id": doc["_id"],
                "type": doc["type"],
                "status": doc["status"],
                "description": doc["description"],
                "linked_thread": doc.get("linked_thread"),
                "updated_at": doc["updated_at"],
            })
        return results

    # ── Writes ──────────────────────────────────────────────────────

    def update_blueprint(
        self, data: Dict[str, Any], summary: str, updated_by: str = "lifecycle"
    ) -> None:
        now = time.time()
        self._blueprints.update_one(
            {"_id": self.workspace_id},
            {"$set": {
                "data": data,
                "summary": summary[:BLUEPRINT_SUMMARY_MAX_CHARS],
                "updated_at": now,
                "updated_by": updated_by,
            }},
            upsert=True,
        )
        self._touch()

    def update_thread(
        self, thread_id: str, platform: str, summary: str, user_id: str = None
    ) -> None:
        now = time.time()
        self._threads.update_one(
            {"_id": thread_id},
            {"$set": {
                "workspace_id": self.workspace_id,
                "platform": platform,
                "last_active": now,
                "summary": summary[:MAX_THREAD_SUMMARY_CHARS],
                "user_id": user_id,
            }},
            upsert=True,
        )
        self._touch()

    def add_learning(
        self, category: str, content: str, source_thread: str = None
    ) -> None:
        now = time.time()
        self._learnings.insert_one({
            "workspace_id": self.workspace_id,
            "category": category,
            "content": content,
            "source_thread": source_thread,
            "created_at": now,
        })
        # Evict oldest beyond limit
        count = self._learnings.count_documents({"workspace_id": self.workspace_id})
        if count > MAX_LEARNINGS:
            oldest = list(
                self._learnings.find(
                    {"workspace_id": self.workspace_id},
                    {"_id": 1},
                ).sort("created_at", ASCENDING).limit(count - MAX_LEARNINGS)
            )
            if oldest:
                self._learnings.delete_many(
                    {"_id": {"$in": [d["_id"] for d in oldest]}}
                )
        self._touch()

    def add_pending_work(
        self, work_id: str, work_type: str, description: str, linked_thread: str = None
    ) -> None:
        now = time.time()
        self._pending.update_one(
            {"_id": work_id},
            {"$set": {
                "workspace_id": self.workspace_id,
                "type": work_type,
                "description": description,
                "linked_thread": linked_thread,
                "updated_at": now,
            },
            "$setOnInsert": {
                "status": "pending",
                "created_at": now,
            }},
            upsert=True,
        )
        self._touch()

    def update_pending_work_status(self, work_id: str, status: str) -> None:
        now = time.time()
        self._pending.update_one(
            {"_id": work_id},
            {"$set": {"status": status, "updated_at": now}},
        )

    # ── Onboarding ──────────────────────────────────────────────────

    def get_onboarding_status(self) -> str:
        doc = self._meta.find_one({"_id": self.workspace_id})
        return doc.get("onboarding_status", "not_started") if doc else "not_started"

    def set_onboarding_status(self, status: str, phase: str = None) -> None:
        now = time.time()
        update: Dict[str, Any] = {
            "onboarding_status": status,
            "onboarding_phase": phase,
            "updated_at": now,
        }
        if status == "completed":
            update["onboarded_at"] = now
        self._meta.update_one(
            {"_id": self.workspace_id},
            {"$set": update},
        )

    def is_onboarded(self) -> bool:
        return self.get_onboarding_status() == "completed"

    def needs_onboarding(self) -> bool:
        return self.get_onboarding_status() != "completed"

    # ── System prompt rendering ─────────────────────────────────────

    def to_system_prompt(self, current_thread_id: str = None) -> str:
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
            age = _format_age(bp["updated_at"])
            parts.append(f"### Workspace Blueprint (updated {age})\n{bp['summary']}\n")

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

    # ── Helpers ─────────────────────────────────────────────────────

    def _touch(self):
        self._meta.update_one(
            {"_id": self.workspace_id},
            {"$set": {"updated_at": time.time()}},
        )

    def close(self) -> None:
        pass  # MongoClient is pooled/singleton


def _format_age(timestamp: float) -> str:
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
