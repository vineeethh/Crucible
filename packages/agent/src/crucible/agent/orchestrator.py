"""Entry points the worker calls: run a fresh/resumed run, and resolve a review.

These wrap the durable runner with the claim/resume logic against the Phase 2
run state machine. The worker builds the model gateway, executor, and limits and
injects them; nothing here imports infrastructure.
"""

from __future__ import annotations

import logging
from typing import Literal

from crucible.agent.errors import AgentError
from crucible.agent.graph import GraphRunner
from crucible.agent.nodes import AgentContext
from crucible.agent.ports import AgentPersistence, AnswerCache, ModelGateway
from crucible.agent.state import AgentState, Node
from crucible.domain import TERMINAL_RUN_STATES, RunStatus
from crucible.execution import ExecutionLimits, Executor

logger = logging.getLogger("crucible.agent.orchestrator")


async def _build_context(
    persistence: AgentPersistence,
    model: ModelGateway,
    executor: Executor,
    limits: ExecutionLimits,
    dataset_version_id: str,
    cache: AnswerCache | None = None,
) -> AgentContext:
    dataset = await persistence.load_dataset(dataset_version_id)
    if dataset is None:
        raise AgentError(f"dataset version {dataset_version_id} not found")
    dataset_bytes = await persistence.load_dataset_bytes(dataset.object_key)
    return AgentContext(
        persistence=persistence,
        model=model,
        executor=executor,
        dataset=dataset,
        dataset_bytes=dataset_bytes,
        limits=limits,
        cache=cache,
    )


async def run_agent(
    persistence: AgentPersistence,
    *,
    model: ModelGateway,
    executor: Executor,
    limits: ExecutionLimits,
    run_id: str,
    stop_after: Node | None = None,
    cache: AnswerCache | None = None,
) -> str:
    """Claim a queued run and drive the graph, or resume a RUNNING run that a
    prior worker left mid-flight. Returns a short outcome string."""
    run = await persistence.load_run(run_id)
    if run is None:
        return "not_found"
    status = RunStatus(run.status)
    if status in TERMINAL_RUN_STATES:
        return "already_terminal"

    if run.cancel_requested and status is RunStatus.QUEUED:
        await persistence.transition(
            run_id,
            expected=RunStatus.QUEUED.value,
            target=RunStatus.CANCELLED.value,
            detail="cancelled before execution started",
        )
        await persistence.emit_event(run_id, "terminal", {"status": RunStatus.CANCELLED.value})
        return "cancelled"

    ctx = await _build_context(
        persistence, model, executor, limits, run.dataset_version_id, cache=cache
    )

    if status is RunStatus.QUEUED:
        claimed = await persistence.transition(
            run_id, expected=RunStatus.QUEUED.value, target=RunStatus.RUNNING.value
        )
        if not claimed:
            return "not_claimable"
        await persistence.emit_event(run_id, "claimed", {"status": RunStatus.RUNNING.value})
        state = AgentState(
            run_id=run_id,
            organization_id=run.organization_id,
            dataset_version_id=run.dataset_version_id,
            question=run.question,
        )
        start = Node.VALIDATE
    elif status is RunStatus.RUNNING:
        checkpoint = await persistence.load_checkpoint(run_id)
        if checkpoint is None:
            state = AgentState(
                run_id=run_id,
                organization_id=run.organization_id,
                dataset_version_id=run.dataset_version_id,
                question=run.question,
            )
            start = Node.VALIDATE
        else:
            node_value, state_json = checkpoint
            state = AgentState.model_validate_json(state_json)
            start = Node(node_value)
        await persistence.emit_event(run_id, "progress", {"resumed_from": start.value})
    else:
        # WAITING_REVIEW is resumed only via resolve_review.
        return "not_runnable"

    runner = GraphRunner(ctx)
    await runner.run(state, start=start, stop_after=stop_after)
    return state.terminal_reason.value if state.terminal_reason else "interrupted"


async def resolve_review(
    persistence: AgentPersistence,
    *,
    model: ModelGateway,
    executor: Executor,
    limits: ExecutionLimits,
    run_id: str,
    decision: Literal["approve", "reject", "revise"],
    feedback: str | None = None,
) -> str:
    """Resume a run that is waiting for a reviewer. Approve continues to
    synthesis; reject abstains; revise feeds `feedback` back into the plan or
    code (nodes.py human_review()/revise()) and re-runs verification — bounded
    by policy.MAX_HUMAN_REVISIONS so this can't be asked forever."""
    run = await persistence.load_run(run_id)
    if run is None:
        return "not_found"
    if RunStatus(run.status) is not RunStatus.WAITING_REVIEW:
        return "not_in_review"

    checkpoint = await persistence.load_checkpoint(run_id)
    if checkpoint is None:
        return "no_checkpoint"
    node_value, state_json = checkpoint
    state = AgentState.model_validate_json(state_json)
    state.review_decision = decision
    state.review_feedback = feedback if decision == "revise" else None

    moved = await persistence.transition(
        run_id,
        expected=RunStatus.WAITING_REVIEW.value,
        target=RunStatus.RUNNING.value,
        detail="review resolved; resuming",
    )
    if not moved:
        return "not_in_review"

    ctx = await _build_context(persistence, model, executor, limits, run.dataset_version_id)
    runner = GraphRunner(ctx)
    await runner.run(state, start=Node(node_value))
    return state.terminal_reason.value if state.terminal_reason else "interrupted"
