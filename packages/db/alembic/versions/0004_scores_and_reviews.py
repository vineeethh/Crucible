"""Typed scores and the human-review queue.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-18

Phase 6:
- `scores`: typed observations (boolean/numeric/categorical/text) attached to a
  run/attempt/eval-item, tagged with the source (deterministic/human/judge) and
  an evaluator version, so a judge score is never mistaken for ground truth.
- `human_reviews`: the review queue with a versioned rubric, optimistic-lock
  claim (one reviewer per run via a unique run_id), a claim SLA, and the
  reviewer's decision. RESTRICT FKs keep review evidence immutable.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

SCORE_TYPES = ("boolean", "numeric", "categorical", "text")
SCORE_SOURCES = ("deterministic", "human", "judge")
TARGET_TYPES = ("run", "attempt", "eval_item")
REVIEW_STATES = ("pending", "claimed", "submitted", "expired")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.create_table(
        "scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("definition_key", sa.String(64), nullable=False),
        sa.Column("score_type", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("value_num", sa.Float(), nullable=True),
        sa.Column("value_bool", sa.Boolean(), nullable=True),
        sa.Column("value_categorical", sa.String(64), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("evaluator_version", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scores"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_scores_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_scores_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(_in("score_type", SCORE_TYPES), name="ck_scores_score_type_valid"),
        sa.CheckConstraint(_in("source", SCORE_SOURCES), name="ck_scores_source_valid"),
        sa.CheckConstraint(_in("target_type", TARGET_TYPES), name="ck_scores_target_type_valid"),
    )
    op.create_index(
        "ix_scores_organization_id_target",
        "scores",
        ["organization_id", "target_type", "target_id"],
    )
    op.create_index(
        "ix_scores_definition_key_created_at", "scores", ["definition_key", "created_at"]
    )

    op.create_table(
        "human_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("rubric_version", sa.String(64), nullable=False),
        # Reviewer identity is the generic actor id (an OIDC user id, or a
        # service/API-key id) — not a users FK, so machine and human reviewers
        # are both representable. Full attribution is in the audit log.
        sa.Column("claimed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision", sa.String(16), nullable=True),
        sa.Column("submitted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_human_reviews"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_human_reviews_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name="fk_human_reviews_run_id_agent_runs",
            ondelete="RESTRICT",
        ),
        # One review row per run: a second concurrent claim hits this and loses.
        sa.UniqueConstraint("run_id", name="uq_human_reviews_run_id"),
        sa.CheckConstraint(_in("status", REVIEW_STATES), name="ck_human_reviews_status_valid"),
    )
    op.create_index(
        "ix_human_reviews_organization_id_status", "human_reviews", ["organization_id", "status"]
    )


def downgrade() -> None:
    op.drop_table("human_reviews")
    op.drop_table("scores")
