"""SQLAlchemy models.

Conventions (plan §5.3):
- Every tenant-owned table carries `organization_id` and indexes it first.
- UUIDv7 primary keys (time-sortable, opaque in public).
- Immutable evidence (dataset versions, run events, audit) uses RESTRICT, not
  cascade, so history cannot be deleted by accident.
- Enumerated statuses are CHECK-constrained, so a bad write fails at the
  database, not silently.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from crucible.domain import (
    DatasetStatus,
    DatasetVersionStatus,
    Role,
    RunEventType,
    RunStatus,
)

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _enum_values(enum_cls: type[StrEnum]) -> str:
    return ", ".join(f"'{member.value}'" for member in enum_cls)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = _pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Phase 10: beta allowlist gate ('active'|'suspended') + optional per-tenant
    # retention override (NULL = platform default).
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    retention_days: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created_at()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    # OIDC subject; the identity provider owns authentication, we own membership.
    subject: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = _created_at()


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_memberships_organization_id"),
        CheckConstraint(f"role IN ({_enum_values(Role)})", name="role_valid"),
        Index("ix_memberships_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint(f"role IN ({_enum_values(Role)})", name="role_valid"),
        Index("ix_api_keys_organization_id_created_at", "organization_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Cleartext prefix identifies the row; only the Argon2id hash of the secret
    # is stored, and the full token is displayed exactly once.
    prefix: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    secret_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    scopes: Mapped[list[str] | None] = mapped_column(JSONB)  # None = full role
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_datasets_organization_id"),
        CheckConstraint(f"status IN ({_enum_values(DatasetStatus)})", name="status_valid"),
        Index("ix_datasets_organization_id_created_at", "organization_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DatasetStatus.ACTIVE.value
    )
    created_at: Mapped[datetime] = _created_at()


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        # Content is identity: the same bytes cannot become two versions.
        UniqueConstraint("dataset_id", "content_sha256", name="uq_dataset_versions_dataset_id"),
        UniqueConstraint(
            "dataset_id", "version_no", name="uq_dataset_versions_dataset_id_version_no"
        ),
        CheckConstraint(f"status IN ({_enum_values(DatasetVersionStatus)})", name="status_valid"),
        CheckConstraint("declared_size_bytes > 0", name="declared_size_positive"),
        Index("ix_dataset_versions_organization_id_created_at", "organization_id", "created_at"),
        Index("ix_dataset_versions_dataset_id_created_at", "dataset_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _pk()
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="RESTRICT"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    declared_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    schema_hash: Mapped[str | None] = mapped_column(String(64))
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    column_count: Mapped[int | None] = mapped_column(Integer)
    profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    invalid_reason: Mapped[str | None] = mapped_column(String(64))
    invalid_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_agent_runs_organization_id"
        ),
        CheckConstraint(f"status IN ({_enum_values(RunStatus)})", name="status_valid"),
        Index("ix_agent_runs_organization_id_created_at", "organization_id", "created_at"),
        Index("ix_agent_runs_status_created_at", "status", "created_at"),
        Index("ix_agent_runs_dataset_version_id_created_at", "dataset_version_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # Freezes every behavior-changing input for this run (plan principle 5).
    config_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_hash: Mapped[str | None] = mapped_column(String(64))
    terminal_detail: Mapped[str | None] = mapped_column(Text)
    failure_category: Mapped[str | None] = mapped_column(String(48))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Phase 4: the final structured answer + provenance, and the verification vector.
    answer: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AgentAttempt(Base):
    __tablename__ = "agent_attempts"
    __table_args__ = (
        UniqueConstraint("run_id", "attempt_no", name="uq_agent_attempts_run_id"),
        CheckConstraint(
            "kind IN ('plan', 'code', 'execute', 'repair', 'verify', 'route', 'cache')",
            name="kind_valid",
        ),
        Index("ix_agent_attempts_run_id_created_at", "run_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    model_provider: Mapped[str | None] = mapped_column(String(64))
    model_id: Mapped[str | None] = mapped_column(String(128))
    exit_class: Mapped[str | None] = mapped_column(String(32))
    failure_category: Mapped[str | None] = mapped_column(String(48))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created_at()


class AgentCheckpoint(Base):
    """One row per run: the serialized graph state and the next node to run.
    Upserted after every node so a worker restart resumes (ADR-008)."""

    __tablename__ = "agent_checkpoints"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="RESTRICT"), primary_key=True
    )
    node: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence_no", name="uq_run_events_run_id"),
        CheckConstraint(f"event_type IN ({_enum_values(RunEventType)})", name="event_type_valid"),
        Index("ix_run_events_run_id_created_at", "run_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_organization_id_created_at", "organization_id", "created_at"),
        Index("ix_audit_events_action_created_at", "action", "created_at"),
    )

    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    target_type: Mapped[str] = mapped_column(String(48), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = _created_at()

    # Append-only: no repository method updates or deletes this table, and
    # Phase 9 IaC withholds UPDATE/DELETE grants from the application role.


class Score(Base):
    __tablename__ = "scores"
    __table_args__ = (
        Index("ix_scores_organization_id_target", "organization_id", "target_type", "target_id"),
        Index("ix_scores_definition_key_created_at", "definition_key", "created_at"),
    )

    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    definition_key: Mapped[str] = mapped_column(String(64), nullable=False)
    score_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    value_num: Mapped[float | None] = mapped_column(Float)
    value_bool: Mapped[bool | None] = mapped_column(Boolean)
    value_categorical: Mapped[str | None] = mapped_column(String(64))
    value_text: Mapped[str | None] = mapped_column(Text)
    evaluator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = _created_at()


class HumanReview(Base):
    __tablename__ = "human_reviews"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_human_reviews_run_id"),
        Index("ix_human_reviews_organization_id_status", "organization_id", "status"),
    )

    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    rubric_version: Mapped[str] = mapped_column(String(64), nullable=False)
    claimed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision: Mapped[str | None] = mapped_column(String(16))
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Budget(Base):
    """Per-organization monthly cost budget (Phase 8). Absent row = unenforced."""

    __tablename__ = "budgets"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    monthly_limit_usd: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BudgetEntry(Base):
    """Append-only budget ledger: reserve at admission, settle/release at
    terminal. Month spend = SUM(amount_usd) over the month, so reserves count
    while a run is in flight and are reversed when it settles."""

    __tablename__ = "budget_entries"
    __table_args__ = (
        Index("ix_budget_entries_organization_id_created_at", "organization_id", "created_at"),
        Index(
            "uq_budget_entries_run_id_kind",
            "run_id",
            "kind",
            unique=True,
            postgresql_where=text("run_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # reserve|settle|release|adjust
    amount_usd: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created_at()


class AnswerCacheEntry(Base):
    """Exact-match verified answers (Phase 8, feature-flagged). The key binds
    tenant + dataset content + config + question; the unique constraint and
    every read are org-scoped, so entries cannot cross tenants (threat T5)."""

    __tablename__ = "answer_cache"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "cache_key", name="uq_answer_cache_organization_id_cache_key"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dataset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    question_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    config_signature: Mapped[str] = mapped_column(String(32), nullable=False)
    answer: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
