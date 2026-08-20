"""Crucible offline evaluation harness.

Boundary rule (import-linter): imports domain, execution, and agent (to run the
real graph) plus pydantic/pyyaml. It never imports db/api/worker/application —
the evaluation plane is decoupled from the serving plane.
"""

from crucible.evaluation.calibration import (
    CalibrationReport,
    DimensionAgreement,
    HoldoutItem,
    default_judge,
    load_holdout,
    quadratic_weighted_kappa,
    run_calibration,
)
from crucible.evaluation.comparator import (
    GateDecision,
    GateStatus,
    evaluate_gate,
    paired_bootstrap_ci,
)
from crucible.evaluation.config import EvalConfig
from crucible.evaluation.efficiency import (
    PolicyGateway,
    default_policies,
    render_router_markdown,
    run_router_experiment,
)
from crucible.evaluation.governance import (
    Baseline,
    baseline_from_result,
    load_baseline,
    write_baseline,
)
from crucible.evaluation.loader import (
    FixtureIntegrityError,
    load_fixture,
    load_suite,
    repo_evals_dir,
)
from crucible.evaluation.outcome import AgentOutcome, outcome_from_trace
from crucible.evaluation.report import build_report, render_markdown
from crucible.evaluation.runner import ExperimentResult, ExperimentRunner
from crucible.evaluation.schemas import (
    EvalCase,
    EvalFixture,
    EvalSuite,
    Oracle,
    OracleType,
)
from crucible.evaluation.scorers import (
    SCORER_VERSION,
    CaseScore,
    score_case,
    score_correctness,
    score_policy,
)

__all__ = [
    "SCORER_VERSION",
    "AgentOutcome",
    "Baseline",
    "CalibrationReport",
    "CaseScore",
    "DimensionAgreement",
    "EvalCase",
    "EvalConfig",
    "EvalFixture",
    "EvalSuite",
    "ExperimentResult",
    "ExperimentRunner",
    "FixtureIntegrityError",
    "GateDecision",
    "GateStatus",
    "HoldoutItem",
    "Oracle",
    "OracleType",
    "PolicyGateway",
    "baseline_from_result",
    "build_report",
    "default_judge",
    "default_policies",
    "evaluate_gate",
    "load_baseline",
    "load_fixture",
    "load_holdout",
    "load_suite",
    "outcome_from_trace",
    "paired_bootstrap_ci",
    "quadratic_weighted_kappa",
    "render_markdown",
    "render_router_markdown",
    "repo_evals_dir",
    "run_calibration",
    "run_router_experiment",
    "score_case",
    "score_correctness",
    "score_policy",
    "write_baseline",
]
