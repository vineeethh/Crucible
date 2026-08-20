"""Shared fixtures for tests that need the live stack (Postgres, Redis, MinIO).

Registered as a pytest plugin in tests/conftest.py, so both the integration and
security suites see these fixtures. Skips cleanly when the stack is not running,
keeping `pytest` green on a machine without Docker; CI runs them with services.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from crucible.db import install_selector_event_loop_policy
from crucible.domain import Role, new_id
from crucible.security import generate_api_key
from crucible_api.main import create_app
from crucible_api.settings import ApiSettings

install_selector_event_loop_policy()  # psycopg async needs a selector loop on Windows

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://crucible:crucible@localhost:55432/crucible"
)
SYNC_URL = DATABASE_URL
# Redis DB 1, not 0: the local `docker compose` worker consumes DB 0, and it
# would race these tests for their own jobs. Integration tests drive the worker
# jobs directly (in-process), so they must own their queue.
REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT_URL", "http://localhost:9000")

TABLES = (
    "audit_events",
    "run_events",
    "agent_runs",
    "dataset_versions",
    "datasets",
    "api_keys",
    "memberships",
    "users",
    "organizations",
)


def _stack_reachable() -> bool:
    try:
        engine = sa.create_engine(SYNC_URL, connect_args={"connect_timeout": 3})
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1 FROM organizations LIMIT 1"))
        return True
    except Exception:
        return False


requires_stack = pytest.mark.skipif(
    not _stack_reachable(),
    reason="compose stack (Postgres migrated to head) not reachable",
)


@dataclass(frozen=True)
class Tenant:
    organization_id: uuid.UUID
    token: str
    role: Role

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture(scope="session")
def engine() -> Iterator[sa.Engine]:
    eng = sa.create_engine(SYNC_URL)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def clean_database(request: pytest.FixtureRequest) -> Iterator[None]:
    """Each stack test starts from an empty data plane. Truncate rather than
    drop, so the migrated schema (the thing under test) is never rebuilt by the
    tests. Unit tests never touch the database, so they skip this entirely."""
    if request.node.get_closest_marker("integration") is None:
        yield
        return
    engine = request.getfixturevalue("engine")
    with engine.begin() as conn:
        conn.execute(sa.text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def settings() -> ApiSettings:
    return ApiSettings(
        _env_file=None,  # type: ignore[call-arg]
        profile="test",
        database_url=DATABASE_URL,
        redis_url=REDIS_URL,
        s3_endpoint_url=S3_ENDPOINT,
        s3_bucket="crucible-test",
        git_sha="test",
    )


@pytest.fixture
def client(settings: ApiSettings) -> Iterator[TestClient]:
    with TestClient(create_app(settings=settings)) as c:
        yield c


def make_tenant(
    engine: sa.Engine, *, slug: str, role: Role = Role.OWNER, expired: bool = False
) -> Tenant:
    """Creates an organization, an owner user, a membership, and an API key."""
    org_id, user_id = new_id(), new_id()
    key = generate_api_key()
    expires = sa.text("now() - interval '1 hour'") if expired else sa.text("NULL")

    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO organizations (id, slug, name) VALUES (:id, :slug, :name)"),
            {"id": org_id, "slug": slug, "name": slug},
        )
        conn.execute(
            sa.text("INSERT INTO users (id, subject, email) VALUES (:id, :sub, :email)"),
            {"id": user_id, "sub": f"{slug}-user", "email": f"{slug}@example.com"},
        )
        conn.execute(
            sa.text(
                "INSERT INTO memberships (id, organization_id, user_id, role) "
                "VALUES (:id, :org, :user, :role)"
            ),
            {"id": new_id(), "org": org_id, "user": user_id, "role": role.value},
        )
        conn.execute(
            sa.text(
                "INSERT INTO api_keys "
                "(id, organization_id, created_by_user_id, name, prefix, secret_hash, role, "
                f" expires_at) VALUES (:id, :org, :user, :name, :prefix, :hash, :role, {expires.text})"
            ),
            {
                "id": new_id(),
                "org": org_id,
                "user": user_id,
                "name": f"{slug}-key",
                "prefix": key.prefix,
                "hash": key.secret_hash,
                "role": role.value,
            },
        )
    return Tenant(organization_id=org_id, token=key.token, role=role)


@pytest.fixture
def alice(engine: sa.Engine) -> Tenant:
    return make_tenant(engine, slug=f"alice-{uuid.uuid4().hex[:8]}")


@pytest.fixture
def bob(engine: sa.Engine) -> Tenant:
    """A second, unrelated tenant — the other side of every isolation test."""
    return make_tenant(engine, slug=f"bob-{uuid.uuid4().hex[:8]}")


@pytest.fixture
def worker_ctx(settings: ApiSettings) -> Iterator[dict[str, Any]]:
    """Minimal arq context so worker jobs can be driven directly from tests."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from crucible.db import create_async_engine_from_url
    from crucible.storage import S3ObjectStorage

    async_engine = create_async_engine_from_url(settings.database_url)
    storage = S3ObjectStorage(
        bucket=settings.s3_bucket,
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
    )
    storage.ensure_bucket()

    from crucible.agent import FakeModel
    from crucible.execution import (
        ExecutionLimits,
        ExecutionResult,
        ExitClass,
        FakeExecutor,
        ResourceUsage,
    )

    def _abstaining(_req: object) -> ExecutionResult:
        # Default worker-job ctx: a fake executor that returns no value, so a run
        # driven with this ctx abstains rather than fabricating an answer. Tests
        # that assert a real answer inject their own scripted executor.
        return ExecutionResult(
            exit_class=ExitClass.OK,
            image_ref="fake",
            limits=ExecutionLimits(),
            usage=ResourceUsage(wall_ms=1, program_exit_code=0),
            result={"value": None},
        )

    yield {
        "session_factory": async_sessionmaker(async_engine, expire_on_commit=False),
        "storage": storage,
        "model": FakeModel(),
        "executor": FakeExecutor(handler=_abstaining),
        "limits": ExecutionLimits(),
    }
