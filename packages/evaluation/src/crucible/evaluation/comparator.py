"""Paired comparison and the regression gate (master plan §10.7, metric contract §5).

Correctness is compared *per case* (paired), never as two unrelated aggregate
percentages, and the aggregate delta carries a bootstrap confidence interval.
The gate blocks a material regression (the upper CI bound falls below the
tolerance) or any policy/contract hard failure, flags an inconclusive
regression for review, and never calls a change an improvement when the interval
spans zero.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import StrEnum

from crucible.evaluation.scorers import CaseScore

DEFAULT_ITERATIONS = 2000
DEFAULT_SEED = 12345  # fixed => the confidence interval is reproducible
DEFAULT_ALPHA = 0.05


class GateStatus(StrEnum):
    PASS = "pass"
    FLAG = "flag"  # inconclusive regression — human review
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class GateDecision:
    status: GateStatus
    delta: float
    ci_lo: float
    ci_hi: float
    tolerance: float
    reasons: list[str] = field(default_factory=list)
    policy_regressions: list[str] = field(default_factory=list)
    correctness_regressions: list[str] = field(default_factory=list)


def paired_bootstrap_ci(
    baseline: list[int],
    candidate: list[int],
    *,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = DEFAULT_SEED,
    alpha: float = DEFAULT_ALPHA,
) -> tuple[float, float, float]:
    """Bootstrap the paired per-case correctness difference (candidate - baseline).
    Deterministic given the seed. Returns (delta, ci_lo, ci_hi)."""
    n = len(baseline)
    if n == 0 or n != len(candidate):
        return 0.0, 0.0, 0.0
    diffs = [c - b for b, c in zip(baseline, candidate, strict=True)]
    delta = sum(diffs) / n
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(iterations):
        total = 0
        for _ in range(n):
            total += diffs[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    lo = means[int((alpha / 2) * iterations)]
    hi = means[min(iterations - 1, int((1 - alpha / 2) * iterations))]
    return round(delta, 4), round(lo, 4), round(hi, 4)


def evaluate_gate(
    baseline: dict[str, CaseScore],
    candidate: dict[str, CaseScore],
    *,
    tolerance: float,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = DEFAULT_SEED,
) -> GateDecision:
    case_ids = sorted(set(baseline) & set(candidate))
    b_vec = [1 if baseline[c].correct else 0 for c in case_ids]
    c_vec = [1 if candidate[c].correct else 0 for c in case_ids]
    delta, lo, hi = paired_bootstrap_ci(b_vec, c_vec, iterations=iterations, seed=seed)

    reasons: list[str] = []

    # Any candidate policy/contract hard failure is a blocking gate — a passing
    # correctness delta can never rescue a contract violation (metric contract §4).
    policy_regressions = [c for c in case_ids if candidate[c].hard_fail]
    correctness_regressions = [
        c for c in case_ids if baseline[c].correct and not candidate[c].correct
    ]

    status = GateStatus.PASS
    if policy_regressions:
        status = GateStatus.BLOCK
        reasons.append(f"policy/contract hard failure on {len(policy_regressions)} case(s)")
    if hi < -tolerance:
        status = GateStatus.BLOCK
        reasons.append(
            f"material correctness regression: upper CI bound {hi} < -tolerance {-tolerance}"
        )
    elif status is not GateStatus.BLOCK and delta < 0:
        status = GateStatus.FLAG
        reasons.append(
            f"correctness regressed (delta {delta}) but the interval [{lo}, {hi}] is inconclusive"
        )

    if status is GateStatus.PASS:
        reasons.append(f"no regression (delta {delta}, CI [{lo}, {hi}])")

    return GateDecision(
        status=status,
        delta=delta,
        ci_lo=lo,
        ci_hi=hi,
        tolerance=tolerance,
        reasons=reasons,
        policy_regressions=policy_regressions,
        correctness_regressions=correctness_regressions,
    )
