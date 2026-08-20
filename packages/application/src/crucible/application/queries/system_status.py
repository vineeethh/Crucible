"""Use case: aggregate dependency probes into a system readiness status."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from crucible.application.ports import HealthProbe
from crucible.domain import ComponentHealth, HealthState, SystemStatus


class GetSystemStatus:
    """Runs all probes concurrently and reports the aggregate.

    A probe that raises (despite the port contract) is converted to DOWN
    rather than failing the whole readiness check — the readiness endpoint
    must itself be reliable.
    """

    def __init__(self, probes: Sequence[HealthProbe]) -> None:
        self._probes = tuple(probes)

    async def __call__(self) -> SystemStatus:
        results = await asyncio.gather(
            *(self._run(p) for p in self._probes),
        )
        return SystemStatus(components=tuple(results))

    @staticmethod
    async def _run(probe: HealthProbe) -> ComponentHealth:
        try:
            return await probe.check()
        except Exception as exc:
            return ComponentHealth(
                name=probe.name,
                state=HealthState.DOWN,
                detail=f"probe raised {type(exc).__name__}",
            )
