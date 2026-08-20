"""Judge calibration (study guide §4.4, master plan §10.5).

Measures how well the LLM judge agrees with held-out human labels on a frozen
rubric, per dimension, using quadratic-weighted Cohen's kappa plus raw agreement.
The report is what licenses using the judge as a *secondary trend* — it never
gates correctness, and this study makes its limits explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from crucible.agent import JUDGE_DIMENSIONS, FakeJudge, Judge


@dataclass(frozen=True, slots=True)
class HoldoutItem:
    id: str
    question: str
    answer_contract: str
    verified_result: object
    explanation: str
    human: dict[str, int]


@dataclass(frozen=True, slots=True)
class DimensionAgreement:
    dimension: str
    raw_agreement: float
    weighted_kappa: float
    n: int


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    rubric_version: str
    n_items: int
    per_dimension: dict[str, DimensionAgreement]
    overall_raw_agreement: float
    disagreements: list[dict[str, object]] = field(default_factory=list)

    @property
    def mean_weighted_kappa(self) -> float:
        if not self.per_dimension:
            return 0.0
        return round(
            sum(d.weighted_kappa for d in self.per_dimension.values()) / len(self.per_dimension), 4
        )


def quadratic_weighted_kappa(a: list[int], b: list[int], *, categories: int = 3) -> float:
    """Cohen's kappa with quadratic weights for ordinal labels in [0, categories).
    Returns 1.0 for perfect agreement, 0 for chance, negative for worse-than-chance.
    Undefined variance (one rater constant) is reported as 1.0 iff identical."""
    if len(a) != len(b) or not a:
        return 0.0
    n = len(a)
    observed = [[0.0] * categories for _ in range(categories)]
    for x, y in zip(a, b, strict=True):
        observed[x][y] += 1.0
    row = [sum(observed[i]) for i in range(categories)]
    col = [sum(observed[i][j] for i in range(categories)) for j in range(categories)]

    def weight(i: int, j: int) -> float:
        return ((i - j) ** 2) / ((categories - 1) ** 2)

    num = sum(weight(i, j) * observed[i][j] for i in range(categories) for j in range(categories))
    den = sum(
        weight(i, j) * row[i] * col[j] / n for i in range(categories) for j in range(categories)
    )
    if den == 0:
        return 1.0 if a == b else 0.0
    return round(1.0 - num / den, 4)


def load_holdout(path: str | Path) -> tuple[str, list[HoldoutItem]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    rubric = str(data.get("rubric", "unknown"))
    items = [
        HoldoutItem(
            id=str(it["id"]),
            question=it["question"],
            answer_contract=it["answer_contract"],
            verified_result=(it.get("verified_result") or {}).get("value"),
            explanation=it.get("explanation", ""),
            human={k: int(v) for k, v in it["human"].items()},
        )
        for it in data["items"]
    ]
    return rubric, items


async def run_calibration(judge: Judge, items: list[HoldoutItem]) -> CalibrationReport:
    human_by_dim: dict[str, list[int]] = {d: [] for d in JUDGE_DIMENSIONS}
    judge_by_dim: dict[str, list[int]] = {d: [] for d in JUDGE_DIMENSIONS}
    disagreements: list[dict[str, object]] = []

    for item in items:
        score, _ = await judge.judge(
            question=item.question,
            answer_contract=item.answer_contract,
            verified_result=item.verified_result,
            explanation=item.explanation,
        )
        for d in JUDGE_DIMENSIONS:
            h, j = item.human[d], score.dimension(d)
            human_by_dim[d].append(h)
            judge_by_dim[d].append(j)
            if abs(h - j) >= 2:
                disagreements.append({"item": item.id, "dimension": d, "human": h, "judge": j})

    per_dimension: dict[str, DimensionAgreement] = {}
    for d in JUDGE_DIMENSIONS:
        hd, jd = human_by_dim[d], judge_by_dim[d]
        agree = sum(1 for x, y in zip(hd, jd, strict=True) if x == y) / len(hd)
        per_dimension[d] = DimensionAgreement(
            dimension=d,
            raw_agreement=round(agree, 4),
            weighted_kappa=quadratic_weighted_kappa(hd, jd),
            n=len(hd),
        )

    total = sum(
        1
        for d in JUDGE_DIMENSIONS
        for x, y in zip(human_by_dim[d], judge_by_dim[d], strict=True)
        if x == y
    )
    denom = sum(len(human_by_dim[d]) for d in JUDGE_DIMENSIONS)
    return CalibrationReport(
        rubric_version=getattr(judge, "rubric_version", "unknown"),
        n_items=len(items),
        per_dimension=per_dimension,
        overall_raw_agreement=round(total / denom, 4) if denom else 0.0,
        disagreements=disagreements,
    )


def default_judge() -> Judge:
    return FakeJudge()
