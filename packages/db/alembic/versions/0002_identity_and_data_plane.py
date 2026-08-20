"""Identity, dataset ingestion, durable runs, and audit.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-14

Phase 2 schema. Design notes that are load-bearing, not decorative:

- Every tenant-owned table carries `organization_id` and leads its compound
  indexes with it, because every product query is tenant-scoped (plan §5.3).
- `dataset_versions` is content-addressed: UNIQUE (dataset_id, content_sha256)
  means identical bytes cannot become two versions. NULL hashes are permitted
  while an upload is in flight (Postgres allows multiple NULLs in a unique index).
- Foreign keys are RESTRICT, never CASCADE: evaluation and audit evidence must
  not be deletable as a side effect of removing a parent row.
- Status columns are CHECK-constrained against the domain enums, so an invalid
  state fails at the database rather than silently persisting.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ROLES = ("owner", "admin", "engineer", "reviewer", "viewer")
DATASET_STATUS = ("active", "deleted")
VERSION_STATUS = ("awaiting_upload", "pending_profile", "ready", "invalid")
RUN_STATUS = (
    "queued",
    "running",
    "waiting_review",
    "answered",
    "abstained",
    "needs_human_review",
    "policy_denied",
    "budget_exhausted",
    "cancelled",
)
EVENT_TYPES = (
    "created",
    "claimed",
    "status_changed",
    "progress",
    "cancel_requested",
    "terminal",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({joined})"


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("subject", name="uq_users_subject"),
    )

    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_memberships_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_memberships_user_id_users", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_memberships_organization_id"),
        sa.CheckConstraint(_in("role", ROLES), name="ck_memberships_role_valid"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("prefix", sa.String(32), nullable=False),
        sa.Column("secret_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_api_keys_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_api_keys_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("prefix", name="uq_api_keys_prefix"),
        sa.CheckConstraint(_in("role", ROLES), name="ck_api_keys_role_valid"),
    )
    op.create_index(
        "ix_api_keys_organization_id_created_at", "api_keys", ["organization_id", "created_at"]
    )

    op.create_table(
        "datasets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_datasets"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_datasets_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("organization_id", "name", name="uq_datasets_organization_id"),
        sa.CheckConstraint(_in("status", DATASET_STATUS), name="ck_datasets_status_valid"),
    )
    op.create_index(
        "ix_datasets_organization_id_created_at", "datasets", ["organization_id", "created_at"]
    )

    op.create_table(
        "dataset_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("declared_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("schema_hash", sa.String(64), nullable=True),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("column_count", sa.Integer(), nullable=True),
        sa.Column("profile", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("invalid_reason", sa.String(64), nullable=True),
        sa.Column("invalid_detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dataset_versions"),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name="fk_dataset_versions_dataset_id_datasets",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_dataset_versions_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("dataset_id", "content_sha256", name="uq_dataset_versions_dataset_id"),
        sa.UniqueConstraint(
            "dataset_id", "version_no", name="uq_dataset_versions_dataset_id_version_no"
        ),
        sa.CheckConstraint(_in("status", VERSION_STATUS), name="ck_dataset_versions_status_valid"),
        sa.CheckConstraint(
            "declared_size_bytes > 0", name="ck_dataset_versions_declared_size_positive"
        ),
    )
    op.create_index(
        "ix_dataset_versions_organization_id_created_at",
        "dataset_versions",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_dataset_versions_dataset_id_created_at",
        "dataset_versions",
        ["dataset_id", "created_at"],
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("config_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("request_hash", sa.String(64), nullable=True),
        sa.Column("terminal_detail", sa.Text(), nullable=True),
        sa.Column("failure_category", sa.String(48), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_runs"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_agent_runs_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_versions.id"],
            name="fk_agent_runs_dataset_version_id_dataset_versions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_agent_runs_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_agent_runs_organization_id"
        ),
        sa.CheckConstraint(_in("status", RUN_STATUS), name="ck_agent_runs_status_valid"),
    )
    op.create_index(
        "ix_agent_runs_organization_id_created_at", "agent_runs", ["organization_id", "created_at"]
    )
    op.create_index("ix_agent_runs_status_created_at", "agent_runs", ["status", "created_at"])
    op.create_index(
        "ix_agent_runs_dataset_version_id_created_at",
        "agent_runs",
        ["dataset_version_id", "created_at"],
    )
    # Partial index for the queue/dashboard hot path: active runs only.
    op.create_index(
        "ix_agent_runs_active",
        "agent_runs",
        ["organization_id", "created_at"],
        postgresql_where=sa.text("status IN ('queued', 'running', 'waiting_review')"),
    )

    op.create_table(
        "run_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_run_events"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name="fk_run_events_run_id_agent_runs",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("run_id", "sequence_no", name="uq_run_events_run_id"),
        sa.CheckConstraint(_in("event_type", EVENT_TYPES), name="ck_run_events_event_type_valid"),
    )
    op.create_index("ix_run_events_run_id_created_at", "run_events", ["run_id", "created_at"])

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("target_type", sa.String(48), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_audit_events_organization_id_organizations",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_audit_events_organization_id_created_at",
        "audit_events",
        ["organization_id", "created_at"],
    )
    op.create_index("ix_audit_events_action_created_at", "audit_events", ["action", "created_at"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("run_events")
    op.drop_table("agent_runs")
    op.drop_table("dataset_versions")
    op.drop_table("datasets")
    op.drop_table("api_keys")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("organizations")
