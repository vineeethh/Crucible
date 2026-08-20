"""Deterministic template model gateway.

The `fake` backend never calls a network provider. Its planner is a small intent
parser over the question and dataset profile; its coder is the deterministic
polars generator. This makes the entire agent pipeline — plan, code, execute,
verify, synthesize — runnable and testable offline, and produces genuinely
correct answers for the bounded operation set (real execution still happens in
the sandbox).

For tests that need to drive specific graph branches (a repair that fixes a
bug, a forced abstention), pass `scripts`: a per-role queue of canned responses
that are popped in order before falling back to the template behavior.
"""

from __future__ import annotations

import re
from collections import deque
from typing import Any

from crucible.agent.models import registry  # module import: safe during pkg init
from crucible.agent.models.codegen import generate_source
from crucible.agent.ports import ModelRole, ModelUsage
from crucible.agent.schemas import (
    AnalysisPlan,
    AnswerKind,
    Filter,
    GeneratedCode,
    Operation,
)
from crucible.agent.state import ColumnView

_NUMERIC_PREFIXES = ("int", "float", "uint", "decimal")

PROMPT_VERSION = "fake-templates@1"
POLICY_VERSION = "static@1"


def _is_numeric(dtype: str) -> bool:
    return dtype.lower().startswith(_NUMERIC_PREFIXES)


def _tokens(text: str) -> set[str]:
    raw = re.split(r"[^a-z0-9]+", text.lower())
    # Singularize crudely so "customers"/"reps"/"rows" match "customer_id"/"rep"/
    # "row" columns. Threshold >3 so 4-letter plurals like "reps" collapse too.
    return {t[:-1] if len(t) > 3 and t.endswith("s") else t for t in raw if t}


def _fuzzy_hit(col_tokens: set[str], q_tokens: set[str]) -> bool:
    if col_tokens & q_tokens:
        return True
    # Prefix overlap for tokens of reasonable length (region ~ regional).
    return any(
        len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a))
        for a in col_tokens
        for b in q_tokens
    )


# CamelCase/underscore-aware, unlike `_tokens` above (which treats "OrderID"
# as one blob "orderid") — needed specifically to recognize an identifier
# column by its LAST component, e.g. "OrderID" -> "Order"+"ID".
_ID_TOKEN_SPLIT = re.compile(r"[_\s]+|(?<=[a-z0-9])(?=[A-Z])")


def _is_identifier_shaped(name: str) -> bool:
    tokens = [t for t in _ID_TOKEN_SPLIT.split(name) if t]
    return bool(tokens) and tokens[-1].lower() == "id"


def _match_column(
    columns: list[ColumnView], q_tokens: set[str], *, numeric: bool | None = None
) -> ColumnView | None:
    for col in columns:
        if numeric is True and not _is_numeric(col.dtype):
            continue
        if numeric is False and _is_numeric(col.dtype):
            continue
        if _fuzzy_hit(_tokens(col.name), q_tokens):
            return col
    return None


def _match_group_column(columns: list[ColumnView], q_tokens: set[str]) -> ColumnView | None:
    """A grouping key is usually a category/label column, so prefer a
    non-numeric match first, and prefer an EXACT token hit over a prefix-fuzzy
    one — in that order of precedence:

      1. non-numeric column, exact token hit
      2. numeric column,     exact token hit   (a region/category CODE)
      3. non-numeric column, fuzzy (prefix) hit
      4. numeric column,     fuzzy (prefix) hit

    Without the exact-first precedence, a plural like "orders" prefix-matches
    "OrderID" (order⊂orderid) and can beat an exact "RegionCode" hit sitting
    later in column order — grouping "how many orders by RegionCode" by
    OrderID (600 near-unique groups) instead of RegionCode. Without the
    non-numeric-first precedence, a numeric metric column mentioned in the
    same question (e.g. "price" in "highest total price ... by rep") can win
    the group slot away from the intended non-numeric grouping key.
    """
    for numeric_pref in (False, True):
        for col in columns:
            if _is_numeric(col.dtype) != numeric_pref:
                continue
            if _tokens(col.name) & q_tokens:
                return col
    for numeric_pref in (False, True):
        for col in columns:
            if _is_numeric(col.dtype) != numeric_pref:
                continue
            if _fuzzy_hit(_tokens(col.name), q_tokens):
                return col
    return None


class FakeModel:
    MODEL_ID = registry.FAKE_TEMPLATE_ID

    def __init__(self, scripts: dict[ModelRole, list[Any]] | None = None) -> None:
        self._scripts: dict[ModelRole, deque[Any]] = {
            role: deque(items) for role, items in (scripts or {}).items()
        }

    # ---------------------------------------------------------------- manifest
    def manifest(self) -> dict[str, dict[str, Any]]:
        return {
            role.value: {
                "provider": "fake",
                "model_id": self.MODEL_ID,
                "prompt_version": PROMPT_VERSION,
                "policy_version": POLICY_VERSION,
                "params": {},
            }
            for role in (ModelRole.PLANNER, ModelRole.CODER, ModelRole.REPAIR)
        }

    def _scripted(self, role: ModelRole) -> Any | None:
        queue = self._scripts.get(role)
        return queue.popleft() if queue else None

    def _usage(self, prompt: str, completion: str) -> ModelUsage:
        # Deterministic token estimates x the registry's declared (synthetic)
        # price, so cost attribution flows through the same pipeline as a real
        # provider's reported usage.
        tokens_in = registry.estimate_tokens(prompt)
        tokens_out = registry.estimate_tokens(completion)
        return ModelUsage(
            provider="fake",
            model_id=self.MODEL_ID,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=registry.compute_cost(
                self.MODEL_ID, tokens_in=tokens_in, tokens_out=tokens_out
            ),
        )

    @staticmethod
    def _prompt_text(question: str, profile: list[ColumnView]) -> str:
        return question + " " + " ".join(f"{c.name}:{c.dtype}" for c in profile)

    # -------------------------------------------------------------------- plan
    async def plan(
        self, *, question: str, profile: list[ColumnView]
    ) -> tuple[AnalysisPlan, ModelUsage]:
        prompt = self._prompt_text(question, profile)
        scripted = self._scripted(ModelRole.PLANNER)
        if isinstance(scripted, AnalysisPlan):
            return scripted, self._usage(prompt, scripted.model_dump_json())
        plan = self._plan_from_question(question, profile)
        return plan, self._usage(prompt, plan.model_dump_json())

    def _plan_from_question(self, question: str, profile: list[ColumnView]) -> AnalysisPlan:
        q = question.lower()
        qt = _tokens(question)

        def abstain(reason: str) -> AnalysisPlan:
            return AnalysisPlan(
                operation=Operation.ABSTAIN,
                answer_kind=AnswerKind.ABSTAIN,
                rationale=reason,
                confidence=0.0,
            )

        # Exact-duplicate-row count. Checked early: "duplicate"/"dedupe" should
        # never fall through to another branch's looser keyword match. But a
        # COMPOUND request ("drop duplicates AND fill missing values") asks for
        # more than a count — answering only the duplicate half and silently
        # dropping the rest is not honest, so that still falls through to abstain.
        if any(w in q for w in ("duplicate", "dedupe", "dedup")) and not any(
            w in q for w in ("fill", "impute")
        ):
            return AnalysisPlan(
                operation=Operation.DEDUPE,
                answer_kind=AnswerKind.INTEGER_SCALAR,
                rationale="count of exact duplicate rows",
            )

        # "top N" / "N largest" is a RANKED LIST (RANK_TOP_N -> TABLE), never
        # max_by_group (which answers a narrower question: the single
        # most-frequent/-summed group, not a ranking).
        top_n_match = re.search(r"\btop\s+(\d+)\b", q) or re.search(
            r"\b(\d+)\s+(?:largest|smallest|highest|lowest)\b", q
        )
        if top_n_match:
            n = int(top_n_match.group(1))
            group = _match_group_column(profile, qt)
            target_pool = [
                c
                for c in profile
                if (group is None or c.name != group.name) and not _is_identifier_shaped(c.name)
            ]
            target = _match_column(target_pool, qt, numeric=True)
            if group is not None and target is not None and 1 <= n <= 50:
                reducer = "mean" if any(w in q for w in ("average", "mean", "avg")) else "sum"
                return AnalysisPlan(
                    operation=Operation.RANK_TOP_N,
                    answer_kind=AnswerKind.TABLE,
                    group_column=group.name,
                    target_column=target.name,
                    group_reducer=reducer,
                    top_n=n,
                    referenced_columns=[group.name, target.name],
                    rationale=f"top {n} {group.name} by {reducer} of {target.name}",
                    confidence=1.0,
                )
            return abstain(
                "a ranked top-N list needs a grouping column and a numeric metric to rank by"
            )

        # Missing / null values.
        if any(w in q for w in ("missing", "null", "empty", "blank")):
            col = _match_column(profile, qt)
            if col is None:
                return abstain("no column in the question matches the dataset schema")
            return AnalysisPlan(
                operation=Operation.MISSING_COUNT,
                answer_kind=AnswerKind.INTEGER_SCALAR,
                target_column=col.name,
                referenced_columns=[col.name],
                rationale=f"count missing values in {col.name}",
            )

        # Distinct / unique count.
        if any(w in q for w in ("distinct", "unique")):
            col = _match_column(profile, qt)
            if col is None:
                return abstain("no column matches for a distinct count")
            return AnalysisPlan(
                operation=Operation.COUNT_DISTINCT,
                answer_kind=AnswerKind.INTEGER_SCALAR,
                target_column=col.name,
                referenced_columns=[col.name],
                rationale=f"distinct values of {col.name}",
            )

        # Superlative over groups: which <group> has the highest/most <metric>.
        superlative_hi = any(
            w in q for w in ("highest", "largest", "most", "maximum", "top", "greatest")
        )
        superlative_lo = any(w in q for w in ("lowest", "smallest", "least", "minimum", "fewest"))
        if superlative_hi or superlative_lo:
            group = _match_group_column(profile, qt)
            # Exclude the group column itself from the target search: a
            # numeric-coded group (e.g. RegionCode) would otherwise be picked
            # as its own aggregation target when it appears earlier in the
            # dataset's column order than the intended metric.
            target_pool = [
                c
                for c in profile
                if (group is None or c.name != group.name) and not _is_identifier_shaped(c.name)
            ]
            target = _match_column(target_pool, qt, numeric=True)
            if group is not None:
                op = Operation.MAX_BY_GROUP if superlative_hi else Operation.MIN_BY_GROUP
                refs = [group.name] + ([target.name] if target else [])
                return AnalysisPlan(
                    operation=op,
                    answer_kind=AnswerKind.CATEGORICAL_SCALAR,
                    group_column=group.name,
                    target_column=target.name if target else None,
                    referenced_columns=refs,
                    rationale=f"{op.value} over {group.name}",
                    confidence=1.0 if target else 0.8,
                )
            return abstain("a superlative question needs a grouping column")

        # Full per-group breakdown ("<metric> by <group>", no superlative word)
        # -> a TABLE answer, one row per group, not one picked winner.
        if " by " in f" {q} ":
            group = _match_group_column(profile, qt)
            # Exclude the group column itself from the target search: a
            # numeric-coded group (e.g. RegionCode) would otherwise be picked
            # as its own aggregation target when it appears earlier in the
            # dataset's column order than the intended metric.
            target_pool = [
                c
                for c in profile
                if (group is None or c.name != group.name) and not _is_identifier_shaped(c.name)
            ]
            target = _match_column(target_pool, qt, numeric=True)
            if group is not None and target is not None:
                reducer = "mean" if any(w in q for w in ("average", "mean", "avg")) else "sum"
                return AnalysisPlan(
                    operation=Operation.GROUP_AGGREGATE,
                    answer_kind=AnswerKind.TABLE,
                    group_column=group.name,
                    target_column=target.name,
                    group_reducer=reducer,
                    referenced_columns=[group.name, target.name],
                    rationale=f"{reducer} of {target.name} by {group.name}",
                    confidence=1.0,
                )
            if group is not None:
                return abstain("a group breakdown needs a numeric column to aggregate")

        # Average / mean.
        if any(w in q for w in ("average", "mean", "avg")):
            col = _match_column(profile, qt, numeric=True)
            if col is None:
                return abstain("no numeric column matches for an average")
            return AnalysisPlan(
                operation=Operation.MEAN,
                answer_kind=AnswerKind.NUMERIC_SCALAR,
                target_column=col.name,
                referenced_columns=[col.name],
                rationale=f"mean of {col.name}",
            )

        # Total / sum.
        if any(w in q for w in ("total", "sum")):
            col = _match_column(profile, qt, numeric=True)
            if col is None:
                return abstain("no numeric column matches for a total")
            return AnalysisPlan(
                operation=Operation.SUM,
                answer_kind=AnswerKind.NUMERIC_SCALAR,
                target_column=col.name,
                referenced_columns=[col.name],
                rationale=f"sum of {col.name}",
            )

        # Plain count (optionally filtered): how many / number of.
        if any(w in q for w in ("how many", "number of", "count")):
            filt = self._parse_filter(question, profile)
            refs = [filt.column] if filt else []
            return AnalysisPlan(
                operation=Operation.COUNT,
                answer_kind=AnswerKind.INTEGER_SCALAR,
                filter=filt,
                referenced_columns=refs,
                rationale="row count" + (" with a filter" if filt else ""),
            )

        return abstain("the question does not map to a supported analysis")

    @staticmethod
    def _parse_filter(question: str, profile: list[ColumnView]) -> Filter | None:
        # A deliberately narrow pattern: "... <column> is/= <value>" or
        # "... in <value>". Anything more complex abstains rather than guess.
        m = re.search(
            r"(?:where|with|for)\s+(\w+)\s*(?:is|=|==|equals?)\s*([\w-]+)", question, re.I
        )
        if not m:
            return None
        col_token, value = m.group(1), m.group(2)
        col = _match_column(profile, _tokens(col_token), numeric=None)
        if col is None:
            return None
        return Filter(column=col.name, op="==", value=value)

    # -------------------------------------------------------------------- code
    async def code(
        self, *, plan: AnalysisPlan, profile: list[ColumnView]
    ) -> tuple[GeneratedCode, ModelUsage]:
        prompt = plan.model_dump_json()
        scripted = self._scripted(ModelRole.CODER)
        if isinstance(scripted, (GeneratedCode, str)):
            src = scripted.source if isinstance(scripted, GeneratedCode) else scripted
            return GeneratedCode(source=src, explanation="scripted"), self._usage(prompt, src)
        source = generate_source(plan)
        return GeneratedCode(source=source, explanation=plan.rationale), self._usage(prompt, source)

    # ------------------------------------------------------------------ repair
    async def repair(
        self, *, plan: AnalysisPlan, profile: list[ColumnView], prior_code: str, error: str
    ) -> tuple[GeneratedCode, ModelUsage]:
        prompt = plan.model_dump_json() + prior_code + error
        scripted = self._scripted(ModelRole.REPAIR)
        if isinstance(scripted, (GeneratedCode, str)):
            src = scripted.source if isinstance(scripted, GeneratedCode) else scripted
            return GeneratedCode(source=src, explanation="scripted repair"), self._usage(
                prompt, src
            )
        # The template coder is deterministic, so regenerating the same plan
        # yields the same code. That is intentional: a deterministic error will
        # reproduce, the oscillation guard will fire, and the run abstains rather
        # than looping. (A real model would attempt an actual fix here.)
        source = generate_source(plan)
        return GeneratedCode(source=source, explanation="regenerated"), self._usage(prompt, source)


class FakeLiteModel(FakeModel):
    """The tier-1 "cheap" gateway for the two-tier router.

    Deliberately narrower than the reference template model: it plans only the
    simple aggregate shapes (sum / count / mean). Anything else abstains with a
    rationale, which the router's declared policy escalates to tier 2 — so the
    routed pipeline trades extra cost on hard questions for a much cheaper
    happy path, without inventing answers at the cheap tier.
    """

    MODEL_ID = registry.FAKE_LITE_ID

    _LITE_OPS = frozenset({Operation.SUM, Operation.COUNT, Operation.MEAN})

    def _plan_from_question(self, question: str, profile: list[ColumnView]) -> AnalysisPlan:
        plan = super()._plan_from_question(question, profile)
        if plan.operation in self._LITE_OPS or plan.is_abstain:
            return plan
        return AnalysisPlan(
            operation=Operation.ABSTAIN,
            answer_kind=AnswerKind.ABSTAIN,
            rationale=f"beyond tier-1 scope ({plan.operation.value})",
            confidence=0.0,
        )
