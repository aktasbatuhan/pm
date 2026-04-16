"""
AWS S3 blob storage backend.

Implements BlobStorageBackend protocol for storing binary artifacts
(session logs, screenshots, trajectories, memories) in AWS S3.

Follows kai-backend conventions:
    - Uses the SAME bucket as kai-backend (e.g. kai-staging-59715f74-6aa8-4136)
    - All keys prefixed: {workspaceId}/agent/{purpose}/...
    - Supports AWS session tokens (required for E2B sandbox credentials)

Requires: boto3 >= 1.35.0
"""

import logging
import mimetypes
import os
from typing import List

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class S3BlobBackend:
    """
    AWS S3 blob storage backend.

    Uses a single shared bucket (kai-backend pattern).
    Supports temporary credentials with session tokens (from E2B sandbox).
    Optional endpoint_url for LocalStack in local development.
    """

    def __init__(
        self,
        region: str = "us-east-1",
        bucket: str = "",
        access_key_id: str = "",
        secret_access_key: str = "",
        session_token: str = "",
        endpoint_url: str = "",
    ):
        client_kwargs = {"region_name": region}
        if access_key_id:
            client_kwargs["aws_access_key_id"] = access_key_id
        if secret_access_key:
            client_kwargs["aws_secret_access_key"] = secret_access_key
        if session_token:
            client_kwargs["aws_session_token"] = session_token
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url

        self._client = boto3.client("s3", **client_kwargs)
        self._bucket = bucket

    def _resolve_bucket(self, bucket: str) -> str:
        """Resolve bucket name. If a shared bucket is configured, use it."""
        if self._bucket:
            return self._bucket
        # Fallback: per-purpose bucket
        name = f"kai-agent-{bucket}".lower().replace("_", "-")[:63]
        return name

    def upload_blob(
        self, bucket: str, key: str, data: bytes, content_type: str = ""
    ) -> str:
        full_bucket = self._resolve_bucket(bucket)
        if not content_type:
            content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
        self._client.put_object(
            Bucket=full_bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return key

    def download_blob(self, bucket: str, key: str) -> bytes:
        full_bucket = self._resolve_bucket(bucket)
        response = self._client.get_object(Bucket=full_bucket, Key=key)
        return response["Body"].read()

    def upload_file(self, bucket: str, key: str, file_path: str) -> str:
        full_bucket = self._resolve_bucket(bucket)
        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        self._client.upload_file(
            file_path,
            full_bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        return key

    def download_file(self, bucket: str, key: str, file_path: str) -> None:
        full_bucket = self._resolve_bucket(bucket)
        self._client.download_file(full_bucket, key, file_path)

    def list_blobs(self, bucket: str, prefix: str = "") -> List[str]:
        full_bucket = self._resolve_bucket(bucket)
        try:
            response = self._client.list_objects_v2(
                Bucket=full_bucket, Prefix=prefix
            )
            return [obj["Key"] for obj in response.get("Contents", [])]
        except ClientError:
            return []

    def delete_blob(self, bucket: str, key: str) -> None:
        full_bucket = self._resolve_bucket(bucket)
        self._client.delete_object(Bucket=full_bucket, Key=key)

    def blob_exists(self, bucket: str, key: str) -> bool:
        full_bucket = self._resolve_bucket(bucket)
        try:
            self._client.head_object(Bucket=full_bucket, Key=key)
            return True
        except ClientError:
            return False
