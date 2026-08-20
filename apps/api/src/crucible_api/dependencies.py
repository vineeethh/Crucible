"""Dependency injection: session, principal, repositories, rate limits.

Authentication accepts either credential (plan §6.3):

    Authorization: Bearer ck_<prefix>_<secret>     -> API key
    Authorization: Bearer <oidc-jwt>               -> OIDC user

Authorization is *not* done here. Each use case checks `Principal.can(...)`,
so a new route cannot accidentally inherit an unchecked permission.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crucible.application import (
    ResolveApiKeyPrincipal,
    ResolveUserPrincipal,
    VerifiedIdentity,
)
from crucible.db import (
    SqlAgentStore,
    SqlAuditSink,
    SqlBudgetRepository,
    SqlDatasetRepository,
    SqlIdentityRepository,
    SqlMetricsRepository,
    SqlReviewRepository,
    SqlRunRepository,
    SqlScoreStore,
)
from crucible.domain import (
    DependencyUnavailable,
    NotAuthenticated,
    OrganizationStatus,
    Permission,
    PermissionDenied,
    Principal,
    RateLimited,
)
from crucible.security import TokenInvalid, split_token, verify_secret
from crucible_api.settings import ApiSettings

BEARER = "bearer "


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session (and one transaction) per request. Commits on success so a
    handler that raises never leaves a half-written audit trail."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_settings(request: Request) -> ApiSettings:
    settings: ApiSettings = request.app.state.settings
    return settings


SettingsDep = Annotated[ApiSettings, Depends(get_settings)]


def get_request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", ""))


RequestIdDep = Annotated[str, Depends(get_request_id)]


def identity_repo(session: SessionDep) -> SqlIdentityRepository:
    return SqlIdentityRepository(session)


def dataset_repo(session: SessionDep) -> SqlDatasetRepository:
    return SqlDatasetRepository(session)


def run_repo(session: SessionDep) -> SqlRunRepository:
    return SqlRunRepository(session)


def audit_sink(session: SessionDep) -> SqlAuditSink:
    return SqlAuditSink(session)


def agent_store(session: SessionDep) -> SqlAgentStore:
    return SqlAgentStore(session)


def review_repo(session: SessionDep) -> SqlReviewRepository:
    return SqlReviewRepository(session)


def score_store(session: SessionDep) -> SqlScoreStore:
    return SqlScoreStore(session)


def metrics_repo(session: SessionDep) -> SqlMetricsRepository:
    return SqlMetricsRepository(session)


def budget_repo(session: SessionDep) -> SqlBudgetRepository:
    return SqlBudgetRepository(session)


IdentityRepoDep = Annotated[SqlIdentityRepository, Depends(identity_repo)]
DatasetRepoDep = Annotated[SqlDatasetRepository, Depends(dataset_repo)]
RunRepoDep = Annotated[SqlRunRepository, Depends(run_repo)]
AuditDep = Annotated[SqlAuditSink, Depends(audit_sink)]
AgentStoreDep = Annotated[SqlAgentStore, Depends(agent_store)]
ReviewRepoDep = Annotated[SqlReviewRepository, Depends(review_repo)]
ScoreStoreDep = Annotated[SqlScoreStore, Depends(score_store)]
MetricsRepoDep = Annotated[SqlMetricsRepository, Depends(metrics_repo)]
BudgetRepoDep = Annotated[SqlBudgetRepository, Depends(budget_repo)]


async def get_principal(
    request: Request,
    identity: IdentityRepoDep,
    authorization: Annotated[str | None, Header()] = None,
    x_organization_id: Annotated[str | None, Header()] = None,
) -> Principal:
    """Resolve the caller. Authentication failures raise NotAuthenticated; the
    exception handler in main.py records the denial in its own transaction (the
    request's session is rolled back by then)."""
    if not authorization or not authorization.lower().startswith(BEARER):
        raise NotAuthenticated("Provide an API key or OIDC token as a Bearer credential.")
    token = authorization[len(BEARER) :].strip()

    if split_token(token) is not None:
        resolver = ResolveApiKeyPrincipal(
            identity=identity, verify_secret=verify_secret, split_token=split_token
        )
        principal = await resolver(token, now=datetime.now(UTC))
    else:
        verifier = getattr(request.app.state, "jwt_verifier", None)
        if verifier is None:
            raise NotAuthenticated("OIDC is not configured on this deployment.")
        try:
            claims = verifier.verify(token)
        except TokenInvalid as exc:
            raise NotAuthenticated("The provided token is not valid.") from exc

        org_id = _parse_org_header(x_organization_id)
        resolver_user = ResolveUserPrincipal(identity=identity)
        principal, _memberships = await resolver_user(
            VerifiedIdentity(subject=claims.subject, email=claims.email, display_name=claims.name),
            organization_id=org_id,
        )

    # Beta allowlist / lifecycle gate (Phase 10): a suspended organization is
    # refused at the authentication boundary for both credential types, so no
    # use case ever runs for it. The data is retained; access is not.
    status = await identity.organization_status(principal.organization_id)
    if status != OrganizationStatus.ACTIVE.value:
        raise PermissionDenied("This organization's access is suspended.")

    request.state.principal = principal
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def _parse_org_header(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotAuthenticated("X-Organization-Id must be a UUID.") from exc


class RateLimit:
    """Per-principal fixed-window limit for a named route group.

    Expensive routes fail **closed**: if Redis is unreachable we return 503
    rather than admit work we cannot account for (plan §5.5).
    """

    def __init__(self, bucket: str, *, per_minute: int) -> None:
        self._bucket = bucket
        self._per_minute = per_minute

    async def __call__(self, request: Request, principal: PrincipalDep) -> None:
        limiter = getattr(request.app.state, "rate_limiter", None)
        if limiter is None:
            return
        limit = self._per_minute
        decision = await limiter.check(
            f"{self._bucket}:{principal.organization_id}:{principal.actor_id}",
            limit=limit,
            window_seconds=60,
        )
        if not decision.limiter_available:
            raise DependencyUnavailable(
                "Rate limiting is unavailable, so this request was refused rather than "
                "admitted without accounting."
            )
        if not decision.allowed:
            raise RateLimited(
                f"Limit of {limit} requests/minute exceeded. Retry in {decision.reset_seconds}s."
            )


write_rate_limit = RateLimit("write", per_minute=60)
run_rate_limit = RateLimit("run", per_minute=20)


def require(permission: Permission) -> Any:
    """Route-level permission guard.

    This is defense in depth for discoverability (it keeps the OpenAPI document
    honest); the authoritative check still lives inside each use case.
    """

    async def _guard(principal: PrincipalDep) -> Principal:
        if not principal.can(permission):
            raise PermissionDenied()
        return principal

    return Depends(_guard)
