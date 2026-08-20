"""Baseline governance (master plan §10.2, §10.7).

The baseline is frozen evidence: the reviewed per-case results of the approved
config, plus the suite hash and the regression tolerance. A candidate is compared
against it without re-running it, so baseline evidence is never overwritten by a
candidate run. Re-baselining is an explicit, reviewed edit to `evals/baseline.json`.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from crucible.evaluation.runner import ExperimentResult
from crucible.evaluation.scorers import CaseScore


class BaselineCase(BaseModel):
    correct: bool
    policy_ok: bool


class Baseline(BaseModel):
    suite_id: str
    suite_version: str
    suite_hash: str
    config_id: str
    config_hash: str
    accuracy: float
    tolerance: float = 0.02
    approved_by: str = ""
    approved_at: str = ""
    notes: str = ""
    per_case: dict[str, BaselineCase] = Field(default_factory=dict)

    def scores(self) -> dict[str, CaseScore]:
        return {
            cid: CaseScore(case_id=cid, correct=bc.correct, policy_ok=bc.policy_ok)
            for cid, bc in self.per_case.items()
        }


def load_baseline(path: str | Path) -> Baseline:
    return Baseline.model_validate_json(Path(path).read_text(encoding="utf-8"))


def baseline_from_result(
    result: ExperimentResult,
    *,
    approved_by: str,
    approved_at: str,
    notes: str = "",
    tolerance: float = 0.02,
) -> Baseline:
    return Baseline(
        suite_id=result.suite_id,
        suite_version=result.suite_version,
        suite_hash=result.suite_hash,
        config_id=result.config.id,
        config_hash=result.config.config_hash,
        accuracy=result.accuracy,
        tolerance=tolerance,
        approved_by=approved_by,
        approved_at=approved_at,
        notes=notes,
        per_case={
            cid: BaselineCase(correct=s.correct, policy_ok=s.policy_ok)
            for cid, s in result.scores.items()
        },
    )


def write_baseline(baseline: Baseline, path: str | Path) -> None:
    Path(path).write_text(baseline.model_dump_json(indent=2) + "\n", encoding="utf-8")
