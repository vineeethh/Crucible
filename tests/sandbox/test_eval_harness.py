"""End-to-end evaluation against the real sandbox (Phase 5 DoD).

Runs the full harness — agent plans, generates code, executes in the Docker
sandbox, is scored against the trusted oracles, and gated against the frozen
baseline. Proves the reference config reproduces the baseline (PASS) and that a
deliberately regressed config is caught (not PASS).
"""

from __future__ import annotations

import asyncio

import pytest

from crucible.agent import FakeModel
from crucible.evaluation import (
    EvalConfig,
    ExperimentRunner,
    GateStatus,
    evaluate_gate,
    load_baseline,
    load_fixture,
    load_suite,
    repo_evals_dir,
)
from crucible.execution import ExecutionLimits
from tests.sandbox.conftest import requires_sandbox
from tests.support.agent_fakes import RegressedFakeModel

pytestmark = [pytest.mark.sandbox, requires_sandbox]

EVALS = repo_evals_dir()
CORE_SUITE = EVALS / "suites" / "core-v1.0.0.yaml"


def _run(model, executor, config, *, smoke: bool):
    suite = load_suite(CORE_SUITE)
    if smoke:
        suite = suite.smoke_suite()
    fixture, content = load_fixture(suite.fixture)
    runner = ExperimentRunner(
        model=model, executor=executor, limits=ExecutionLimits(wall_seconds=25), config=config
    )
    return suite, asyncio.run(runner.run(suite, fixture, content))


def test_reference_config_reproduces_the_baseline(executor) -> None:
    config = EvalConfig(id="reference@1", model_backend="fake", executor_backend="docker")
    suite, result = _run(FakeModel(), executor, config, smoke=True)
    baseline = load_baseline(EVALS / "baseline.json")

    # Every smoke case the reference answers correctly (real computation).
    for cid in suite.smoke:
        assert result.scores[cid].correct, f"{cid} should pass for the reference config"

    gate = evaluate_gate(
        {c: baseline.scores()[c] for c in suite.smoke},
        result.scores,
        tolerance=baseline.tolerance,
    )
    assert gate.status is GateStatus.PASS


def test_injected_regression_is_caught(executor) -> None:
    config = EvalConfig(
        id="regressed@1", model_backend="fake", executor_backend="docker", model_variant="regressed"
    )
    _suite, result = _run(RegressedFakeModel(), executor, config, smoke=False)
    baseline = load_baseline(EVALS / "baseline.json")

    gate = evaluate_gate(baseline.scores(), result.scores, tolerance=baseline.tolerance)

    # The harness must catch it: the gate is not PASS and names the regressed cases.
    assert gate.status is not GateStatus.PASS
    assert gate.correctness_regressions, "the regression produced no detected failures"
