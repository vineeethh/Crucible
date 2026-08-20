"""The held-out router experiment (master plan Phase 8).

Runs the same suite under two declared policies — the single-tier default and
the two-tier routed gateway — over the *real* agent graph and sandbox, then
reports quality, cost, latency, retry effect, and sample size for each policy,
plus a paired quality gate (the routed policy must not regress correctness).

Honesty rules baked in:
- escalations are counted and their cost INCLUDES the burned tier-1 call;
- costs are computed from the registry's declared prices; when those prices
  are synthetic (the offline fakes), the report says so in `pricing_note`;
- the quality comparison is the same paired bootstrap the release gate uses —
  a savings number is meaningless next to an unmeasured quality loss.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from crucible.agent import (
    DatasetView,
    EvalTrace,
    FakeLiteModel,
    FakeModel,
    ModelGateway,
    RouterPolicy,
    TieredModelGateway,
    run_to_completion,
)
from crucible.evaluation.comparator import evaluate_gate
from crucible.evaluation.config import EvalConfig
from crucible.evaluation.outcome import AgentOutcome, outcome_from_trace
from crucible.evaluation.schemas import EvalFixture, EvalSuite
from crucible.evaluation.scorers import CaseScore, score_case
from crucible.execution import ExecutionLimits, Executor

QUALITY_TOLERANCE = 0.02  # same tolerance the release gate applies


@dataclass(frozen=True, slots=True)
class PolicyGateway:
    """A named, versioned gateway configuration under experiment."""

    policy_id: str
    policy_version: str
    gateway: ModelGateway
    config: EvalConfig


def default_policies() -> list[PolicyGateway]:
    """The two offline policies: the reference single-tier gateway, and the
    two-tier router (cheap FakeLite primary, reference secondary)."""
    router_policy = RouterPolicy()
    return [
        PolicyGateway(
            policy_id="default",
            policy_version="single-tier@1",
            gateway=FakeModel(),
            config=EvalConfig(
                id="default", model_backend="fake", executor_backend="", model_variant="reference"
            ),
        ),
        PolicyGateway(
            policy_id="routed",
            policy_version=router_policy.policy_version,
            gateway=TieredModelGateway(
                primary=FakeLiteModel(), secondary=FakeModel(), policy=router_policy
            ),
            config=EvalConfig(
                id="routed", model_backend="fake", executor_backend="", model_variant="two-tier"
            ),
        ),
    ]


@dataclass(slots=True)
class _CaseRun:
    outcome: AgentOutcome
    score: CaseScore
    escalated: bool
    fallback: bool
    cost_known: bool


def _route_flags(trace: EvalTrace) -> tuple[bool, bool]:
    escalated = False
    fallback = False
    for attempt in trace.attempts:
        route = attempt.payload.get("route") if isinstance(attempt.payload, dict) else None
        if isinstance(route, dict) and route.get("escalated"):
            escalated = True
            if route.get("reason") == "primary_error":
                fallback = True
    return escalated, fallback


def _percentile(sorted_values: list[int], pct: float) -> int:
    if not sorted_values:
        return 0
    import math

    rank = max(1, math.ceil(pct * len(sorted_values)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


@dataclass(slots=True)
class PolicySummary:
    policy_id: str
    policy_version: str
    config_hash: str
    n_cases: int = 0
    accuracy: float = 0.0
    answered: int = 0
    abstained: int = 0
    escalations: int = 0
    fallbacks: int = 0
    total_cost_usd: float = 0.0
    cost_attribution_complete: bool = True
    mean_latency_ms: int = 0
    p95_latency_ms: int = 0
    mean_execute_attempts: float = 0.0  # the retry effect: repairs re-execute


async def run_policy(
    policy: PolicyGateway,
    suite: EvalSuite,
    fixture: EvalFixture,
    fixture_bytes: bytes,
    *,
    executor: Executor,
    limits: ExecutionLimits,
) -> tuple[PolicySummary, dict[str, _CaseRun]]:
    dataset = DatasetView(
        version_id=fixture.id,
        object_key=f"(eval:{fixture.id})",
        content_sha256=fixture.sha256,
        media_type="text/csv",
        filename=fixture.file,
        profile=fixture.column_views(),
    )
    runs: dict[str, _CaseRun] = {}
    latencies: list[int] = []
    for case in suite.cases:
        trace = await run_to_completion(
            model=policy.gateway,
            executor=executor,
            limits=limits,
            question=case.question,
            dataset=dataset,
            dataset_bytes=fixture_bytes,
        )
        outcome = outcome_from_trace(trace)
        escalated, fallback = _route_flags(trace)
        model_attempts = [a for a in trace.attempts if a.kind in ("plan", "code", "repair")]
        cost_known = all(a.cost_usd is not None for a in model_attempts)
        runs[case.id] = _CaseRun(
            outcome=outcome,
            score=score_case(case, outcome),
            escalated=escalated,
            fallback=fallback,
            cost_known=cost_known,
        )
        latencies.append(outcome.latency_ms)

    summary = PolicySummary(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        config_hash=policy.config.config_hash,
    )
    summary.n_cases = len(runs)
    if runs:
        summary.accuracy = round(sum(1 for r in runs.values() if r.score.correct) / len(runs), 4)
        summary.mean_execute_attempts = round(
            sum(r.outcome.attempt_count for r in runs.values()) / len(runs), 3
        )
    summary.answered = sum(1 for r in runs.values() if r.outcome.terminal == "answered")
    summary.abstained = sum(1 for r in runs.values() if r.outcome.terminal == "abstained")
    summary.escalations = sum(1 for r in runs.values() if r.escalated)
    summary.fallbacks = sum(1 for r in runs.values() if r.fallback)
    summary.total_cost_usd = round(sum(r.outcome.cost_usd for r in runs.values()), 6)
    summary.cost_attribution_complete = all(r.cost_known for r in runs.values())
    ordered = sorted(latencies)
    summary.mean_latency_ms = int(sum(ordered) / len(ordered)) if ordered else 0
    summary.p95_latency_ms = _percentile(ordered, 0.95)
    return summary, runs


async def run_router_experiment(
    suite: EvalSuite,
    fixture: EvalFixture,
    fixture_bytes: bytes,
    *,
    executor: Executor,
    limits: ExecutionLimits,
    git_sha: str = "unknown",
    policies: list[PolicyGateway] | None = None,
) -> dict[str, Any]:
    """Run every policy over the held-out suite and build the comparable
    report. The first policy is the baseline for the quality gate."""
    chosen = policies if policies is not None else default_policies()
    summaries: list[PolicySummary] = []
    per_policy_runs: dict[str, dict[str, _CaseRun]] = {}
    for policy in chosen:
        summary, runs = await run_policy(
            policy, suite, fixture, fixture_bytes, executor=executor, limits=limits
        )
        summaries.append(summary)
        per_policy_runs[policy.policy_id] = runs

    base_id = chosen[0].policy_id
    gates: dict[str, Any] = {}
    for policy in chosen[1:]:
        decision = evaluate_gate(
            {cid: r.score for cid, r in per_policy_runs[base_id].items()},
            {cid: r.score for cid, r in per_policy_runs[policy.policy_id].items()},
            tolerance=QUALITY_TOLERANCE,
        )
        gates[policy.policy_id] = {
            "status": decision.status.value,
            "delta": decision.delta,
            "ci_lo": decision.ci_lo,
            "ci_hi": decision.ci_hi,
            "tolerance": decision.tolerance,
            "reasons": decision.reasons,
        }

    cases: list[dict[str, Any]] = []
    for case in suite.cases:
        row: dict[str, Any] = {"id": case.id, "tags": list(case.tags)}
        for policy in chosen:
            run = per_policy_runs[policy.policy_id][case.id]
            row[policy.policy_id] = {
                "correct": run.score.correct,
                "terminal": run.outcome.terminal,
                "cost_usd": run.outcome.cost_usd,
                "latency_ms": run.outcome.latency_ms,
                "escalated": run.escalated,
            }
        cases.append(row)

    body: dict[str, Any] = {
        "kind": "router-experiment",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha,
        "suite": {"id": suite.id, "version": suite.version, "hash": suite.content_hash},
        "fixture_sha256": fixture.sha256,
        "executor_backend": executor.backend,
        "quality_tolerance": QUALITY_TOLERANCE,
        "pricing_note": (
            "Costs are computed from the model registry's declared prices; the "
            "fake provider's prices are SYNTHETIC (they exercise the accounting "
            "pipeline, not a market rate). Escalated calls include the burned "
            "tier-1 cost."
        ),
        "policies": [asdict(s) for s in summaries],
        "quality_gates": gates,
        "cases": cases,
    }
    canonical = json.dumps(body, separators=(",", ":"), sort_keys=True)
    body["content_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return body


def render_router_markdown(report: dict[str, Any]) -> str:
    """The shareable performance report (docs/evaluation/router-experiment.md)."""
    lines: list[str] = [
        "# Router experiment report",
        "",
        f"- generated: {report['generated_at']} · git `{report['git_sha']}` · "
        f"executor `{report['executor_backend']}`",
        f"- suite `{report['suite']['id']}@{report['suite']['version']}` "
        f"(hash `{report['suite']['hash'][:16]}`) · fixture `{report['fixture_sha256'][:16]}`",
        f"- report sha256 `{report['content_sha256'][:16]}`",
        "",
        f"> {report['pricing_note']}",
        "",
        "## Policies",
        "",
        "| policy | version | n | accuracy | answered | abstained | escalations | fallbacks "
        "| total cost (USD) | mean ms | p95 ms | mean executes |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in report["policies"]:
        lines.append(
            f"| {p['policy_id']} | `{p['policy_version']}` | {p['n_cases']} | {p['accuracy']} "
            f"| {p['answered']} | {p['abstained']} | {p['escalations']} | {p['fallbacks']} "
            f"| {p['total_cost_usd']} | {p['mean_latency_ms']} | {p['p95_latency_ms']} "
            f"| {p['mean_execute_attempts']} |"
        )
    lines += ["", "## Quality gates (vs the first policy)", ""]
    for policy_id, gate in report["quality_gates"].items():
        lines.append(
            f"- **{policy_id}**: {gate['status'].upper()} — paired Δ {gate['delta']}, "
            f"95% CI [{gate['ci_lo']}, {gate['ci_hi']}], tolerance {gate['tolerance']}"
        )
    lines += [
        "",
        "## Per-case",
        "",
        "| case | tags | "
        + " | ".join(f"{p['policy_id']} ✓/cost/esc" for p in report["policies"])
        + " |",
        "|---|---|" + "---|" * len(report["policies"]),
    ]
    for row in report["cases"]:
        cells = []
        for p in report["policies"]:
            r = row[p["policy_id"]]
            mark = "✓" if r["correct"] else "✗"
            esc = " ↑" if r.get("escalated") else ""
            cells.append(f"{mark} ${r['cost_usd']}{esc}")
        lines.append(f"| {row['id']} | {' '.join(row['tags'])} | " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)
