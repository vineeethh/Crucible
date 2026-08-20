"""Typed structured outputs and evidence for the agent graph.

These are the contracts at the boundaries between nodes. Model output (plan,
code) is untrusted until it validates against these schemas, and the verifier
records a structured vector rather than a single opaque "confidence" number.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Operation(StrEnum):
    """The bounded set of analyses the workload supports. Anything outside
    this set becomes an honest abstention, never a guess.

    These are domain-agnostic transform primitives — none is specific to
    sales/retail data; each composes over any tabular dataset's own columns.

    GROUP_AGGREGATE and RANK_TOP_N answer with a TABLE (multiple rows)
    instead of one scalar."""

    SUM = "sum"
    MEAN = "mean"
    COUNT = "count"
    COUNT_DISTINCT = "count_distinct"
    MISSING_COUNT = "missing_count"
    MAX_BY_GROUP = "max_by_group"
    MIN_BY_GROUP = "min_by_group"
    GROUP_AGGREGATE = "group_aggregate"
    DEDUPE = "dedupe"  # count of exact-duplicate rows over the whole dataset
    RANK_TOP_N = "rank_top_n"  # top-N rows by a group's reduced value
    ABSTAIN = "abstain"  # the model's honest "I cannot answer this over this data"


# Operations whose target_column is a monetary/quantity aggregate — the shape
# the anti-fabrication guard (policy.py) checks against an identifier-shaped
# column (see PlanStep.column_role).
MONETARY_AGGREGATE_OPS = frozenset(
    {Operation.SUM, Operation.MEAN, Operation.GROUP_AGGREGATE, Operation.RANK_TOP_N}
)


class AnswerKind(StrEnum):
    NUMERIC_SCALAR = "numeric_scalar"
    INTEGER_SCALAR = "integer_scalar"
    CATEGORICAL_SCALAR = "categorical_scalar"
    TABLE = "table"  # a multi-row result (evals/metric-contract.md's Table type)
    ABSTAIN = "abstain"


class Filter(BaseModel):
    column: str
    op: str = Field(default="==", pattern=r"^(==|!=|>|>=|<|<=)$")
    value: str


class PlanStep(BaseModel):
    """One structural transform. `AnalysisPlan.steps` holds one or more of
    these, but only `steps[0]` is executed end to end today — chaining several
    steps into one program is a follow-up, not yet built. The shape is kept
    forward-compatible so that follow-up is additive, not a rework.
    """

    @model_validator(mode="before")
    @classmethod
    def _null_to_default(cls, data: Any) -> Any:
        """A real model emits explicit JSON `null` for a field it considers
        inapplicable to this operation (e.g. `group_reducer` on a plain SUM),
        not just omits the key. Fields typed `str`/`list` (not `X | None`)
        then fail pydantic validation on that `null` — this coerces it back to
        the field's own default before validation, rather than the whole plan
        response being discarded as invalid structured output."""
        if not isinstance(data, dict):
            return data
        defaults = {"group_reducer": "sum", "column_role": "", "referenced_columns": []}
        return {k: (defaults[k] if k in defaults and v is None else v) for k, v in data.items()}

    operation: Operation
    target_column: str | None = None
    group_column: str | None = None
    # Meaningful for GROUP_AGGREGATE and RANK_TOP_N: how each group's
    # target_column is reduced to one row of the output table.
    group_reducer: str = Field(default="sum", pattern=r"^(sum|mean|count)$")
    # RANK_TOP_N only: how many top rows (by group_reducer, descending) to
    # return. 1-50 — an unbounded "top N" is not a reviewable table.
    top_n: int | None = Field(default=None, ge=1, le=50)
    filter: Filter | None = None
    # The planner's short, required-in-the-prompt justification for *why* this
    # column was chosen, e.g. "monetary amount", "row identifier", "category
    # label", "date". Not pydantic-required (many operations, e.g. COUNT with
    # no filter, use no column at all) — but the planner prompt asks for it on
    # every step that names a target_column, and the anti-fabrication guard
    # treats a missing role on a monetary aggregate as an unresolved signal,
    # not a free pass.
    column_role: str = ""
    referenced_columns: list[str] = Field(default_factory=list)


class AnalysisPlan(BaseModel):
    """A reviewable plan, not free-form reasoning (master plan §8.3).

    Internally always a `steps` list; a model response using the older flat
    single-operation shape (operation/target_column/group_column/filter/
    column_role/referenced_columns at the top level) is accepted and wrapped
    into a one-element `steps` list by `_wrap_flat_shape` below, so the
    planner prompt can keep asking for a flat JSON object today. Multi-step
    plans (the model emitting `steps` directly) are already valid input; the
    coder/executor side that would actually chain them is the follow-up.
    """

    steps: list[PlanStep] = Field(min_length=1, max_length=6)
    answer_kind: AnswerKind
    rationale: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="before")
    @classmethod
    def _wrap_flat_shape(cls, data: Any) -> Any:
        if not isinstance(data, dict) or "steps" in data:
            return data
        step_fields = {
            "operation",
            "target_column",
            "group_column",
            "group_reducer",
            "top_n",
            "filter",
            "column_role",
            "referenced_columns",
        }
        if "operation" not in data:
            return data
        step = {k: v for k, v in data.items() if k in step_fields}
        rest = {k: v for k, v in data.items() if k not in step_fields}
        rest["steps"] = [step]
        return rest

    # -- back-compat accessors onto the first (and, today, only-executed) step
    @property
    def operation(self) -> Operation:
        return self.steps[0].operation

    @property
    def target_column(self) -> str | None:
        return self.steps[0].target_column

    @property
    def group_column(self) -> str | None:
        return self.steps[0].group_column

    @property
    def group_reducer(self) -> str:
        return self.steps[0].group_reducer

    @property
    def top_n(self) -> int | None:
        return self.steps[0].top_n

    @property
    def filter(self) -> Filter | None:
        return self.steps[0].filter

    @property
    def column_role(self) -> str:
        return self.steps[0].column_role

    @property
    def referenced_columns(self) -> list[str]:
        seen: list[str] = []
        for step in self.steps:
            for col in step.referenced_columns:
                if col not in seen:
                    seen.append(col)
        return seen

    @property
    def is_abstain(self) -> bool:
        return self.steps[0].operation is Operation.ABSTAIN or self.answer_kind is AnswerKind.ABSTAIN


class GeneratedCode(BaseModel):
    """Untrusted Python source produced by the coder role."""

    source: str
    explanation: str = ""


class ChallengeOutcome(BaseModel):
    """One metamorphic re-execution: the SAME generated program run again
    against a transformed dataset, checking a relation that needs no gold
    answer (master plan Tier 2, metric-contract.md's "invariant/metamorphic
    scorer"). `held=False` means the program's answer changed under a
    transform that should never have changed it — evidence the program is
    wrong, independent of what the correct answer actually is."""

    transform: str  # e.g. "row_shuffle", "column_reorder"
    relation: str  # human-readable statement of what was expected
    held: bool
    detail: str = ""


class VerificationDecision(StrEnum):
    ANSWER = "answer"
    REVIEW = "review"
    ABSTAIN = "abstain"


class VerificationVector(BaseModel):
    """Structured evidence combined into an answer/review/abstain decision.

    This is *online serving* verification: it establishes execution success,
    schema/provenance consistency, and policy compliance. It deliberately does
    not claim the answer is mathematically correct just because code ran
    (master plan §8.3) — that certainty only exists offline against a known
    reference (Phase 5). `metamorphic_checks` is the exception: a violated
    invariant IS direct evidence of a wrong program, with no gold needed.
    """

    plan_valid: bool = False
    columns_exist: bool = False
    execution_ok: bool = False
    result_schema_valid: bool = False
    provenance_present: bool = False
    policy_ok: bool = False
    ambiguous: bool = False  # e.g. a tie in a max-by-group — the data is unclear
    metamorphic_checks: list[ChallengeOutcome] = Field(default_factory=list)
    decision: VerificationDecision = VerificationDecision.ABSTAIN
    reasons: list[str] = Field(default_factory=list)


class Provenance(BaseModel):
    """Points the answer at the actual computed result and how it was produced."""

    dataset_version_id: str
    dataset_sha256: str | None = None
    operation: str = ""
    columns_used: list[str] = Field(default_factory=list)
    code_sha256: str = ""
    attempt_count: int = 0
    executor_backend: str = ""
    image_ref: str = ""


class Answer(BaseModel):
    answer_kind: AnswerKind
    value: object = None
    text: str = ""
    provenance: Provenance
    limitations: str = ""
    # True when this answer was replayed from the exact cache (Phase 8). The
    # provenance still points at the original computation's evidence.
    cached: bool = False
    # TABLE answers only: the artifact filename holding the rows, and the row
    # count computed inside the sandbox. Row content is never in this object
    # or in `text` — only the API layer serves the artifact bytes themselves.
    table_ref: str | None = None
    row_count: int | None = None


class JudgeRubricScore(BaseModel):
    """The LLM judge's narrow, ordinal assessment of *explanation quality* only
    (master plan §10.5). Each dimension is 0/1/2. The judge never scores the
    numeric answer — that has a deterministic oracle — and can never override it.
    """

    groundedness: int = Field(ge=0, le=2)
    provenance: int = Field(ge=0, le=2)
    usefulness: int = Field(ge=0, le=2)
    uncertainty: int = Field(ge=0, le=2)
    rationale: str = ""

    @property
    def total(self) -> int:
        return self.groundedness + self.provenance + self.usefulness + self.uncertainty

    def dimension(self, name: str) -> int:
        return int(getattr(self, name))


JUDGE_DIMENSIONS = ("groundedness", "provenance", "usefulness", "uncertainty")
