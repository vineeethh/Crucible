"""Health and build-information value objects for the readiness/version path."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class HealthState(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    """Result of probing one dependency (database, queue, storage...)."""

    name: str
    state: HealthState
    detail: str = ""
    latency_ms: float | None = None


@dataclass(frozen=True, slots=True)
class SystemStatus:
    """Aggregated readiness of the service and its probed dependencies."""

    components: tuple[ComponentHealth, ...] = field(default=())

    @property
    def state(self) -> HealthState:
        if not self.components:
            return HealthState.OK
        states = {c.state for c in self.components}
        if states == {HealthState.OK}:
            return HealthState.OK
        if HealthState.DOWN in states:
            return HealthState.DOWN
        return HealthState.DEGRADED

    @property
    def ready(self) -> bool:
        return self.state is not HealthState.DOWN


@dataclass(frozen=True, slots=True)
class BuildInfo:
    """Identity of the running build; every deploy must be traceable to a SHA."""

    git_sha: str
    version: str
    profile: str
    built_at: str = "unknown"
