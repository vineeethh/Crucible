"""S3-compatible object storage (MinIO locally, S3/GCS interop in cloud).

boto3 is synchronous; presigning is pure local crypto (no I/O), and the byte
operations here are used by the worker, which is already off the request path.
Calls that do touch the network are dispatched to a thread by the caller.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


@dataclass(frozen=True, slots=True)
class ObjectInfo:
    key: str
    size_bytes: int
    content_type: str
    etag: str


def dataset_object_key(
    organization_id: uuid.UUID, dataset_id: uuid.UUID, version_id: uuid.UUID, filename: str
) -> str:
    """Tenant-prefixed key. Storage IAM policies are written against the
    `org/{organization_id}/` prefix, so the key layout is a security control,
    not a convenience (threat model T5).

    The client's filename never reaches the key: only a whitelisted suffix is
    derived from it, so a hostile name cannot traverse or collide.
    """
    suffix = filename[filename.rfind(".") :].lower() if "." in filename else ""
    safe_suffix = suffix if suffix in (".csv", ".parquet") else ".bin"
    return f"org/{organization_id}/datasets/{dataset_id}/versions/{version_id}{safe_suffix}"


class S3ObjectStorage:
    """S3 client pair: one for server-side calls, one for presigning.

    `public_endpoint_url` exists because a presigned URL is signed *for a
    specific host*, and the host the server uses is not always the host the
    client can reach. In compose, the API talks to `http://minio:9000` while
    the browser must use `http://localhost:9000`; signing with the internal
    name would produce URLs that no client can resolve. In cloud deployments
    both endpoints are the same and this collapses to one client.
    """

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        public_endpoint_url: str | None = None,
        region: str = "us-east-1",
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        self._bucket = bucket

        def _client(endpoint: str | None) -> Any:
            return boto3.client(
                "s3",
                endpoint_url=endpoint,
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )

        self._client = _client(endpoint_url)
        self._presign_client: Any = (
            _client(public_endpoint_url)
            if public_endpoint_url and public_endpoint_url != endpoint_url
            else self._client
        )

    @property
    def bucket(self) -> str:
        return self._bucket

    def ensure_bucket(self) -> None:
        """Create the bucket if missing (local/dev convenience; cloud buckets
        are created by IaC in Phase 9)."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)

    def presign_put(self, key: str, *, content_type: str, expires_seconds: int = 900) -> str:
        """Short-lived upload URL bound to key and content type."""
        return str(
            self._presign_client.generate_presigned_url(
                "put_object",
                Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=expires_seconds,
            )
        )

    def presign_get(self, key: str, *, expires_seconds: int = 300) -> str:
        """Short-lived download URL. Every issuance is an audited event."""
        return str(
            self._presign_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": key,
                    "ResponseContentDisposition": "attachment",
                },
                ExpiresIn=expires_seconds,
            )
        )

    def head(self, key: str) -> ObjectInfo | None:
        try:
            resp = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError:
            return None
        return ObjectInfo(
            key=key,
            size_bytes=int(resp["ContentLength"]),
            content_type=str(resp.get("ContentType", "application/octet-stream")),
            etag=str(resp.get("ETag", "")).strip('"'),
        )

    def get_bytes(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self._bucket, Key=key)
        body: bytes = resp["Body"].read()
        return body

    def put_bytes(self, key: str, data: bytes, *, content_type: str) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    @staticmethod
    def sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()
