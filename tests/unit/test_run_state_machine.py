"""Run state machine: terminal is terminal, and only declared edges exist."""

import pytest

from crucible.application import request_hash
from crucible.domain import (
    ACTIVE_RUN_STATES,
    TERMINAL_RUN_STATES,
    RunStatus,
    can_transition,
)


def test_states_partition_into_active_and_terminal() -> None:
    assert set(RunStatus) == ACTIVE_RUN_STATES | TERMINAL_RUN_STATES
    assert not (ACTIVE_RUN_STATES & TERMINAL_RUN_STATES)


@pytest.mark.parametrize("terminal", sorted(TERMINAL_RUN_STATES))
@pytest.mark.parametrize("target", sorted(RunStatus))
def test_terminal_states_never_transition(terminal: RunStatus, target: RunStatus) -> None:
    """History is never rewritten — no edge leaves a terminal state."""
    assert not can_transition(terminal, target)


def test_queued_can_be_claimed_or_cancelled() -> None:
    assert can_transition(RunStatus.QUEUED, RunStatus.RUNNING)
    assert can_transition(RunStatus.QUEUED, RunStatus.CANCELLED)
    assert can_transition(RunStatus.QUEUED, RunStatus.POLICY_DENIED)


def test_queued_cannot_jump_straight_to_answered() -> None:
    """A run must be claimed before it can produce an answer; skipping the
    claim would mean an answer with no execution behind it."""
    assert not can_transition(RunStatus.QUEUED, RunStatus.ANSWERED)
    assert not can_transition(RunStatus.QUEUED, RunStatus.WAITING_REVIEW)


def test_running_reaches_every_terminal_outcome() -> None:
    for terminal in TERMINAL_RUN_STATES:
        assert can_transition(RunStatus.RUNNING, terminal)


def test_review_can_resume_or_finish() -> None:
    assert can_transition(RunStatus.WAITING_REVIEW, RunStatus.ANSWERED)
    assert can_transition(RunStatus.WAITING_REVIEW, RunStatus.ABSTAINED)
    assert can_transition(RunStatus.WAITING_REVIEW, RunStatus.RUNNING)
    assert not can_transition(RunStatus.WAITING_REVIEW, RunStatus.BUDGET_EXHAUSTED)


def test_request_hash_is_order_independent_and_content_sensitive() -> None:
    a = request_hash({"question": "how many rows?", "dataset_version_id": "v1"})
    b = request_hash({"dataset_version_id": "v1", "question": "how many rows?"})
    c = request_hash({"dataset_version_id": "v1", "question": "how many columns?"})
    assert a == b
    assert a != c
