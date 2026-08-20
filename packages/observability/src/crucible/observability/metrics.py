"""Reliability, cost, and latency metrics aggregated from run telemetry.

Pure functions over a list of `RunTelemetry` records (the API/db builds them from
queries), so the aggregation is trivially testable and has no infrastructure
dependency. These feed the reliability and cost dashboards and the SLIs.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from crucible.domain import TERMINAL_RUN_STATES, RunStatus


@dataclass(frozen=True, slots=True)
class RunTelemetry:
    run_id: str
    status: str
    failure_category: str | None
    cost_usd: float
    latency_ms: int
    attempt_count: int
    trace_complete: bool


@dataclass(frozen=True, slots=True)
class ReliabilityMetrics:
    total: int
    terminal: int
    terminal_states: dict[str, int]
    answered: int
    abstained: int
    technical_completion_rate: float  # terminal-non-error / terminal
    trace_completeness: float
    failure_taxonomy: dict[str, int]


@dataclass(frozen=True, slots=True)
class CostLatencyMetrics:
    runs_with_cost: int
    total_cost_usd: float
    cost_attribution_completeness: float  # runs with a cost value / runs that ran a model
    latency_p50_ms: int
    latency_p95_ms: int
    latency_p99_ms: int


_OPERATIONAL = frozenset({"policy_denied", "budget_exhausted", "cancelled"})


def reliability(runs: list[RunTelemetry]) -> ReliabilityMetrics:
    total = len(runs)
    terminal = [r for r in runs if RunStatus(r.status) in TERMINAL_RUN_STATES]
    states = Counter(r.status for r in terminal)
    taxonomy = Counter(r.failure_category for r in runs if r.failure_category)
    answered = states.get("answered", 0)
    abstained = states.get("abstained", 0)
    # Technical completion: reached a genuine agent outcome (answered/abstained/
    # needs_review), excluding operational terminals (cancelled, budget, policy).
    completed = sum(v for s, v in states.items() if s not in _OPERATIONAL)
    trace_ok = sum(1 for r in terminal if r.trace_complete)
    return ReliabilityMetrics(
        total=total,
        terminal=len(terminal),
        terminal_states=dict(sorted(states.items())),
        answered=answered,
        abstained=abstained,
        technical_completion_rate=_ratio(completed, len(terminal)),
        trace_completeness=_ratio(trace_ok, len(terminal)),
        failure_taxonomy={k: v for k, v in sorted(taxonomy.items())},
    )


def cost_latency(runs: list[RunTelemetry]) -> CostLatencyMetrics:
    ran_model = [r for r in runs if r.attempt_count > 0]
    with_cost = [r for r in ran_model if r.cost_usd > 0 or r.cost_usd == 0.0]
    latencies = sorted(r.latency_ms for r in runs if r.latency_ms > 0)
    return CostLatencyMetrics(
        runs_with_cost=len(with_cost),
        total_cost_usd=round(sum(r.cost_usd for r in runs), 6),
        cost_attribution_completeness=_ratio(len(with_cost), len(ran_model)),
        latency_p50_ms=_percentile(latencies, 50),
        latency_p95_ms=_percentile(latencies, 95),
        latency_p99_ms=_percentile(latencies, 99),
    )


def _ratio(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def _percentile(sorted_values: list[int], pct: int) -> int:
    if not sorted_values:
        return 0
    # Nearest-rank percentile.
    rank = max(1, (pct * len(sorted_values) + 99) // 100)
    return sorted_values[min(rank - 1, len(sorted_values) - 1)]
