"""
Migration utility: export local SQLite data to MongoDB + files to MinIO.

Usage:
    python -m storage.migrate [--mongodb-uri URI] [--minio-endpoint HOST:PORT]

Reads from the local SQLite databases (~/.hermes/state.db, workspace.db)
and uploads everything to the configured remote backends.
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def migrate_sessions(local_db, remote_db):
    """Migrate all sessions and messages from SQLite to MongoDB."""
    print("Exporting sessions from SQLite...")
    sessions = local_db.export_all()
    print(f"  Found {len(sessions)} sessions")

    migrated = 0
    for session_data in sessions:
        session_id = session_data.get("id")
        if not session_id:
            continue

        # Check if already migrated
        if remote_db.get_session(session_id):
            continue

        # Create session in remote
        remote_db.create_session(
            session_id=session_id,
            source=session_data.get("source", "cli"),
            model=session_data.get("model"),
            model_config=json.loads(session_data["model_config"])
            if isinstance(session_data.get("model_config"), str)
            else session_data.get("model_config"),
            system_prompt=session_data.get("system_prompt"),
            user_id=session_data.get("user_id"),
            parent_session_id=session_data.get("parent_session_id"),
        )

        # Update token counts
        remote_db.update_token_counts(
            session_id,
            input_tokens=session_data.get("input_tokens", 0),
            output_tokens=session_data.get("output_tokens", 0),
        )

        # Set title if exists
        title = session_data.get("title")
        if title:
            try:
                remote_db.set_session_title(session_id, title)
            except ValueError:
                pass  # Title conflict

        # End session if it was ended
        if session_data.get("ended_at"):
            remote_db.end_session(session_id, session_data.get("end_reason", "migrated"))

        # Migrate messages
        messages = session_data.get("messages", [])
        for msg in messages:
            tool_calls = msg.get("tool_calls")
            if isinstance(tool_calls, str):
                try:
                    tool_calls = json.loads(tool_calls)
                except (json.JSONDecodeError, TypeError):
                    tool_calls = None

            remote_db.append_message(
                session_id=session_id,
                role=msg.get("role", "user"),
                content=msg.get("content"),
                tool_name=msg.get("tool_name"),
                tool_calls=tool_calls,
                tool_call_id=msg.get("tool_call_id"),
                token_count=msg.get("token_count"),
                finish_reason=msg.get("finish_reason"),
            )

        migrated += 1
        if migrated % 50 == 0:
            print(f"  Migrated {migrated}/{len(sessions)} sessions...")

    print(f"  Migrated {migrated} new sessions ({len(sessions) - migrated} already existed)")
    return migrated


def migrate_workspace(local_ws, remote_ws):
    """Migrate workspace context from SQLite to MongoDB."""
    print("Migrating workspace context...")

    # Blueprint
    bp = local_ws.get_blueprint()
    if bp:
        remote_ws.update_blueprint(bp["data"], bp["summary"])
        print("  Migrated blueprint")

    # Threads
    threads = local_ws.get_threads(limit=100)
    for t in threads:
        remote_ws.update_thread(
            t["thread_id"], t["platform"], t["summary"], t.get("user_id")
        )
    print(f"  Migrated {len(threads)} threads")

    # Learnings
    learnings = local_ws.get_learnings(limit=100)
    # Insert in reverse order so oldest first (add_learning auto-evicts)
    for l in reversed(learnings):
        remote_ws.add_learning(l["category"], l["content"], l.get("source_thread"))
    print(f"  Migrated {len(learnings)} learnings")

    # Pending work
    pending = local_ws.get_pending_work(active_only=False)
    for w in pending:
        remote_ws.add_pending_work(
            w["id"], w["type"], w["description"], w.get("linked_thread")
        )
        if w.get("status") != "pending":
            remote_ws.update_pending_work_status(w["id"], w["status"])
    print(f"  Migrated {len(pending)} work items")

    # Onboarding status
    status = local_ws.get_onboarding_status()
    if status != "not_started":
        remote_ws.set_onboarding_status(status)
        print(f"  Migrated onboarding status: {status}")


def migrate_blobs(blob_backend, hermes_home: Path, workspace_id: str):
    """Upload local files to MinIO/S3.

    Key pattern: {workspaceId}/agent/{purpose}/{sessionId}/{filename}
    For migration, session_id is extracted from filenames where possible.
    """
    if not blob_backend:
        print("No blob backend configured — skipping file migration")
        return

    uploaded = 0

    # Screenshots → {wsId}/agent/screenshots/migrated/{file}
    screenshots_dir = hermes_home / "browser_screenshots"
    if screenshots_dir.exists():
        for f in screenshots_dir.glob("*.png"):
            key = f"{workspace_id}/agent/screenshots/migrated/{f.name}"
            blob_backend.upload_file("agent", key, str(f))
            uploaded += 1
        print(f"  Uploaded {uploaded} screenshots")

    # Cron outputs → {wsId}/agent/cron-output/{jobId}/{file}
    cron_dir = hermes_home / "cron" / "output"
    if cron_dir.exists():
        cron_count = 0
        for f in cron_dir.rglob("*"):
            if f.is_file():
                rel = f.relative_to(cron_dir)
                key = f"{workspace_id}/agent/cron-output/{rel}"
                blob_backend.upload_file("agent", key, str(f))
                cron_count += 1
        print(f"  Uploaded {cron_count} cron outputs")
        uploaded += cron_count

    # Memory files → {wsId}/agent/memories/migrated/{file}
    memories_dir = hermes_home / "memories"
    if memories_dir.exists():
        mem_count = 0
        for f in memories_dir.glob("*.md"):
            key = f"{workspace_id}/agent/memories/migrated/{f.name}"
            blob_backend.upload_file("agent", key, str(f))
            mem_count += 1
        print(f"  Uploaded {mem_count} memory files")
        uploaded += mem_count

    # Session JSONL transcripts → {wsId}/agent/sessions/{sessionId}.jsonl
    # Extract session_id from filename (e.g., "20260327_203200_37f495.jsonl")
    sessions_dir = hermes_home / "sessions"
    if sessions_dir.exists():
        jsonl_count = 0
        for f in sessions_dir.glob("*.jsonl"):
            session_id = f.stem  # filename without extension IS the session_id
            key = f"{workspace_id}/agent/sessions/{session_id}.jsonl"
            blob_backend.upload_file("agent", key, str(f))
            jsonl_count += 1
        print(f"  Uploaded {jsonl_count} JSONL transcripts")
        uploaded += jsonl_count

    print(f"  Total: {uploaded} files uploaded")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate kai-agent local data to MongoDB + MinIO"
    )
    parser.add_argument(
        "--mongodb-uri",
        default=os.getenv("MONGODB_URI", "mongodb://localhost:27017"),
        help="MongoDB connection URI",
    )
    parser.add_argument(
        "--database",
        default="kai_agent",
        help="MongoDB database name",
    )
    parser.add_argument(
        "--aws-region",
        default=os.getenv("AWS_REGION", "us-east-1"),
        help="AWS region",
    )
    parser.add_argument(
        "--aws-bucket",
        default=os.getenv("AWS_S3_BUCKET", ""),
        help="AWS S3 bucket name",
    )
    parser.add_argument(
        "--aws-access-key-id",
        default=os.getenv("AWS_ACCESS_KEY_ID", ""),
    )
    parser.add_argument(
        "--aws-secret-access-key",
        default=os.getenv("AWS_SECRET_ACCESS_KEY", ""),
    )
    parser.add_argument(
        "--aws-session-token",
        default=os.getenv("AWS_SESSION_TOKEN", ""),
    )
    parser.add_argument(
        "--aws-endpoint-url",
        default=os.getenv("AWS_S3_ENDPOINT_URL", ""),
        help="S3 endpoint URL (for LocalStack)",
    )
    parser.add_argument(
        "--workspace-id",
        default=os.getenv("KAI_WORKSPACE_ID", os.getenv("HERMES_WORKSPACE_ID", "default")),
    )
    parser.add_argument(
        "--skip-sessions",
        action="store_true",
        help="Skip session migration",
    )
    parser.add_argument(
        "--skip-workspace",
        action="store_true",
        help="Skip workspace context migration",
    )
    parser.add_argument(
        "--skip-blobs",
        action="store_true",
        help="Skip blob file migration",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    hermes_home = Path(
        os.getenv("KAI_HOME", os.getenv("HERMES_HOME", Path.home() / ".kai-agent"))
    )

    print(f"=== Kai Agent Migration ===")
    print(f"  Local home:    {hermes_home}")
    print(f"  MongoDB:       {args.mongodb_uri}")
    print(f"  S3 Bucket:     {args.aws_bucket or '(not configured)'}")
    print(f"  Workspace ID:  {args.workspace_id}")
    print()

    start = time.time()

    # Session migration
    if not args.skip_sessions:
        try:
            from kai_state import SessionDB
            from storage.mongodb import MongoSessionBackend

            local_db = SessionDB()
            remote_db = MongoSessionBackend(uri=args.mongodb_uri, database=args.database)
            migrate_sessions(local_db, remote_db)
            local_db.close()
        except Exception as e:
            print(f"  Session migration failed: {e}")

    # Workspace migration
    if not args.skip_workspace:
        try:
            from workspace_context import WorkspaceContext
            from storage.mongo_workspace import MongoWorkspaceBackend

            local_ws = WorkspaceContext(args.workspace_id)
            remote_ws = MongoWorkspaceBackend(
                workspace_id=args.workspace_id,
                uri=args.mongodb_uri,
                database=args.database,
            )
            migrate_workspace(local_ws, remote_ws)
            local_ws.close()
        except Exception as e:
            print(f"  Workspace migration failed: {e}")

    # Blob migration
    if not args.skip_blobs and args.aws_access_key_id:
        try:
            from storage.s3_backend import S3BlobBackend

            blob = S3BlobBackend(
                region=args.aws_region,
                bucket=args.aws_bucket,
                access_key_id=args.aws_access_key_id,
                secret_access_key=args.aws_secret_access_key,
                session_token=args.aws_session_token,
                endpoint_url=args.aws_endpoint_url,
            )
            migrate_blobs(blob, hermes_home, args.workspace_id)
        except Exception as e:
            print(f"  Blob migration failed: {e}")

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
