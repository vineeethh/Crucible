"""Fixture integrity, case immutability/lineage, baseline governance, and
report reproducibility."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crucible.evaluation import (
    FixtureIntegrityError,
    build_report,
    evaluate_gate,
    load_baseline,
    load_fixture,
    load_suite,
    repo_evals_dir,
)
from crucible.evaluation.comparator import GateStatus
from crucible.evaluation.config import EvalConfig
from crucible.evaluation.governance import baseline_from_result
from crucible.evaluation.outcome import AgentOutcome
from crucible.evaluation.runner import ExperimentResult
from crucible.evaluation.scorers import CaseScore

EVALS = repo_evals_dir()
# The suite `evals/baseline.json` currently tracks. Bumping this and the
# committed baseline together is the reviewed re-baseline step; the lineage
# test below is what forces them to move in lockstep.
CORE_SUITE = EVALS / "suites" / "core-v1.1.0.yaml"
RETAIL_SUITE = EVALS / "suites" / "retail-v1.0.0.yaml"
ADVERSARIAL_SUITE = EVALS / "suites" / "adversarial-v1.0.0.yaml"


def test_core_suite_loads_and_smoke_is_a_subset() -> None:
    suite = load_suite(CORE_SUITE)
    ids = {c.id for c in suite.cases}
    assert set(suite.smoke) <= ids
    smoke = suite.smoke_suite()
    assert len(smoke.cases) == len(suite.smoke)
    assert smoke.purpose == "smoke"


def test_fixture_hash_is_verified() -> None:
    fixture, content = load_fixture("eval_sales_v1")
    assert fixture.rows == 9
    assert len(content) > 0


def test_tampered_fixture_is_rejected(tmp_path: Path) -> None:
    fixture, content = load_fixture("eval_sales_v1")
    # Build a fixture dir with the manifest but corrupted bytes.
    (tmp_path / "fixtures").mkdir()
    manifest_src = (EVALS / "fixtures" / "eval_sales_v1.manifest.yaml").read_text()
    (tmp_path / "fixtures" / "eval_sales_v1.manifest.yaml").write_text(manifest_src)
    (tmp_path / "fixtures" / fixture.file).write_bytes(content + b"tampered")
    with pytest.raises(FixtureIntegrityError):
        load_fixture("eval_sales_v1", evals_dir=tmp_path)


def test_case_content_hash_is_stable_across_loads() -> None:
    a = load_suite(CORE_SUITE)
    b = load_suite(CORE_SUITE)
    assert a.content_hash == b.content_hash
    assert a.case("core-sum-price").content_hash == b.case("core-sum-price").content_hash


@pytest.mark.parametrize(
    ("suite_path", "baseline_name"),
    [
        (CORE_SUITE, "baseline.json"),
        (RETAIL_SUITE, "baseline-retail.json"),
        (ADVERSARIAL_SUITE, "baseline-adversarial.json"),
    ],
)
def test_committed_baseline_matches_the_current_suite(suite_path: Path, baseline_name: str) -> None:
    """Lineage guard: the frozen baseline pins the suite content hash. If a
    released case is edited, this fails — forcing a reviewed re-baseline rather
    than silently changing what 'correct' means."""
    suite = load_suite(suite_path)
    baseline = load_baseline(EVALS / baseline_name)
    assert baseline.suite_hash == suite.content_hash
    assert baseline.suite_id == suite.id
    assert set(baseline.per_case) == {c.id for c in suite.cases}


def test_superseded_core_v1_0_0_cases_survive_verbatim_in_v1_1_0() -> None:
    """v1.1.0 supersedes v1.0.0 by ADDING cases, never altering one. Any drift in
    a carried-over case would silently redefine a gold that a released baseline
    already approved."""
    old = load_suite(EVALS / "suites" / "core-v1.0.0.yaml")
    new = load_suite(CORE_SUITE)
    new_by_id = {c.id: c for c in new.cases}
    for case in old.cases:
        assert case.id in new_by_id, f"v1.1.0 dropped {case.id}"
        assert new_by_id[case.id].content_hash == case.content_hash, f"v1.1.0 altered {case.id}"
    assert len(new.cases) > len(old.cases)


def _fake_result() -> ExperimentResult:
    config = EvalConfig(id="ref@1", model_backend="fake", executor_backend="fake")
    result = ExperimentResult(
        config=config,
        suite_id="core",
        suite_version="1.0.0",
        suite_hash="h",
        fixture_id="eval_sales_v1",
        fixture_sha256="abc",
    )
    for i in range(4):
        result.outcomes[f"c{i}"] = AgentOutcome(
            terminal="answered",
            value=i,
            answer_kind="integer_scalar",
            provenance={"operation": "count"},
            verification={"result_schema_valid": True},
            execution_ok=True,
            exit_class="ok",
            failure_category=None,
            attempt_count=1,
            cost_usd=0.0,
            latency_ms=3,
        )
        result.scores[f"c{i}"] = CaseScore(case_id=f"c{i}", correct=True, policy_ok=True)
    return result


def test_report_is_reproducible() -> None:
    """The content hash covers everything except the wall-clock timestamp, so two
    runs of the same experiment produce the identical signed content."""
    result = _fake_result()
    baseline = baseline_from_result(result, approved_by="t", approved_at="2026-07-17")
    gate = evaluate_gate(baseline.scores(), result.scores, tolerance=0.02)
    assert gate.status is GateStatus.PASS

    tags = {cid: [] for cid in result.scores}
    r1 = build_report(
        candidate=result,
        baseline=baseline,
        gate=gate,
        git_sha="abc",
        generated_at=datetime.now(UTC).isoformat(),
        suite_cases_tags=tags,
    )
    r2 = build_report(
        candidate=result,
        baseline=baseline,
        gate=gate,
        git_sha="abc",
        generated_at="a-different-time",
        suite_cases_tags=tags,
    )
    assert r1["content_sha256"] == r2["content_sha256"]


def _load_reference_compute():
    path = EVALS / "references" / "eval_sales_v1_reference.py"
    spec = importlib.util.spec_from_file_location("eval_sales_v1_reference", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.compute


def test_gold_answers_match_the_independent_reference() -> None:
    """Ground-truth rule: every case's gold answer is cross-checked against the
    independent reference calculator, not trusted from hand arithmetic alone."""
    compute = _load_reference_compute()
    ref = compute()
    suite = load_suite(CORE_SUITE)
    mapping = {
        "core-sum-price": "sum_price",
        "core-sum-units": "sum_units",
        "core-mean-price": "mean_price",
        "core-mean-units": "mean_units",
        "core-row-count": "row_count",
        "core-distinct-region": "distinct_region",
        "core-distinct-rep": "distinct_rep",
        "core-missing-price": "missing_price",
        "core-missing-units": "missing_units",
        "core-max-region-price": "max_region_price",
        "core-max-category-units": "max_category_units",
        "core-min-region-price": "min_region_price",
        "core-top-rep": "top_rep_count",
    }
    for case_id, ref_key in mapping.items():
        expected = suite.case(case_id).oracle.expected
        got = ref[ref_key]
        if isinstance(got, str) or isinstance(expected, str):
            assert str(expected).strip().lower() == str(got).strip().lower(), case_id
        else:
            assert abs(float(expected) - float(got)) < 0.01, case_id
