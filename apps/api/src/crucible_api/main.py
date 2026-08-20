"""API application factory and composition root.

Run locally:  uv run uvicorn --factory crucible_api.main:create_app --reload

Health path (Phase 1) plus the Phase 2 data plane: identity, API keys, dataset
ingestion, and durable runs. Errors render as RFC 9457 application/problem+json.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict

import redis.asyncio as aioredis
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from crucible.application import AuditEntry, GetSystemStatus, HealthProbe
from crucible.db import (
    SqlAuditSink,
    create_async_engine_from_url,
    install_selector_event_loop_policy,
)
from crucible.domain import (
    ActorType,
    AuditAction,
    AuditResult,
    DomainError,
    NotAuthenticated,
    PermissionDenied,
    Principal,
    ProblemDetail,
)
from crucible.security import JwtVerifier, RedisRateLimiter
from crucible.storage import S3ObjectStorage
from crucible_api.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from crucible_api.probes import DatabaseProbe, RedisProbe
from crucible_api.routers import budget as budget_router
from crucible_api.routers import datasets as datasets_router
from crucible_api.routers import identity as identity_router
from crucible_api.routers import metrics as metrics_router
from crucible_api.routers import reviews as reviews_router
from crucible_api.routers import runs as runs_router
from crucible_api.settings import ApiSettings, resolve_build_info

PROBLEM_CONTENT_TYPE = "application/problem+json"

logger = logging.getLogger("crucible.api")

# Must run before any event loop exists (Windows dev only; no-op elsewhere).
install_selector_event_loop_policy()


def create_app(
    settings: ApiSettings | None = None,
    probes: Sequence[HealthProbe] | None = None,
) -> FastAPI:
    cfg = settings or ApiSettings()
    build = resolve_build_info(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = cfg

        engine = create_async_engine_from_url(cfg.database_url)
        app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)

        redis_client = aioredis.from_url(cfg.redis_url)  # type: ignore[no-untyped-call]
        app.state.rate_limiter = RedisRateLimiter(redis_client)
        # arq's create_pool connects eagerly. As with object storage above, a
        # missing queue must not stop the process from booting in local/test:
        # /readyz probes Redis and requests that need the queue fail with 503.
        # Production (any other profile) still fails fast if the queue is down.
        queue_pool = None
        redis_settings = RedisSettings.from_dsn(cfg.redis_url)
        if cfg.profile in ("local", "test"):
            # Fail fast rather than burning the default 5x1s retry budget when the
            # queue is intentionally absent (e.g. the unit-test lane has no Redis).
            redis_settings.conn_retries = 1
        try:
            queue_pool = await create_pool(redis_settings)
        except Exception:
            if cfg.profile not in ("local", "test"):
                raise
            logger.warning("job queue (redis) not reachable at startup", exc_info=True)
        app.state.queue_pool = queue_pool

        storage = S3ObjectStorage(
            bucket=cfg.s3_bucket,
            endpoint_url=cfg.s3_endpoint_url,
            public_endpoint_url=cfg.s3_public_endpoint_url,
            region=cfg.s3_region,
            access_key=cfg.s3_access_key,
            secret_key=cfg.s3_secret_key,
        )
        if cfg.profile in ("local", "test"):
            # Cloud buckets are created by IaC (Phase 9); locally we make the
            # stack self-starting. A slow-starting MinIO must not kill the API:
            # object storage is probed by /readyz, and requests that need it
            # fail with a 503 rather than the process refusing to boot.
            try:
                storage.ensure_bucket()
            except Exception:
                logger.warning("object storage not reachable at startup", exc_info=True)
        app.state.storage = storage

        app.state.jwt_verifier = (
            JwtVerifier.from_jwks_uri(
                issuer=str(cfg.oidc_issuer),
                audience=str(cfg.oidc_audience),
                jwks_uri=str(cfg.oidc_jwks_uri),
            )
            if cfg.oidc_enabled
            else None
        )

        app.state.probes = (
            list(probes)
            if probes is not None
            else [DatabaseProbe(engine), RedisProbe(redis_client)]
        )
        try:
            yield
        finally:
            if queue_pool is not None:
                await queue_pool.aclose()
            await redis_client.aclose()
            await engine.dispose()

    app = FastAPI(
        title="Crucible API",
        version=cfg.app_version,
        description="Evaluation and reliability platform for LLM agents.",
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/readyz", tags=["health"])
    async def readyz(request: Request) -> JSONResponse:
        status = await GetSystemStatus(request.app.state.probes)()
        body = {
            "state": status.state.value,
            "components": [asdict(c) for c in status.components],
        }
        return JSONResponse(body, status_code=200 if status.ready else 503)

    @app.get("/version", tags=["health"])
    async def version() -> dict[str, str]:
        return {k: str(v) for k, v in asdict(build).items()}

    app.include_router(identity_router.router)
    app.include_router(datasets_router.router)
    app.include_router(runs_router.router)
    app.include_router(reviews_router.router)
    app.include_router(metrics_router.router)
    app.include_router(budget_router.router)
    app.include_router(metrics_router.trace_router)

    @app.exception_handler(NotAuthenticated)
    @app.exception_handler(PermissionDenied)
    async def denial_problem(request: Request, exc: DomainError) -> JSONResponse:
        """Denials are security evidence, so they are audited before the
        response is returned.

        The request's own session is rolled back when the use case raised, so
        this writes through a fresh session that commits independently. Without
        that, the very events an incident review needs would vanish with the
        failed transaction.
        """
        await _audit_denial(request, exc)
        return await domain_problem(request, exc)

    @app.exception_handler(DomainError)
    async def domain_problem(request: Request, exc: DomainError) -> JSONResponse:
        problem = exc.problem
        body = {**problem.to_dict(), "request_id": _request_id(request)}
        headers = {"WWW-Authenticate": "Bearer"} if problem.status == 401 else None
        return JSONResponse(
            body,
            status_code=problem.status,
            media_type=PROBLEM_CONTENT_TYPE,
            headers=headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_problem(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        problem = ProblemDetail(
            type="about:blank",
            title=str(exc.detail),
            status=exc.status_code,
            detail=str(exc.detail),
            request_id=_request_id(request),
        )
        return JSONResponse(
            problem.to_dict(), status_code=exc.status_code, media_type=PROBLEM_CONTENT_TYPE
        )

    @app.exception_handler(RequestValidationError)
    async def validation_problem(request: Request, exc: RequestValidationError) -> JSONResponse:
        problem = ProblemDetail(
            type="https://crucible.dev/problems/validation",
            title="Request validation failed",
            status=422,
            detail="One or more request fields are invalid.",
            request_id=_request_id(request),
        )
        return JSONResponse(
            {**problem.to_dict(), "errors": exc.errors()},
            status_code=422,
            media_type=PROBLEM_CONTENT_TYPE,
        )

    return app


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "")) or request.headers.get(
        REQUEST_ID_HEADER, ""
    )


async def _audit_denial(request: Request, exc: DomainError) -> None:
    """Append an ACCESS_DENIED row in its own transaction.

    A principal exists for a 403 (authenticated, not entitled) and does not for
    a 401 (authentication itself failed); both are recorded, with whatever
    attribution is available.
    """
    principal: Principal | None = getattr(request.state, "principal", None)
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        return
    try:
        async with factory() as session:
            await SqlAuditSink(session).record(
                AuditEntry(
                    organization_id=principal.organization_id if principal else None,
                    actor_type=principal.actor_type if principal else ActorType.USER,
                    actor_id=principal.actor_id if principal else None,
                    action=AuditAction.ACCESS_DENIED,
                    result=AuditResult.DENIED,
                    target_type="request",
                    target_id=None,
                    request_id=_request_id(request),
                    metadata={
                        "status": exc.problem.status,
                        "reason": exc.problem.type.rsplit("/", 1)[-1],
                        "method": request.method,
                        "path": request.url.path,
                    },
                )
            )
            await session.commit()
    except Exception:
        logger.exception("failed to record access denial")
