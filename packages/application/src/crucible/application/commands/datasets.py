"""Dataset ingestion use cases.

Flow (plan §6.1 — the API never streams file bytes):

  1. `StartDatasetUpload`   -> policy check, immutable version row, presigned PUT
  2. client PUTs bytes directly to object storage
  3. `CompleteDatasetUpload` -> size check, content-hash dedupe, enqueue profiling
  4. worker profiler         -> verify declared hash, profile, mark ready

A version's identity is the SHA-256 of its bytes. Re-uploading identical
content to the same dataset returns the existing version instead of creating a
second one.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Protocol

from crucible.application.ports import (
    AuditEntry,
    AuditSink,
    DatasetRepository,
    DatasetVersionRecord,
    JobQueue,
    ObjectStore,
)
from crucible.domain import (
    MAX_UPLOAD_BYTES,
    AuditAction,
    AuditResult,
    Conflict,
    DatasetVersionStatus,
    NotFound,
    PayloadTooLarge,
    Permission,
    PermissionDenied,
    Principal,
    UnsupportedMedia,
    UploadPolicyError,
    ValidationFailed,
    check_upload_policy,
    new_id,
)

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9 ._-]{0,62}[a-zA-Z0-9]$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class KeyFactory(Protocol):
    """Builds the tenant-prefixed object key. Injected so the application layer
    never imports the storage adapter."""

    def __call__(
        self,
        organization_id: uuid.UUID,
        dataset_id: uuid.UUID,
        version_id: uuid.UUID,
        filename: str,
    ) -> str: ...


def _require(principal: Principal, permission: Permission) -> None:
    if not principal.can(permission):
        raise PermissionDenied()


@dataclass(frozen=True, slots=True)
class StartUploadInput:
    dataset_name: str
    filename: str
    content_type: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class StartUploadResult:
    dataset_id: uuid.UUID
    version_id: uuid.UUID
    upload_url: str
    object_key: str
    expires_seconds: int


class StartDatasetUpload:
    def __init__(
        self,
        *,
        datasets: DatasetRepository,
        storage: ObjectStore,
        audit: AuditSink,
        key_factory: KeyFactory,
        url_ttl_seconds: int = 900,
    ) -> None:
        self._datasets = datasets
        self._storage = storage
        self._audit = audit
        self._key_factory = key_factory
        self._ttl = url_ttl_seconds

    async def __call__(
        self, principal: Principal, data: StartUploadInput, *, request_id: str = ""
    ) -> StartUploadResult:
        _require(principal, Permission.DATASET_WRITE)

        if not _NAME_RE.match(data.dataset_name):
            raise ValidationFailed(
                "Dataset name must be 2-64 characters of letters, digits, space, dot, dash, "
                "or underscore.",
                code="invalid-dataset-name",
            )

        violation = check_upload_policy(
            filename=data.filename,
            content_type=data.content_type,
            declared_size=data.size_bytes,
        )
        if violation is UploadPolicyError.TOO_LARGE:
            raise PayloadTooLarge(f"Uploads are limited to {MAX_UPLOAD_BYTES} bytes.")
        if violation is UploadPolicyError.EMPTY:
            raise ValidationFailed("File size must be greater than zero.", code="empty-upload")
        if violation is not None:
            raise UnsupportedMedia("Only CSV and Parquet uploads are supported.")

        org = principal.organization_id
        dataset = await self._datasets.dataset_by_name(organization_id=org, name=data.dataset_name)
        if dataset is None:
            dataset = await self._datasets.create_dataset(
                organization_id=org, name=data.dataset_name
            )
            await self._audit.record(
                AuditEntry(
                    organization_id=org,
                    actor_type=principal.actor_type,
                    actor_id=principal.actor_id,
                    action=AuditAction.DATASET_CREATED,
                    result=AuditResult.ALLOWED,
                    target_type="dataset",
                    target_id=str(dataset.id),
                    request_id=request_id,
                    metadata={"name": data.dataset_name},
                )
            )

        version_id = new_id()
        object_key = self._key_factory(org, dataset.id, version_id, data.filename)
        version = await self._datasets.create_version(
            organization_id=org,
            dataset_id=dataset.id,
            version_id=version_id,
            object_key=object_key,
            content_type=data.content_type,
            declared_size_bytes=data.size_bytes,
            filename=data.filename,
        )

        url = self._storage.presign_put(
            object_key, content_type=data.content_type, expires_seconds=self._ttl
        )
        await self._audit.record(
            AuditEntry(
                organization_id=org,
                actor_type=principal.actor_type,
                actor_id=principal.actor_id,
                action=AuditAction.DATASET_UPLOAD_STARTED,
                result=AuditResult.ALLOWED,
                target_type="dataset_version",
                target_id=str(version.id),
                request_id=request_id,
                metadata={
                    "dataset_id": str(dataset.id),
                    "content_type": data.content_type,
                    "declared_size_bytes": data.size_bytes,
                },
            )
        )
        return StartUploadResult(
            dataset_id=dataset.id,
            version_id=version.id,
            upload_url=url,
            object_key=object_key,
            expires_seconds=self._ttl,
        )


@dataclass(frozen=True, slots=True)
class CompleteUploadInput:
    version_id: uuid.UUID
    content_sha256: str


class CompleteDatasetUpload:
    """Confirms the bytes landed, dedupes by content hash, queues profiling.

    The client-declared hash is re-computed from the stored bytes by the worker;
    a mismatch marks the version invalid rather than trusting the client.
    """

    def __init__(
        self,
        *,
        datasets: DatasetRepository,
        storage: ObjectStore,
        queue: JobQueue,
        audit: AuditSink,
    ) -> None:
        self._datasets = datasets
        self._storage = storage
        self._queue = queue
        self._audit = audit

    async def __call__(
        self, principal: Principal, data: CompleteUploadInput, *, request_id: str = ""
    ) -> DatasetVersionRecord:
        _require(principal, Permission.DATASET_WRITE)
        org = principal.organization_id

        if not _SHA256_RE.match(data.content_sha256):
            raise ValidationFailed(
                "content_sha256 must be a lowercase hex SHA-256 digest.", code="invalid-digest"
            )

        version = await self._datasets.get_version(organization_id=org, version_id=data.version_id)
        if version is None:
            raise NotFound("Dataset version")
        if version.status is not DatasetVersionStatus.AWAITING_UPLOAD:
            # Completing twice is a client retry: return current state rather
            # than re-running the pipeline (idempotent by construction).
            return version

        info = self._storage.head(version.object_key)
        if info is None:
            raise Conflict(
                "No uploaded object was found for this version. PUT the file to the upload URL "
                "before completing.",
                code="upload-missing",
            )
        if info.size_bytes > MAX_UPLOAD_BYTES:
            await self._datasets.mark_version_invalid(
                version_id=version.id,
                reason="too_large",
                detail=f"Uploaded {info.size_bytes} bytes exceeds the {MAX_UPLOAD_BYTES} limit.",
            )
            self._storage.delete(version.object_key)
            raise PayloadTooLarge(f"Uploads are limited to {MAX_UPLOAD_BYTES} bytes.")

        existing = await self._datasets.version_by_content_hash(
            dataset_id=version.dataset_id, content_sha256=data.content_sha256
        )
        if existing is not None and existing.id != version.id:
            # Identical content already exists for this dataset. Content is the
            # identity, so return the original and discard this upload.
            self._storage.delete(version.object_key)
            await self._datasets.delete_version(version.id)
            return existing

        version = await self._datasets.mark_version_uploaded(
            version_id=version.id,
            size_bytes=info.size_bytes,
            content_sha256=data.content_sha256,
        )
        await self._queue.enqueue("profile_dataset_version", str(version.id))
        await self._audit.record(
            AuditEntry(
                organization_id=org,
                actor_type=principal.actor_type,
                actor_id=principal.actor_id,
                action=AuditAction.DATASET_VERSION_COMPLETED,
                result=AuditResult.ALLOWED,
                target_type="dataset_version",
                target_id=str(version.id),
                request_id=request_id,
                metadata={"content_sha256": data.content_sha256, "size_bytes": info.size_bytes},
            )
        )
        return version


class CreateDatasetDownloadUrl:
    """Issues a short-lived download URL. Every issuance is audited (plan §6.3)."""

    def __init__(
        self, *, datasets: DatasetRepository, storage: ObjectStore, audit: AuditSink
    ) -> None:
        self._datasets = datasets
        self._storage = storage
        self._audit = audit

    async def __call__(
        self, principal: Principal, version_id: uuid.UUID, *, request_id: str = ""
    ) -> str:
        _require(principal, Permission.DATASET_DOWNLOAD)
        version = await self._datasets.get_version(
            organization_id=principal.organization_id, version_id=version_id
        )
        if version is None:
            raise NotFound("Dataset version")
        if version.status is DatasetVersionStatus.AWAITING_UPLOAD:
            raise Conflict("This version has no uploaded content yet.", code="upload-missing")

        url = self._storage.presign_get(version.object_key, expires_seconds=300)
        await self._audit.record(
            AuditEntry(
                organization_id=principal.organization_id,
                actor_type=principal.actor_type,
                actor_id=principal.actor_id,
                action=AuditAction.DATASET_DOWNLOADED,
                result=AuditResult.ALLOWED,
                target_type="dataset_version",
                target_id=str(version_id),
                request_id=request_id,
            )
        )
        return url
