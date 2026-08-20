"""Transport DTOs. Deliberately distinct from domain entities and DB rows so a
storage detail (object keys, secret hashes) cannot leak into a response by
accident."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from crucible.application import (
    AgentAttemptRecord,
    ApiKeyRecord,
    DatasetRecord,
    DatasetVersionRecord,
    RunEventRecord,
    RunRecord,
)
from crucible.domain import MAX_QUESTION_CHARS, MAX_UPLOAD_BYTES, Permission, Role


class MembershipOut(BaseModel):
    organization_id: uuid.UUID
    organization_slug: str
    organization_name: str
    role: Role


class MeOut(BaseModel):
    actor_type: str
    actor_id: uuid.UUID
    organization_id: uuid.UUID
    role: Role
    permissions: list[Permission]


# ------------------------------------------------------------------- datasets


class StartUploadIn(BaseModel):
    dataset_name: str = Field(min_length=2, max_length=64)
    filename: str = Field(min_length=1, max_length=255)
    content_type: Literal["text/csv", "application/vnd.apache.parquet"]
    size_bytes: int = Field(gt=0, le=MAX_UPLOAD_BYTES)


class StartUploadOut(BaseModel):
    dataset_id: uuid.UUID
    version_id: uuid.UUID
    upload_url: str
    expires_seconds: int
    instructions: str = (
        "PUT the file bytes to upload_url with the same Content-Type, then POST "
        "/v1/datasets/versions/{version_id}/complete with the file's SHA-256."
    )


class CompleteUploadIn(BaseModel):
    content_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class DatasetOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime

    @classmethod
    def of(cls, record: DatasetRecord) -> DatasetOut:
        return cls(id=record.id, name=record.name, created_at=record.created_at)


class DatasetVersionOut(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    version_no: int
    status: str
    content_type: str
    size_bytes: int | None
    content_sha256: str | None
    schema_hash: str | None
    row_count: int | None
    column_count: int | None
    profile: dict[str, Any] | None
    invalid_reason: str | None
    created_at: datetime | None

    @classmethod
    def of(cls, record: DatasetVersionRecord) -> DatasetVersionOut:
        # object_key is intentionally not exposed: it is an internal storage
        # detail and a cross-tenant probing surface.
        return cls(
            id=record.id,
            dataset_id=record.dataset_id,
            version_no=record.version_no,
            status=record.status.value,
            content_type=record.content_type,
            size_bytes=record.size_bytes,
            content_sha256=record.content_sha256,
            schema_hash=record.schema_hash,
            row_count=record.row_count,
            column_count=record.column_count,
            profile=record.profile,
            invalid_reason=record.invalid_reason,
            created_at=record.created_at,
        )


class DownloadUrlOut(BaseModel):
    url: str
    expires_seconds: int


# ----------------------------------------------------------------------- runs


class CreateRunIn(BaseModel):
    dataset_version_id: uuid.UUID
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


class RunOut(BaseModel):
    id: uuid.UUID
    dataset_version_id: uuid.UUID
    question: str
    status: str
    config_manifest: dict[str, Any]
    terminal_detail: str | None
    failure_category: str | None
    cancel_requested: bool
    answer: dict[str, Any] | None
    verification: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, record: RunRecord) -> RunOut:
        return cls(
            id=record.id,
            dataset_version_id=record.dataset_version_id,
            question=record.question,
            status=record.status.value,
            config_manifest=record.config_manifest,
            terminal_detail=record.terminal_detail,
            failure_category=record.failure_category,
            cancel_requested=record.cancel_requested_at is not None,
            answer=record.answer,
            verification=record.verification,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class AttemptOut(BaseModel):
    attempt_no: int
    kind: str
    sequence_no: int
    payload: dict[str, Any]
    model_provider: str | None
    model_id: str | None
    exit_class: str | None
    failure_category: str | None
    duration_ms: int | None
    cost_usd: float | None
    source_sha256: str | None
    created_at: datetime

    @classmethod
    def of(cls, record: AgentAttemptRecord) -> AttemptOut:
        return cls(
            attempt_no=record.attempt_no,
            kind=record.kind,
            sequence_no=record.sequence_no,
            payload=record.payload,
            model_provider=record.model_provider,
            model_id=record.model_id,
            exit_class=record.exit_class,
            failure_category=record.failure_category,
            duration_ms=record.duration_ms,
            cost_usd=record.cost_usd,
            source_sha256=record.source_sha256,
            created_at=record.created_at,
        )


class ReviewIn(BaseModel):
    decision: Literal["approve", "reject", "revise"]
    # Only meaningful (and only sent to the worker) when decision == "revise":
    # folded into the plan/code prompt for the automatic retry that follows.
    feedback: str | None = None


# --------------------------------------------------------------- review queue


class ReviewQueueItemOut(BaseModel):
    run_id: uuid.UUID
    question: str
    created_at: datetime
    review_status: str | None
    verification: dict[str, Any] | None


class ReviewOut(BaseModel):
    run_id: uuid.UUID
    status: str
    rubric_version: str
    decision: str | None


class RubricGradesIn(BaseModel):
    groundedness: int = Field(ge=0, le=2)
    provenance: int = Field(ge=0, le=2)
    usefulness: int = Field(ge=0, le=2)
    uncertainty: int = Field(ge=0, le=2)


class SubmitReviewIn(BaseModel):
    decision: Literal["approve", "reject"]
    grades: RubricGradesIn


# --------------------------------------------------------------------- metrics


class ReliabilityOut(BaseModel):
    total: int
    terminal: int
    terminal_states: dict[str, int]
    answered: int
    abstained: int
    technical_completion_rate: float
    trace_completeness: float
    failure_taxonomy: dict[str, int]


class CostLatencyOut(BaseModel):
    runs_with_cost: int
    total_cost_usd: float
    cost_attribution_completeness: float
    latency_p50_ms: int
    latency_p95_ms: int
    latency_p99_ms: int


class AlertOut(BaseModel):
    rule_id: str
    severity: str
    firing: bool
    detail: str
    runbook: str


class RunEventOut(BaseModel):
    sequence_no: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime

    @classmethod
    def of(cls, record: RunEventRecord) -> RunEventOut:
        return cls(
            sequence_no=record.sequence_no,
            event_type=record.event_type.value,
            payload=record.payload,
            created_at=record.created_at,
        )


# ------------------------------------------------------------------- api keys


class CreateApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    role: Role
    scopes: list[Permission] | None = None
    expires_at: datetime | None = None


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    role: Role
    scopes: list[Permission] | None
    expires_at: datetime | None
    revoked_at: datetime | None

    @classmethod
    def of(cls, record: ApiKeyRecord) -> ApiKeyOut:
        return cls(
            id=record.id,
            name=record.name,
            prefix=record.prefix,
            role=record.role,
            scopes=list(record.scopes) if record.scopes is not None else None,
            expires_at=record.expires_at,
            revoked_at=record.revoked_at,
        )


class CreatedApiKeyOut(ApiKeyOut):
    token: str = Field(description="The full API key. Shown once and never retrievable again.")


# ---------------------------------------------------------------------- budget


class BudgetOut(BaseModel):
    monthly_limit_usd: float | None
    month_spend_usd: float
    remaining_usd: float | None


class SetBudgetIn(BaseModel):
    monthly_limit_usd: float = Field(ge=0)


class CacheStatsOut(BaseModel):
    hits: int
    misses: int
    false_hits: int
    stores: int
    hit_rate: float
