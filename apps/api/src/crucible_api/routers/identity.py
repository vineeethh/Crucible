"""Identity and API-key management."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from crucible.application import (
    CreateApiKey,
    CreateApiKeyInput,
    ListApiKeys,
    RevokeApiKey,
)
from crucible.security import generate_api_key
from crucible_api.dependencies import (
    AuditDep,
    IdentityRepoDep,
    PrincipalDep,
    RequestIdDep,
)
from crucible_api.schemas import ApiKeyOut, CreateApiKeyIn, CreatedApiKeyOut, MeOut

router = APIRouter(prefix="/v1", tags=["identity"])


@router.get("/me", response_model=MeOut)
async def me(principal: PrincipalDep) -> MeOut:
    return MeOut(
        actor_type=principal.actor_type.value,
        actor_id=principal.actor_id,
        organization_id=principal.organization_id,
        role=principal.role,
        permissions=sorted(principal.permissions),
    )


@router.get("/api-keys", response_model=list[ApiKeyOut])
async def list_keys(principal: PrincipalDep, identity: IdentityRepoDep) -> list[ApiKeyOut]:
    records = await ListApiKeys(identity=identity)(principal)
    return [ApiKeyOut.of(r) for r in records]


@router.post("/api-keys", response_model=CreatedApiKeyOut, status_code=status.HTTP_201_CREATED)
async def create_key(
    body: CreateApiKeyIn,
    principal: PrincipalDep,
    identity: IdentityRepoDep,
    audit: AuditDep,
    request_id: RequestIdDep,
) -> CreatedApiKeyOut:
    def generator() -> tuple[str, str, str]:
        generated = generate_api_key()
        return generated.token, generated.prefix, generated.secret_hash

    created = await CreateApiKey(identity=identity, audit=audit, generator=generator)(
        principal,
        CreateApiKeyInput(
            name=body.name,
            role=body.role,
            scopes=tuple(body.scopes) if body.scopes else None,
            expires_at=body.expires_at,
        ),
        request_id=request_id,
    )
    return CreatedApiKeyOut(**ApiKeyOut.of(created.record).model_dump(), token=created.token)


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    key_id: uuid.UUID,
    principal: PrincipalDep,
    identity: IdentityRepoDep,
    audit: AuditDep,
    request_id: RequestIdDep,
) -> Response:
    await RevokeApiKey(identity=identity, audit=audit)(principal, key_id, request_id=request_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
