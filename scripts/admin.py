"""Platform support / admin CLI (master plan Phase 10).

The operator surface for the private beta: list tenants, suspend/activate access
(the beta allowlist), set per-tenant budget and retention, run the retention
job, and handle a data-erasure request — each with a dry run where deletion is
involved. This talks to the database directly (like scripts/bootstrap_org.py):
it is a break-glass operator tool, not an API surface, so it needs no platform-
admin role in the request path.

    uv run python scripts/admin.py list
    uv run python scripts/admin.py suspend --slug acme
    uv run python scripts/admin.py activate --slug acme
    uv run python scripts/admin.py set-budget --slug acme --usd 50
    uv run python scripts/admin.py set-retention --slug acme --days 30
    uv run python scripts/admin.py retention [--apply]
    uv run python scripts/admin.py purge-org --slug acme [--apply]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crucible.application import DEFAULT_RETENTION_DAYS, ApplyRetention
from crucible.db import (
    SqlBudgetRepository,
    SqlIdentityRepository,
    SqlRetentionRepository,
    create_async_engine_from_url,
    install_selector_event_loop_policy,
)
from crucible.db import models as m
from crucible.domain import OrganizationStatus
from crucible_api.settings import ApiSettings

install_selector_event_loop_policy()


async def _org_id(session: AsyncSession, slug: str) -> uuid.UUID:
    row = (
        await session.execute(select(m.Organization).where(m.Organization.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        raise SystemExit(f"no organization with slug '{slug}'")
    return row.id


async def _main(args: argparse.Namespace) -> int:
    settings = ApiSettings()
    engine = create_async_engine_from_url(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        identity = SqlIdentityRepository(session)
        budgets = SqlBudgetRepository(session)
        retention = SqlRetentionRepository(session)

        if args.command == "list":
            orgs = await identity.list_organizations()
            print(f"{'slug':<24} {'status':<10} {'retention':<10} created")
            for o in orgs:
                ret = "default" if o.retention_days is None else f"{o.retention_days}d"
                print(f"{o.slug:<24} {o.status:<10} {ret:<10} {o.created_at.date()}")

        elif args.command in ("suspend", "activate"):
            status = (
                OrganizationStatus.SUSPENDED
                if args.command == "suspend"
                else OrganizationStatus.ACTIVE
            )
            org_id = await _org_id(session, args.slug)
            await identity.set_organization_status(organization_id=org_id, status=status.value)
            await session.commit()
            print(f"{args.slug}: status -> {status.value}")

        elif args.command == "set-budget":
            org_id = await _org_id(session, args.slug)
            await budgets.set_limit(organization_id=org_id, monthly_limit_usd=args.usd)
            await session.commit()
            print(f"{args.slug}: monthly budget -> ${args.usd}")

        elif args.command == "set-retention":
            org_id = await _org_id(session, args.slug)
            days = None if args.days <= 0 else args.days
            await identity.set_organization_retention(organization_id=org_id, retention_days=days)
            await session.commit()
            print(f"{args.slug}: retention -> {'default' if days is None else f'{days}d'}")

        elif args.command == "retention":
            outcome = await ApplyRetention(
                retention=retention, identity=identity, default_days=DEFAULT_RETENTION_DAYS
            )(dry_run=not args.apply)
            if args.apply:
                await session.commit()
                print(
                    f"retention APPLIED: deleted runs={outcome.runs} cache={outcome.cache_entries}"
                )
            else:
                print(f"retention DRY RUN: would delete runs={outcome.runs}")
                for slug, n in sorted(outcome.per_org.items()):
                    print(f"  {slug}: {n}")

        elif args.command == "purge-org":
            org_id = await _org_id(session, args.slug)
            counts = await retention.describe_organization(org_id)
            if not args.apply:
                print(f"purge DRY RUN for {args.slug}: would delete")
                for label, n in counts.items():
                    print(f"  {label}: {n}")
            else:
                await retention.purge_organization(org_id)
                await session.commit()
                print(f"purge APPLIED for {args.slug}: {counts}")

    await engine.dispose()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="admin", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list organizations")

    for name, help_text in (("suspend", "block a tenant"), ("activate", "restore a tenant")):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--slug", required=True)

    b = sub.add_parser("set-budget", help="set a tenant's monthly USD budget")
    b.add_argument("--slug", required=True)
    b.add_argument("--usd", type=float, required=True)

    r = sub.add_parser("set-retention", help="set a tenant's retention (days; <=0 = default)")
    r.add_argument("--slug", required=True)
    r.add_argument("--days", type=int, required=True)

    ret = sub.add_parser("retention", help="run the retention job (dry run unless --apply)")
    ret.add_argument("--apply", action="store_true")

    purge = sub.add_parser("purge-org", help="erase a tenant's data (dry run unless --apply)")
    purge.add_argument("--slug", required=True)
    purge.add_argument("--apply", action="store_true")

    return asyncio.run(_main(p.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
