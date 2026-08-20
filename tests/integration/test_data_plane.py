"""Phase 2 acceptance: upload -> immutable version -> profile -> durable run.

Exercises the real API against the real Postgres/Redis/MinIO stack, and drives
the worker jobs directly (arq delivery itself is covered by the compose smoke).
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from crucible_worker.jobs.datasets import profile_dataset_version
from crucible_worker.jobs.runs import execute_run
from tests.support.stack import Tenant, requires_stack

pytestmark = [pytest.mark.integration, requires_stack]

CSV = (
    b"region,amount,ordered_at\n"
    b"north,10.5,2024-01-01\n"
    b"south,20.0,2024-02-01\n"
    b"north,5.25,2024-03-01\n"
)
CSV_SHA = hashlib.sha256(CSV).hexdigest()


def upload_csv(
    client: TestClient,
    tenant: Tenant,
    *,
    data: bytes = CSV,
    name: str = "sales",
    filename: str = "sales.csv",
) -> dict[str, Any]:
    started = client.post(
        "/v1/datasets/uploads",
        headers=tenant.auth,
        json={
            "dataset_name": name,
            "filename": filename,
            "content_type": "text/csv",
            "size_bytes": len(data),
        },
    )
    assert started.status_code == 201, started.text
    body = started.json()

    # The client PUTs straight to object storage: the bytes never touch the API.
    put = httpx.put(
        body["upload_url"], content=data, headers={"Content-Type": "text/csv"}, timeout=30
    )
    assert put.status_code in (200, 204), put.text

    completed = client.post(
        f"/v1/datasets/versions/{body['version_id']}/complete",
        headers=tenant.auth,
        json={"content_sha256": hashlib.sha256(data).hexdigest()},
    )
    assert completed.status_code == 200, completed.text
    return {**body, "version": completed.json()}


def ready_version(
    client: TestClient, tenant: Tenant, worker_ctx: dict[str, Any], **kwargs: Any
) -> str:
    result = upload_csv(client, tenant, **kwargs)
    version_id = result["version_id"]
    outcome = asyncio.run(profile_dataset_version(worker_ctx, version_id))
    assert outcome["result"] == "ready", outcome
    return str(version_id)


# ------------------------------------------------------------------ happy path


def test_upload_profile_run_lifecycle(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    version_id = ready_version(client, alice, worker_ctx)

    version = client.get(f"/v1/datasets/versions/{version_id}", headers=alice.auth).json()
    assert version["status"] == "ready"
    assert version["content_sha256"] == CSV_SHA
    assert version["row_count"] == 3
    assert version["column_count"] == 3
    assert version["schema_hash"]
    assert "object_key" not in version  # storage layout is never exposed

    created = client.post(
        "/v1/runs",
        headers=alice.auth,
        json={"dataset_version_id": version_id, "question": "What is the total amount?"},
    )
    assert created.status_code == 202, created.text
    run = created.json()
    assert run["status"] == "queued"
    assert run["config_manifest"]["dataset_content_sha256"] == CSV_SHA
    assert created.headers["Location"] == f"/v1/runs/{run['id']}"

    # The worker runs the agent. The default worker_ctx executor returns no
    # value, so the run abstains rather than fabricating an answer (a real answer
    # requires the Docker/microVM executor; see the sandbox and agent suites).
    outcome = asyncio.run(execute_run(worker_ctx, run["id"]))
    assert outcome["result"] == "abstained"

    final = client.get(f"/v1/runs/{run['id']}", headers=alice.auth).json()
    assert final["status"] == "abstained"
    assert final["answer"] is None

    events = client.get(f"/v1/runs/{run['id']}/events", headers=alice.auth).json()
    types = [e["event_type"] for e in events]
    assert types[0] == "created" and types[1] == "claimed" and types[-1] == "terminal"


def test_identical_content_reuses_the_same_version(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    """Content is identity: the same bytes cannot become two versions."""
    first = ready_version(client, alice, worker_ctx)
    second = upload_csv(client, alice)["version"]
    assert second["id"] == first
    assert second["status"] == "ready"


def test_different_content_creates_a_new_version(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    v1 = ready_version(client, alice, worker_ctx)
    other = CSV + b"east,1.0,2024-04-01\n"
    v2 = ready_version(client, alice, worker_ctx, data=other)
    assert v1 != v2

    dataset_id = client.get("/v1/datasets", headers=alice.auth).json()[0]["id"]
    versions = client.get(f"/v1/datasets/{dataset_id}/versions", headers=alice.auth).json()
    assert [v["version_no"] for v in versions] == [2, 1]


# --------------------------------------------------------------- ingest policy


def test_declared_hash_must_match_the_uploaded_bytes(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    """A client that lies about its digest gets an invalid version, not a
    silently accepted one."""
    started = client.post(
        "/v1/datasets/uploads",
        headers=alice.auth,
        json={
            "dataset_name": "liar",
            "filename": "x.csv",
            "content_type": "text/csv",
            "size_bytes": len(CSV),
        },
    ).json()
    httpx.put(started["upload_url"], content=CSV, headers={"Content-Type": "text/csv"}, timeout=30)
    client.post(
        f"/v1/datasets/versions/{started['version_id']}/complete",
        headers=alice.auth,
        json={"content_sha256": "0" * 64},
    )

    outcome = asyncio.run(profile_dataset_version(worker_ctx, started["version_id"]))
    assert outcome == {"result": "invalid", "reason": "content_hash_mismatch"}

    version = client.get(
        f"/v1/datasets/versions/{started['version_id']}", headers=alice.auth
    ).json()
    assert version["status"] == "invalid"
    assert version["invalid_reason"] == "content_hash_mismatch"


def test_unparseable_upload_becomes_invalid_not_ready(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    result = upload_csv(client, alice, data=b"\x00\x01\x02\x03garbage", name="broken")
    outcome = asyncio.run(profile_dataset_version(worker_ctx, result["version_id"]))
    assert outcome["result"] == "invalid"

    version = client.get(f"/v1/datasets/versions/{result['version_id']}", headers=alice.auth).json()
    assert version["status"] == "invalid"


def test_run_requires_a_ready_version(client: TestClient, alice: Tenant) -> None:
    """A version that has not been profiled cannot back a run."""
    started = client.post(
        "/v1/datasets/uploads",
        headers=alice.auth,
        json={
            "dataset_name": "pending",
            "filename": "x.csv",
            "content_type": "text/csv",
            "size_bytes": 10,
        },
    ).json()
    response = client.post(
        "/v1/runs",
        headers=alice.auth,
        json={"dataset_version_id": started["version_id"], "question": "anything?"},
    )
    assert response.status_code == 409
    assert response.json()["type"].endswith("dataset-not-ready")


@pytest.mark.parametrize(
    ("content_type", "filename", "expected"),
    [
        ("application/zip", "payload.zip", 422),  # rejected by the schema enum
        ("text/csv", "payload.zip", 415),  # extension policy
    ],
)
def test_disallowed_uploads_are_refused(
    client: TestClient, alice: Tenant, content_type: str, filename: str, expected: int
) -> None:
    response = client.post(
        "/v1/datasets/uploads",
        headers=alice.auth,
        json={
            "dataset_name": "bad",
            "filename": filename,
            "content_type": content_type,
            "size_bytes": 100,
        },
    )
    assert response.status_code == expected


def test_oversize_upload_is_refused_before_any_bytes_move(
    client: TestClient, alice: Tenant
) -> None:
    response = client.post(
        "/v1/datasets/uploads",
        headers=alice.auth,
        json={
            "dataset_name": "huge",
            "filename": "huge.csv",
            "content_type": "text/csv",
            "size_bytes": 500 * 1024 * 1024,
        },
    )
    assert response.status_code == 422  # schema bound; policy also enforces 413


# ------------------------------------------------------------------ idempotency


def test_idempotency_key_replays_the_same_run(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    body = {"dataset_version_id": version_id, "question": "How many rows?"}
    headers = {**alice.auth, "Idempotency-Key": "key-123"}

    first = client.post("/v1/runs", headers=headers, json=body)
    second = client.post("/v1/runs", headers=headers, json=body)

    assert first.status_code == 202
    assert second.status_code == 200  # replay, not a new run
    assert first.json()["id"] == second.json()["id"]


def test_idempotency_key_reuse_with_a_different_body_is_rejected(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    headers = {**alice.auth, "Idempotency-Key": "key-456"}

    client.post(
        "/v1/runs",
        headers=headers,
        json={"dataset_version_id": version_id, "question": "How many rows?"},
    )
    conflict = client.post(
        "/v1/runs",
        headers=headers,
        json={"dataset_version_id": version_id, "question": "A different question?"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["type"].endswith("idempotency-key-reuse")


# ----------------------------------------------------------------- cancellation


def test_queued_run_cancels_synchronously(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    run = client.post(
        "/v1/runs",
        headers=alice.auth,
        json={"dataset_version_id": version_id, "question": "q?"},
    ).json()

    cancelled = client.post(f"/v1/runs/{run['id']}/cancel", headers=alice.auth)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    # A worker that later picks up the job must not resurrect a cancelled run.
    outcome = asyncio.run(execute_run(worker_ctx, run["id"]))
    assert outcome["result"] == "already_terminal"
    assert client.get(f"/v1/runs/{run['id']}", headers=alice.auth).json()["status"] == "cancelled"


def test_terminal_run_cannot_be_cancelled(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    run = client.post(
        "/v1/runs",
        headers=alice.auth,
        json={"dataset_version_id": version_id, "question": "q?"},
    ).json()
    asyncio.run(execute_run(worker_ctx, run["id"]))

    response = client.post(f"/v1/runs/{run['id']}/cancel", headers=alice.auth)
    assert response.status_code == 409
    assert response.json()["type"].endswith("run-terminal")


def test_job_redelivery_is_safe(
    client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]
) -> None:
    """At-least-once delivery: running the job twice must not double-terminate
    or append duplicate terminal events."""
    version_id = ready_version(client, alice, worker_ctx)
    run = client.post(
        "/v1/runs",
        headers=alice.auth,
        json={"dataset_version_id": version_id, "question": "q?"},
    ).json()

    assert asyncio.run(execute_run(worker_ctx, run["id"]))["result"] == "abstained"
    # Re-delivery after a terminal run is a no-op, not a second termination.
    assert asyncio.run(execute_run(worker_ctx, run["id"]))["result"] == "already_terminal"

    events = client.get(f"/v1/runs/{run['id']}/events", headers=alice.auth).json()
    assert sum(1 for e in events if e["event_type"] == "terminal") == 1


# ------------------------------------------------------------------- audit log


def test_sensitive_actions_are_audited(
    client: TestClient,
    alice: Tenant,
    worker_ctx: dict[str, Any],
    engine: sa.Engine,
) -> None:
    version_id = ready_version(client, alice, worker_ctx)
    run = client.post(
        "/v1/runs",
        headers=alice.auth,
        json={"dataset_version_id": version_id, "question": "q?"},
    ).json()
    client.post(f"/v1/runs/{run['id']}/cancel", headers=alice.auth)
    client.post(f"/v1/datasets/versions/{version_id}/download-url", headers=alice.auth)

    with engine.begin() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT action, result, target_id FROM audit_events "
                "WHERE organization_id = :org ORDER BY created_at"
            ),
            {"org": alice.organization_id},
        ).all()

    actions = [r.action for r in rows]
    assert "dataset.created" in actions
    assert "dataset.upload_started" in actions
    assert "dataset.version_completed" in actions
    assert "run.created" in actions
    assert "run.cancelled" in actions
    assert "dataset.downloaded" in actions  # every download URL issuance is evidence
    assert all(r.result == "allowed" for r in rows)
