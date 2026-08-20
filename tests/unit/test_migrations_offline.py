"""Alembic offline check: migrations render valid SQL without a database.

This keeps a meaningful migration gate in the fast PR lane; the integration
test (tests/integration) applies them to a live Postgres.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    cfg = Config(str(REPO_ROOT / "packages" / "db" / "alembic.ini"))
    return cfg


def test_offline_upgrade_renders_bootstrap_sql(capsys: "object") -> None:
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        command.upgrade(_alembic_config(), "head", sql=True)
    sql = buf.getvalue()
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "alembic_version" in sql


def test_single_head_revision() -> None:
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config())
    heads = script.get_heads()
    # A branched history means two migrations claim the same parent, which
    # `alembic upgrade head` cannot resolve. Keep the line linear.
    assert len(heads) == 1, f"expected a single linear head, got {heads}"
    assert heads == ["0006"]
