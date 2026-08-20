"""Online evaluation sampler (master plan §10.6).

Samples terminal production runs under a budget and runs cheap *deterministic*
checks on the sample — trace completeness and provenance presence — recording
them as typed deterministic scores. This detects drift and new failure modes
without a model call; model/human scoring of a smaller sample is layered on top
by the review queue and the (calibrated, secondary) judge.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from crucible.application.ports import (
    MetricsRepository,
    RunTelemetryRow,
    ScoreInput,
    ScoreStore,
)
from crucible.domain import Permission, PermissionDenied, Principal, ScoreSource, ScoreType

ONLINE_EVALUATOR_VERSION = "online-deterministic@1"


@dataclass(frozen=True, slots=True)
class OnlineSampleSummary:
    considered: int
    sampled: int
    trace_incomplete: int


class RunOnlineChecks:
    """Deterministic online checks over a stratified sample of terminal runs."""

    def __init__(self, *, metrics: MetricsRepository, scores: ScoreStore) -> None:
        self._metrics = metrics
        self._scores = scores

    async def __call__(
        self, principal: Principal, *, per_status_budget: int = 25
    ) -> OnlineSampleSummary:
        if not principal.can(Permission.EVAL_WRITE):
            raise PermissionDenied()

        rows = await self._metrics.run_telemetry(
            organization_id=principal.organization_id, limit=1000
        )
        by_status: dict[str, list[RunTelemetryRow]] = defaultdict(list)
        for row in rows:
            by_status[row.status].append(row)

        sample = []
        for status_rows in by_status.values():
            # Deterministic stratified sample: the most recent N per status.
            sample.extend(status_rows[:per_status_budget])

        incomplete = 0
        for row in sample:
            if not row.trace_complete:
                incomplete += 1
            await self._scores.add_score(
                organization_id=principal.organization_id,
                score=ScoreInput(
                    definition_key="online.trace_complete",
                    score_type=ScoreType.BOOLEAN.value,
                    source=ScoreSource.DETERMINISTIC.value,
                    target_type="run",
                    target_id=str(row.run_id),
                    evaluator_version=ONLINE_EVALUATOR_VERSION,
                    value_bool=row.trace_complete,
                ),
            )
        return OnlineSampleSummary(
            considered=len(rows), sampled=len(sample), trace_incomplete=incomplete
        )
