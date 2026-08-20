"""Run routes: create (202 + idempotency), get, cancel, events, SSE stream."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crucible.application import (
    CancelRun,
    CreateRun,
    CreateRunInput,
    GetRun,
    ListRunAttempts,
    ListRunEvents,
    ListRuns,
    ResolveRunReview,
)
from crucible.db import SqlRunRepository
from crucible.domain import TERMINAL_RUN_STATES, Principal, RunStatus
from crucible_api.dependencies import (
    AgentStoreDep,
    AuditDep,
    BudgetRepoDep,
    DatasetRepoDep,
    PrincipalDep,
    RequestIdDep,
    RunRepoDep,
    SettingsDep,
    run_rate_limit,
)
from crucible_api.queue import ArqJobQueue
from crucible_api.schemas import AttemptOut, CreateRunIn, ReviewIn, RunEventOut, RunOut

router = APIRouter(prefix="/v1/runs", tags=["runs"])

SSE_POLL_SECONDS = 1.0
SSE_MAX_SECONDS = 300


@router.post(
    "",
    response_model=RunOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(run_rate_limit)],
)
async def create_run(
    body: CreateRunIn,
    request: Request,
    response: Response,
    principal: PrincipalDep,
    runs: RunRepoDep,
    datasets: DatasetRepoDep,
    audit: AuditDep,
    settings: SettingsDep,
    budgets: BudgetRepoDep,
    request_id: RequestIdDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RunOut:
    """Accepts the run and returns immediately (ADR-004). Progress is available
    from `GET /v1/runs/{id}` and streamed from `/v1/runs/{id}/stream`."""
    record, created = await CreateRun(
        runs=runs,
        datasets=datasets,
        queue=ArqJobQueue(request.app.state.queue_pool),
        audit=audit,
        release_id=settings.git_sha,
        budgets=budgets,
    )(
        principal,
        CreateRunInput(
            dataset_version_id=body.dataset_version_id,
            question=body.question,
            idempotency_key=idempotency_key,
        ),
        request_id=request_id,
    )
    if not created:
        # Idempotent replay: same key, same body, same run.
        response.status_code = status.HTTP_200_OK
    response.headers["Location"] = f"/v1/runs/{record.id}"
    return RunOut.of(record)


@router.get("", response_model=list[RunOut])
async def list_runs(
    principal: PrincipalDep, runs: RunRepoDep, limit: int = 50, offset: int = 0
) -> list[RunOut]:
    records = await ListRuns(runs=runs)(principal, limit=limit, offset=offset)
    return [RunOut.of(r) for r in records]


@router.get("/{run_id}", response_model=RunOut)
async def get_run(run_id: uuid.UUID, principal: PrincipalDep, runs: RunRepoDep) -> RunOut:
    return RunOut.of(await GetRun(runs=runs)(principal, run_id))


@router.post("/{run_id}/cancel", response_model=RunOut)
async def cancel_run(
    run_id: uuid.UUID,
    principal: PrincipalDep,
    runs: RunRepoDep,
    audit: AuditDep,
    request_id: RequestIdDep,
) -> RunOut:
    record = await CancelRun(runs=runs, audit=audit)(principal, run_id, request_id=request_id)
    return RunOut.of(record)


@router.get("/{run_id}/attempts", response_model=list[AttemptOut])
async def list_attempts(
    run_id: uuid.UUID,
    principal: PrincipalDep,
    runs: RunRepoDep,
    attempts: AgentStoreDep,
) -> list[AttemptOut]:
    records = await ListRunAttempts(runs=runs, attempts=attempts)(principal, run_id)
    return [AttemptOut.of(r) for r in records]


@router.post("/{run_id}/review", response_model=RunOut)
async def submit_review(
    run_id: uuid.UUID,
    body: ReviewIn,
    request: Request,
    principal: PrincipalDep,
    runs: RunRepoDep,
    audit: AuditDep,
    request_id: RequestIdDep,
) -> RunOut:
    record = await ResolveRunReview(
        runs=runs, queue=ArqJobQueue(request.app.state.queue_pool), audit=audit
    )(principal, run_id, approve=body.approve, request_id=request_id)
    return RunOut.of(record)


@router.get("/{run_id}/events", response_model=list[RunEventOut])
async def list_events(
    run_id: uuid.UUID,
    principal: PrincipalDep,
    runs: RunRepoDep,
    after: int = 0,
) -> list[RunEventOut]:
    records = await ListRunEvents(runs=runs)(principal, run_id, after_sequence=after)
    return [RunEventOut.of(r) for r in records]


@router.get("/{run_id}/stream")
async def stream_run(
    run_id: uuid.UUID, request: Request, principal: PrincipalDep, runs: RunRepoDep
) -> StreamingResponse:
    """SSE progress stream.

    Ownership is checked once, up front, with the request-scoped session. The
    stream then uses its own short-lived sessions per poll so it does not hold
    a database transaction open for its lifetime. Polling `GET /events?after=`
    remains supported for clients behind proxies that break SSE.
    """
    await GetRun(runs=runs)(principal, run_id)  # 404 for another tenant's run
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return StreamingResponse(
        _events(run_id, principal, factory, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _events(
    run_id: uuid.UUID,
    principal: Principal,
    factory: async_sessionmaker[AsyncSession],
    request: Request,
) -> AsyncIterator[str]:
    last_seq = 0
    waited = 0.0
    while waited < SSE_MAX_SECONDS:
        if await request.is_disconnected():
            return
        async with factory() as session:
            repo = SqlRunRepository(session)
            events = await repo.list_events(run_id=run_id, after_sequence=last_seq)
            for event in events:
                last_seq = event.sequence_no
                payload = {
                    "sequence_no": event.sequence_no,
                    "event_type": event.event_type.value,
                    "payload": event.payload,
                    "created_at": event.created_at.isoformat(),
                }
                yield f"id: {event.sequence_no}\nevent: {event.event_type.value}\n"
                yield f"data: {json.dumps(payload)}\n\n"

            run = await repo.get_run(organization_id=principal.organization_id, run_id=run_id)
            if run is not None and RunStatus(run.status) in TERMINAL_RUN_STATES:
                yield f"event: close\ndata: {json.dumps({'status': run.status.value})}\n\n"
                return

        await asyncio.sleep(SSE_POLL_SECONDS)
        waited += SSE_POLL_SECONDS

    yield 'event: timeout\ndata: {"reason":"stream_budget_exhausted"}\n\n'
