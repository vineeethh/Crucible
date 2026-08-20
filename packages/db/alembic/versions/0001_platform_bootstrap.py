"""Platform bootstrap: required PostgreSQL extensions.

Revision ID: 0001
Revises: None
Create Date: 2026-07-14

First migration deliberately contains no product schema (that arrives with
Phase 2's identity/data plane). It pins the platform prerequisites:

- pgvector: ADR-002 keeps vector capability inside PostgreSQL rather than a
  dedicated vector database; enabling it here means every environment created
  from migrations is capable from day one.

The local compose image (pgvector/pgvector:pg17) and Cloud SQL both ship the
extension; CREATE EXTENSION is idempotent.
"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
