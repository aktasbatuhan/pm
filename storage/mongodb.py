"""
MongoDB session storage backend.

Drop-in replacement for kai_state.SessionDB — implements the same
method signatures so it satisfies SessionStorageBackend protocol.

Follows kai-backend conventions:
    - Same database (default: kai_test)
    - Collections prefixed with agent_: agent_sessions, agent_messages
    - All documents include workspaceId field for workspace scoping
    - Indexes include workspaceId as primary grouping key

Requires: pymongo >= 4.6.0
    pip install kai-agent[remote-storage]
"""

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import pymongo
from pymongo import MongoClient, ASCENDING, DESCENDING

logger = logging.getLogger(__name__)

# Singleton client — thread-safe, connection-pooled
_clients: Dict[str, MongoClient] = {}


def _get_client(uri: str) -> MongoClient:
    if uri not in _clients:
        _clients[uri] = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return _clients[uri]


class MongoSessionBackend:
    """
    MongoDB-backed session and message storage.

    All documents are scoped to a workspaceId, matching kai-backend conventions.
    Collections: agent_sessions, agent_messages (in the same DB as kai-backend).
    """

    MAX_TITLE_LENGTH = 100  # Match SessionDB

    def __init__(
        self,
        uri: str = "mongodb://localhost:27017",
        database: str = "kai_test",
        workspace_id: str = None,
    ):
        self._client = _get_client(uri)
        self._db = self._client[database]
        from kai_env import get_env
        self._workspace_id = workspace_id or get_env("KAI_WORKSPACE_ID", "default")
        # Collections follow kai-backend naming: agent_ prefix
        self._sessions = self._db["agent_sessions"]
        self._messages = self._db["agent_messages"]
        self._ensure_indexes()

    def _ensure_indexes(self):
        """Create indexes (idempotent). workspaceId is the primary grouping key."""
        self._sessions.create_index([("workspaceId", ASCENDING), ("started_at", DESCENDING)])
        self._sessions.create_index([("workspaceId", ASCENDING), ("source", ASCENDING)])
        self._sessions.create_index("parent_session_id")
        try:
            self._sessions.create_index(
                [("workspaceId", ASCENDING), ("title", ASCENDING)],
                unique=True,
                partialFilterExpression={"title": {"$exists": True, "$type": "string"}},
            )
        except pymongo.errors.OperationFailure:
            pass
        self._messages.create_index([("session_id", ASCENDING), ("seq", ASCENDING)])
        self._messages.create_index([("workspaceId", ASCENDING), ("session_id", ASCENDING)])
        try:
            self._messages.create_index([("content", "text")])
        except pymongo.errors.OperationFailure:
            pass

    # ── Session lifecycle ───────────────────────────────────────────

    def create_session(
        self,
        session_id: str,
        source: str,
        model: str = None,
        model_config: Dict[str, Any] = None,
        system_prompt: str = None,
        user_id: str = None,
        parent_session_id: str = None,
    ) -> str:
        doc = {
            "_id": session_id,
            "workspaceId": self._workspace_id,
            "source": source,
            "user_id": user_id,
            "model": model,
            "model_config": model_config,
            "system_prompt": system_prompt,
            "parent_session_id": parent_session_id,
            "started_at": time.time(),
            "ended_at": None,
            "end_reason": None,
            "message_count": 0,
            "tool_call_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "title": None,
        }
        try:
            self._sessions.insert_one(doc)
        except pymongo.errors.DuplicateKeyError:
            pass
        return session_id

    def end_session(self, session_id: str, end_reason: str) -> None:
        self._sessions.update_one(
            {"_id": session_id},
            {"$set": {"ended_at": time.time(), "end_reason": end_reason}},
        )

    def update_system_prompt(self, session_id: str, system_prompt: str) -> None:
        self._sessions.update_one(
            {"_id": session_id},
            {"$set": {"system_prompt": system_prompt}},
        )

    def update_token_counts(
        self, session_id: str, input_tokens: int = 0, output_tokens: int = 0
    ) -> None:
        self._sessions.update_one(
            {"_id": session_id},
            {"$inc": {"input_tokens": input_tokens, "output_tokens": output_tokens}},
        )

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        doc = self._sessions.find_one({"_id": session_id})
        if not doc:
            return None
        return self._session_doc_to_dict(doc)

    @staticmethod
    def _session_doc_to_dict(doc: dict) -> Dict[str, Any]:
        result = dict(doc)
        result["id"] = result.pop("_id")
        return result

    # ── Titles ──────────────────────────────────────────────────────

    @staticmethod
    def sanitize_title(title: Optional[str]) -> Optional[str]:
        if not title:
            return None
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', title)
        cleaned = re.sub(
            r'[\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff\ufffc\ufff9-\ufffb]',
            '', cleaned,
        )
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        if not cleaned:
            return None
        if len(cleaned) > MongoSessionBackend.MAX_TITLE_LENGTH:
            raise ValueError(
                f"Title too long ({len(cleaned)} chars, max {MongoSessionBackend.MAX_TITLE_LENGTH})"
            )
        return cleaned

    def set_session_title(self, session_id: str, title: str) -> bool:
        title = self.sanitize_title(title)
        if title:
            conflict = self._sessions.find_one(
                {"title": title, "_id": {"$ne": session_id}, "workspaceId": self._workspace_id}
            )
            if conflict:
                raise ValueError(
                    f"Title '{title}' is already in use by session {conflict['_id']}"
                )
        result = self._sessions.update_one(
            {"_id": session_id}, {"$set": {"title": title}}
        )
        return result.modified_count > 0

    def get_session_title(self, session_id: str) -> Optional[str]:
        doc = self._sessions.find_one({"_id": session_id}, {"title": 1})
        return doc["title"] if doc else None

    def get_session_by_title(self, title: str) -> Optional[Dict[str, Any]]:
        doc = self._sessions.find_one({"title": title, "workspaceId": self._workspace_id})
        if not doc:
            return None
        return self._session_doc_to_dict(doc)

    def resolve_session_by_title(self, title: str) -> Optional[str]:
        exact = self.get_session_by_title(title)
        escaped = re.escape(title)
        pattern = f"^{escaped} #\\d+$"
        numbered = list(
            self._sessions.find(
                {"title": {"$regex": pattern}, "workspaceId": self._workspace_id},
                {"_id": 1, "title": 1, "started_at": 1},
            ).sort("started_at", DESCENDING)
        )
        if numbered:
            return numbered[0]["_id"]
        elif exact:
            return exact["id"]
        return None

    def get_next_title_in_lineage(self, base_title: str) -> str:
        match = re.match(r'^(.*?) #(\d+)$', base_title)
        base = match.group(1) if match else base_title

        escaped = re.escape(base)
        existing = list(
            self._sessions.find(
                {"$or": [
                    {"title": base, "workspaceId": self._workspace_id},
                    {"title": {"$regex": f"^{escaped} #\\d+$"}, "workspaceId": self._workspace_id},
                ]},
                {"title": 1},
            )
        )
        if not existing:
            return base

        max_num = 1
        for doc in existing:
            m = re.match(r'^.* #(\d+)$', doc.get("title", ""))
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"{base} #{max_num + 1}"

    # ── Messages ────────────────────────────────────────────────────

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str = None,
        tool_name: str = None,
        tool_calls: Any = None,
        tool_call_id: str = None,
        token_count: int = None,
        finish_reason: str = None,
    ) -> int:
        last = self._messages.find_one(
            {"session_id": session_id},
            {"seq": 1},
            sort=[("seq", DESCENDING)],
        )
        seq = (last["seq"] + 1) if last else 1

        doc = {
            "workspaceId": self._workspace_id,
            "session_id": session_id,
            "seq": seq,
            "role": role,
            "content": content,
            "tool_call_id": tool_call_id,
            "tool_calls": tool_calls,
            "tool_name": tool_name,
            "timestamp": time.time(),
            "token_count": token_count,
            "finish_reason": finish_reason,
        }
        self._messages.insert_one(doc)

        num_tool_calls = 0
        if tool_calls is not None:
            num_tool_calls = len(tool_calls) if isinstance(tool_calls, list) else 1

        inc = {"message_count": 1}
        if num_tool_calls > 0:
            inc["tool_call_count"] = num_tool_calls
        self._sessions.update_one({"_id": session_id}, {"$inc": inc})

        return seq

    def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        cursor = self._messages.find(
            {"session_id": session_id}
        ).sort([("seq", ASCENDING)])

        result = []
        for doc in cursor:
            msg = dict(doc)
            msg["id"] = msg.pop("_id")
            result.append(msg)
        return result

    def get_messages_as_conversation(self, session_id: str) -> List[Dict[str, Any]]:
        cursor = self._messages.find(
            {"session_id": session_id},
            {"role": 1, "content": 1, "tool_call_id": 1, "tool_calls": 1, "tool_name": 1},
        ).sort([("seq", ASCENDING)])

        messages = []
        for doc in cursor:
            msg = {"role": doc["role"], "content": doc.get("content")}
            if doc.get("tool_call_id"):
                msg["tool_call_id"] = doc["tool_call_id"]
            if doc.get("tool_name"):
                msg["tool_name"] = doc["tool_name"]
            if doc.get("tool_calls"):
                msg["tool_calls"] = doc["tool_calls"]
            messages.append(msg)
        return messages

    def clear_messages(self, session_id: str) -> None:
        self._messages.delete_many({"session_id": session_id})
        self._sessions.update_one(
            {"_id": session_id},
            {"$set": {"message_count": 0, "tool_call_count": 0}},
        )

    # ── Search ──────────────────────────────────────────────────────

    def search_messages(
        self,
        query: str,
        source_filter: List[str] = None,
        role_filter: List[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        if not query or not query.strip():
            return []

        if source_filter is None:
            source_filter = ["cli", "telegram", "discord", "whatsapp", "slack"]

        session_filter = {"source": {"$in": source_filter}, "workspaceId": self._workspace_id}
        session_ids = [
            doc["_id"]
            for doc in self._sessions.find(session_filter, {"_id": 1})
        ]
        if not session_ids:
            return []

        msg_query: Dict[str, Any] = {
            "$text": {"$search": query},
            "session_id": {"$in": session_ids},
        }
        if role_filter:
            msg_query["role"] = {"$in": role_filter}

        try:
            cursor = self._messages.find(
                msg_query,
                {"score": {"$meta": "textScore"}},
            ).sort([("score", {"$meta": "textScore"})]).skip(offset).limit(limit)

            matches = []
            for doc in cursor:
                session = self._sessions.find_one({"_id": doc["session_id"]})
                content_str = doc.get("content", "") or ""
                snippet = content_str[:200] + ("..." if len(content_str) > 200 else "")

                match = {
                    "id": doc["_id"],
                    "session_id": doc["session_id"],
                    "role": doc["role"],
                    "snippet": snippet,
                    "timestamp": doc.get("timestamp"),
                    "tool_name": doc.get("tool_name"),
                    "source": session.get("source") if session else None,
                    "model": session.get("model") if session else None,
                    "session_started": session.get("started_at") if session else None,
                    "context": [],
                }

                seq = doc.get("seq", 0)
                if seq > 0:
                    ctx_cursor = self._messages.find(
                        {
                            "session_id": doc["session_id"],
                            "seq": {"$gte": max(1, seq - 1), "$lte": seq + 1},
                        },
                    ).sort([("seq", ASCENDING)])
                    match["context"] = [
                        {"role": c["role"], "content": (c.get("content") or "")[:200]}
                        for c in ctx_cursor
                    ]

                matches.append(match)
            return matches
        except pymongo.errors.OperationFailure:
            return []

    def search_sessions(
        self,
        source: str = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"workspaceId": self._workspace_id}
        if source:
            query["source"] = source
        cursor = self._sessions.find(query).sort(
            "started_at", DESCENDING
        ).skip(offset).limit(limit)
        return [self._session_doc_to_dict(doc) for doc in cursor]

    def list_sessions_rich(
        self,
        source: str = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"workspaceId": self._workspace_id}
        if source:
            query["source"] = source
        cursor = self._sessions.find(query).sort(
            "started_at", DESCENDING
        ).skip(offset).limit(limit)

        sessions = []
        for doc in cursor:
            s = self._session_doc_to_dict(doc)

            first_user = self._messages.find_one(
                {"session_id": s["id"], "role": "user", "content": {"$ne": None}},
                sort=[("seq", ASCENDING)],
            )
            if first_user and first_user.get("content"):
                raw = first_user["content"].replace("\n", " ").replace("\r", " ")[:63].strip()
                s["preview"] = raw[:60] + ("..." if len(raw) > 60 else "")
            else:
                s["preview"] = ""

            last_msg = self._messages.find_one(
                {"session_id": s["id"]},
                {"timestamp": 1},
                sort=[("seq", DESCENDING)],
            )
            s["last_active"] = last_msg["timestamp"] if last_msg else s.get("started_at")

            sessions.append(s)
        return sessions

    # ── Utility ─────────────────────────────────────────────────────

    def session_count(self, source: str = None) -> int:
        query: Dict[str, Any] = {"workspaceId": self._workspace_id}
        if source:
            query["source"] = source
        return self._sessions.count_documents(query)

    def message_count(self, session_id: str = None) -> int:
        query: Dict[str, Any] = {"workspaceId": self._workspace_id}
        if session_id:
            query["session_id"] = session_id
        return self._messages.count_documents(query)

    # ── Export & cleanup ────────────────────────────────────────────

    def export_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        session = self.get_session(session_id)
        if not session:
            return None
        messages = self.get_messages(session_id)
        return {**session, "messages": messages}

    def export_all(self, source: str = None) -> List[Dict[str, Any]]:
        sessions = self.search_sessions(source=source, limit=100000)
        results = []
        for session in sessions:
            messages = self.get_messages(session["id"])
            results.append({**session, "messages": messages})
        return results

    def delete_session(self, session_id: str) -> bool:
        result = self._sessions.delete_one({"_id": session_id})
        self._messages.delete_many({"session_id": session_id})
        return result.deleted_count > 0

    def prune_sessions(self, older_than_days: int = 90, source: str = None) -> int:
        cutoff = time.time() - (older_than_days * 86400)
        query: Dict[str, Any] = {
            "workspaceId": self._workspace_id,
            "started_at": {"$lt": cutoff},
            "ended_at": {"$ne": None},
        }
        if source:
            query["source"] = source

        session_ids = [
            doc["_id"]
            for doc in self._sessions.find(query, {"_id": 1})
        ]
        if not session_ids:
            return 0

        self._messages.delete_many({"session_id": {"$in": session_ids}})
        result = self._sessions.delete_many({"_id": {"$in": session_ids}})
        return result.deleted_count

    def close(self) -> None:
        pass  # MongoClient is pooled/singleton
