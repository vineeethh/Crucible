"""Domain-layer contract tests: pure types stay aligned with the frozen docs."""

from crucible.domain import (
    TERMINAL_RUN_STATES,
    ComponentHealth,
    FailureCategory,
    HealthState,
    ProblemDetail,
    RunStatus,
    SystemStatus,
)


def test_terminal_states_match_prd_section_3() -> None:
    """PRD §3 declares exactly these user-facing terminal outcomes (+ cancelled)."""
    assert {
        RunStatus.ANSWERED,
        RunStatus.ABSTAINED,
        RunStatus.NEEDS_HUMAN_REVIEW,
        RunStatus.POLICY_DENIED,
        RunStatus.BUDGET_EXHAUSTED,
        RunStatus.CANCELLED,
    } == TERMINAL_RUN_STATES


def test_failure_taxonomy_is_frozen_v0_1_0() -> None:
    """18 categories, mirroring docs/evaluation/failure-taxonomy.md exactly."""
    assert len(FailureCategory) == 18
    assert {c.value for c in FailureCategory} >= {
        "INJECTION_SUSPECTED",
        "CACHE_FALSE_HIT",
        "RESULT_ORACLE_MISMATCH",
        "TOOL_POLICY_DENIED",
    }


def test_system_status_aggregation() -> None:
    ok = ComponentHealth(name="a", state=HealthState.OK)
    down = ComponentHealth(name="b", state=HealthState.DOWN)
    degraded = ComponentHealth(name="c", state=HealthState.DEGRADED)

    assert SystemStatus(components=(ok,)).state is HealthState.OK
    assert SystemStatus(components=(ok, degraded)).state is HealthState.DEGRADED
    assert SystemStatus(components=(ok, down)).state is HealthState.DOWN
    assert SystemStatus(components=()).state is HealthState.OK  # no probes configured
    assert not SystemStatus(components=(ok, down)).ready


def test_problem_detail_serializes_flat() -> None:
    p = ProblemDetail(type="about:blank", title="t", status=400, detail="d", request_id="r1")
    d = p.to_dict()
    assert d["status"] == 400
    assert d["retryable"] is False
