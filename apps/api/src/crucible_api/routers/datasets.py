"""Dataset ingestion routes.

The API issues a presigned URL and confirms the result; file bytes never pass
through this process (plan §6.1).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status

from crucible.application import (
    CompleteDatasetUpload,
    CompleteUploadInput,
    CreateDatasetDownloadUrl,
    GetDatasetVersion,
    ListDatasets,
    ListDatasetVersions,
    StartDatasetUpload,
    StartUploadInput,
)
from crucible.storage import dataset_object_key
from crucible_api.dependencies import (
    AuditDep,
    DatasetRepoDep,
    PrincipalDep,
    RequestIdDep,
    SettingsDep,
    write_rate_limit,
)
from crucible_api.queue import ArqJobQueue
from crucible_api.schemas import (
    CompleteUploadIn,
    DatasetOut,
    DatasetVersionOut,
    DownloadUrlOut,
    StartUploadIn,
    StartUploadOut,
)

router = APIRouter(prefix="/v1/datasets", tags=["datasets"])


@router.get("", response_model=list[DatasetOut])
async def list_datasets(principal: PrincipalDep, datasets: DatasetRepoDep) -> list[DatasetOut]:
    records = await ListDatasets(datasets=datasets)(principal)
    return [DatasetOut.of(r) for r in records]


@router.get("/{dataset_id}/versions", response_model=list[DatasetVersionOut])
async def list_versions(
    dataset_id: uuid.UUID, principal: PrincipalDep, datasets: DatasetRepoDep
) -> list[DatasetVersionOut]:
    records = await ListDatasetVersions(datasets=datasets)(principal, dataset_id)
    return [DatasetVersionOut.of(r) for r in records]


@router.post(
    "/uploads",
    response_model=StartUploadOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(write_rate_limit)],
)
async def start_upload(
    body: StartUploadIn,
    request: Request,
    principal: PrincipalDep,
    datasets: DatasetRepoDep,
    audit: AuditDep,
    settings: SettingsDep,
    request_id: RequestIdDep,
) -> StartUploadOut:
    result = await StartDatasetUpload(
        datasets=datasets,
        storage=request.app.state.storage,
        audit=audit,
        key_factory=dataset_object_key,
        url_ttl_seconds=settings.upload_url_ttl_seconds,
    )(
        principal,
        StartUploadInput(
            dataset_name=body.dataset_name,
            filename=body.filename,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
        ),
        request_id=request_id,
    )
    return StartUploadOut(
        dataset_id=result.dataset_id,
        version_id=result.version_id,
        upload_url=result.upload_url,
        expires_seconds=result.expires_seconds,
    )


@router.post(
    "/versions/{version_id}/complete",
    response_model=DatasetVersionOut,
    dependencies=[Depends(write_rate_limit)],
)
async def complete_upload(
    version_id: uuid.UUID,
    body: CompleteUploadIn,
    request: Request,
    principal: PrincipalDep,
    datasets: DatasetRepoDep,
    audit: AuditDep,
    request_id: RequestIdDep,
) -> DatasetVersionOut:
    record = await CompleteDatasetUpload(
        datasets=datasets,
        storage=request.app.state.storage,
        queue=ArqJobQueue(request.app.state.queue_pool),
        audit=audit,
    )(
        principal,
        CompleteUploadInput(version_id=version_id, content_sha256=body.content_sha256),
        request_id=request_id,
    )
    return DatasetVersionOut.of(record)


@router.get("/versions/{version_id}", response_model=DatasetVersionOut)
async def get_version(
    version_id: uuid.UUID, principal: PrincipalDep, datasets: DatasetRepoDep
) -> DatasetVersionOut:
    record = await GetDatasetVersion(datasets=datasets)(principal, version_id)
    return DatasetVersionOut.of(record)


@router.post("/versions/{version_id}/download-url", response_model=DownloadUrlOut)
async def download_url(
    version_id: uuid.UUID,
    request: Request,
    principal: PrincipalDep,
    datasets: DatasetRepoDep,
    audit: AuditDep,
    request_id: RequestIdDep,
) -> DownloadUrlOut:
    url = await CreateDatasetDownloadUrl(
        datasets=datasets, storage=request.app.state.storage, audit=audit
    )(principal, version_id, request_id=request_id)
    return DownloadUrlOut(url=url, expires_seconds=300)
