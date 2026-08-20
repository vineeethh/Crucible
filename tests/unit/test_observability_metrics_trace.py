"""Reliability/cost aggregation, trace completeness, and SLO alerts."""

from crucible.observability import (
    RunTelemetry,
    RunTraceInput,
    build_run_trace,
    cost_latency,
    evaluate_slo_alerts,
    export_trace,
    pseudonymize,
    reliability,
)
from crucible.observability.slo import Severity


def _run(
    status: str,
    *,
    cat: str | None = None,
    cost: float = 0.0,
    latency: int = 0,
    complete: bool = True,
    attempts: int = 1,
) -> RunTelemetry:
    return RunTelemetry(
        run_id=status + str(latency),
        status=status,
        failure_category=cat,
        cost_usd=cost,
        latency_ms=latency,
        attempt_count=attempts,
        trace_complete=complete,
    )


def test_reliability_aggregation() -> None:
    runs = [
        _run("answered", latency=10),
        _run("answered", latency=20),
        _run("abstained", cat="SANDBOX_TIMEOUT", latency=5),
        _run("cancelled", complete=True),
        _run("running", complete=False, attempts=0),  # not terminal
    ]
    m = reliability(runs)
    assert m.total == 5
    assert m.terminal == 4
    assert m.answered == 2
    assert m.abstained == 1
    # completion excludes the operational 'cancelled': 3 of 4 terminal.
    assert m.technical_completion_rate == 0.75
    assert m.failure_taxonomy == {"SANDBOX_TIMEOUT": 1}


def test_trace_completeness_ratio() -> None:
    runs = [_run("answered", complete=True), _run("answered", complete=False)]
    assert reliability(runs).trace_completeness == 0.5


def test_cost_latency_percentiles_and_attribution() -> None:
    runs = [_run("answered", cost=0.01, latency=lat, attempts=1) for lat in (10, 20, 30, 40, 100)]
    m = cost_latency(runs)
    assert m.total_cost_usd == 0.05
    assert m.cost_attribution_completeness == 1.0
    assert m.latency_p50_ms == 30
    assert m.latency_p95_ms == 100


def test_build_trace_and_completeness_complete() -> None:
    inp = RunTraceInput(
        run_id="r1",
        organization_id="org-1",
        status="answered",
        config_manifest={"release_id": "abc123", "dataset_content_sha256": "sha"},
        events=[
            {"event_type": "created", "payload": {"status": "queued"}, "sequence_no": 1},
            {"event_type": "progress", "payload": {"node": "plan"}, "sequence_no": 2},
            {"event_type": "terminal", "payload": {"status": "answered"}, "sequence_no": 3},
        ],
        attempts=[
            {"kind": "plan", "model_id": "fake-template", "exit_class": None, "duration_ms": 1}
        ],
    )
    trace = build_run_trace(inp)
    assert trace.completeness.complete
    assert trace.model_ids == ("fake-template",)
    assert trace.dataset_sha256 == "sha"


def test_incomplete_trace_lists_missing() -> None:
    inp = RunTraceInput(
        run_id="r2",
        organization_id="org-1",
        status="answered",
        config_manifest={"release_id": "unknown"},
        events=[{"event_type": "created", "payload": {"status": "queued"}, "sequence_no": 1}],
        attempts=[{"kind": "plan", "model_id": None}],
    )
    trace = build_run_trace(inp)
    assert not trace.completeness.complete
    assert "node_trace" in trace.completeness.missing
    assert "terminal_event" in trace.completeness.missing
    assert "release" in trace.completeness.missing
    assert "model_versions" in trace.completeness.missing


def test_export_trace_uses_pseudonym_and_bounded_question() -> None:
    inp = RunTraceInput(
        run_id="r3",
        organization_id="org-secret",
        status="answered",
        config_manifest={"release_id": "v1"},
        events=[],
        attempts=[],
    )
    exported = export_trace(build_run_trace(inp), question="What is the total amount? " * 30)
    assert exported["tenant"] == pseudonymize("org-secret")
    assert "org-secret" not in str(exported)  # raw org id never exported
    assert exported["question"]["truncated"] is True


def test_alerts_fire_on_low_completeness_and_containment() -> None:
    runs = [_run("answered", complete=False) for _ in range(5)]
    fired = {a.rule_id: a for a in evaluate_slo_alerts(reliability(runs), containment_breaches=1)}
    assert fired["sandbox_containment"].firing
    assert fired["sandbox_containment"].severity is Severity.SEV1
    assert fired["trace_completeness"].firing


def test_alerts_clear_when_healthy() -> None:
    runs = [_run("answered", complete=True, latency=5) for _ in range(10)]
    alerts = evaluate_slo_alerts(reliability(runs), containment_breaches=0)
    assert all(not a.firing for a in alerts)
