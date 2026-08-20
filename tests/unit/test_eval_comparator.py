"""Paired bootstrap CI and the regression gate — including the DoD's
"catch a deliberately injected regression"."""

from crucible.evaluation import GateStatus, evaluate_gate, paired_bootstrap_ci
from crucible.evaluation.scorers import CaseScore


def _scores(
    correct: dict[str, bool], *, policy: dict[str, bool] | None = None
) -> dict[str, CaseScore]:
    policy = policy or {}
    return {
        cid: CaseScore(case_id=cid, correct=c, policy_ok=policy.get(cid, True))
        for cid, c in correct.items()
    }


def test_bootstrap_is_deterministic() -> None:
    b = [1, 1, 1, 1, 0, 1, 1, 1]
    c = [1, 0, 1, 0, 0, 1, 1, 0]
    first = paired_bootstrap_ci(b, c, seed=12345)
    second = paired_bootstrap_ci(b, c, seed=12345)
    assert first == second  # fixed seed => reproducible interval


def test_identical_scores_have_zero_delta_and_ci() -> None:
    v = [1, 1, 0, 1]
    assert paired_bootstrap_ci(v, v) == (0.0, 0.0, 0.0)


def test_improvement_has_positive_delta() -> None:
    delta, _lo, _hi = paired_bootstrap_ci([0, 0, 0, 0], [1, 1, 1, 0])
    assert delta > 0


def test_gate_passes_when_identical() -> None:
    scores = _scores({f"c{i}": True for i in range(10)})
    decision = evaluate_gate(scores, scores, tolerance=0.02)
    assert decision.status is GateStatus.PASS
    assert decision.delta == 0.0


def test_gate_blocks_a_material_regression() -> None:
    """The DoD case: a candidate that fails several cases the baseline passed is
    blocked (the upper CI bound falls below the tolerance)."""
    ids = [f"c{i}" for i in range(16)]
    baseline = _scores({i: True for i in ids})
    # Candidate fails 5 of 16.
    candidate = _scores({i: (idx >= 5) for idx, i in enumerate(ids)})
    decision = evaluate_gate(baseline, candidate, tolerance=0.02)
    assert decision.status is GateStatus.BLOCK
    assert len(decision.correctness_regressions) == 5
    assert decision.ci_hi < -0.02


def test_gate_flags_an_inconclusive_regression() -> None:
    ids = [f"c{i}" for i in range(20)]
    baseline = _scores({i: True for i in ids})
    # A single regression: the point estimate dips but the interval is wide.
    candidate = _scores({i: (idx != 0) for idx, i in enumerate(ids)})
    decision = evaluate_gate(baseline, candidate, tolerance=0.02)
    assert decision.status is GateStatus.FLAG
    assert decision.delta < 0


def test_policy_hard_failure_blocks_regardless_of_correctness() -> None:
    """A contract/safety failure blocks even if correctness is unchanged — a
    passing correctness delta can never rescue a policy violation."""
    ids = [f"c{i}" for i in range(10)]
    baseline = _scores({i: True for i in ids})
    candidate = _scores({i: True for i in ids}, policy={"c3": False})
    decision = evaluate_gate(baseline, candidate, tolerance=0.02)
    assert decision.status is GateStatus.BLOCK
    assert "c3" in decision.policy_regressions
