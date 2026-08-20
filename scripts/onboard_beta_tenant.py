"""Onboard a private-beta tenant (master plan Phase 10).

One command to bring a named beta cohort member onto the platform: create the
organization (allowlisted = `active`), an owner user + membership, an owner API
key, and a default monthly budget so spend is bounded from minute one. Prints
the credential once and the next steps from docs/operations/beta-onboarding.md.

    uv run python scripts/onboard_beta_tenant.py \
        --slug acme --name "Acme Inc" --owner-email ops@acme.example --budget-usd 25
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from crucible.db import create_async_engine_from_url, install_selector_event_loop_policy
from crucible.db import models as m
from crucible.domain import OrganizationStatus, Role, new_id
from crucible.security import generate_api_key
from crucible_api.settings import ApiSettings

install_selector_event_loop_policy()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--owner-subject", default=None)
    parser.add_argument("--owner-email", default=None)
    parser.add_argument("--budget-usd", type=float, default=25.0)
    parser.add_argument("--retention-days", type=int, default=0, help="0 = platform default")
    args = parser.parse_args()

    settings = ApiSettings()
    engine = create_async_engine_from_url(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        existing = (
            await session.execute(select(m.Organization).where(m.Organization.slug == args.slug))
        ).scalar_one_or_none()
        if existing is not None:
            print(f"organization '{args.slug}' already exists ({existing.id})", file=sys.stderr)
            return 1

        org = m.Organization(
            id=new_id(),
            slug=args.slug,
            name=args.name or args.slug,
            status=OrganizationStatus.ACTIVE.value,
            retention_days=args.retention_days or None,
        )
        session.add(org)
        await session.flush()

        user = m.User(
            id=new_id(),
            subject=args.owner_subject or f"{args.slug}-owner",
            email=args.owner_email,
            display_name=f"{args.name or args.slug} owner",
        )
        session.add(user)
        await session.flush()
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
                name="beta-onboarding",
                prefix=generated.prefix,
                secret_hash=generated.secret_hash,
                role=Role.OWNER.value,
                scopes=None,
            )
        )
        session.add(m.Budget(organization_id=org.id, monthly_limit_usd=args.budget_usd))
        await session.commit()
        org_id = org.id

    await engine.dispose()

    print(f"organization_id:   {org_id}")
    print(f"organization_slug: {args.slug}")
    print("status:            active (allowlisted)")
    print(f"monthly_budget:    ${args.budget_usd}")
    print(
        f"retention:         {'platform default' if not args.retention_days else f'{args.retention_days}d'}"
    )
    print(f"api_key:           {generated.token}")
    print("\nThis token is shown once. Share it over a secure channel.")
    print("Next steps: docs/operations/beta-onboarding.md")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
