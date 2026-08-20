"""The durable graph runner (ADR-008).

Runs the node graph over an AgentState, persisting a checkpoint after every node
so a worker restart resumes from the last completed node rather than re-running
model calls and sandbox executions. Terminal reasons map to the Phase 2 run
state machine; human review is an interrupt that leaves the run in
`waiting_review` until a reviewer resolves it.

The runner is the only place that transitions run status, so `agent_runs`
remains the single source of truth (checkpoints hold only resume state).
"""

from __future__ import annotations

import logging

from crucible.agent.nodes import DISPATCH, AgentContext, AgentNodes
from crucible.agent.ports import AgentPersistence
from crucible.agent.state import AgentState, Node, TerminalReason
from crucible.domain import RunStatus

logger = logging.getLogger("crucible.agent.graph")

# Bound the number of node steps so a logic bug can never loop forever. The
# longest legitimate path (with two repairs) is well under this.
MAX_STEPS = 64

_TERMINAL_STATUS: dict[TerminalReason, RunStatus] = {
    TerminalReason.ANSWERED: RunStatus.ANSWERED,
    TerminalReason.ABSTAINED: RunStatus.ABSTAINED,
    TerminalReason.POLICY_DENIED: RunStatus.POLICY_DENIED,
    TerminalReason.BUDGET_EXHAUSTED: RunStatus.BUDGET_EXHAUSTED,
    TerminalReason.CANCELLED: RunStatus.CANCELLED,
}


class GraphRunner:
    def __init__(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        self._nodes = AgentNodes(ctx)
        self._p: AgentPersistence = ctx.persistence

    async def run(
        self, state: AgentState, *, start: Node, stop_after: Node | None = None
    ) -> AgentState:
        """Drive the graph from `start`. `stop_after` is a test hook that
        simulates a crash: it stops the loop after that node runs, leaving the
        run RUNNING with a checkpoint so a subsequent call resumes it."""
        node = start
        for _ in range(MAX_STEPS):
            if node is Node.DONE:
                await self._finalize(state)
                return state

            if await self._p.is_cancel_requested(state.run_id):
                state.terminal_reason = TerminalReason.CANCELLED
                state.detail = "cancelled during execution"
                await self._finalize(state)
                return state

            result = await getattr(self._nodes, DISPATCH[node])(state)
            await self._p.emit_event(
                state.run_id,
                "progress",
                {"node": node.value, "next": result.next.value},
            )
            await self._p.save_checkpoint(state.run_id, result.next.value, state.model_dump_json())

            if result.interrupt:
                await self._enter_review(state)
                return state

            if stop_after is not None and node is stop_after:
                # Simulated crash: leave the run RUNNING with a checkpoint.
                return state

            node = result.next

        # Step budget exhausted: abstain rather than spin.
        state.terminal_reason = TerminalReason.ABSTAINED
        state.detail = "graph step budget exhausted"
        await self._finalize(state)
        return state

    async def _enter_review(self, state: AgentState) -> None:
        moved = await self._p.transition(
            state.run_id,
            expected=RunStatus.RUNNING.value,
            target=RunStatus.WAITING_REVIEW.value,
            detail="verification routed this answer to human review",
        )
        if moved:
            await self._p.set_result(
                state.run_id,
                answer=None,
                verification=state.verification.model_dump() if state.verification else None,
            )
            await self._p.emit_event(
                state.run_id, "status_changed", {"status": RunStatus.WAITING_REVIEW.value}
            )

    async def _finalize(self, state: AgentState) -> None:
        reason = state.terminal_reason or TerminalReason.ABSTAINED
        target = _TERMINAL_STATUS[reason]
        # The run is always RUNNING when it reaches a terminal: a fresh run
        # claimed QUEUED→RUNNING, and a resumed review already moved
        # WAITING_REVIEW→RUNNING before re-entering the graph. The only time the
        # run is WAITING_REVIEW is the interrupt, which never calls _finalize.
        expected = RunStatus.RUNNING.value
        answer = state.answer.model_dump() if state.answer else None
        verification = state.verification.model_dump() if state.verification else None
        await self._p.set_result(state.run_id, answer=answer, verification=verification)
        moved = await self._p.transition(
            state.run_id, expected=expected, target=target.value, detail=state.detail
        )
        if not moved:
            logger.warning(
                "run %s could not transition to %s from %s", state.run_id, target.value, expected
            )
            return
        await self._p.emit_event(
            state.run_id,
            "terminal",
            {"status": target.value, "reason": reason.value, "detail": state.detail},
        )
