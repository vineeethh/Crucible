"""Judge calibration: weighted kappa and agreement against held-out labels."""

import asyncio

from crucible.evaluation import (
    default_judge,
    load_holdout,
    quadratic_weighted_kappa,
    repo_evals_dir,
    run_calibration,
)

HOLDOUT = repo_evals_dir() / "calibration" / "judge-holdout-v1.yaml"


def test_kappa_perfect_agreement() -> None:
    a = [0, 1, 2, 0, 1, 2]
    assert quadratic_weighted_kappa(a, a) == 1.0


def test_kappa_constant_identical_is_one() -> None:
    assert quadratic_weighted_kappa([2, 2, 2], [2, 2, 2]) == 1.0


def test_kappa_systematic_max_disagreement_is_zero_or_negative() -> None:
    assert quadratic_weighted_kappa([0, 0, 0], [2, 2, 2]) <= 0.0


def test_kappa_partial_agreement_is_between() -> None:
    k = quadratic_weighted_kappa([0, 1, 2, 2], [0, 1, 2, 1])
    assert 0.0 < k < 1.0


def test_holdout_loads_and_is_stratified() -> None:
    rubric, items = load_holdout(HOLDOUT)
    assert rubric == "judge-rubric@1"
    assert len(items) >= 10
    # Contains both grounded and ungrounded/abstention examples.
    assert any(i.human["groundedness"] == 2 for i in items)
    assert any(i.human["groundedness"] == 0 for i in items)


def test_calibration_reports_agreement() -> None:
    _rubric, items = load_holdout(HOLDOUT)
    report = asyncio.run(run_calibration(default_judge(), items))
    assert report.n_items == len(items)
    assert set(report.per_dimension) == {"groundedness", "provenance", "usefulness", "uncertainty"}
    # The deterministic judge agrees substantially with the human labels.
    assert report.overall_raw_agreement > 0.6
    assert -1.0 <= report.mean_weighted_kappa <= 1.0
