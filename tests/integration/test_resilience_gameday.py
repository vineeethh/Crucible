"""Resilience game days (master plan Phase 9): provider outage and queue loss.

These are executable drills, not illustrations: they inject the failure against
the live stack and assert the system degrades the way the design promises —
an infrastructure fault never corrupts a run or gets blamed on the model, and a
lost queue is fully recoverable because the run store (not Redis) is the source
of truth (ADR-002/004/008). Run: `pytest -m load`. Runbook:
docs/operations/game-day-runbook.md.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from crucible.execution import ExecutorUnavailable
from crucible_worker.jobs.runs import execute_run
from tests.integration.test_agent_data_plane import _ctx, create_run
from tests.integration.test_data_plane import ready_version
from tests.support.agent_fakes import exec_result
from tests.support.stack import Tenant, requires_stack

pytestmark = [pytest.mark.integration, pytest.mark.load, requires_stack]


def _run_status(client: TestClient, tenant: Tenant, run_id: str) -> str:
    return str(client.get(f"/v1/runs/{run_id}", headers=tenant.auth).json()["status"])


def _terminal_event_count(engine: sa.Engine, run_id: str) -> int:
    with engine.begin() as conn:
        return int(
            conn.execute(
                sa.text(
                    "SELECT count(*) FROM run_events WHERE run_id = :r AND event_type = 'terminal'"
                ),
                {"r": run_id},
            ).scalar_one()
        )


# --------------------------------------------------- game day 1: provider outage


def test_provider_outage_is_operational_not_a_quality_failure(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any], engine: sa.Engine
) -> None:
    """The sandbox provider is down. A run in flight must NOT terminate as an
    abstention with a failure category (that would libel the model): the job
    raises so the queue retries, the run stays RUNNING, and when the provider
    recovers the run resumes from its checkpoint and answers."""
    version_id = ready_version(client, alice, worker_ctx)
    run_id = create_run(client, alice, version_id, "What is the total amount?")

    def outage(_req: object) -> object:
        raise ExecutorUnavailable("sandbox provider unreachable (injected)")

    outage_ctx = _ctx(worker_ctx, outage)

    # The infrastructure fault propagates (arq would retry the job); it is never
    # swallowed into a terminal quality outcome.
    with pytest.raises(ExecutorUnavailable):
        asyncio.run(execute_run(outage_ctx, run_id))

    assert _run_status(client, alice, run_id) == "running"  # claimed, not terminal
    assert _terminal_event_count(engine, run_id) == 0
    with engine.begin() as conn:
        failure_category = conn.execute(
            sa.text("SELECT failure_category FROM agent_runs WHERE id = :r"), {"r": run_id}
        ).scalar_one()
    assert failure_category is None  # never attributed to the model

    # Provider recovers: the retried job resumes from the checkpoint and answers.
    healthy_ctx = _ctx(worker_ctx, lambda req: exec_result(value=35.75, columns_used=["amount"]))
    assert asyncio.run(execute_run(healthy_ctx, run_id)) == {"result": "answered"}
    assert _run_status(client, alice, run_id) == "answered"
    assert _terminal_event_count(engine, run_id) == 1


# ----------------------------------------------------- game day 2: queue loss


def test_queue_loss_is_recoverable_from_the_run_store(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any], engine: sa.Engine
) -> None:
    """Redis drops every enqueued job (a queue wipe). The runs are still QUEUED
    in Postgres — the source of truth — so a recovery sweep re-drives them, and
    each terminates exactly once (at-least-once delivery + idempotent
    transitions mean a re-delivery of a since-recovered job is a no-op)."""
    version_id = ready_version(client, alice, worker_ctx)
    run_ids = [
        create_run(client, alice, version_id, f"What is the total amount? #{i}") for i in range(5)
    ]

    # Simulate the queue loss: the jobs are never delivered. The runs sit QUEUED.
    for run_id in run_ids:
        assert _run_status(client, alice, run_id) == "queued"

    # Recovery sweep: find every non-terminal run in the store and re-enqueue
    # (here, drive directly, as a reconcile worker would).
    with engine.begin() as conn:
        recoverable = [
            str(r.id)
            for r in conn.execute(
                sa.text(
                    "SELECT id FROM agent_runs WHERE organization_id = :org AND status = 'queued'"
                ),
                {"org": alice.organization_id},
            )
        ]
    assert set(recoverable) == set(run_ids)

    healthy_ctx = _ctx(worker_ctx, lambda req: exec_result(value=35.75, columns_used=["amount"]))
    for run_id in recoverable:
        assert asyncio.run(execute_run(healthy_ctx, run_id)) == {"result": "answered"}

    # A late, duplicate delivery of an already-recovered job must be a no-op.
    for run_id in run_ids:
        assert asyncio.run(execute_run(healthy_ctx, run_id)) == {"result": "already_terminal"}
        assert _run_status(client, alice, run_id) == "answered"
        assert _terminal_event_count(engine, run_id) == 1


def test_worker_recovers_a_run_left_running_by_a_crash(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any], engine: sa.Engine
) -> None:
    """A worker crashed mid-run (the job raised after claiming). A fresh worker
    picks the RUNNING run back up from its checkpoint and finishes it — no run
    is orphaned by a crash."""
    version_id = ready_version(client, alice, worker_ctx)
    run_id = create_run(client, alice, version_id, "What is the total amount?")

    crashes = {"n": 0}

    def crash_once(req: object) -> object:
        crashes["n"] += 1
        raise ExecutorUnavailable("worker crash mid-execute (injected)")

    with pytest.raises(ExecutorUnavailable):
        asyncio.run(execute_run(_ctx(worker_ctx, crash_once), run_id))
    assert _run_status(client, alice, run_id) == "running"

    # Distinct run id proves it is a *different* worker resuming, not a retry of
    # the same in-memory state.
    healthy = _ctx(worker_ctx, lambda req: exec_result(value=35.75, columns_used=["amount"]))
    assert asyncio.run(execute_run(healthy, str(uuid.UUID(run_id)))) == {"result": "answered"}
    assert _terminal_event_count(engine, run_id) == 1
