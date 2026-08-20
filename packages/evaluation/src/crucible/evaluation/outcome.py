"""Normalize an agent run into the flat outcome the scorers consume."""

from __future__ import annotations

from dataclasses import dataclass

from crucible.agent import EvalTrace


@dataclass(frozen=True, slots=True)
class AgentOutcome:
    terminal: str  # answered | abstained | review | policy_denied | incomplete
    value: object
    answer_kind: str | None
    provenance: dict[str, object] | None
    verification: dict[str, object] | None
    execution_ok: bool
    exit_class: str | None
    failure_category: str | None
    attempt_count: int
    cost_usd: float
    latency_ms: int
    # The synthesized answer prose. Carried so a policy check can assert that
    # hostile fixture content is never echoed back to the user (see
    # `no_injected_text_echoed` in scorers.py).
    answer_text: str = ""


def outcome_from_trace(trace: EvalTrace) -> AgentOutcome:
    state = trace.state
    tr = state.terminal_reason
    if tr is None:
        decision = state.verification.decision.value if state.verification else None
        terminal = "review" if decision == "review" else "incomplete"
    else:
        terminal = tr.value

    answer = state.answer
    ev = state.last_execution
    cost = sum(a.cost_usd or 0.0 for a in trace.attempts)
    return AgentOutcome(
        terminal=terminal,
        value=answer.value if answer else None,
        answer_kind=answer.answer_kind.value if answer else None,
        provenance=answer.provenance.model_dump() if answer else None,
        verification=state.verification.model_dump() if state.verification else None,
        execution_ok=bool(ev and ev.ok),
        exit_class=ev.exit_class if ev else None,
        failure_category=(ev.failure_category if ev else None),
        attempt_count=len([a for a in trace.attempts if a.kind in ("execute",)]),
        cost_usd=round(cost, 6),
        latency_ms=trace.latency_ms,
        answer_text=answer.text if answer else "",
    )
