"""API-key lifecycle use cases.

The plaintext token is returned exactly once, at creation. A key can never
grant more than its own role, and never more than the creator holds.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from crucible.application.ports import (
    ApiKeyRecord,
    AuditEntry,
    AuditSink,
    IdentityRepository,
)
from crucible.domain import (
    AuditAction,
    AuditResult,
    NotFound,
    Permission,
    PermissionDenied,
    Principal,
    Role,
    ValidationFailed,
)


class KeyGenerator(Protocol):
    """Returns (token, prefix, secret_hash). Injected so the application layer
    does not depend on the hashing implementation."""

    def __call__(self) -> tuple[str, str, str]: ...


@dataclass(frozen=True, slots=True)
class CreateApiKeyInput:
    name: str
    role: Role
    scopes: tuple[Permission, ...] | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CreatedApiKey:
    record: ApiKeyRecord
    token: str  # shown once; never retrievable again


class CreateApiKey:
    def __init__(
        self, *, identity: IdentityRepository, audit: AuditSink, generator: KeyGenerator
    ) -> None:
        self._identity = identity
        self._audit = audit
        self._generate = generator

    async def __call__(
        self, principal: Principal, data: CreateApiKeyInput, *, request_id: str = ""
    ) -> CreatedApiKey:
        if not principal.can(Permission.APIKEY_MANAGE):
            raise PermissionDenied()
        if not data.name.strip():
            raise ValidationFailed("Key name must not be empty.", code="invalid-key-name")

        # Privilege escalation guard: a key may not exceed its creator's
        # permissions, whatever role is requested.
        from crucible.domain import ROLE_PERMISSIONS

        requested = ROLE_PERMISSIONS[data.role]
        if not requested <= principal.permissions:
            raise PermissionDenied(
                "An API key cannot be granted permissions beyond those of its creator."
            )

        token, prefix, secret_hash = self._generate()
        record = await self._identity.create_api_key(
            organization_id=principal.organization_id,
            created_by=principal.user_id,
            name=data.name.strip(),
            prefix=prefix,
            secret_hash=secret_hash,
            role=data.role,
            scopes=data.scopes,
            expires_at=data.expires_at,
        )
        await self._audit.record(
            AuditEntry(
                organization_id=principal.organization_id,
                actor_type=principal.actor_type,
                actor_id=principal.actor_id,
                action=AuditAction.API_KEY_CREATED,
                result=AuditResult.ALLOWED,
                target_type="api_key",
                target_id=str(record.id),
                request_id=request_id,
                metadata={"role": data.role.value, "prefix": prefix},
            )
        )
        return CreatedApiKey(record=record, token=token)


class RevokeApiKey:
    def __init__(self, *, identity: IdentityRepository, audit: AuditSink) -> None:
        self._identity = identity
        self._audit = audit

    async def __call__(
        self, principal: Principal, key_id: uuid.UUID, *, request_id: str = ""
    ) -> None:
        if not principal.can(Permission.APIKEY_MANAGE):
            raise PermissionDenied()
        revoked = await self._identity.revoke_api_key(
            organization_id=principal.organization_id, key_id=key_id
        )
        if not revoked:
            raise NotFound("API key")
        await self._audit.record(
            AuditEntry(
                organization_id=principal.organization_id,
                actor_type=principal.actor_type,
                actor_id=principal.actor_id,
                action=AuditAction.API_KEY_REVOKED,
                result=AuditResult.ALLOWED,
                target_type="api_key",
                target_id=str(key_id),
                request_id=request_id,
            )
        )
