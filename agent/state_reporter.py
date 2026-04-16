"""
State reporter — pushes agent state, activities, patterns, sessions, and learnings
to the kai-backend via MCP tools.

All calls are fire-and-forget via a background thread with a queue.
If MCP is unreachable, events are logged and dropped (no retry).

Usage:
    reporter = StateReporter(workspace_id="ws_123", agent_id="agent_456")
    reporter.start()
    reporter.report_activity("scanning", "Deep scan started on api-gateway", detail="tier=deep")
    reporter.report_pattern("anomaly", "47 commits to auth/session.ts", ...)
    reporter.push_learning("security", "auth-service has highest blast radius")
    reporter.report_session("lifecycle", "Daily cycle", tool_call_count=15, duration_ms=120000)
    reporter.stop()
"""

import json
import logging
import queue
import threading
import time
from typing import Optional

from agent.mcp_bridge import mcp_call, get_workspace_id, get_agent_id

log = logging.getLogger("state-reporter")

# How long to batch activity events before flushing (seconds)
_BATCH_INTERVAL = 2.0

# Activity action types that map tool names to human-readable actions
_TOOL_ACTION_MAP = {
    "brief_store": "briefing",
    "brief_get_latest": "reviewing",
    "brief_get_action_items": "reviewing",
    "brief_resolve_action": "resolving",
    "read_file": "reading",
    "web_search": "researching",
    "memory": "remembering",
    "todo": "planning",
}

# Tool names to human-readable descriptions
_TOOL_DESC_MAP = {
    "brief_store": "Stored daily brief",
    "brief_get_latest": "Reading latest brief",
    "brief_get_action_items": "Checking action items",
    "brief_resolve_action": "Resolving action item",
    "read_file": "Reading file",
    "web_search": "Searching the web",
    "terminal": "Running terminal command",
    "memory": "Accessing memory",
    "todo": "Managing tasks",
}


class StateReporter:
    """Fire-and-forget reporter that pushes agent telemetry to kai-backend via MCP."""

    def __init__(self, workspace_id: Optional[str] = None, agent_id: Optional[str] = None):
        self.workspace_id = workspace_id or get_workspace_id()
        self.agent_id = agent_id or get_agent_id()
        self._queue: queue.Queue = queue.Queue(maxsize=500)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._started = False

    def start(self):
        """Start the background consumer thread."""
        if self._started:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._consumer_loop, daemon=True, name="state-reporter")
        self._thread.start()
        self._started = True
        log.debug("StateReporter started (workspace=%s, agent=%s)", self.workspace_id, self.agent_id)

    def stop(self):
        """Signal the consumer thread to drain and stop."""
        if not self._started:
            return
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._started = False
        log.debug("StateReporter stopped")

    def _enqueue(self, item: dict):
        """Put an item on the queue. Drop if full."""
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            log.debug("StateReporter queue full, dropping event: %s", item.get("_type"))

    def _consumer_loop(self):
        """Background thread: drain queue and send batched MCP calls."""
        activity_batch: list[dict] = []
        last_flush = time.monotonic()

        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.5)
                item_type = item.pop("_type", None)

                if item_type == "activity":
                    activity_batch.append(item)
                else:
                    # Non-activity items are sent immediately
                    self._send_item(item_type, item)

                # Flush activity batch if interval elapsed
                if activity_batch and (time.monotonic() - last_flush) >= _BATCH_INTERVAL:
                    self._flush_activities(activity_batch)
                    activity_batch = []
                    last_flush = time.monotonic()

            except queue.Empty:
                # Flush any pending activities on timeout
                if activity_batch and (time.monotonic() - last_flush) >= _BATCH_INTERVAL:
                    self._flush_activities(activity_batch)
                    activity_batch = []
                    last_flush = time.monotonic()

        # Final drain on stop
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                item_type = item.pop("_type", None)
                if item_type == "activity":
                    activity_batch.append(item)
                else:
                    self._send_item(item_type, item)
            except queue.Empty:
                break

        if activity_batch:
            self._flush_activities(activity_batch)

    def _flush_activities(self, batch: list[dict]):
        """Send each activity in the batch."""
        for activity in batch:
            self._send_item("activity", activity)

    def _send_item(self, item_type: Optional[str], item: dict):
        """Send a single item to the backend via MCP."""
        tool_map = {
            "activity": "report_activity",
            "pattern": "report_pattern",
            "session": "report_session",
            "learning": "workspace_learnings_add",
        }
        tool_name = tool_map.get(item_type)
        if not tool_name:
            log.debug("Unknown item type: %s", item_type)
            return

        try:
            mcp_call(tool_name, item, timeout=10)
        except Exception as e:
            log.debug("Failed to send %s via MCP: %s", item_type, e)

    # ── Public API ─────────────────────────────────────────────────────────

    def report_activity(
        self,
        tool_name: str,
        args: dict,
        result_preview: str = "",
        duration_ms: float = 0,
    ):
        """Report a tool call as an activity feed entry."""
        action = _TOOL_ACTION_MAP.get(tool_name, "started")
        description = _TOOL_DESC_MAP.get(tool_name)

        if not description:
            # Build description from tool name and args
            description = tool_name.replace("_", " ").replace("kai ", "")
            # Add relevant arg context
            for key in ("repoId", "repo", "path", "file", "query"):
                val = args.get(key)
                if val:
                    description += f" — {val}"
                    break

        # Mark critical PM actions as hot
        is_hot = tool_name in ("brief_store",)

        detail = f"{tool_name}({json.dumps(args, default=str)[:200]})" if args else tool_name

        self._enqueue({
            "_type": "activity",
            "workspaceId": self.workspace_id,
            "agentId": self.agent_id,
            "action": action,
            "description": description,
            "detail": detail,
            "isHot": is_hot,
            "timestamp": int(time.time() * 1000),
        })

    def report_pattern(
        self,
        pattern_type: str,
        title: str,
        description: str,
        signal_strength: int = 3,
        detail: Optional[str] = None,
        related_repo: Optional[str] = None,
        related_file: Optional[str] = None,
    ):
        """Report a detected codebase pattern."""
        item = {
            "_type": "pattern",
            "workspaceId": self.workspace_id,
            "type": pattern_type,
            "title": title,
            "description": description,
            "signalStrength": signal_strength,
        }
        if detail:
            item["detail"] = detail
        if related_repo:
            item["relatedRepo"] = related_repo
        if related_file:
            item["relatedFile"] = related_file
        self._enqueue(item)

    def report_session(
        self,
        session_type: str,
        description: str,
        tool_call_count: int = 0,
        duration_ms: Optional[int] = None,
    ):
        """Report session metadata after a session ends."""
        item = {
            "_type": "session",
            "workspaceId": self.workspace_id,
            "agentId": self.agent_id,
            "sessionType": session_type,
            "description": description,
            "toolCallCount": tool_call_count,
        }
        if duration_ms is not None:
            item["duration"] = duration_ms
        self._enqueue(item)

    def push_learning(self, category: str, content: str, source: str = "agent"):
        """Push a learning/insight to the backend."""
        self._enqueue({
            "_type": "learning",
            "workspaceId": self.workspace_id,
            "category": category,
            "content": content,
            "source": source,
        })

    def detect_state_transition(self, tool_name: str, args: dict, result: str):
        """Detect if a tool call implies an agent state change worth noting.

        Called after every tool dispatch. Checks for critical findings
        and reports them as hot activities.
        """
        # Check for critical action items in brief results
        if tool_name in ("brief_get_action_items", "brief_get_latest"):
            try:
                parsed = json.loads(result)
                actions = parsed.get("action_items", parsed.get("actions", []))
                if isinstance(actions, list):
                    critical_actions = [
                        a for a in actions
                        if (a.get("priority", "") or "").lower() == "critical"
                    ]
                    if critical_actions:
                        self._enqueue({
                            "_type": "activity",
                            "workspaceId": self.workspace_id,
                            "agentId": self.agent_id,
                            "action": "critical_action",
                            "description": f"Critical action item: {critical_actions[0].get('title', 'unknown')}",
                            "detail": f"{len(critical_actions)} critical action(s)",
                            "isHot": True,
                            "timestamp": int(time.time() * 1000),
                        })
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
