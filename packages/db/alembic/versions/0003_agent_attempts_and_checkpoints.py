"""Agent attempts, resume checkpoints, and run answer/verification.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-16

Phase 4 schema for the durable data-agent:

- `agent_attempts`: append-only evidence of each plan/code/execute/repair/verify
  step, with model attribution, exit class, duration, and cost. RESTRICT FKs
  keep it as immutable evidence.
- `agent_checkpoints`: one row per run holding the serialized graph state and the
  next node, upserted after each node so a worker restart resumes rather than
  re-running model calls and sandbox executions (ADR-008).
- `agent_runs.answer` / `agent_runs.verification`: the final structured answer +
  provenance and the verification vector.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

ATTEMPT_KINDS = ("plan", "code", "execute", "repair", "verify")


def upgrade() -> None:
    op.add_column(
        "agent_runs", sa.Column("answer", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column(
        "agent_runs",
        sa.Column("verification", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.create_table(
        "agent_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_provider", sa.String(64), nullable=True),
        sa.Column("model_id", sa.String(128), nullable=True),
        sa.Column("exit_class", sa.String(32), nullable=True),
        sa.Column("failure_category", sa.String(48), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_attempts"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name="fk_agent_attempts_run_id_agent_runs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_agent_attempts_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("run_id", "attempt_no", name="uq_agent_attempts_run_id"),
        sa.CheckConstraint(
            "kind IN (" + ", ".join(f"'{k}'" for k in ATTEMPT_KINDS) + ")",
            name="ck_agent_attempts_kind_valid",
        ),
    )
    op.create_index(
        "ix_agent_attempts_run_id_created_at", "agent_attempts", ["run_id", "created_at"]
    )

    op.create_table(
        "agent_checkpoints",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node", sa.String(32), nullable=False),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("run_id", name="pk_agent_checkpoints"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name="fk_agent_checkpoints_run_id_agent_runs",
            ondelete="RESTRICT",
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_checkpoints")
    op.drop_table("agent_attempts")
    op.drop_column("agent_runs", "verification")
    op.drop_column("agent_runs", "answer")
