"""
Evaluator storage — create, list, and manage evaluators.

Writes to the SAME MongoDB collections and S3 paths as kai-backend,
so evaluators created by the agent are visible in the frontend.

MongoDB collections (existing kai-backend collections):
    evaluators                       — evaluator metadata
    evolution_evaluator_generations  — generation job tracking

S3 key pattern (matches backend upload.ts):
    {workspaceId}/{repoId}/evaluator_uploads/{timestamp}.py
    {workspaceId}/agent/evaluators/{evaluatorId}.py  (agent-created)
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

from bson import ObjectId

from storage.mongodb import _get_client

logger = logging.getLogger(__name__)


class EvaluatorStore:
    """
    Create and manage evaluators in the same MongoDB + S3 as kai-backend.

    Writes to the `evaluators` and `evolution_evaluator_generations`
    collections in the shared database.
    """

    def __init__(
        self,
        uri: str = "mongodb://localhost:27017",
        database: str = "kai_test",
        workspace_id: str = None,
        blob_backend=None,
    ):
        client = _get_client(uri)
        self._db = client[database]
        from kai_env import get_env
        self._workspace_id = workspace_id or get_env("KAI_WORKSPACE_ID", "default")
        self._evaluators = self._db["evaluators"]
        self._generations = self._db["evolution_evaluator_generations"]
        self._blob = blob_backend
        self._ensure_indexes()

    def _ensure_indexes(self):
        try:
            self._evaluators.create_index(
                [("workspaceId", 1), ("repoId", 1), ("createdAt", -1)]
            )
            self._generations.create_index([("repoId", 1), ("createdAt", -1)])
        except Exception:
            pass

    # ── Create evaluator ────────────────────────────────────────────

    def create_evaluator(
        self,
        name: str,
        repo_id: str,
        code: str,
        repo_source_id: str = None,
        user_id: str = None,
        scopes: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create an evaluator: upload code to S3 and register in MongoDB.

        This creates a 'uploaded' kind evaluator (same as user upload in frontend).
        The code is stored in S3 and referenced by s3Key.

        Args:
            name: Human-readable evaluator name
            repo_id: Repository ID this evaluator is for
            code: Python evaluator script content
            repo_source_id: Repo source ID (optional)
            user_id: Creator user ID (optional, defaults to 'agent')
            scopes: Code scopes [{path, fromLine, toLine}] (optional)

        Returns:
            Evaluator document dict with _id, s3Key, etc.
        """
        evaluator_id = ObjectId()
        now = time.time()
        timestamp = int(now * 1000)

        # S3 key follows backend pattern: {workspaceId}/{repoId}/evaluator_uploads/{ts}.py
        s3_key = f"{self._workspace_id}/{repo_id}/evaluator_uploads/{timestamp}.py"

        # Upload to S3
        if self._blob:
            self._blob.upload_blob(
                "evaluators",
                s3_key,
                code.encode("utf-8"),
                "text/x-python",
            )
            logger.info(f"Uploaded evaluator to S3: {s3_key}")

        # Create evaluator document (matches backend's EvaluatorModel schema)
        doc = {
            "_id": evaluator_id,
            "userId": ObjectId(user_id) if user_id and user_id != "agent" else "agent",
            "workspaceId": self._workspace_id,
            "repoId": repo_id,
            "repoSourceId": repo_source_id or repo_id,
            "name": name,
            "detail": {
                "kind": "uploaded",
                "s3Key": s3_key,
                "uploadedAt": time.time(),
            },
            "createdAt": time.time(),
            "updatedAt": time.time(),
        }
        self._evaluators.insert_one(doc)

        result = dict(doc)
        result["_id"] = str(result["_id"])
        logger.info(f"Created evaluator '{name}' ({result['_id']}) for repo {repo_id}")
        return result

    def create_evaluator_generation(
        self,
        repo_id: str,
        scopes: List[Dict[str, Any]],
        repo_source_id: str = None,
        user_id: str = None,
    ) -> Dict[str, Any]:
        """
        Track an evaluator generation job.

        Creates a 'pending' generation record. The agent can then update it
        as the generation progresses (in_progress → completed/failed).

        Args:
            repo_id: Repository ID
            scopes: Code scopes [{path, fromLine, toLine}]
            repo_source_id: Repo source ID
            user_id: Creator user ID

        Returns:
            Generation document dict with _id, status, etc.
        """
        gen_id = ObjectId()
        doc = {
            "_id": gen_id,
            "userId": ObjectId(user_id) if user_id and user_id != "agent" else "agent",
            "workspaceId": self._workspace_id,
            "repoId": repo_id,
            "repoSourceId": repo_source_id or repo_id,
            "status": "pending",
            "scopes": scopes,
            "startedAt": None,
            "completedAt": None,
            "error": None,
            "evaluatorS3": None,
            "validationResult": None,
            "costTracking": None,
            "attempts": [],
            "createdAt": time.time(),
            "updatedAt": time.time(),
        }
        self._generations.insert_one(doc)

        result = dict(doc)
        result["_id"] = str(result["_id"])
        return result

    def update_generation(
        self, generation_id: str, **kwargs
    ) -> bool:
        """
        Update a generation record (status, evaluatorS3, validationResult, etc.).

        Common updates:
            status="in_progress", startedAt=time.time()
            status="completed", completedAt=time.time(), evaluatorS3="..."
            status="failed", error="..."
        """
        kwargs["updatedAt"] = time.time()
        result = self._generations.update_one(
            {"_id": ObjectId(generation_id)},
            {"$set": kwargs},
        )
        return result.modified_count > 0

    def add_generation_attempt(
        self,
        generation_id: str,
        attempt_number: int,
        attempt_type: str,
        prompt_system: str,
        prompt_user: str,
        llm_response: str,
        llm_model: str,
        tokens_used: int,
        code: str,
        validation_error: str = None,
        validation_score: Dict[str, Any] = None,
    ) -> str:
        """
        Record a generation attempt and upload the code to S3.

        Returns the S3 key where the attempt code was stored.
        """
        code_s3 = f"{self._workspace_id}/agent/evaluator_attempts/{generation_id}/{attempt_number}.py"

        if self._blob:
            self._blob.upload_blob(
                "evaluators", code_s3, code.encode("utf-8"), "text/x-python"
            )

        attempt = {
            "attemptNumber": attempt_number,
            "type": attempt_type,
            "promptSystem": prompt_system,
            "promptUser": prompt_user,
            "llmResponse": llm_response,
            "llmModel": llm_model,
            "tokensUsed": tokens_used,
            "codeS3": code_s3,
            "validationError": validation_error,
            "validationScore": validation_score,
            "createdAt": time.time(),
        }

        self._generations.update_one(
            {"_id": ObjectId(generation_id)},
            {"$push": {"attempts": attempt}, "$set": {"updatedAt": time.time()}},
        )
        return code_s3

    def complete_generation(
        self,
        generation_id: str,
        evaluator_name: str,
        repo_id: str,
        final_code: str,
        validation_passed: bool = True,
        cost_tracking: Dict[str, Any] = None,
        repo_source_id: str = None,
        user_id: str = None,
    ) -> Dict[str, Any]:
        """
        Complete a generation: upload final evaluator, create evaluator doc, link them.

        Returns the created evaluator document.
        """
        # Upload final evaluator to S3
        s3_key = f"{self._workspace_id}/{repo_id}/evaluator_uploads/{int(time.time() * 1000)}.py"
        if self._blob:
            self._blob.upload_blob(
                "evaluators", s3_key, final_code.encode("utf-8"), "text/x-python"
            )

        # Create evaluator document
        evaluator_id = ObjectId()
        eval_doc = {
            "_id": evaluator_id,
            "userId": ObjectId(user_id) if user_id and user_id != "agent" else "agent",
            "workspaceId": self._workspace_id,
            "repoId": repo_id,
            "repoSourceId": repo_source_id or repo_id,
            "name": evaluator_name,
            "detail": {
                "kind": "generated",
                "generationId": ObjectId(generation_id),
                "s3Key": s3_key,
            },
            "createdAt": time.time(),
            "updatedAt": time.time(),
        }
        self._evaluators.insert_one(eval_doc)

        # Update generation as completed
        update = {
            "status": "completed",
            "completedAt": time.time(),
            "evaluatorS3": s3_key,
            "updatedAt": time.time(),
        }
        if validation_passed is not None:
            update["validationResult"] = {
                "passed": validation_passed,
                "initialProgramScore": {},
                "brokenProgramDetected": False,
                "attempts": 0,
                "failures": [],
            }
        if cost_tracking:
            update["costTracking"] = cost_tracking
        self._generations.update_one(
            {"_id": ObjectId(generation_id)}, {"$set": update}
        )

        result = dict(eval_doc)
        result["_id"] = str(result["_id"])
        return result

    # ── Read evaluators ─────────────────────────────────────────────

    def list_evaluators(
        self,
        repo_id: str = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List evaluators for workspace, optionally filtered by repo."""
        query: Dict[str, Any] = {"workspaceId": self._workspace_id}
        if repo_id:
            query["repoId"] = repo_id
        cursor = self._evaluators.find(query).sort(
            "createdAt", -1
        ).skip(offset).limit(limit)

        results = []
        for doc in cursor:
            d = dict(doc)
            d["_id"] = str(d["_id"])
            results.append(d)
        return results

    def get_evaluator(self, evaluator_id: str) -> Optional[Dict[str, Any]]:
        """Get a single evaluator by ID."""
        doc = self._evaluators.find_one({"_id": ObjectId(evaluator_id)})
        if not doc:
            return None
        result = dict(doc)
        result["_id"] = str(result["_id"])
        return result

    def get_evaluator_code(self, evaluator_id: str) -> Optional[str]:
        """Download evaluator code from S3."""
        doc = self.get_evaluator(evaluator_id)
        if not doc or not self._blob:
            return None
        s3_key = doc.get("detail", {}).get("s3Key")
        if not s3_key:
            return None
        try:
            data = self._blob.download_blob("evaluators", s3_key)
            return data.decode("utf-8")
        except Exception as e:
            logger.warning(f"Failed to download evaluator code: {e}")
            return None

    def list_generations(
        self,
        repo_id: str = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List evaluator generations."""
        query: Dict[str, Any] = {"workspaceId": self._workspace_id}
        if repo_id:
            query["repoId"] = repo_id
        cursor = self._generations.find(query).sort(
            "createdAt", -1
        ).skip(offset).limit(limit)

        results = []
        for doc in cursor:
            d = dict(doc)
            d["_id"] = str(d["_id"])
            results.append(d)
        return results

    def get_generation(self, generation_id: str) -> Optional[Dict[str, Any]]:
        """Get a single generation by ID."""
        doc = self._generations.find_one({"_id": ObjectId(generation_id)})
        if not doc:
            return None
        result = dict(doc)
        result["_id"] = str(result["_id"])
        return result

    # ── Delete ──────────────────────────────────────────────────────

    def delete_evaluator(self, evaluator_id: str) -> bool:
        """Delete evaluator doc and its S3 file."""
        doc = self.get_evaluator(evaluator_id)
        if not doc:
            return False

        # Delete S3 file
        s3_key = doc.get("detail", {}).get("s3Key")
        if s3_key and self._blob:
            try:
                self._blob.delete_blob("evaluators", s3_key)
            except Exception:
                pass

        result = self._evaluators.delete_one({"_id": ObjectId(evaluator_id)})
        return result.deleted_count > 0
