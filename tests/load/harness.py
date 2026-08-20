"""The load/soak engine: fixed concurrency of async workers hammering a set of
weighted request scenarios for a duration, with nearest-rank latency
percentiles and a hard pass/fail gate.

Transport-agnostic: it drives any `httpx.AsyncClient`, so the same code loads a
real staging URL (over the network) or the ASGI app in-process (the CI smoke).
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

# A scenario returns the HTTP response so the harness can classify it. It is
# given the shared client and must not raise for an expected error status — only
# transport failures (timeouts, resets) raise, and those count as errors.
ScenarioFn = Callable[[httpx.AsyncClient], Awaitable[httpx.Response]]


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    weight: int
    call: ScenarioFn


@dataclass(frozen=True, slots=True)
class LoadThresholds:
    max_error_rate: float = 0.01  # ≤ 1% of requests may fail
    max_p95_ms: float = 750.0
    max_p99_ms: float = 1500.0
    min_throughput_rps: float = 0.0  # 0 disables the throughput gate


@dataclass(slots=True)
class LoadResult:
    total: int = 0
    errors: int = 0
    duration_s: float = 0.0
    latencies_ms: list[float] = field(default_factory=list)
    status_counts: dict[int, int] = field(default_factory=dict)
    per_scenario: dict[str, int] = field(default_factory=dict)

    @property
    def error_rate(self) -> float:
        return self.errors / self.total if self.total else 1.0

    @property
    def throughput_rps(self) -> float:
        return self.total / self.duration_s if self.duration_s else 0.0

    def percentile(self, pct: float) -> float:
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        rank = max(1, math.ceil(pct / 100 * len(ordered)))
        return round(ordered[min(rank, len(ordered)) - 1], 2)

    @property
    def p50_ms(self) -> float:
        return self.percentile(50)

    @property
    def p95_ms(self) -> float:
        return self.percentile(95)

    @property
    def p99_ms(self) -> float:
        return self.percentile(99)

    def gate(self, thresholds: LoadThresholds) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if self.error_rate > thresholds.max_error_rate:
            reasons.append(f"error rate {self.error_rate:.3%} > {thresholds.max_error_rate:.3%}")
        if self.p95_ms > thresholds.max_p95_ms:
            reasons.append(f"p95 {self.p95_ms}ms > {thresholds.max_p95_ms}ms")
        if self.p99_ms > thresholds.max_p99_ms:
            reasons.append(f"p99 {self.p99_ms}ms > {thresholds.max_p99_ms}ms")
        if thresholds.min_throughput_rps and self.throughput_rps < thresholds.min_throughput_rps:
            reasons.append(
                f"throughput {self.throughput_rps:.1f} rps < {thresholds.min_throughput_rps} rps"
            )
        return (not reasons), reasons

    def summary(self) -> str:
        return (
            f"requests={self.total} errors={self.errors} "
            f"({self.error_rate:.2%}) rps={self.throughput_rps:.1f} "
            f"p50={self.p50_ms}ms p95={self.p95_ms}ms p99={self.p99_ms}ms "
            f"statuses={dict(sorted(self.status_counts.items()))}"
        )


def _expand(scenarios: list[Scenario]) -> list[Scenario]:
    plan: list[Scenario] = []
    for s in scenarios:
        plan.extend([s] * max(1, s.weight))
    return plan


async def _warmup(client: httpx.AsyncClient, scenarios: list[Scenario], rounds: int) -> None:
    """Pay cold-start costs (lifespan, first DB/Redis connections, first query
    plans) before measuring, so the reported percentiles reflect steady state
    rather than one-time connection setup."""
    for _ in range(rounds):
        for scenario in scenarios:
            with contextlib.suppress(Exception):
                await scenario.call(client)


async def run_load(
    client: httpx.AsyncClient,
    scenarios: list[Scenario],
    *,
    concurrency: int,
    duration_s: float,
    warmup_rounds: int = 0,
    ok_statuses: frozenset[int] = frozenset({200, 201, 202}),
) -> LoadResult:
    """Drive `scenarios` at `concurrency` for `duration_s` seconds. A response
    whose status is not in `ok_statuses`, and any transport exception, counts as
    an error. `warmup_rounds` sequential passes over the scenarios run first and
    are not measured."""
    if warmup_rounds:
        await _warmup(client, scenarios, warmup_rounds)
    result = LoadResult()
    plan = _expand(scenarios)
    deadline = time.monotonic() + duration_s
    lock = asyncio.Lock()
    counter = {"i": 0}

    async def worker() -> None:
        while time.monotonic() < deadline:
            async with lock:
                scenario = plan[counter["i"] % len(plan)]
                counter["i"] += 1
            started = time.perf_counter()
            try:
                response = await scenario.call(client)
                elapsed_ms = (time.perf_counter() - started) * 1000
                ok = response.status_code in ok_statuses
                status = response.status_code
            except Exception:
                elapsed_ms = (time.perf_counter() - started) * 1000
                ok = False
                status = 0  # transport failure
            async with lock:
                result.total += 1
                result.latencies_ms.append(elapsed_ms)
                result.status_counts[status] = result.status_counts.get(status, 0) + 1
                result.per_scenario[scenario.name] = result.per_scenario.get(scenario.name, 0) + 1
                if not ok:
                    result.errors += 1

    start = time.monotonic()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    result.duration_s = time.monotonic() - start
    return result
