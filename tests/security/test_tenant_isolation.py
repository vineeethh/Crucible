"""Tenant isolation and authentication (threat model T5, T6).

The Phase 2 acceptance criterion: *a different organization cannot access any
resource even by guessed ID*. Bob holds a valid, unexpired owner key — he is
authenticated, just not entitled. Every cross-tenant read must be indistinct
from "does not exist", so IDs cannot be probed for existence.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from crucible.domain import Role
from tests.integration.test_data_plane import ready_version
from tests.support.stack import Tenant, make_tenant, requires_stack

pytestmark = [pytest.mark.integration, requires_stack]


@pytest.fixture
def alice_version(client: TestClient, alice: Tenant, worker_ctx: dict[str, Any]) -> str:
    return ready_version(client, alice, worker_ctx)


@pytest.fixture
def alice_run(client: TestClient, alice: Tenant, alice_version: str) -> str:
    run = client.post(
        "/v1/runs",
        headers=alice.auth,
        json={"dataset_version_id": alice_version, "question": "How many rows?"},
    ).json()
    return str(run["id"])


# ----------------------------------------------------- cross-tenant reads (IDOR)


def test_bob_cannot_read_alices_dataset_version(
    client: TestClient, bob: Tenant, alice_version: str
) -> None:
    response = client.get(f"/v1/datasets/versions/{alice_version}", headers=bob.auth)
    assert response.status_code == 404  # not 403: existence is not confirmed


def test_bob_cannot_list_alices_datasets(
    client: TestClient, bob: Tenant, alice_version: str
) -> None:
    assert client.get("/v1/datasets", headers=bob.auth).json() == []


def test_bob_cannot_list_versions_of_alices_dataset(
    client: TestClient, alice: Tenant, bob: Tenant, alice_version: str
) -> None:
    dataset_id = client.get("/v1/datasets", headers=alice.auth).json()[0]["id"]
    response = client.get(f"/v1/datasets/{dataset_id}/versions", headers=bob.auth)
    assert response.status_code == 404


def test_bob_cannot_read_alices_run(client: TestClient, bob: Tenant, alice_run: str) -> None:
    assert client.get(f"/v1/runs/{alice_run}", headers=bob.auth).status_code == 404


def test_bob_cannot_read_alices_run_events(client: TestClient, bob: Tenant, alice_run: str) -> None:
    """Run events carry no organization column of their own — ownership is
    proven through the parent run before any event is read."""
    assert client.get(f"/v1/runs/{alice_run}/events", headers=bob.auth).status_code == 404


def test_bob_cannot_stream_alices_run(client: TestClient, bob: Tenant, alice_run: str) -> None:
    assert client.get(f"/v1/runs/{alice_run}/stream", headers=bob.auth).status_code == 404


def test_bobs_run_list_never_contains_alices_runs(
    client: TestClient, bob: Tenant, alice_run: str
) -> None:
    assert client.get("/v1/runs", headers=bob.auth).json() == []


# --------------------------------------------------- cross-tenant writes (IDOR)


def test_bob_cannot_cancel_alices_run(client: TestClient, bob: Tenant, alice_run: str) -> None:
    assert client.post(f"/v1/runs/{alice_run}/cancel", headers=bob.auth).status_code == 404


def test_bob_cannot_complete_alices_upload(client: TestClient, alice: Tenant, bob: Tenant) -> None:
    started = client.post(
        "/v1/datasets/uploads",
        headers=alice.auth,
        json={
            "dataset_name": "private",
            "filename": "x.csv",
            "content_type": "text/csv",
            "size_bytes": 100,
        },
    ).json()
    response = client.post(
        f"/v1/datasets/versions/{started['version_id']}/complete",
        headers=bob.auth,
        json={"content_sha256": "a" * 64},
    )
    assert response.status_code == 404


def test_bob_cannot_mint_a_download_url_for_alices_data(
    client: TestClient, bob: Tenant, alice_version: str
) -> None:
    """The sharpest exfiltration path: a presigned URL needs no further auth,
    so the entitlement check must happen before one is ever created."""
    response = client.post(f"/v1/datasets/versions/{alice_version}/download-url", headers=bob.auth)
    assert response.status_code == 404


def test_bob_cannot_start_a_run_on_alices_dataset(
    client: TestClient, bob: Tenant, alice_version: str
) -> None:
    response = client.post(
        "/v1/runs",
        headers=bob.auth,
        json={"dataset_version_id": alice_version, "question": "steal this"},
    )
    assert response.status_code == 404


def test_bob_cannot_revoke_alices_api_key(client: TestClient, alice: Tenant, bob: Tenant) -> None:
    key_id = client.get("/v1/api-keys", headers=alice.auth).json()[0]["id"]
    assert client.delete(f"/v1/api-keys/{key_id}", headers=bob.auth).status_code == 404


def test_bob_cannot_see_alices_api_keys(client: TestClient, alice: Tenant, bob: Tenant) -> None:
    prefixes = {k["prefix"] for k in client.get("/v1/api-keys", headers=bob.auth).json()}
    alice_prefixes = {k["prefix"] for k in client.get("/v1/api-keys", headers=alice.auth).json()}
    assert not (prefixes & alice_prefixes)


def test_organization_header_cannot_be_used_to_switch_tenants(
    client: TestClient, alice: Tenant, bob: Tenant, alice_version: str
) -> None:
    """An API key is bound to its organization; a header must not override it."""
    response = client.get(
        f"/v1/datasets/versions/{alice_version}",
        headers={**bob.auth, "X-Organization-Id": str(alice.organization_id)},
    )
    assert response.status_code == 404


def test_guessed_ids_do_not_leak_existence(client: TestClient, bob: Tenant) -> None:
    random_id = uuid.uuid4()
    assert client.get(f"/v1/runs/{random_id}", headers=bob.auth).status_code == 404
    assert client.get(f"/v1/datasets/versions/{random_id}", headers=bob.auth).status_code == 404


# ------------------------------------------------------------- authentication


def test_no_credential_is_401(client: TestClient) -> None:
    response = client.get("/v1/runs")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize(
    "header",
    [
        "Bearer ck_000000000000_wrongsecret",
        "Bearer garbage",
        "Bearer ",
        "Basic dXNlcjpwYXNz",
    ],
)
def test_bad_credentials_are_401(client: TestClient, header: str) -> None:
    assert client.get("/v1/runs", headers={"Authorization": header}).status_code == 401


def test_expired_key_is_rejected(client: TestClient, engine: sa.Engine) -> None:
    expired = make_tenant(engine, slug=f"exp-{uuid.uuid4().hex[:8]}", expired=True)
    assert client.get("/v1/runs", headers=expired.auth).status_code == 401


def test_revoked_key_stops_working_immediately(
    client: TestClient, engine: sa.Engine, alice: Tenant
) -> None:
    victim = make_tenant(engine, slug=f"rev-{uuid.uuid4().hex[:8]}")
    assert client.get("/v1/runs", headers=victim.auth).status_code == 200

    with engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE api_keys SET revoked_at = now() WHERE organization_id = :org"),
            {"org": victim.organization_id},
        )
    assert client.get("/v1/runs", headers=victim.auth).status_code == 401


def test_key_secret_is_never_returned_by_the_api(client: TestClient, alice: Tenant) -> None:
    created = client.post(
        "/v1/api-keys",
        headers=alice.auth,
        json={"name": "ci", "role": "engineer"},
    )
    assert created.status_code == 201
    token = created.json()["token"]

    listed = client.get("/v1/api-keys", headers=alice.auth).json()
    assert all("token" not in k and "secret_hash" not in k for k in listed)
    # The new key works, proving the token we saw once is the real credential.
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


# --------------------------------------------------------------- authorization


def test_viewer_cannot_upload_or_run(
    client: TestClient, engine: sa.Engine, worker_ctx: dict[str, Any]
) -> None:
    viewer = make_tenant(engine, slug=f"view-{uuid.uuid4().hex[:8]}", role=Role.VIEWER)
    upload = client.post(
        "/v1/datasets/uploads",
        headers=viewer.auth,
        json={
            "dataset_name": "nope",
            "filename": "x.csv",
            "content_type": "text/csv",
            "size_bytes": 10,
        },
    )
    assert upload.status_code == 403
    assert client.get("/v1/datasets", headers=viewer.auth).status_code == 200  # reads are fine

    run = client.post(
        "/v1/runs",
        headers=viewer.auth,
        json={"dataset_version_id": str(uuid.uuid4()), "question": "q"},
    )
    assert run.status_code == 403  # permission is checked before existence


def test_engineer_cannot_manage_api_keys(client: TestClient, engine: sa.Engine) -> None:
    engineer = make_tenant(engine, slug=f"eng-{uuid.uuid4().hex[:8]}", role=Role.ENGINEER)
    assert client.get("/v1/api-keys", headers=engineer.auth).status_code == 403
    assert (
        client.post(
            "/v1/api-keys", headers=engineer.auth, json={"name": "x", "role": "viewer"}
        ).status_code
        == 403
    )


def test_admin_cannot_mint_a_key_beyond_their_own_permissions(
    client: TestClient, engine: sa.Engine
) -> None:
    """Privilege-escalation guard: an admin may not create an owner key."""
    admin = make_tenant(engine, slug=f"adm-{uuid.uuid4().hex[:8]}", role=Role.ADMIN)
    response = client.post(
        "/v1/api-keys", headers=admin.auth, json={"name": "escalate", "role": "owner"}
    )
    assert response.status_code == 403


def test_scoped_key_is_narrowed_not_widened(client: TestClient, alice: Tenant) -> None:
    created = client.post(
        "/v1/api-keys",
        headers=alice.auth,
        json={"name": "read-only-runs", "role": "engineer", "scopes": ["run:read"]},
    ).json()
    scoped = {"Authorization": f"Bearer {created['token']}"}

    me = client.get("/v1/me", headers=scoped).json()
    assert me["permissions"] == ["run:read"]
    assert client.get("/v1/runs", headers=scoped).status_code == 200
    assert (
        client.post(
            "/v1/runs",
            headers=scoped,
            json={"dataset_version_id": str(uuid.uuid4()), "question": "q"},
        ).status_code
        == 403
    )


# -------------------------------------------------------------------- headers


def test_security_headers_and_request_id_are_present(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-Id": "abc-123"})
    assert response.headers["X-Request-Id"] == "abc-123"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_failed_authentication_is_audited(client: TestClient, engine: sa.Engine) -> None:
    """A brute-force attempt leaves evidence even though no principal exists.

    The denial is written in its own transaction: the request's session is
    rolled back when authentication raises, so an audit row attached to it
    would be lost exactly when it matters most.
    """
    client.get("/v1/runs", headers={"Authorization": "Bearer ck_000000000000_nope"})

    rows = _denials(engine)
    assert len(rows) == 1
    assert rows[0].action == "access.denied"
    assert rows[0].metadata["status"] == 401
    assert rows[0].metadata["path"] == "/v1/runs"
    assert rows[0].organization_id is None  # nobody was authenticated


def test_permission_denial_is_audited_with_attribution(
    client: TestClient, engine: sa.Engine
) -> None:
    """A 403 names the tenant and the actor that attempted the action."""
    viewer = make_tenant(engine, slug=f"aud-{uuid.uuid4().hex[:8]}", role=Role.VIEWER)
    response = client.post(
        "/v1/datasets/uploads",
        headers=viewer.auth,
        json={
            "dataset_name": "denied",
            "filename": "x.csv",
            "content_type": "text/csv",
            "size_bytes": 10,
        },
    )
    assert response.status_code == 403

    rows = _denials(engine)
    assert len(rows) == 1
    assert rows[0].organization_id == viewer.organization_id
    assert rows[0].actor_type == "api_key"
    assert rows[0].metadata["status"] == 403


def _denials(engine: sa.Engine) -> list[Any]:
    with engine.begin() as conn:
        return list(
            conn.execute(
                sa.text(
                    "SELECT organization_id, actor_type, action, metadata "
                    "FROM audit_events WHERE result = 'denied' ORDER BY created_at"
                )
            ).all()
        )


def test_worker_jobs_reject_unknown_ids(worker_ctx: dict[str, Any]) -> None:
    from crucible_worker.jobs.datasets import profile_dataset_version
    from crucible_worker.jobs.runs import execute_run

    assert asyncio.run(execute_run(worker_ctx, str(uuid.uuid4())))["result"] == "not_found"
    assert (
        asyncio.run(profile_dataset_version(worker_ctx, str(uuid.uuid4())))["result"] == "not_found"
    )
