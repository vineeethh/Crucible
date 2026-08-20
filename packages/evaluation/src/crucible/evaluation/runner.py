"""Experiment runner: run the agent over every case in a suite, then score.

Runs the real agent graph (via the eval entrypoint) so the evaluation measures
shipped behavior, not a reimplementation. The result is per-case outcomes and
scores plus the config and content hashes needed for a reproducible report.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from crucible.agent import DatasetView, ModelGateway, run_to_completion
from crucible.evaluation.config import EvalConfig
from crucible.evaluation.outcome import AgentOutcome, outcome_from_trace
from crucible.evaluation.schemas import EvalFixture, EvalSuite
from crucible.evaluation.scorers import CaseScore, score_case
from crucible.execution import ExecutionLimits, Executor


@dataclass(slots=True)
class ExperimentResult:
    config: EvalConfig
    suite_id: str
    suite_version: str
    suite_hash: str
    fixture_id: str
    fixture_sha256: str
    outcomes: dict[str, AgentOutcome] = field(default_factory=dict)
    scores: dict[str, CaseScore] = field(default_factory=dict)

    @property
    def accuracy(self) -> float:
        if not self.scores:
            return 0.0
        return round(sum(1 for s in self.scores.values() if s.correct) / len(self.scores), 4)


class ExperimentRunner:
    def __init__(
        self,
        *,
        model: ModelGateway,
        executor: Executor,
        limits: ExecutionLimits,
        config: EvalConfig,
    ) -> None:
        self._model = model
        self._executor = executor
        self._limits = limits
        self._config = config

    async def run(
        self, suite: EvalSuite, fixture: EvalFixture, fixture_bytes: bytes
    ) -> ExperimentResult:
        dataset = DatasetView(
            version_id=fixture.id,
            object_key=f"(eval:{fixture.id})",
            content_sha256=fixture.sha256,
            media_type="text/csv",
            filename=fixture.file,
            profile=fixture.column_views(),
        )
        result = ExperimentResult(
            config=self._config,
            suite_id=suite.id,
            suite_version=suite.version,
            suite_hash=suite.content_hash,
            fixture_id=fixture.id,
            fixture_sha256=fixture.sha256,
        )
        for case in suite.cases:
            trace = await run_to_completion(
                model=self._model,
                executor=self._executor,
                limits=self._limits,
                question=case.question,
                dataset=dataset,
                dataset_bytes=fixture_bytes,
            )
            outcome = outcome_from_trace(trace)
            result.outcomes[case.id] = outcome
            result.scores[case.id] = score_case(case, outcome)
        return result
