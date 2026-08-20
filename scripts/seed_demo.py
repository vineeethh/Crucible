"""Seed a demo organization with data and a few finished runs.

Gives the product dashboard something real to show: a ready dataset, an
*answered* run (with provenance), an *abstained* run, and a run *waiting for
review*. Everything is driven in-process against the same Postgres + MinIO the
app uses — no API server or worker process needs to be running — so a reviewer
can go from a clean checkout to a populated dashboard in one command:

    uv run python scripts/seed_demo.py --slug demo

Prints an API key once. Put it in apps/web/.env.local as CRUCIBLE_API_KEY.

The generated code "execution" is scripted with a fake executor (no Docker), so
the answers are deterministic; the agent graph, persistence, profiling, and
verification are the real ones.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from crucible.agent import FakeModel
from crucible.db import create_async_engine_from_url, install_selector_event_loop_policy
from crucible.db import models as m
from crucible.db.repositories import SqlDatasetRepository, SqlRunRepository
from crucible.domain import Role, new_id
from crucible.execution import (
    ExecutionLimits,
    ExecutionRequest,
    ExecutionResult,
    ExitClass,
    FakeExecutor,
    ResourceUsage,
)
from crucible.security import generate_api_key
from crucible.storage import S3ObjectStorage, dataset_object_key
from crucible_api.settings import ApiSettings
from crucible_worker.jobs.datasets import profile_dataset_version
from crucible_worker.jobs.runs import execute_run

install_selector_event_loop_policy()  # Windows dev only; no-op elsewhere

DEMO_CSV = (
    b"region,amount,ordered_at\n"
    b"north,10.5,2024-01-01\n"
    b"south,20.0,2024-02-01\n"
    b"north,5.25,2024-03-01\n"
    b"west,12.0,2024-04-01\n"
)


def _constant(result: ExecutionResult) -> Callable[[ExecutionRequest], ExecutionResult]:
    """A sandbox handler that always returns the same scripted result."""
    return lambda _request: result


def _exec(
    *, value: object = None, columns: list[str] | None = None, ambiguous: bool = False
) -> ExecutionResult:
    result: dict[str, object] = {"value": value}
    if columns is not None:
        result["columns_used"] = columns
    if ambiguous:
        result["ambiguous"] = True
    return ExecutionResult(
        exit_class=ExitClass.OK,
        image_ref="fake-image",
        limits=ExecutionLimits(),
        usage=ResourceUsage(wall_ms=7, program_exit_code=0),
        result=result,
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", default="demo")
    parser.add_argument("--name", default=None)
    args = parser.parse_args()

    settings = ApiSettings()
    engine = create_async_engine_from_url(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    storage = S3ObjectStorage(
        bucket=settings.s3_bucket,
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
    )
    storage.ensure_bucket()

    ctx_base = {
        "session_factory": factory,
        "storage": storage,
        "model": FakeModel(),
        "limits": ExecutionLimits(),
    }

    # 1. Organization, owner, membership, API key. -----------------------------
    async with factory() as session:
        org = (
            await session.execute(select(m.Organization).where(m.Organization.slug == args.slug))
        ).scalar_one_or_none()
        if org is None:
            org = m.Organization(id=new_id(), slug=args.slug, name=args.name or args.slug)
            session.add(org)
            await session.flush()
        user = (
            await session.execute(select(m.User).where(m.User.subject == f"{args.slug}-owner"))
        ).scalar_one_or_none()
        if user is None:
            user = m.User(
                id=new_id(), subject=f"{args.slug}-owner", email=f"{args.slug}@example.com"
            )
            session.add(user)
            await session.flush()
        if (
            await session.execute(
                select(m.Membership).where(
                    m.Membership.organization_id == org.id, m.Membership.user_id == user.id
                )
            )
        ).scalar_one_or_none() is None:
            session.add(
                m.Membership(
                    id=new_id(), organization_id=org.id, user_id=user.id, role=Role.OWNER.value
                )
            )
        generated = generate_api_key()
        session.add(
            m.ApiKey(
                id=new_id(),
                organization_id=org.id,
                created_by_user_id=user.id,
                name="demo-seed",
                prefix=generated.prefix,
                secret_hash=generated.secret_hash,
                role=Role.OWNER.value,
                scopes=None,
            )
        )
        await session.commit()
        org_id, user_id = org.id, user.id

    # 2. Dataset + version: store the bytes, then profile them. -----------------
    content_sha = S3ObjectStorage.sha256(DEMO_CSV)
    async with factory() as session:
        datasets = SqlDatasetRepository(session)
        dataset = await datasets.dataset_by_name(organization_id=org_id, name="sales")
        if dataset is None:
            dataset = await datasets.create_dataset(organization_id=org_id, name="sales")
        version_id = new_id()
        object_key = dataset_object_key(org_id, dataset.id, version_id, "sales.csv")
        version = await datasets.create_version(
            organization_id=org_id,
            dataset_id=dataset.id,
            version_id=version_id,
            object_key=object_key,
            content_type="text/csv",
            declared_size_bytes=len(DEMO_CSV),
            filename="sales.csv",
        )
        storage.put_bytes(object_key, DEMO_CSV, content_type="text/csv")
        await datasets.mark_version_uploaded(
            version_id=version.id, size_bytes=len(DEMO_CSV), content_sha256=content_sha
        )
        await session.commit()

    profiled = await profile_dataset_version(ctx_base, str(version_id))
    if profiled.get("result") != "ready":
        print(f"warning: dataset did not become ready: {profiled}", file=sys.stderr)

    # 3. A few runs with distinct terminal outcomes. ---------------------------
    scripts = [
        ("What is the total amount?", _exec(value=47.75, columns=["amount"])),
        (
            "Which region had the highest amount?",
            _exec(value="north", columns=["region"], ambiguous=True),
        ),
        ("Write a limerick about the sales data.", _exec(value=None)),
    ]
    outcomes: list[tuple[str, str]] = []
    for question, scripted in scripts:
        async with factory() as session:
            runs = SqlRunRepository(session)
            run = await runs.create_run(
                organization_id=org_id,
                dataset_version_id=version_id,
                question=question,
                config_manifest={
                    "release_id": settings.git_sha,
                    "dataset_content_sha256": content_sha,
                    "model_backend": "fake",
                    "executor_backend": "fake",
                },
                idempotency_key=None,
                request_hash=None,
                created_by=user_id,
            )
            await session.commit()
            run_id = run.id
        ctx = {**ctx_base, "executor": FakeExecutor(handler=_constant(scripted))}
        result = await execute_run(ctx, str(run_id))
        outcomes.append((question, result.get("result", "?")))

    await engine.dispose()

    print(f"organization_id: {org_id}")
    print(f"organization_slug: {args.slug}")
    print(f"api_key: {generated.token}")
    print("\nseeded:")
    print("  dataset 'sales' v1 (ready)")
    for question, outcome in outcomes:
        print(f"  run [{outcome}] — {question}")
    print("\nSet in apps/web/.env.local:")
    print("  CRUCIBLE_API_URL=http://localhost:8100")
    print(f"  CRUCIBLE_API_KEY={generated.token}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
