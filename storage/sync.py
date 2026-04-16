"""
Dual-write synchronization layer.

Wraps a local backend (SQLite) and a remote backend (MongoDB) to provide
local-first writes with async replication to remote storage.

Local writes are synchronous (fast, always available).
Remote writes are queued and processed by a background daemon thread.
If remote fails, operations are retried with exponential backoff.
"""

import logging
import queue
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DualWriteSessionBackend:
    """
    Local-first session storage with async remote replication.

    All reads hit the local backend (fast path).
    All writes go to local synchronously, then queued for remote.
    """

    def __init__(self, local, remote, sync_config: Dict[str, Any] = None):
        self._local = local
        self._remote = remote
        self._config = sync_config or {}
        self._retry_max = self._config.get("retry_max", 3)

        self._queue: queue.Queue = queue.Queue()
        self._running = True
        self._worker = threading.Thread(
            target=self._sync_loop, name="storage-sync", daemon=True
        )
        self._worker.start()

    def _enqueue(self, method: str, *args, **kwargs):
        """Queue a remote write operation."""
        self._queue.put((method, args, kwargs))

    def _sync_loop(self):
        """Background worker: process remote write queue."""
        while self._running or not self._queue.empty():
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            method, args, kwargs = item
            self._execute_remote(method, args, kwargs)
            self._queue.task_done()

    def _execute_remote(self, method: str, args: tuple, kwargs: dict):
        """Execute a remote operation with retry."""
        for attempt in range(self._retry_max):
            try:
                getattr(self._remote, method)(*args, **kwargs)
                return
            except Exception as e:
                delay = min(2 ** attempt, 30)
                logger.warning(
                    f"Remote sync {method} failed (attempt {attempt + 1}/{self._retry_max}): {e}"
                )
                if attempt < self._retry_max - 1:
                    time.sleep(delay)
        logger.error(f"Remote sync {method} gave up after {self._retry_max} attempts")

    # ── Proxy: reads go to local ────────────────────────────────────

    # Expose _conn for code that accesses SessionDB._conn directly (e.g. cli.py)
    @property
    def _conn(self):
        return self._local._conn

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._local.get_session(session_id)

    def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        return self._local.get_messages(session_id)

    def get_messages_as_conversation(self, session_id: str) -> List[Dict[str, Any]]:
        return self._local.get_messages_as_conversation(session_id)

    def search_messages(self, query, source_filter=None, role_filter=None, limit=20, offset=0):
        return self._local.search_messages(query, source_filter, role_filter, limit, offset)

    def search_sessions(self, source=None, limit=20, offset=0):
        return self._local.search_sessions(source, limit, offset)

    def list_sessions_rich(self, source=None, limit=20, offset=0):
        return self._local.list_sessions_rich(source, limit, offset)

    def get_session_title(self, session_id: str) -> Optional[str]:
        return self._local.get_session_title(session_id)

    def get_session_by_title(self, title: str) -> Optional[Dict[str, Any]]:
        return self._local.get_session_by_title(title)

    def resolve_session_by_title(self, title: str) -> Optional[str]:
        return self._local.resolve_session_by_title(title)

    def get_next_title_in_lineage(self, base_title: str) -> str:
        return self._local.get_next_title_in_lineage(base_title)

    def session_count(self, source=None) -> int:
        return self._local.session_count(source)

    def message_count(self, session_id=None) -> int:
        return self._local.message_count(session_id)

    def export_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._local.export_session(session_id)

    def export_all(self, source=None):
        return self._local.export_all(source)

    @staticmethod
    def sanitize_title(title):
        from kai_state import SessionDB
        return SessionDB.sanitize_title(title)

    # ── Proxy: writes go to local + queued remote ───────────────────

    def create_session(self, session_id, source, model=None, model_config=None,
                       system_prompt=None, user_id=None, parent_session_id=None):
        result = self._local.create_session(
            session_id, source, model, model_config,
            system_prompt, user_id, parent_session_id,
        )
        self._enqueue(
            "create_session",
            session_id, source, model, model_config,
            system_prompt, user_id, parent_session_id,
        )
        return result

    def end_session(self, session_id, end_reason):
        self._local.end_session(session_id, end_reason)
        self._enqueue("end_session", session_id, end_reason)

    def update_system_prompt(self, session_id, system_prompt):
        self._local.update_system_prompt(session_id, system_prompt)
        self._enqueue("update_system_prompt", session_id, system_prompt)

    def update_token_counts(self, session_id, input_tokens=0, output_tokens=0):
        self._local.update_token_counts(session_id, input_tokens, output_tokens)
        self._enqueue("update_token_counts", session_id, input_tokens, output_tokens)

    def append_message(self, session_id, role, content=None, tool_name=None,
                       tool_calls=None, tool_call_id=None, token_count=None,
                       finish_reason=None):
        result = self._local.append_message(
            session_id, role, content, tool_name,
            tool_calls, tool_call_id, token_count, finish_reason,
        )
        self._enqueue(
            "append_message",
            session_id, role, content, tool_name,
            tool_calls, tool_call_id, token_count, finish_reason,
        )
        return result

    def set_session_title(self, session_id, title):
        result = self._local.set_session_title(session_id, title)
        self._enqueue("set_session_title", session_id, title)
        return result

    def clear_messages(self, session_id):
        self._local.clear_messages(session_id)
        self._enqueue("clear_messages", session_id)

    def delete_session(self, session_id):
        result = self._local.delete_session(session_id)
        self._enqueue("delete_session", session_id)
        return result

    def prune_sessions(self, older_than_days=90, source=None):
        result = self._local.prune_sessions(older_than_days, source)
        self._enqueue("prune_sessions", older_than_days, source)
        return result

    def close(self):
        self._running = False
        # Drain remaining items
        self._worker.join(timeout=10.0)
        self._local.close()
        self._remote.close()


class DualWriteWorkspaceBackend:
    """
    Local-first workspace storage with async remote replication.

    Same pattern as DualWriteSessionBackend but for workspace context.
    """

    def __init__(self, local, remote, sync_config: Dict[str, Any] = None):
        self._local = local
        self._remote = remote
        self._config = sync_config or {}
        self._retry_max = self._config.get("retry_max", 3)

        self._queue: queue.Queue = queue.Queue()
        self._running = True
        self._worker = threading.Thread(
            target=self._sync_loop, name="workspace-sync", daemon=True
        )
        self._worker.start()

    @property
    def workspace_id(self) -> str:
        return self._local.workspace_id

    def _enqueue(self, method: str, *args, **kwargs):
        self._queue.put((method, args, kwargs))

    def _sync_loop(self):
        while self._running or not self._queue.empty():
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            method, args, kwargs = item
            self._execute_remote(method, args, kwargs)
            self._queue.task_done()

    def _execute_remote(self, method: str, args: tuple, kwargs: dict):
        for attempt in range(self._retry_max):
            try:
                getattr(self._remote, method)(*args, **kwargs)
                return
            except Exception as e:
                delay = min(2 ** attempt, 30)
                logger.warning(
                    f"Workspace sync {method} failed (attempt {attempt + 1}/{self._retry_max}): {e}"
                )
                if attempt < self._retry_max - 1:
                    time.sleep(delay)
        logger.error(f"Workspace sync {method} gave up after {self._retry_max} attempts")

    # ── Reads go to local ───────────────────────────────────────────

    def get_blueprint(self):
        return self._local.get_blueprint()

    def get_threads(self, limit=10):
        return self._local.get_threads(limit)

    def get_learnings(self, limit=30):
        return self._local.get_learnings(limit)

    def get_pending_work(self, active_only=True):
        return self._local.get_pending_work(active_only)

    def get_onboarding_status(self):
        return self._local.get_onboarding_status()

    def is_onboarded(self):
        return self._local.is_onboarded()

    def needs_onboarding(self):
        return self._local.needs_onboarding()

    def to_system_prompt(self, current_thread_id=None):
        return self._local.to_system_prompt(current_thread_id)

    # ── Writes go to local + queued remote ──────────────────────────

    def update_blueprint(self, data, summary, updated_by="lifecycle"):
        self._local.update_blueprint(data, summary, updated_by)
        self._enqueue("update_blueprint", data, summary, updated_by)

    def update_thread(self, thread_id, platform, summary, user_id=None):
        self._local.update_thread(thread_id, platform, summary, user_id)
        self._enqueue("update_thread", thread_id, platform, summary, user_id)

    def add_learning(self, category, content, source_thread=None):
        self._local.add_learning(category, content, source_thread)
        self._enqueue("add_learning", category, content, source_thread)

    def add_pending_work(self, work_id, work_type, description, linked_thread=None):
        self._local.add_pending_work(work_id, work_type, description, linked_thread)
        self._enqueue("add_pending_work", work_id, work_type, description, linked_thread)

    def update_pending_work_status(self, work_id, status):
        self._local.update_pending_work_status(work_id, status)
        self._enqueue("update_pending_work_status", work_id, status)

    def set_onboarding_status(self, status, phase=None):
        self._local.set_onboarding_status(status, phase)
        self._enqueue("set_onboarding_status", status, phase)

    def close(self):
        self._running = False
        self._worker.join(timeout=10.0)
        self._local.close()
        self._remote.close()


class BlobSyncWorker:
    """
    Background worker that uploads local files to MinIO.

    Usage:
        worker = BlobSyncWorker(blob_backend)
        worker.queue_upload("screenshots", "ws/sess/img.png", "/local/path/img.png")
    """

    def __init__(self, blob_backend, retry_max: int = 3):
        self._backend = blob_backend
        self._retry_max = retry_max
        self._queue: queue.Queue = queue.Queue()
        self._running = True
        self._worker = threading.Thread(
            target=self._upload_loop, name="blob-sync", daemon=True
        )
        self._worker.start()

    def queue_upload(self, bucket: str, key: str, file_path: str):
        """Queue a file for async upload to MinIO."""
        self._queue.put((bucket, key, file_path))

    def queue_upload_bytes(self, bucket: str, key: str, data: bytes, content_type: str = ""):
        """Queue bytes for async upload to MinIO."""
        self._queue.put((bucket, key, data, content_type))

    def _upload_loop(self):
        while self._running or not self._queue.empty():
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            for attempt in range(self._retry_max):
                try:
                    if len(item) == 3:
                        bucket, key, file_path = item
                        self._backend.upload_file(bucket, key, file_path)
                    else:
                        bucket, key, data, content_type = item
                        self._backend.upload_blob(bucket, key, data, content_type)
                    logger.debug(f"Uploaded blob {item[0]}/{item[1]}")
                    break
                except Exception as e:
                    delay = min(2 ** attempt, 30)
                    logger.warning(
                        f"Blob upload {item[0]}/{item[1]} failed "
                        f"(attempt {attempt + 1}/{self._retry_max}): {e}"
                    )
                    if attempt < self._retry_max - 1:
                        import time
                        time.sleep(delay)
            self._queue.task_done()

    def stop(self):
        self._running = False
        self._worker.join(timeout=10.0)
