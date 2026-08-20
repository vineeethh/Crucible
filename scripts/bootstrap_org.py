"""Create an organization, an owner user, and its first API key.

There is no self-service signup in v1, and no "default org" fallback anywhere
in the code — an organization is created deliberately, here or (in Phase 9) by
an audited admin path.

    uv run python scripts/bootstrap_org.py --slug demo --name "Demo Org"

Prints the API key token once. It is not recoverable afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from crucible.db import create_async_engine_from_url, install_selector_event_loop_policy
from crucible.db import models as m
from crucible.domain import Role, new_id
from crucible.security import generate_api_key
from crucible_api.settings import ApiSettings

install_selector_event_loop_policy()  # Windows dev only; no-op elsewhere


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--owner-subject", default="local-owner")
    parser.add_argument("--owner-email", default=None)
    parser.add_argument("--key-name", default="bootstrap")
    args = parser.parse_args()

    settings = ApiSettings()
    engine = create_async_engine_from_url(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        org = (
            await session.execute(select(m.Organization).where(m.Organization.slug == args.slug))
        ).scalar_one_or_none()
        if org is None:
            org = m.Organization(id=new_id(), slug=args.slug, name=args.name or args.slug)
            session.add(org)
            await session.flush()

        user = (
            await session.execute(select(m.User).where(m.User.subject == args.owner_subject))
        ).scalar_one_or_none()
        if user is None:
            user = m.User(
                id=new_id(),
                subject=args.owner_subject,
                email=args.owner_email,
                display_name="Bootstrap owner",
            )
            session.add(user)
            await session.flush()

        membership = (
            await session.execute(
                select(m.Membership).where(
                    m.Membership.organization_id == org.id, m.Membership.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            session.add(
                m.Membership(
                    id=new_id(),
                    organization_id=org.id,
                    user_id=user.id,
                    role=Role.OWNER.value,
                )
            )

        generated = generate_api_key()
        session.add(
            m.ApiKey(
                id=new_id(),
                organization_id=org.id,
                created_by_user_id=user.id,
                name=args.key_name,
                prefix=generated.prefix,
                secret_hash=generated.secret_hash,
                role=Role.OWNER.value,
                scopes=None,
            )
        )
        await session.commit()

    await engine.dispose()

    print(f"organization_id: {org.id}")
    print(f"organization_slug: {org.slug}")
    print(f"api_key: {generated.token}")
    print("\nThis token is shown once. Use it as: Authorization: Bearer <token>")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
