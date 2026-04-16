"""
Storage abstraction layer for Kai Agent.

Provides Protocol-based interfaces for session, workspace, and blob storage,
with pluggable backends (SQLite local, MongoDB, MinIO).

Usage:
    from storage import create_session_backend, create_blob_backend, create_workspace_backend

    session_db = create_session_backend(config)
    blob_store = create_blob_backend(config)
    workspace_ctx = create_workspace_backend(config, workspace_id)
"""

from storage.protocols import SessionStorageBackend, BlobStorageBackend, WorkspaceStorageBackend
from storage.factory import create_session_backend, create_blob_backend, create_workspace_backend

__all__ = [
    "SessionStorageBackend",
    "BlobStorageBackend",
    "WorkspaceStorageBackend",
    "create_session_backend",
    "create_blob_backend",
    "create_workspace_backend",
]
