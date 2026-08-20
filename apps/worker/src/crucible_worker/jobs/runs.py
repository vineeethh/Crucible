"""Run execution job.

Phase 4: the durable data-agent. This job hands the run to the agent graph,
which claims a queued run (or resumes a RUNNING run a prior worker left
mid-flight), plans → generates code → executes it in the sandbox → observes →
repairs (bounded) → verifies → synthesizes an answer with provenance, or
abstains truthfully, or routes to human review.

Phase 8 adds two thin concerns around the graph:
- the exact answer cache is injected when the feature flag enabled it at
  worker startup (ctx["cache"]);
- budget settlement: when a run reaches a terminal state, the ledger's
  admission reserve is replaced with the actual attempt cost. Settlement is
  idempotent (a partial unique index on (run_id, kind)), so at-least-once job
  delivery cannot double-charge.

The graph is the only thing that transitions run status, so `agent_runs` remains
the single source of truth (ADR-008). This job is a thin delegator; the
resume-after-restart logic lives in the orchestrator.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from crucible.agent import resolve_review, run_agent
from crucible.db import SqlBudgetRepository, SqlRunRepository
from crucible.db import models as m
from crucible_worker.agent_runtime import SqlAgentPersistence

logger = logging.getLogger("crucible.worker.runs")

# Outcomes after which the run is terminal and the ledger can settle.
_TERMINAL_OUTCOMES = frozenset(
    {"answered", "abstained", "policy_denied", "budget_exhausted", "cancelled"}
)


async def _settle_budget(factory: async_sessionmaker[Any], run_id: str) -> None:
    """Replace the admission reserve with the actual attempt cost: one `settle`
    entry (the real spend) plus one `release` entry (the reserve reversal).
    A re-delivered job finds the entries already present and does nothing."""
    rid = uuid.UUID(run_id)
    async with factory() as session:
        budgets = SqlBudgetRepository(session)
        run = await SqlRunRepository(session).get_run_unscoped(rid)
        if run is None:
            return
        if await budgets.get_limit(run.organization_id) is None:
            return  # no budget configured for this org: nothing to settle
        actual = (
            await session.execute(
                select(func.coalesce(func.sum(m.AgentAttempt.cost_usd), 0.0)).where(
                    m.AgentAttempt.run_id == rid
                )
            )
        ).scalar_one()
        settled = await budgets.add_entry(
            organization_id=run.organization_id,
            run_id=rid,
            kind="settle",
            amount_usd=round(float(actual), 6),
            detail="actual attempt cost",
        )
        if settled:
            reserve = await budgets.reserve_amount(rid)
            if reserve is not None:
                await budgets.add_entry(
                    organization_id=run.organization_id,
                    run_id=rid,
                    kind="release",
                    amount_usd=-reserve,
                    detail="admission reserve released",
                )
        await session.commit()


async def execute_run(ctx: dict[str, Any], run_id: str) -> dict[str, str]:
    persistence = SqlAgentPersistence(ctx["session_factory"], ctx["storage"])
    outcome = await run_agent(
        persistence,
        model=ctx["model"],
        executor=ctx["executor"],
        limits=ctx["limits"],
        run_id=run_id,
        cache=ctx.get("cache"),
    )
    if outcome in _TERMINAL_OUTCOMES:
        await _settle_budget(ctx["session_factory"], run_id)
    logger.info("execute_run: run %s -> %s", run_id, outcome)
    return {"result": outcome}


async def resolve_run_review(ctx: dict[str, Any], run_id: str, approve: bool) -> dict[str, str]:
    """Resume a run waiting for a reviewer (approve → synthesize, reject →
    abstain). Enqueued by the API when a reviewer acts."""
    persistence = SqlAgentPersistence(ctx["session_factory"], ctx["storage"])
    outcome = await resolve_review(
        persistence,
        model=ctx["model"],
        executor=ctx["executor"],
        limits=ctx["limits"],
        run_id=run_id,
        approve=approve,
    )
    if outcome in _TERMINAL_OUTCOMES:
        await _settle_budget(ctx["session_factory"], run_id)
    logger.info("resolve_run_review: run %s approve=%s -> %s", run_id, approve, outcome)
    return {"result": outcome}
