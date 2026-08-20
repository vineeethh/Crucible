"""Phase 10 acceptance against the live stack: the beta allowlist (org
suspension refused at the auth boundary), data retention (terminal runs and
evidence reaped past a window), and right-to-erasure (a tenant's data purged,
with a dry run first)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from crucible.application import ApplyRetention
from crucible.db import SqlIdentityRepository, SqlRetentionRepository
from crucible_worker.jobs.runs import execute_run
from tests.integration.test_agent_data_plane import _ctx, create_run
from tests.integration.test_data_plane import ready_version
from tests.support.agent_fakes import exec_result
from tests.support.stack import Tenant, requires_stack

pytestmark = [pytest.mark.integration, requires_stack]


def _set_status(engine: sa.Engine, org_id: Any, status: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE organizations SET status = :s WHERE id = :o"),
            {"s": status, "o": org_id},
        )


def _backdate_run(engine: sa.Engine, run_id: str, days: int) -> None:
    when = datetime.now(UTC) - timedelta(days=days)
    with engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE agent_runs SET created_at = :t WHERE id = :r"),
            {"t": when, "r": run_id},
        )


# --------------------------------------------------------- beta allowlist gate


def test_suspended_organization_is_refused_at_auth(
    client: TestClient, alice: Tenant, engine: sa.Engine
) -> None:
    assert client.get("/v1/runs", headers=alice.auth).status_code == 200

    _set_status(engine, alice.organization_id, "suspended")
    refused = client.get("/v1/runs", headers=alice.auth)
    assert refused.status_code == 403
    # Even health-independent authed reads are refused; the org simply cannot act.
    assert client.get("/v1/budget", headers=alice.auth).status_code == 403

    _set_status(engine, alice.organization_id, "active")
    assert client.get("/v1/runs", headers=alice.auth).status_code == 200


# --------------------------------------------------------------- retention


def _answered_run(client: TestClient, tenant: Tenant, version_id: str, worker_ctx: Any) -> str:
    run_id = create_run(client, tenant, version_id, "What is the total amount?")
    ctx = _ctx(worker_ctx, lambda req: exec_result(value=35.75, columns_used=["amount"]))
    assert asyncio.run(execute_run(ctx, run_id)) == {"result": "answered"}
    return run_id


def test_retention_deletes_old_terminal_runs_and_keeps_recent(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any], engine: sa.Engine
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    old_run = _answered_run(client, alice, version_id, worker_ctx)
    recent_run = _answered_run(client, alice, version_id, worker_ctx)
    _backdate_run(engine, old_run, days=120)  # older than the 90-day default

    factory = worker_ctx["session_factory"]

    async def dry_run() -> int:
        async with factory() as session:
            outcome = await ApplyRetention(
                retention=SqlRetentionRepository(session),
                identity=SqlIdentityRepository(session),
                default_days=90,
            )(dry_run=True)
            return outcome.runs

    # Dry run reports the old run without deleting anything.
    assert asyncio.run(dry_run()) >= 1
    assert client.get(f"/v1/runs/{old_run}", headers=alice.auth).status_code == 200

    async def apply() -> int:
        async with factory() as session:
            outcome = await ApplyRetention(
                retention=SqlRetentionRepository(session),
                identity=SqlIdentityRepository(session),
                default_days=90,
            )(dry_run=False)
            await session.commit()
            return outcome.runs

    deleted = asyncio.run(apply())
    assert deleted >= 1

    # The old run and all its evidence are gone; the recent run is untouched.
    assert client.get(f"/v1/runs/{old_run}", headers=alice.auth).status_code == 404
    assert client.get(f"/v1/runs/{recent_run}", headers=alice.auth).status_code == 200
    with engine.begin() as conn:
        orphans = conn.execute(
            sa.text("SELECT count(*) FROM run_events WHERE run_id = :r"), {"r": old_run}
        ).scalar_one()
        attempts = conn.execute(
            sa.text("SELECT count(*) FROM agent_attempts WHERE run_id = :r"), {"r": old_run}
        ).scalar_one()
    assert orphans == 0 and attempts == 0  # no dangling evidence


def test_retention_never_reaps_a_non_terminal_run(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any], engine: sa.Engine
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    # A queued (non-terminal) run, backdated: it must survive retention.
    queued = create_run(client, alice, version_id, "What is the total amount?")
    _backdate_run(engine, queued, days=365)

    factory = worker_ctx["session_factory"]

    async def apply() -> None:
        async with factory() as session:
            await SqlRetentionRepository(session).delete_expired_runs(
                cutoff=datetime.now(UTC), organization_id=alice.organization_id
            )
            await session.commit()

    asyncio.run(apply())
    assert client.get(f"/v1/runs/{queued}", headers=alice.auth).status_code == 200


# --------------------------------------------------------------- erasure


def test_purge_organization_removes_all_tenant_data(
    client: TestClient, bob: Tenant, worker_ctx: dict[str, Any], engine: sa.Engine
) -> None:
    version_id = ready_version(client, bob, worker_ctx)
    _answered_run(client, bob, version_id, worker_ctx)
    factory = worker_ctx["session_factory"]

    async def describe() -> dict[str, int]:
        async with factory() as session:
            return await SqlRetentionRepository(session).describe_organization(bob.organization_id)

    before = asyncio.run(describe())
    assert before["runs"] >= 1 and before["datasets"] >= 1 and before["api_keys"] >= 1

    async def purge() -> dict[str, int]:
        async with factory() as session:
            counts = await SqlRetentionRepository(session).purge_organization(bob.organization_id)
            await session.commit()
            return counts

    purged = asyncio.run(purge())
    assert purged["runs"] >= 1

    # The org is gone: its key no longer authenticates, and no rows remain.
    assert client.get("/v1/runs", headers=bob.auth).status_code in (401, 403)
    with engine.begin() as conn:
        for table in ("agent_runs", "datasets", "api_keys", "memberships"):
            remaining = conn.execute(
                sa.text(f"SELECT count(*) FROM {table} WHERE organization_id = :o"),
                {"o": bob.organization_id},
            ).scalar_one()
            assert remaining == 0, table
        org = conn.execute(
            sa.text("SELECT count(*) FROM organizations WHERE id = :o"),
            {"o": bob.organization_id},
        ).scalar_one()
    assert org == 0
