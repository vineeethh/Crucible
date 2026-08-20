"""Phase 4 acceptance against the live stack: a run flows through the durable
agent, persists an answer with provenance (or abstains, or waits for review),
and the API surfaces it. Resume-after-restart is exercised against real Postgres.

The executor is a scripted FakeExecutor here (no Docker) so these run in the
default integration lane; real code execution is covered by the sandbox suite.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from crucible.agent import Node, run_agent
from crucible.execution import ExecutionLimits, ExitClass, FakeExecutor
from crucible_worker.agent_runtime import SqlAgentPersistence
from crucible_worker.jobs.runs import execute_run, resolve_run_review
from tests.integration.test_data_plane import ready_version
from tests.support.agent_fakes import exec_result
from tests.support.stack import Tenant, requires_stack

pytestmark = [pytest.mark.integration, requires_stack]


def _ctx(worker_ctx: dict[str, Any], handler: Any) -> dict[str, Any]:
    """Build the arq-style context the agent jobs expect, with a scripted
    executor injected in place of the real sandbox."""
    from crucible.agent import FakeModel

    return {
        "session_factory": worker_ctx["session_factory"],
        "storage": worker_ctx["storage"],
        "model": FakeModel(),
        "executor": FakeExecutor(handler=handler),
        "limits": ExecutionLimits(),
    }


def create_run(client: TestClient, tenant: Tenant, version_id: str, question: str) -> str:
    resp = client.post(
        "/v1/runs",
        headers=tenant.auth,
        json={"dataset_version_id": version_id, "question": question},
    )
    assert resp.status_code == 202, resp.text
    return str(resp.json()["id"])


def test_agent_answers_and_api_surfaces_provenance(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    run_id = create_run(client, alice, version_id, "What is the total amount?")

    ctx = _ctx(worker_ctx, lambda req: exec_result(value=35.75, columns_used=["amount"]))
    outcome = asyncio.run(execute_run(ctx, run_id))
    assert outcome == {"result": "answered"}

    run = client.get(f"/v1/runs/{run_id}", headers=alice.auth).json()
    assert run["status"] == "answered"
    assert run["answer"]["value"] == 35.75
    assert run["answer"]["provenance"]["operation"] == "sum"
    assert run["answer"]["provenance"]["columns_used"] == ["amount"]
    assert run["verification"]["decision"] == "answer"

    attempts = client.get(f"/v1/runs/{run_id}/attempts", headers=alice.auth).json()
    assert [a["kind"] for a in attempts] == ["route", "plan", "code", "execute", "verify"]

    events = client.get(f"/v1/runs/{run_id}/events", headers=alice.auth).json()
    nodes = [e["payload"].get("node") for e in events if "node" in e["payload"]]
    assert "synthesize" in nodes and "verify" in nodes


def test_agent_abstains_on_unsupported_question(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    run_id = create_run(client, alice, version_id, "Write me a poem about the data.")

    ctx = _ctx(worker_ctx, lambda req: exec_result(value=1))
    assert asyncio.run(execute_run(ctx, run_id)) == {"result": "abstained"}

    run = client.get(f"/v1/runs/{run_id}", headers=alice.auth).json()
    assert run["status"] == "abstained"
    assert run["answer"] is None


def test_review_flow_via_api(client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    run_id = create_run(client, alice, version_id, "Which region had the highest amount?")

    ctx = _ctx(
        worker_ctx, lambda req: exec_result(value="north", columns_used=["region"], ambiguous=True)
    )
    assert asyncio.run(execute_run(ctx, run_id)) == {"result": "interrupted"}

    run = client.get(f"/v1/runs/{run_id}", headers=alice.auth).json()
    assert run["status"] == "waiting_review"
    assert run["answer"] is None

    # A reviewer approves through the API; the worker job resumes the graph.
    resp = client.post(f"/v1/runs/{run_id}/review", headers=alice.auth, json={"approve": True})
    assert resp.status_code == 200
    assert asyncio.run(resolve_run_review(ctx, run_id, True)) == {"result": "answered"}

    run = client.get(f"/v1/runs/{run_id}", headers=alice.auth).json()
    assert run["status"] == "answered"
    assert run["answer"]["value"] == "north"


def test_review_cannot_be_submitted_for_a_non_review_run(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    run_id = create_run(client, alice, version_id, "What is the total amount?")
    resp = client.post(f"/v1/runs/{run_id}/review", headers=alice.auth, json={"approve": True})
    assert resp.status_code == 409
    assert resp.json()["type"].endswith("run-not-in-review")


def test_resume_after_worker_restart_against_postgres(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    run_id = create_run(client, alice, version_id, "What is the total amount?")

    from crucible.agent import FakeModel

    persistence = SqlAgentPersistence(worker_ctx["session_factory"], worker_ctx["storage"])
    handler = lambda req: exec_result(value=35.75, columns_used=["amount"])  # noqa: E731

    # Simulate a crash after the CODE node: the run is left RUNNING with a
    # checkpoint in Postgres.
    first = asyncio.run(
        run_agent(
            persistence,
            model=FakeModel(),
            executor=FakeExecutor(handler=handler),
            limits=ExecutionLimits(),
            run_id=run_id,
            stop_after=Node.CODE,
        )
    )
    assert first == "interrupted"
    assert client.get(f"/v1/runs/{run_id}", headers=alice.auth).json()["status"] == "running"

    # A fresh worker picks the run back up and resumes from the checkpoint.
    second = asyncio.run(
        run_agent(
            persistence,
            model=FakeModel(),
            executor=FakeExecutor(handler=handler),
            limits=ExecutionLimits(),
            run_id=run_id,
        )
    )
    assert second == "answered"
    run = client.get(f"/v1/runs/{run_id}", headers=alice.auth).json()
    assert run["status"] == "answered"
    assert run["answer"]["value"] == 35.75


def test_bob_cannot_see_alices_run_attempts(
    client: TestClient, alice: Tenant, bob: Tenant, worker_ctx: dict[str, Any]
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    run_id = create_run(client, alice, version_id, "What is the total amount?")
    ctx = _ctx(worker_ctx, lambda req: exec_result(value=1.0, columns_used=["amount"]))
    asyncio.run(execute_run(ctx, run_id))

    assert client.get(f"/v1/runs/{run_id}/attempts", headers=bob.auth).status_code == 404
    assert client.get(f"/v1/runs/{run_id}", headers=bob.auth).status_code == 404


def test_non_repairable_failure_abstains(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    run_id = create_run(client, alice, version_id, "What is the total amount?")
    ctx = _ctx(worker_ctx, lambda req: exec_result(exit_class=ExitClass.POLICY_VIOLATION))
    assert asyncio.run(execute_run(ctx, run_id)) == {"result": "abstained"}
    run = client.get(f"/v1/runs/{run_id}", headers=alice.auth).json()
    assert run["status"] == "abstained"
