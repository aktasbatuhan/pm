"""
Storage backend factory.

Reads the ``storage`` section from config and returns the appropriate
backend instances.  When ``backend`` is ``"local"`` (the default), the
existing SQLite classes are returned unchanged — zero new dependencies.

For ``"remote"`` or ``"dual"`` modes, the MongoDB / boto3 packages must
be installed (``pip install kai-agent[remote-storage]``).

Follows kai-backend conventions:
    - Same MongoDB database (kai_test dev / kai prod)
    - Same S3 bucket (AWS)
    - All data scoped by workspaceId
    - S3 keys: {workspaceId}/agent/{purpose}/...
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from storage.protocols import (
    BlobStorageBackend,
    SessionStorageBackend,
    WorkspaceStorageBackend,
)

logger = logging.getLogger(__name__)


def _get_storage_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the storage section from config, with env-var overrides."""
    storage = config.get("storage", {})

    # Env-var overrides (highest priority)
    backend_env = os.getenv("KAI_STORAGE_BACKEND")
    if backend_env:
        storage["backend"] = backend_env

    # MongoDB config
    mongo_cfg = storage.get("mongodb", {})
    mongo_uri_env = os.getenv("MONGODB_URI")
    if mongo_uri_env:
        mongo_cfg["uri"] = mongo_uri_env
    mongo_db_env = os.getenv("MONGODB_DATABASE")
    if mongo_db_env:
        mongo_cfg["database"] = mongo_db_env
    storage["mongodb"] = mongo_cfg

    # AWS S3 config
    s3_cfg = storage.get("s3", {})
    for env_key, cfg_key in [
        ("AWS_ACCESS_KEY_ID", "access_key_id"),
        ("AWS_SECRET_ACCESS_KEY", "secret_access_key"),
        ("AWS_SESSION_TOKEN", "session_token"),
        ("AWS_S3_BUCKET", "bucket"),
        ("AWS_REGION", "region"),
        ("AWS_S3_ENDPOINT_URL", "endpoint_url"),
    ]:
        val = os.getenv(env_key)
        if val:
            s3_cfg[cfg_key] = val
    storage["s3"] = s3_cfg

    return storage


def _get_workspace_id() -> str:
    """Get workspace ID from env."""
    from kai_env import get_env
    return get_env("KAI_WORKSPACE_ID", "default")


def _require_package(name: str, pip_extra: str = "remote-storage"):
    """Raise a clear error if an optional package is missing."""
    try:
        __import__(name)
    except ImportError:
        raise ImportError(
            f"Package '{name}' is required for remote storage but is not installed. "
            f"Install it with: pip install kai-agent[{pip_extra}]"
        )


# ── Session backend ─────────────────────────────────────────────────


def create_session_backend(config: Dict[str, Any]) -> SessionStorageBackend:
    """
    Create a session storage backend based on config.

    Returns:
        - ``"local"``  → kai_state.SessionDB  (SQLite, default)
        - ``"remote"`` → storage.mongodb.MongoSessionBackend
        - ``"dual"``   → storage.sync.DualWriteSessionBackend
    """
    storage = _get_storage_config(config)
    backend = storage.get("backend", "local")

    if backend == "local":
        from kai_state import SessionDB
        return SessionDB()

    mongo_cfg = storage.get("mongodb", {})
    mongo_uri = mongo_cfg.get("uri", "mongodb://localhost:27017")
    mongo_db = mongo_cfg.get("database", "kai_test")
    workspace_id = _get_workspace_id()

    if backend == "remote":
        _require_package("pymongo")
        from storage.mongodb import MongoSessionBackend
        return MongoSessionBackend(
            uri=mongo_uri, database=mongo_db, workspace_id=workspace_id,
        )

    if backend == "dual":
        _require_package("pymongo")
        from kai_state import SessionDB
        from storage.mongodb import MongoSessionBackend
        from storage.sync import DualWriteSessionBackend

        local = SessionDB()
        remote = MongoSessionBackend(
            uri=mongo_uri, database=mongo_db, workspace_id=workspace_id,
        )
        sync_cfg = storage.get("sync", {})
        return DualWriteSessionBackend(local, remote, sync_cfg)

    raise ValueError(f"Unknown storage backend: {backend!r}. Use 'local', 'remote', or 'dual'.")


# ── Blob backend ────────────────────────────────────────────────────


def create_blob_backend(config: Dict[str, Any]) -> Optional[BlobStorageBackend]:
    """
    Create a blob storage backend (S3/MinIO) if configured.

    Returns None when backend is ``"local"`` or S3 is not configured.
    Uses the same bucket as kai-backend when AWS_S3_BUCKET is set.
    """
    storage = _get_storage_config(config)
    backend = storage.get("backend", "local")

    if backend == "local":
        return None

    s3_cfg = storage.get("s3", {})
    access_key_id = s3_cfg.get("access_key_id", "")
    bucket = s3_cfg.get("bucket", "")

    if not access_key_id and not bucket:
        logger.warning("AWS S3 not configured — blob storage disabled")
        return None

    _require_package("boto3")
    from storage.s3_backend import S3BlobBackend

    return S3BlobBackend(
        region=s3_cfg.get("region", "us-east-1"),
        bucket=bucket,
        access_key_id=access_key_id,
        secret_access_key=s3_cfg.get("secret_access_key", ""),
        session_token=s3_cfg.get("session_token", ""),
        endpoint_url=s3_cfg.get("endpoint_url", ""),
    )


# ── Workspace backend ───────────────────────────────────────────────


def create_workspace_backend(
    config: Dict[str, Any], workspace_id: str = None
) -> WorkspaceStorageBackend:
    """
    Create a workspace context backend based on config.

    Returns:
        - ``"local"``  → workspace_context.WorkspaceContext  (SQLite, default)
        - ``"remote"`` → storage.mongo_workspace.MongoWorkspaceBackend
        - ``"dual"``   → storage.sync.DualWriteWorkspaceBackend
    """
    ws_id = workspace_id or _get_workspace_id()
    storage = _get_storage_config(config)
    backend = storage.get("backend", "local")

    if backend == "local":
        from workspace_context import WorkspaceContext
        return WorkspaceContext(ws_id)

    mongo_cfg = storage.get("mongodb", {})
    mongo_uri = mongo_cfg.get("uri", "mongodb://localhost:27017")
    mongo_db = mongo_cfg.get("database", "kai_test")

    if backend == "remote":
        _require_package("pymongo")
        from storage.mongo_workspace import MongoWorkspaceBackend
        return MongoWorkspaceBackend(
            workspace_id=ws_id, uri=mongo_uri, database=mongo_db,
        )

    if backend == "dual":
        _require_package("pymongo")
        from workspace_context import WorkspaceContext
        from storage.mongo_workspace import MongoWorkspaceBackend
        from storage.sync import DualWriteWorkspaceBackend

        local = WorkspaceContext(ws_id)
        remote = MongoWorkspaceBackend(
            workspace_id=ws_id, uri=mongo_uri, database=mongo_db,
        )
        sync_cfg = storage.get("sync", {})
        return DualWriteWorkspaceBackend(local, remote, sync_cfg)

    raise ValueError(f"Unknown storage backend: {backend!r}. Use 'local', 'remote', or 'dual'.")


# ── Evaluator store ─────────────────────────────────────────────────


def create_evaluator_store(config: Dict[str, Any]):
    """
    Create an evaluator store for creating/managing evaluators.

    Writes to the SAME MongoDB collections as kai-backend (evaluators,
    evolution_evaluator_generations) and uploads code to S3.

    Returns None if backend is "local" (evaluators need remote storage).
    """
    storage = _get_storage_config(config)
    backend = storage.get("backend", "local")

    if backend == "local":
        return None

    _require_package("pymongo")
    from storage.evaluators import EvaluatorStore

    mongo_cfg = storage.get("mongodb", {})
    blob = create_blob_backend(config)

    return EvaluatorStore(
        uri=mongo_cfg.get("uri", "mongodb://localhost:27017"),
        database=mongo_cfg.get("database", "kai_test"),
        workspace_id=_get_workspace_id(),
        blob_backend=blob,
    )
