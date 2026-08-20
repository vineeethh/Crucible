"""Reliability, cost/latency, alert, and per-run trace endpoints.

The API composes the application read queries with the observability aggregation
functions (the application layer stays free of the observability dependency).
The trace endpoint returns the redacted, export-safe representation.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict

from fastapi import APIRouter

from crucible.application import (
    GetCacheStats,
    GetRun,
    GetRunTelemetry,
    ListRunAttempts,
    ListRunEvents,
    MetricsRepository,
)
from crucible.domain import Principal
from crucible.observability import (
    RunTelemetry,
    RunTraceInput,
    build_run_trace,
    cost_latency,
    evaluate_slo_alerts,
    export_trace,
    reliability,
)
from crucible_api.dependencies import (
    AgentStoreDep,
    MetricsRepoDep,
    PrincipalDep,
    RunRepoDep,
)
from crucible_api.schemas import AlertOut, CacheStatsOut, CostLatencyOut, ReliabilityOut

router = APIRouter(prefix="/v1/metrics", tags=["observability"])
trace_router = APIRouter(prefix="/v1/runs", tags=["observability"])


async def _telemetry(
    principal: Principal, metrics: MetricsRepository, limit: int
) -> list[RunTelemetry]:
    rows = await GetRunTelemetry(metrics=metrics)(principal, limit=limit)
    return [
        RunTelemetry(
            run_id=str(r.run_id),
            status=r.status,
            failure_category=r.failure_category,
            cost_usd=r.cost_usd,
            latency_ms=r.latency_ms,
            attempt_count=r.attempt_count,
            trace_complete=r.trace_complete,
        )
        for r in rows
    ]


@router.get("/reliability", response_model=ReliabilityOut)
async def reliability_metrics(
    principal: PrincipalDep, metrics: MetricsRepoDep, limit: int = 500
) -> ReliabilityOut:
    m = reliability(await _telemetry(principal, metrics, limit))
    return ReliabilityOut(**asdict(m))


@router.get("/cost", response_model=CostLatencyOut)
async def cost_metrics(
    principal: PrincipalDep, metrics: MetricsRepoDep, limit: int = 500
) -> CostLatencyOut:
    m = cost_latency(await _telemetry(principal, metrics, limit))
    return CostLatencyOut(**asdict(m))


@router.get("/cache", response_model=CacheStatsOut)
async def cache_metrics(principal: PrincipalDep, metrics: MetricsRepoDep) -> CacheStatsOut:
    stats = await GetCacheStats(metrics=metrics)(principal)
    return CacheStatsOut(
        hits=stats.hits,
        misses=stats.misses,
        false_hits=stats.false_hits,
        stores=stats.stores,
        hit_rate=stats.hit_rate,
    )


@router.get("/alerts", response_model=list[AlertOut])
async def alerts(
    principal: PrincipalDep, metrics: MetricsRepoDep, limit: int = 500
) -> list[AlertOut]:
    m = reliability(await _telemetry(principal, metrics, limit))
    fired = evaluate_slo_alerts(m)
    return [
        AlertOut(
            rule_id=a.rule_id,
            severity=a.severity.value,
            firing=a.firing,
            detail=a.detail,
            runbook=a.runbook,
        )
        for a in fired
    ]


@trace_router.get("/{run_id}/trace")
async def run_trace(
    run_id: uuid.UUID,
    principal: PrincipalDep,
    runs: RunRepoDep,
    attempts: AgentStoreDep,
) -> dict[str, object]:
    run = await GetRun(runs=runs)(principal, run_id)  # 404 for another tenant
    events = await ListRunEvents(runs=runs)(principal, run_id)
    attempt_records = await ListRunAttempts(runs=runs, attempts=attempts)(principal, run_id)
    trace = build_run_trace(
        RunTraceInput(
            run_id=str(run.id),
            organization_id=str(run.organization_id),
            status=run.status.value,
            config_manifest=run.config_manifest,
            events=[
                {
                    "event_type": e.event_type.value,
                    "payload": e.payload,
                    "sequence_no": e.sequence_no,
                }
                for e in events
            ],
            attempts=[
                {
                    "kind": a.kind,
                    "model_id": a.model_id,
                    "exit_class": a.exit_class,
                    "duration_ms": a.duration_ms,
                    "cost_usd": a.cost_usd,
                    "payload": a.payload,
                }
                for a in attempt_records
            ],
        )
    )
    return export_trace(trace, question=run.question)
