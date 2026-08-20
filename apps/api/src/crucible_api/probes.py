"""Concrete HealthProbe adapters wired into application ports."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from crucible.db.engine import ping as db_ping
from crucible.domain import ComponentHealth, HealthState


class DatabaseProbe:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @property
    def name(self) -> str:
        return "postgres"

    async def check(self) -> ComponentHealth:
        return await db_ping(self._engine, name=self.name)


class RedisProbe:
    def __init__(self, client: Any) -> None:  # redis.asyncio.Redis; Any keeps mypy strict happy
        self._client = client

    @property
    def name(self) -> str:
        return "redis"

    async def check(self) -> ComponentHealth:
        start = time.perf_counter()
        try:
            await self._client.ping()
        except Exception as exc:
            return ComponentHealth(
                name=self.name, state=HealthState.DOWN, detail=type(exc).__name__
            )
        latency = (time.perf_counter() - start) * 1000
        return ComponentHealth(name=self.name, state=HealthState.OK, latency_ms=round(latency, 2))
