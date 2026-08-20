"""Durable agent graph: terminal paths, bounded repair, review interrupt, and
resume-after-restart — all driven in memory with a scripted executor."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from crucible.agent import ColumnView, FakeModel, Node, resolve_review, run_agent
from crucible.execution import (
    ExecutionLimits,
    ExecutionRequest,
    ExecutionResult,
    ExitClass,
    FakeExecutor,
)
from tests.support.agent_fakes import InMemoryPersistence, exec_result

PROFILE = [
    ColumnView(name="region", dtype="String"),
    ColumnView(name="amount", dtype="Float64"),
    ColumnView(name="customer_id", dtype="String"),
]


def drive(
    p: InMemoryPersistence,
    *,
    handler: Callable[[ExecutionRequest], ExecutionResult],
    run_id: str = "r1",
    model: FakeModel | None = None,
    stop_after: Node | None = None,
) -> str:
    return asyncio.run(
        run_agent(
            p,
            model=model or FakeModel(),
            executor=FakeExecutor(handler=handler),
            limits=ExecutionLimits(),
            run_id=run_id,
            stop_after=stop_after,
        )
    )


# ----------------------------------------------------------------- answered path


def test_answered_path_produces_answer_with_provenance() -> None:
    p = InMemoryPersistence()
    p.add_run("r1", question="What is the total amount?", profile=PROFILE)

    outcome = drive(p, handler=lambda req: exec_result(value=30.0, columns_used=["amount"]))

    assert outcome == "answered"
    assert p.status_of("r1") == "answered"
    answer, verification = p.results["r1"]
    assert answer is not None
    assert answer["value"] == 30.0
    assert answer["provenance"]["columns_used"] == ["amount"]
    assert answer["provenance"]["operation"] == "sum"
    assert verification["decision"] == "answer"
    # Every node on the path emitted a trace event.
    nodes = p.event_nodes("r1")
    for expected in (
        "validate",
        "profile",
        "plan",
        "code",
        "execute",
        "observe",
        "verify",
        "synthesize",
        "output_guard",
    ):
        assert expected in nodes
    assert p.terminal_event("r1") == {"status": "answered", "reason": "answered", "detail": ""}


def test_attempts_are_recorded_for_each_step() -> None:
    p = InMemoryPersistence()
    p.add_run("r1", question="What is the total amount?", profile=PROFILE)
    drive(p, handler=lambda req: exec_result(value=30.0, columns_used=["amount"]))
    kinds = [a.kind for a in p.attempts]
    assert kinds == ["route", "plan", "code", "execute", "challenge", "verify"]
    plan_attempt = p.attempts[1]
    assert plan_attempt.model_provider == "fake"


# --------------------------------------------------------------- abstention paths


def test_unsupported_question_abstains_without_executing() -> None:
    p = InMemoryPersistence()
    p.add_run("r1", question="Predict next quarter and explain the strategy.", profile=PROFILE)

    outcome = drive(p, handler=lambda req: exec_result(value=1))

    assert outcome == "abstained"
    assert p.status_of("r1") == "abstained"
    assert "execute" not in p.event_nodes("r1")  # never ran code


def test_non_repairable_execution_failure_abstains() -> None:
    p = InMemoryPersistence()
    p.add_run("r1", question="What is the total amount?", profile=PROFILE)

    outcome = drive(p, handler=lambda req: exec_result(exit_class=ExitClass.POLICY_VIOLATION))

    assert outcome == "abstained"
    assert p.results["r1"][0] is None  # no answer


# ------------------------------------------------------------------ bounded repair


def test_repair_then_success() -> None:
    calls = {"n": 0}

    def handler(req: ExecutionRequest) -> ExecutionResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return exec_result(exit_class=ExitClass.RUNTIME_ERROR, stderr="NameError: df")
        return exec_result(value=30.0, columns_used=["amount"])

    p = InMemoryPersistence()
    p.add_run("r1", question="What is the total amount?", profile=PROFILE)
    outcome = drive(p, handler=handler)

    assert outcome == "answered"
    assert any(a.kind == "repair" for a in p.attempts)


def test_oscillation_guard_stops_identical_failures() -> None:
    """The deterministic fake regenerates identical code; an identical repeat
    failure fingerprint stops the loop after a single repair."""
    p = InMemoryPersistence()
    p.add_run("r1", question="What is the total amount?", profile=PROFILE)

    outcome = drive(
        p, handler=lambda req: exec_result(exit_class=ExitClass.RUNTIME_ERROR, stderr="same error")
    )

    assert outcome == "abstained"
    repairs = [a for a in p.attempts if a.kind == "repair"]
    assert len(repairs) == 1  # stopped by the oscillation guard, not the cap


def test_repair_cap_is_enforced_with_distinct_failures() -> None:
    counter = {"n": 0}

    def handler(req: ExecutionRequest) -> ExecutionResult:
        counter["n"] += 1
        # A different error each time so fingerprints differ and the cap (not the
        # oscillation guard) is what stops the loop.
        return exec_result(
            exit_class=ExitClass.RUNTIME_ERROR, stderr=f"error variant {counter['n']}"
        )

    p = InMemoryPersistence()
    p.add_run("r1", question="What is the total amount?", profile=PROFILE)
    outcome = drive(p, handler=handler)

    assert outcome == "abstained"
    repairs = [a for a in p.attempts if a.kind == "repair"]
    assert len(repairs) == 2  # MAX_REPAIRS


# --------------------------------------------------------------- human review


def test_ambiguous_result_routes_to_review_then_approve() -> None:
    p = InMemoryPersistence()
    p.add_run("r1", question="Which region had the highest amount?", profile=PROFILE)

    outcome = drive(
        p, handler=lambda req: exec_result(value="north", columns_used=["region"], ambiguous=True)
    )

    assert outcome == "interrupted"
    assert p.status_of("r1") == "waiting_review"
    assert "r1" in p.checkpoints

    resolved = asyncio.run(
        resolve_review(
            p,
            model=FakeModel(),
            executor=FakeExecutor(
                handler=lambda req: exec_result(
                    value="north", columns_used=["region"], ambiguous=True
                )
            ),
            limits=ExecutionLimits(),
            run_id="r1",
            approve=True,
        )
    )
    assert resolved == "answered"
    assert p.status_of("r1") == "answered"
    assert p.results["r1"][0]["value"] == "north"


def test_review_rejection_abstains() -> None:
    p = InMemoryPersistence()
    p.add_run("r1", question="Which region had the highest amount?", profile=PROFILE)
    drive(
        p, handler=lambda req: exec_result(value="north", columns_used=["region"], ambiguous=True)
    )

    resolved = asyncio.run(
        resolve_review(
            p,
            model=FakeModel(),
            executor=FakeExecutor(handler=lambda req: exec_result(value="north")),
            limits=ExecutionLimits(),
            run_id="r1",
            approve=False,
        )
    )
    assert resolved == "abstained"
    assert p.status_of("r1") == "abstained"


# --------------------------------------------------------- resume after restart


def test_resume_after_worker_restart() -> None:
    """A crash after the CODE node leaves the run RUNNING with a checkpoint; a
    subsequent call resumes from EXECUTE and finishes without re-planning."""
    p = InMemoryPersistence()
    p.add_run("r1", question="What is the total amount?", profile=PROFILE)

    first = drive(
        p,
        handler=lambda req: exec_result(value=30.0, columns_used=["amount"]),
        stop_after=Node.CODE,
    )
    assert first == "interrupted"
    assert p.status_of("r1") == "running"  # left mid-flight
    node, _state = p.checkpoints["r1"]
    assert node == "execute"

    plan_attempts_before = [a for a in p.attempts if a.kind == "plan"]

    second = drive(p, handler=lambda req: exec_result(value=30.0, columns_used=["amount"]))
    assert second == "answered"
    assert p.status_of("r1") == "answered"
    # The plan was not re-run on resume (resume started at EXECUTE).
    plan_attempts_after = [a for a in p.attempts if a.kind == "plan"]
    assert len(plan_attempts_after) == len(plan_attempts_before)
    assert "resumed_from" in [k for _rid, _t, pl in p.events for k in pl]


# ----------------------------------------------------------------- cancellation


def test_queued_cancel_is_honored_before_execution() -> None:
    p = InMemoryPersistence()
    p.add_run("r1", question="What is the total amount?", profile=PROFILE)
    p.runs["r1"].cancel_requested = True

    outcome = drive(p, handler=lambda req: exec_result(value=1))

    assert outcome == "cancelled"
    assert p.status_of("r1") == "cancelled"
    assert "execute" not in p.event_nodes("r1")
