"""LLM-as-a-judge (master plan §10.5, study guide §4.4).

The judge scores explanation quality against a narrow, frozen rubric. It is
given the question, the answer contract, the *verified* structured result, and
the candidate explanation — not the model identity, and never the authority to
decide the numeric answer. It is a secondary trend, calibrated against held-out
human labels, and it never overrides a Tier 1 oracle.

`FakeJudge` is deterministic and offline (for calibration machinery + tests);
`OpenAICompatJudge` is the real contract, deny-by-default.
"""

from __future__ import annotations

import re
from typing import Protocol

from crucible.agent.errors import ModelNotConfigured
from crucible.agent.ports import ModelUsage
from crucible.agent.schemas import JudgeRubricScore

JUDGE_RUBRIC_VERSION = "judge-rubric@1"


class Judge(Protocol):
    @property
    def rubric_version(self) -> str: ...

    async def judge(
        self,
        *,
        question: str,
        answer_contract: str,
        verified_result: object,
        explanation: str,
    ) -> tuple[JudgeRubricScore, ModelUsage]: ...


class FakeJudge:
    """Deterministic rubric scorer.

    Heuristics stand in for a model: does the explanation reference the computed
    value and the columns (groundedness/provenance), is it concise and on-point
    (usefulness), and does it acknowledge limitations when warranted
    (uncertainty). Deterministic, so calibration against human labels is stable.
    """

    @property
    def rubric_version(self) -> str:
        return JUDGE_RUBRIC_VERSION

    async def judge(
        self,
        *,
        question: str,
        answer_contract: str,
        verified_result: object,
        explanation: str,
    ) -> tuple[JudgeRubricScore, ModelUsage]:
        text = explanation.lower()
        value_str = _value_str(verified_result)

        grounded = 0
        if value_str and value_str in text:
            grounded = 2
        elif any(
            tok in text for tok in ("compute", "result", "value", "total", "count", "average")
        ):
            grounded = 1
        if _contradicts(text):
            grounded = 0

        provenance = 0
        if re.search(r"\bcolumn|over the|grouped|filter|dataset\b", text):
            provenance = 2 if value_str and value_str in text else 1

        usefulness = 2 if 0 < len(explanation) <= 240 else (1 if explanation else 0)

        uncertainty = 0
        if any(
            tok in text
            for tok in (
                "cannot",
                "insufficient",
                "abstain",
                "ambiguous",
                "not verified",
                "limitation",
            )
        ):
            uncertainty = 2
        elif "approximately" in text or "assum" in text:
            uncertainty = 1

        score = JudgeRubricScore(
            groundedness=grounded,
            provenance=provenance,
            usefulness=usefulness,
            uncertainty=uncertainty,
            rationale="deterministic heuristic assessment",
        )
        return score, ModelUsage(provider="fake", model_id="fake-judge", cost_usd=0.0)


def _value_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _contradicts(text: str) -> bool:
    return any(tok in text for tok in ("actually wrong", "made up", "guessed", "no idea"))


class OpenAICompatJudge:
    """Real judge contract against an OpenAI-compatible endpoint. Deny-by-default;
    a different model family from the generator where feasible (bias reduction,
    not independence). Network integration is provisioned in Phase 9/10."""

    def __init__(self, *, base_url: str | None = None, model: str | None = None) -> None:
        self._base_url = base_url
        self._model = model

    @property
    def rubric_version(self) -> str:
        return JUDGE_RUBRIC_VERSION

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._model)

    async def judge(
        self, *, question: str, answer_contract: str, verified_result: object, explanation: str
    ) -> tuple[JudgeRubricScore, ModelUsage]:
        if not self.configured:
            raise ModelNotConfigured("the judge requires base_url and model; no silent fallback")
        raise ModelNotConfigured("judge provider integration is not provisioned yet")
