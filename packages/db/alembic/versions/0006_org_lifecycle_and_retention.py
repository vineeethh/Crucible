"""Organization lifecycle (beta allowlist) and per-tenant retention.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-21

Phase 10:
- `organizations.status`: the private-beta allowlist gate. Only `active`
  organizations authenticate; `suspended` is a reversible block enforced at the
  authentication boundary (data is retained). Defaults `active` so existing
  tenants are unaffected.
- `organizations.retention_days`: optional per-tenant override of the platform
  data-retention window (NULL = use the platform default). The retention job
  deletes terminal runs and their evidence older than the window; audit events
  and datasets are governed separately.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

ORG_STATUSES = ("active", "suspended")


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
    )
    op.add_column(
        "organizations",
        sa.Column("retention_days", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "status_valid",
        "organizations",
        "status IN (" + ", ".join(f"'{s}'" for s in ORG_STATUSES) + ")",
    )
    op.create_check_constraint(
        "retention_days_positive",
        "organizations",
        "retention_days IS NULL OR retention_days > 0",
    )


def downgrade() -> None:
    # Explicit SQL with the fully-qualified names: passing the bare name to
    # drop_constraint would re-apply the naming convention and double-prefix it.
    op.execute(
        "ALTER TABLE organizations "
        "DROP CONSTRAINT IF EXISTS ck_organizations_retention_days_positive"
    )
    op.execute("ALTER TABLE organizations DROP CONSTRAINT IF EXISTS ck_organizations_status_valid")
    op.drop_column("organizations", "retention_days")
    op.drop_column("organizations", "status")
