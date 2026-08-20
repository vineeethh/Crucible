"""Engine factories and a readiness ping. URLs are passed in by the composing
app's settings object — this module never reads environment variables."""

from __future__ import annotations

import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crucible.domain import ComponentHealth, HealthState


def create_async_engine_from_url(url: str, *, pool_pre_ping: bool = True) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=pool_pre_ping)


async def ping(engine: AsyncEngine, *, name: str = "postgres") -> ComponentHealth:
    """SELECT 1 readiness probe; reports DOWN instead of raising."""
    start = time.perf_counter()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        return ComponentHealth(name=name, state=HealthState.DOWN, detail=type(exc).__name__)
    latency = (time.perf_counter() - start) * 1000
    return ComponentHealth(name=name, state=HealthState.OK, latency_ms=round(latency, 2))
