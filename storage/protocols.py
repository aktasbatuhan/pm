"""
Storage protocol definitions for Kai Agent.

These Protocol classes define the interfaces that all storage backends must
satisfy. Existing SQLite classes (SessionDB, WorkspaceContext) already conform
to these protocols via structural subtyping — no inheritance changes needed.

New backends (MongoDB, MinIO) implement the same method signatures.
"""

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class SessionStorageBackend(Protocol):
    """
    Protocol for session and message storage.

    Matches the public interface of kai_state.SessionDB exactly,
    so the existing SQLite implementation satisfies this without changes.
    """

    # -- Session lifecycle --

    def create_session(
        self,
        session_id: str,
        source: str,
        model: str = None,
        model_config: Dict[str, Any] = None,
        system_prompt: str = None,
        user_id: str = None,
        parent_session_id: str = None,
    ) -> str: ...

    def end_session(self, session_id: str, end_reason: str) -> None: ...

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]: ...

    def update_system_prompt(self, session_id: str, system_prompt: str) -> None: ...

    def update_token_counts(
        self, session_id: str, input_tokens: int = 0, output_tokens: int = 0
    ) -> None: ...

    # -- Titles --

    def set_session_title(self, session_id: str, title: str) -> bool: ...

    def get_session_title(self, session_id: str) -> Optional[str]: ...

    def get_session_by_title(self, title: str) -> Optional[Dict[str, Any]]: ...

    def resolve_session_by_title(self, title: str) -> Optional[str]: ...

    def get_next_title_in_lineage(self, base_title: str) -> str: ...

    # -- Messages --

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
    ) -> int: ...

    def get_messages(self, session_id: str) -> List[Dict[str, Any]]: ...

    def get_messages_as_conversation(self, session_id: str) -> List[Dict[str, Any]]: ...

    def clear_messages(self, session_id: str) -> None: ...

    # -- Search & listing --

    def search_messages(
        self,
        query: str,
        source_filter: List[str] = None,
        role_filter: List[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]: ...

    def search_sessions(
        self,
        source: str = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]: ...

    def list_sessions_rich(
        self,
        source: str = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]: ...

    # -- Utility --

    def session_count(self, source: str = None) -> int: ...

    def message_count(self, session_id: str = None) -> int: ...

    # -- Export & cleanup --

    def export_session(self, session_id: str) -> Optional[Dict[str, Any]]: ...

    def export_all(self, source: str = None) -> List[Dict[str, Any]]: ...

    def delete_session(self, session_id: str) -> bool: ...

    def prune_sessions(self, older_than_days: int = 90, source: str = None) -> int: ...

    def close(self) -> None: ...


@runtime_checkable
class BlobStorageBackend(Protocol):
    """
    Protocol for binary/file object storage (screenshots, trajectories, etc.).

    No existing local implementation — this is a new capability provided by
    MinIO (or S3-compatible) backends.
    """

    def upload_blob(
        self, bucket: str, key: str, data: bytes, content_type: str = ""
    ) -> str:
        """Upload bytes. Returns the object key."""
        ...

    def download_blob(self, bucket: str, key: str) -> bytes:
        """Download and return bytes."""
        ...

    def upload_file(self, bucket: str, key: str, file_path: str) -> str:
        """Upload a local file. Returns the object key."""
        ...

    def download_file(self, bucket: str, key: str, file_path: str) -> None:
        """Download to a local file path."""
        ...

    def list_blobs(self, bucket: str, prefix: str = "") -> List[str]:
        """List object keys under a prefix."""
        ...

    def delete_blob(self, bucket: str, key: str) -> None:
        """Delete an object."""
        ...

    def blob_exists(self, bucket: str, key: str) -> bool:
        """Check if an object exists."""
        ...


@runtime_checkable
class WorkspaceStorageBackend(Protocol):
    """
    Protocol for workspace context storage.

    Matches the public interface of workspace_context.WorkspaceContext,
    so the existing SQLite implementation satisfies this without changes.
    """

    workspace_id: str

    # -- Reads --

    def get_blueprint(self) -> Optional[Dict[str, Any]]: ...

    def get_threads(self, limit: int = 10) -> List[Dict[str, Any]]: ...

    def get_learnings(self, limit: int = 30) -> List[Dict[str, Any]]: ...

    def get_pending_work(self, active_only: bool = True) -> List[Dict[str, Any]]: ...

    # -- Writes --

    def update_blueprint(
        self, data: Dict[str, Any], summary: str, updated_by: str = "lifecycle"
    ) -> None: ...

    def update_thread(
        self, thread_id: str, platform: str, summary: str, user_id: str = None
    ) -> None: ...

    def add_learning(
        self, category: str, content: str, source_thread: str = None
    ) -> None: ...

    def add_pending_work(
        self, work_id: str, work_type: str, description: str, linked_thread: str = None
    ) -> None: ...

    def update_pending_work_status(self, work_id: str, status: str) -> None: ...

    # -- Onboarding --

    def get_onboarding_status(self) -> str: ...

    def set_onboarding_status(self, status: str, phase: str = None) -> None: ...

    def is_onboarded(self) -> bool: ...

    def needs_onboarding(self) -> bool: ...

    # -- Rendering --

    def to_system_prompt(self, current_thread_id: str = None) -> str: ...

    def close(self) -> None: ...
