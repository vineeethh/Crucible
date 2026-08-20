"""Principal resolution: turn a credential into an org-scoped Principal.

Two credential types (plan §6.3):

- **OIDC JWT** — the token is verified by the transport layer (signature,
  issuer, audience, expiry); this service maps the verified subject onto a
  user and an organization membership. Membership, not the token, decides the
  role: a valid token for a user with no membership is 403, never a default org.
- **API key** — prefix lookup plus constant-time secret verification; the key
  carries its own role and optional narrowing scopes.

Authentication says who you are. Authorization (`Principal.can`) is checked in
each use case, not here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from crucible.application.ports import IdentityRepository, MembershipRecord
from crucible.domain import (
    ActorType,
    NotAuthenticated,
    PermissionDenied,
    Principal,
)


class SecretVerifier(Protocol):
    def __call__(self, secret_hash: str, secret: str) -> bool: ...


class TokenSplitter(Protocol):
    def __call__(self, token: str) -> tuple[str, str] | None: ...


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    """What the transport layer proved about an OIDC caller."""

    subject: str
    email: str | None = None
    display_name: str | None = None


class ResolveUserPrincipal:
    def __init__(self, *, identity: IdentityRepository) -> None:
        self._identity = identity

    async def __call__(
        self, verified: VerifiedIdentity, *, organization_id: uuid.UUID | None = None
    ) -> tuple[Principal, list[MembershipRecord]]:
        user = await self._identity.upsert_user(
            subject=verified.subject,
            email=verified.email,
            display_name=verified.display_name,
        )
        memberships = await self._identity.memberships_for_user(user.id)
        if not memberships:
            raise PermissionDenied(
                "Your account is not a member of any organization. Ask an owner to invite you."
            )

        if organization_id is None:
            if len(memberships) > 1:
                raise PermissionDenied(
                    "You belong to multiple organizations. Send the X-Organization-Id header "
                    "to choose one."
                )
            chosen = memberships[0]
        else:
            match = [m for m in memberships if m.organization_id == organization_id]
            if not match:
                # Deliberately 403, not 404: the caller already proved identity,
                # and we do not confirm whether the organization exists.
                raise PermissionDenied("You are not a member of the requested organization.")
            chosen = match[0]

        principal = Principal(
            organization_id=chosen.organization_id,
            actor_type=ActorType.USER,
            actor_id=user.id,
            role=chosen.role,
        )
        return principal, memberships


class ResolveApiKeyPrincipal:
    def __init__(
        self,
        *,
        identity: IdentityRepository,
        verify_secret: SecretVerifier,
        split_token: TokenSplitter,
    ) -> None:
        self._identity = identity
        self._verify = verify_secret
        self._split = split_token

    async def __call__(self, token: str, *, now: datetime) -> Principal:
        parts = self._split(token)
        if parts is None:
            raise NotAuthenticated("Malformed API key.")
        prefix, secret = parts

        record = await self._identity.api_key_by_prefix(prefix)
        if record is None:
            # Still pay the verification cost path shape: an unknown prefix and
            # a wrong secret must be indistinguishable to a caller.
            raise NotAuthenticated("Invalid API key.")
        if not self._verify(record.secret_hash, secret):
            raise NotAuthenticated("Invalid API key.")
        if not record.is_usable(now):
            raise NotAuthenticated("This API key is revoked or expired.")

        await self._identity.touch_api_key(record.id)
        return Principal(
            organization_id=record.organization_id,
            actor_type=ActorType.API_KEY,
            actor_id=record.id,
            role=record.role,
            scopes=frozenset(record.scopes) if record.scopes is not None else None,
        )
