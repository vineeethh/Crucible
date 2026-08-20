"""Phase 6 acceptance against the live stack: human review is safe under
concurrency, observability metrics/trace surface a terminal run's evidence, and
the online sampler records deterministic scores per tenant.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from crucible.security import generate_api_key
from crucible_worker.jobs.online import run_online_checks
from crucible_worker.jobs.runs import execute_run, resolve_run_review
from tests.integration.test_agent_data_plane import _ctx, create_run
from tests.integration.test_data_plane import ready_version
from tests.support.agent_fakes import exec_result
from tests.support.stack import Tenant, requires_stack

pytestmark = [pytest.mark.integration, requires_stack]


def add_reviewer_key(engine: sa.Engine, tenant: Tenant) -> Tenant:
    """A second API key in the *same* organization — a distinct reviewer actor."""
    from crucible.domain import Role, new_id

    key = generate_api_key()
    with engine.begin() as conn:
        user_id = conn.execute(
            sa.text("SELECT user_id FROM memberships WHERE organization_id = :org LIMIT 1"),
            {"org": tenant.organization_id},
        ).scalar_one()
        conn.execute(
            sa.text(
                "INSERT INTO api_keys "
                "(id, organization_id, created_by_user_id, name, prefix, secret_hash, role) "
                "VALUES (:id, :org, :user, :name, :prefix, :hash, :role)"
            ),
            {
                "id": new_id(),
                "org": tenant.organization_id,
                "user": user_id,
                "name": "reviewer-2",
                "prefix": key.prefix,
                "hash": key.secret_hash,
                "role": Role.REVIEWER.value,
            },
        )
    return Tenant(organization_id=tenant.organization_id, token=key.token, role=Role.REVIEWER)


def run_awaiting_review(client: TestClient, tenant: Tenant, worker_ctx: dict[str, Any]) -> str:
    version_id = ready_version(client, tenant, worker_ctx)
    run_id = create_run(client, tenant, version_id, "Which region had the highest amount?")
    ctx = _ctx(
        worker_ctx,
        lambda req: exec_result(value="north", columns_used=["region"], ambiguous=True),
    )
    assert asyncio.run(execute_run(ctx, run_id)) == {"result": "interrupted"}
    assert (
        client.get(f"/v1/runs/{run_id}", headers=tenant.auth).json()["status"] == "waiting_review"
    )
    return run_id


# --------------------------------------------------------------- review queue


def test_queue_lists_runs_awaiting_review(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    run_id = run_awaiting_review(client, alice, worker_ctx)
    queue = client.get("/v1/reviews", headers=alice.auth).json()
    assert any(item["run_id"] == run_id for item in queue)


def test_only_one_reviewer_can_claim_a_run(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any], engine: sa.Engine
) -> None:
    """Two reviewers in the same org race to claim; exactly one wins, the other
    gets a 409 conflict rather than a silently shared claim."""
    reviewer2 = add_reviewer_key(engine, alice)
    run_id = run_awaiting_review(client, alice, worker_ctx)

    first = client.post(f"/v1/reviews/{run_id}/claim", headers=alice.auth)
    second = client.post(f"/v1/reviews/{run_id}/claim", headers=reviewer2.auth)

    assert first.status_code == 200, first.text
    assert second.status_code == 409
    assert second.json()["type"].endswith("review-claimed")


def test_non_claimant_cannot_submit(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any], engine: sa.Engine
) -> None:
    reviewer2 = add_reviewer_key(engine, alice)
    run_id = run_awaiting_review(client, alice, worker_ctx)
    assert client.post(f"/v1/reviews/{run_id}/claim", headers=alice.auth).status_code == 200

    body = {
        "decision": "approve",
        "grades": {"groundedness": 2, "provenance": 2, "usefulness": 2, "uncertainty": 2},
    }
    stolen = client.post(f"/v1/reviews/{run_id}/submit", headers=reviewer2.auth, json=body)
    assert stolen.status_code == 409
    assert stolen.json()["type"].endswith("review-not-claimed")


def test_claim_submit_records_scores_and_resolves_run(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any], engine: sa.Engine
) -> None:
    run_id = run_awaiting_review(client, alice, worker_ctx)
    assert client.post(f"/v1/reviews/{run_id}/claim", headers=alice.auth).status_code == 200

    body = {
        "decision": "approve",
        "grades": {"groundedness": 2, "provenance": 2, "usefulness": 1, "uncertainty": 2},
    }
    submitted = client.post(f"/v1/reviews/{run_id}/submit", headers=alice.auth, json=body)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["decision"] == "approve"

    # The rubric grades are persisted as typed human scores (never a gate).
    with engine.begin() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT definition_key, source, value_categorical FROM scores "
                "WHERE target_id = :rid ORDER BY definition_key"
            ),
            {"rid": run_id},
        ).all()
    keys = {r.definition_key for r in rows}
    assert keys == {
        "rubric.groundedness",
        "rubric.provenance",
        "rubric.usefulness",
        "rubric.uncertainty",
    }
    assert all(r.source == "human" for r in rows)

    # The worker resumes the graph: approve -> answered.
    ctx = _ctx(
        worker_ctx,
        lambda req: exec_result(value="north", columns_used=["region"], ambiguous=True),
    )

    assert asyncio.run(resolve_run_review(ctx, run_id, True)) == {"result": "answered"}
    assert client.get(f"/v1/runs/{run_id}", headers=alice.auth).json()["status"] == "answered"


# ------------------------------------------------------- metrics & trace


def test_metrics_and_trace_surface_a_terminal_run(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    run_id = create_run(client, alice, version_id, "What is the total amount?")
    ctx = _ctx(worker_ctx, lambda req: exec_result(value=35.75, columns_used=["amount"]))
    from crucible_worker.jobs.runs import execute_run

    assert asyncio.run(execute_run(ctx, run_id)) == {"result": "answered"}

    reliability = client.get("/v1/metrics/reliability", headers=alice.auth).json()
    assert reliability["terminal"] >= 1
    assert reliability["answered"] >= 1
    assert 0.0 <= reliability["trace_completeness"] <= 1.0

    cost = client.get("/v1/metrics/cost", headers=alice.auth).json()
    assert "latency_p95_ms" in cost

    alerts = client.get("/v1/metrics/alerts", headers=alice.auth).json()
    by_rule = {a["rule_id"]: a for a in alerts}
    # Containment is always reported (and healthy here); every alert names a runbook.
    assert by_rule["sandbox_containment"]["firing"] is False
    assert all(a["runbook"] for a in alerts)

    trace = client.get(f"/v1/runs/{run_id}/trace", headers=alice.auth).json()
    assert trace["run_id"] == run_id
    assert trace["redaction_state"] == "redacted"
    assert isinstance(trace["complete"], bool)
    assert trace["model_ids"]  # a run that reached the model records its version
    # The tenant is pseudonymized; the raw org id never appears in the export.
    assert str(alice.organization_id) not in str(trace)
    assert trace["question"]["sha256"]
    assert trace["question"]["truncated"] is False  # short question fits the excerpt bound


def test_trace_is_tenant_isolated(
    client: TestClient, alice: Tenant, bob: Tenant, worker_ctx: dict[str, Any]
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    run_id = create_run(client, alice, version_id, "What is the total amount?")
    ctx = _ctx(worker_ctx, lambda req: exec_result(value=1.0, columns_used=["amount"]))
    from crucible_worker.jobs.runs import execute_run

    asyncio.run(execute_run(ctx, run_id))
    assert client.get(f"/v1/runs/{run_id}/trace", headers=bob.auth).status_code == 404


# --------------------------------------------------------------- online eval


def test_online_sampler_records_deterministic_scores(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any], engine: sa.Engine
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    run_id = create_run(client, alice, version_id, "What is the total amount?")
    ctx = _ctx(worker_ctx, lambda req: exec_result(value=35.75, columns_used=["amount"]))
    from crucible_worker.jobs.runs import execute_run

    asyncio.run(execute_run(ctx, run_id))

    summary = asyncio.run(run_online_checks(worker_ctx))
    assert summary["sampled"] >= 1

    with engine.begin() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT source, score_type FROM scores "
                "WHERE definition_key = 'online.trace_complete' AND target_id = :rid"
            ),
            {"rid": run_id},
        ).all()
    assert rows, "online sampler recorded no deterministic score for the terminal run"
    assert rows[0].source == "deterministic"
    assert rows[0].score_type == "boolean"
