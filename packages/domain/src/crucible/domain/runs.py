"""Run lifecycle: state machine, event types, and the frozen failure taxonomy.

The taxonomy mirrors docs/evaluation/failure-taxonomy.md v0.1.0. Adding a
category is a reviewed governance change, and both places change together.
"""

from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    """Durable agent-run state machine (terminal states per the PRD, §3)."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    # terminal
    ANSWERED = "answered"
    ABSTAINED = "abstained"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    POLICY_DENIED = "policy_denied"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"


TERMINAL_RUN_STATES: frozenset[RunStatus] = frozenset(
    {
        RunStatus.ANSWERED,
        RunStatus.ABSTAINED,
        RunStatus.NEEDS_HUMAN_REVIEW,
        RunStatus.POLICY_DENIED,
        RunStatus.BUDGET_EXHAUSTED,
        RunStatus.CANCELLED,
    }
)

ACTIVE_RUN_STATES: frozenset[RunStatus] = frozenset(
    {RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.WAITING_REVIEW}
)

# Every legal transition, exhaustively. Anything absent is a bug, not a
# judgement call — the worker and API both check this before writing.
_ALLOWED: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.POLICY_DENIED}),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.WAITING_REVIEW,
            RunStatus.ANSWERED,
            RunStatus.ABSTAINED,
            RunStatus.NEEDS_HUMAN_REVIEW,
            RunStatus.POLICY_DENIED,
            RunStatus.BUDGET_EXHAUSTED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.WAITING_REVIEW: frozenset(
        {RunStatus.RUNNING, RunStatus.ANSWERED, RunStatus.ABSTAINED, RunStatus.CANCELLED}
    ),
}


def can_transition(current: RunStatus, target: RunStatus) -> bool:
    if current in TERMINAL_RUN_STATES:
        return False  # terminal is terminal; history is never rewritten
    return target in _ALLOWED.get(current, frozenset())


class RunEventType(StrEnum):
    """Append-only run history; also what the SSE stream replays."""

    CREATED = "created"
    CLAIMED = "claimed"
    STATUS_CHANGED = "status_changed"
    PROGRESS = "progress"
    CANCEL_REQUESTED = "cancel_requested"
    TERMINAL = "terminal"


class FailureCategory(StrEnum):
    """Frozen failure taxonomy v0.1.0 (docs/evaluation/failure-taxonomy.md)."""

    INPUT_INVALID = "INPUT_INVALID"
    INJECTION_SUSPECTED = "INJECTION_SUSPECTED"
    DATASET_PARSE_ERROR = "DATASET_PARSE_ERROR"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    PLAN_INVALID = "PLAN_INVALID"
    TOOL_POLICY_DENIED = "TOOL_POLICY_DENIED"
    CODE_SYNTAX_ERROR = "CODE_SYNTAX_ERROR"
    CODE_RUNTIME_ERROR = "CODE_RUNTIME_ERROR"
    SANDBOX_TIMEOUT = "SANDBOX_TIMEOUT"
    SANDBOX_RESOURCE_LIMIT = "SANDBOX_RESOURCE_LIMIT"
    RESULT_SERIALIZATION_ERROR = "RESULT_SERIALIZATION_ERROR"
    RESULT_ORACLE_MISMATCH = "RESULT_ORACLE_MISMATCH"
    EXPLANATION_UNGROUNDED = "EXPLANATION_UNGROUNDED"
    JUDGE_DISAGREEMENT = "JUDGE_DISAGREEMENT"
    CACHE_FALSE_HIT = "CACHE_FALSE_HIT"
    MODEL_PROVIDER_ERROR = "MODEL_PROVIDER_ERROR"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


MAX_QUESTION_CHARS = 2000
