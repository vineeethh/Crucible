"""Phase 8 acceptance against the live stack: budget admission and settlement,
the exact cache end to end (store → hit → org isolation), and the new
budget/cache metrics endpoints."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from crucible.db import SqlCacheStore
from crucible_worker.agent_runtime import SqlAnswerCache
from crucible_worker.jobs.runs import execute_run
from tests.integration.test_agent_data_plane import _ctx, create_run
from tests.integration.test_data_plane import ready_version
from tests.support.agent_fakes import exec_result
from tests.support.stack import Tenant, requires_stack

pytestmark = [pytest.mark.integration, requires_stack]


def set_budget(client: TestClient, tenant: Tenant, limit: float) -> dict[str, Any]:
    response = client.put("/v1/budget", headers=tenant.auth, json={"monthly_limit_usd": limit})
    assert response.status_code == 200, response.text
    return dict(response.json())


# -------------------------------------------------------------------- budgets


def test_budget_defaults_to_unenforced(client: TestClient, alice: Tenant) -> None:
    status = client.get("/v1/budget", headers=alice.auth).json()
    assert status["monthly_limit_usd"] is None
    assert status["month_spend_usd"] == 0.0
    assert status["remaining_usd"] is None


def test_admission_refuses_when_the_budget_is_exhausted(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    set_budget(client, alice, 0.0)

    refused = client.post(
        "/v1/runs",
        headers=alice.auth,
        json={"dataset_version_id": version_id, "question": "What is the total amount?"},
    )
    assert refused.status_code == 409
    assert refused.json()["type"].endswith("budget-exhausted")

    # Raising the limit lets the same request through.
    set_budget(client, alice, 5.0)
    accepted = client.post(
        "/v1/runs",
        headers=alice.auth,
        json={"dataset_version_id": version_id, "question": "What is the total amount?"},
    )
    assert accepted.status_code == 202, accepted.text


def test_run_reserves_then_settles_actual_cost(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any], engine: sa.Engine
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    set_budget(client, alice, 5.0)
    run_id = create_run(client, alice, version_id, "What is the total amount?")

    with engine.begin() as conn:
        kinds = {
            r.kind
            for r in conn.execute(
                sa.text("SELECT kind FROM budget_entries WHERE run_id = :rid"), {"rid": run_id}
            )
        }
    assert kinds == {"reserve"}

    ctx = _ctx(worker_ctx, lambda req: exec_result(value=35.75, columns_used=["amount"]))
    assert asyncio.run(execute_run(ctx, run_id)) == {"result": "answered"}

    with engine.begin() as conn:
        rows = conn.execute(
            sa.text("SELECT kind, amount_usd FROM budget_entries WHERE run_id = :rid"),
            {"rid": run_id},
        ).all()
    by_kind = {r.kind: float(r.amount_usd) for r in rows}
    assert set(by_kind) == {"reserve", "settle", "release"}
    assert by_kind["release"] == -by_kind["reserve"]  # the reserve is fully reversed
    assert by_kind["settle"] >= 0.0  # actual model cost (registry-priced fakes)

    # Settlement is idempotent under job re-delivery.
    assert asyncio.run(execute_run(ctx, run_id)) == {"result": "already_terminal"}
    with engine.begin() as conn:
        count = conn.execute(
            sa.text("SELECT count(*) FROM budget_entries WHERE run_id = :rid"), {"rid": run_id}
        ).scalar()
    assert count == 3

    status = client.get("/v1/budget", headers=alice.auth).json()
    assert status["month_spend_usd"] == pytest.approx(by_kind["settle"], abs=1e-6)


def test_only_org_managers_can_set_the_budget(
    client: TestClient, alice: Tenant, engine: sa.Engine
) -> None:
    from tests.integration.test_observability_review import add_reviewer_key

    reviewer = add_reviewer_key(engine, alice)
    denied = client.put("/v1/budget", headers=reviewer.auth, json={"monthly_limit_usd": 1.0})
    assert denied.status_code == 403


def test_budget_is_tenant_scoped(client: TestClient, alice: Tenant, bob: Tenant) -> None:
    set_budget(client, alice, 3.0)
    assert client.get("/v1/budget", headers=bob.auth).json()["monthly_limit_usd"] is None


# ---------------------------------------------------------------- exact cache


def test_cache_stores_then_replays_and_reports_stats(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    cache = SqlAnswerCache(worker_ctx["session_factory"])

    first = create_run(client, alice, version_id, "What is the total amount?")
    ctx = {
        **_ctx(worker_ctx, lambda req: exec_result(value=35.75, columns_used=["amount"])),
        "cache": cache,
    }
    assert asyncio.run(execute_run(ctx, first)) == {"result": "answered"}

    # Same question, same dataset content, same config: replayed, marked cached.
    second = create_run(client, alice, version_id, "What is the total amount?")
    assert asyncio.run(execute_run(ctx, second)) == {"result": "answered"}
    replayed = client.get(f"/v1/runs/{second}", headers=alice.auth).json()
    assert replayed["answer"]["cached"] is True
    assert replayed["answer"]["value"] == 35.75

    stats = client.get("/v1/metrics/cache", headers=alice.auth).json()
    assert stats["hits"] == 1 and stats["stores"] == 1 and stats["misses"] == 1
    assert stats["false_hits"] == 0


def test_cache_cannot_cross_tenants_even_with_identical_content(
    client: TestClient, alice: Tenant, bob: Tenant, worker_ctx: dict[str, Any]
) -> None:
    """Alice and Bob upload byte-identical datasets and ask the same question.
    Bob's run must compute fresh — the SQL lookup is org-scoped and the key
    binds the tenant."""
    cache = SqlAnswerCache(worker_ctx["session_factory"])
    handler = lambda req: exec_result(value=35.75, columns_used=["amount"])  # noqa: E731

    a_version = ready_version(client, alice, worker_ctx)
    a_run = create_run(client, alice, a_version, "What is the total amount?")
    assert (
        asyncio.run(execute_run({**_ctx(worker_ctx, handler), "cache": cache}, a_run))["result"]
        == "answered"
    )

    b_version = ready_version(client, bob, worker_ctx)
    b_run = create_run(client, bob, b_version, "What is the total amount?")
    assert (
        asyncio.run(execute_run({**_ctx(worker_ctx, handler), "cache": cache}, b_run))["result"]
        == "answered"
    )

    bob_stats = client.get("/v1/metrics/cache", headers=bob.auth).json()
    assert bob_stats["hits"] == 0  # computed fresh, never replayed across orgs
    assert bob_stats["misses"] == 1

    bob_answer = client.get(f"/v1/runs/{b_run}", headers=bob.auth).json()["answer"]
    assert bob_answer["cached"] is False


def test_sql_cache_lookup_is_org_scoped_even_with_a_stolen_key(
    worker_ctx: dict[str, Any], alice: Tenant, bob: Tenant, client: TestClient
) -> None:
    """Defense in depth: even if another tenant somehow obtained a raw cache
    key, the SQL lookup filters by organization and returns nothing."""

    async def scenario() -> None:
        factory = worker_ctx["session_factory"]
        async with factory() as session:
            store = SqlCacheStore(session)
            await store.store(
                organization_id=alice.organization_id,
                cache_key="k" * 64,
                dataset_version_id=uuid.uuid4(),
                dataset_sha256="sha",
                question_sha256="qsha",
                config_signature="cfg",
                answer={"value": 1},
                verification=None,
            )
            await session.commit()
            stolen = await store.lookup(organization_id=bob.organization_id, cache_key="k" * 64)
            assert stolen is None
            own = await store.lookup(organization_id=alice.organization_id, cache_key="k" * 64)
            assert own is not None

    asyncio.run(scenario())
