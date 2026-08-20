"""Budget ledger and exact answer cache.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-19

Phase 8:
- `budgets`: one row per organization with a monthly USD limit. Absent row =
  no budget enforcement (the pre-Phase-8 behavior).
- `budget_entries`: the append-only ledger. `reserve` at run admission,
  `settle` (actual attempt cost) and `release` (reserve reversal) at terminal.
  Month spend is the SUM of entries in the month, so admission naturally
  counts in-flight reserves. A partial unique index on (run_id, kind) makes
  settlement idempotent under at-least-once job delivery.
- `answer_cache`: exact-match verified answers. The cache key already binds
  tenant + dataset content + config + question; the unique constraint is
  (organization_id, cache_key) and every read is org-scoped in SQL, so an
  entry can never serve another tenant/dataset/config (threat T5).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

ENTRY_KINDS = ("reserve", "settle", "release", "adjust")

# Phase 8 adds two evidence kinds to agent attempts: `route` (the routing
# policy in effect / an escalation) and `cache` (hit/miss/false_hit/store).
OLD_ATTEMPT_KINDS = ("plan", "code", "execute", "repair", "verify")
NEW_ATTEMPT_KINDS = (*OLD_ATTEMPT_KINDS, "route", "cache")


def _kind_check(kinds: tuple[str, ...]) -> str:
    return "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")"


# 0003 created this constraint inside create_table with an explicit name that
# the metadata naming convention wrapped AGAIN, so the on-disk name is the
# double-prefixed one. We normalize to the single, intended name here; both
# spellings are dropped defensively so the migration works on either history.
_LEGACY_KIND_CONSTRAINT = "ck_agent_attempts_ck_agent_attempts_kind_valid"
_KIND_CONSTRAINT = "ck_agent_attempts_kind_valid"


def upgrade() -> None:
    op.execute(f"ALTER TABLE agent_attempts DROP CONSTRAINT IF EXISTS {_LEGACY_KIND_CONSTRAINT}")
    op.execute(f"ALTER TABLE agent_attempts DROP CONSTRAINT IF EXISTS {_KIND_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE agent_attempts ADD CONSTRAINT {_KIND_CONSTRAINT} "
        f"CHECK ({_kind_check(NEW_ATTEMPT_KINDS)})"
    )

    op.create_table(
        "budgets",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monthly_limit_usd", sa.Numeric(12, 4), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("organization_id", name="pk_budgets"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_budgets_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("monthly_limit_usd >= 0", name="ck_budgets_limit_non_negative"),
    )

    op.create_table(
        "budget_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("amount_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("detail", sa.String(200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_budget_entries"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_budget_entries_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name="fk_budget_entries_run_id_agent_runs",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "kind IN (" + ", ".join(f"'{k}'" for k in ENTRY_KINDS) + ")",
            name="ck_budget_entries_kind_valid",
        ),
    )
    op.create_index(
        "ix_budget_entries_organization_id_created_at",
        "budget_entries",
        ["organization_id", "created_at"],
    )
    # Idempotent settlement: at most one entry of each kind per run.
    op.create_index(
        "uq_budget_entries_run_id_kind",
        "budget_entries",
        ["run_id", "kind"],
        unique=True,
        postgresql_where=sa.text("run_id IS NOT NULL"),
    )

    op.create_table(
        "answer_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_sha256", sa.String(64), nullable=False),
        sa.Column("question_sha256", sa.String(64), nullable=False),
        sa.Column("config_signature", sa.String(32), nullable=False),
        sa.Column("answer", postgresql.JSONB(), nullable=False),
        sa.Column("verification", postgresql.JSONB(), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_answer_cache"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_answer_cache_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "organization_id", "cache_key", name="uq_answer_cache_organization_id_cache_key"
        ),
    )


def downgrade() -> None:
    op.drop_table("answer_cache")
    op.drop_table("budget_entries")
    op.drop_table("budgets")
    op.execute(f"ALTER TABLE agent_attempts DROP CONSTRAINT IF EXISTS {_KIND_CONSTRAINT}")
    op.execute(f"ALTER TABLE agent_attempts DROP CONSTRAINT IF EXISTS {_LEGACY_KIND_CONSTRAINT}")
    # Restore the exact 0003-era on-disk name so a re-upgrade sees the same
    # state a fresh 0003→0004 chain produces.
    op.execute(
        f"ALTER TABLE agent_attempts ADD CONSTRAINT {_LEGACY_KIND_CONSTRAINT} "
        f"CHECK ({_kind_check(OLD_ATTEMPT_KINDS)})"
    )
