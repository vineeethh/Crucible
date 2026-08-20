"""Online evaluation job (master plan §10.6).

Periodically samples terminal production runs per organization and runs cheap,
*deterministic* checks over the sample (trace completeness, provenance presence),
recording them as typed deterministic scores. This is the drift/quality signal
that runs without any model call; model/human scoring is layered on top by the
review queue and the calibrated, secondary judge.

The job holds no user, so it synthesizes a per-organization *system* principal
(an API-key actor, owner role) scoped to that one organization — the command
still enforces `EVAL_WRITE` and reads only that tenant's runs (threat model T5).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from crucible.application import RunOnlineChecks
from crucible.db import SqlMetricsRepository, SqlScoreStore
from crucible.domain import ActorType, Principal, Role

logger = logging.getLogger("crucible.worker.online")

# A stable, well-known actor id so online-eval scores are attributable to the
# system evaluator rather than any human or tenant API key.
SYSTEM_EVALUATOR_ID = uuid.UUID("00000000-0000-0000-0000-0000000e0a11")


def _system_principal(organization_id: uuid.UUID) -> Principal:
    return Principal(
        organization_id=organization_id,
        actor_type=ActorType.API_KEY,
        actor_id=SYSTEM_EVALUATOR_ID,
        role=Role.OWNER,
    )


async def run_online_checks(ctx: dict[str, Any], per_status_budget: int = 25) -> dict[str, int]:
    factory: async_sessionmaker[Any] = ctx["session_factory"]
    total_sampled = 0
    total_incomplete = 0
    orgs = 0

    async with factory() as session:
        org_ids = (await session.execute(sa.text("SELECT id FROM organizations"))).scalars().all()

    for org_id in org_ids:
        async with factory() as session:
            command = RunOnlineChecks(
                metrics=SqlMetricsRepository(session),
                scores=SqlScoreStore(session),
            )
            summary = await command(
                _system_principal(uuid.UUID(str(org_id))), per_status_budget=per_status_budget
            )
            await session.commit()
        orgs += 1
        total_sampled += summary.sampled
        total_incomplete += summary.trace_incomplete

    logger.info(
        "run_online_checks: orgs=%s sampled=%s trace_incomplete=%s",
        orgs,
        total_sampled,
        total_incomplete,
    )
    return {"orgs": orgs, "sampled": total_sampled, "trace_incomplete": total_incomplete}
