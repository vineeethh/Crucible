"""Retry and confidence policy — a finite-state policy, not an optimistic loop.

Reflection is bounded (master plan §8.3): repair only correctable classes, cap
attempts, and stop on a repeated code/error fingerprint so the loop cannot
oscillate. The confidence policy combines the verification vector into an
answer / review / abstain decision without ever claiming certainty from the mere
fact that code ran.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

from crucible.agent.schemas import (
    MONETARY_AGGREGATE_OPS,
    AnalysisPlan,
    AnswerKind,
    Operation,
    VerificationDecision,
    VerificationVector,
)
from crucible.agent.state import ColumnView
from crucible.domain import FailureCategory
from crucible.execution import ArtifactRef

MAX_REPAIRS = 2  # after the initial attempt

# Separate budget from MAX_REPAIRS above: a repair fixes a CRASH (the code
# didn't run); a revision fixes a VERIFIED-WRONG answer (the code ran, but
# verify() caught a semantic or computational failure — Node.REVISE). Kept
# distinct because they're different failure modes with different prompts.
MAX_REVISIONS = 2  # automatic verify()-driven revisions before routing to a human
MAX_HUMAN_REVISIONS = 3  # "revise" resumes a human can request before abstaining

# Failure categories a repair may address. Everything else is terminal: a policy
# denial, injection suspicion, or exhausted budget is never retried with more
# access (master plan §8.3, failure taxonomy).
_REPAIRABLE: frozenset[FailureCategory] = frozenset(
    {
        FailureCategory.CODE_SYNTAX_ERROR,
        FailureCategory.CODE_RUNTIME_ERROR,
        FailureCategory.SCHEMA_MISMATCH,
        FailureCategory.RESULT_SERIALIZATION_ERROR,
    }
)


def is_repairable(category: FailureCategory | None) -> bool:
    return category in _REPAIRABLE


def fingerprint(code_sha256: str, failure_category: str | None, error_detail: str | None) -> str:
    """A stable signature for an attempt outcome. If the same code produces the
    same error class twice, repairing again is pointless — abstain instead."""
    basis = f"{code_sha256}|{failure_category}|{(error_detail or '')[:200]}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def revision_fingerprint(plan_json: str, reasons: list[str]) -> str:
    """Same oscillation-guard shape as fingerprint() above, for the
    verify()-driven revision loop: if the same plan produces the same set of
    verification failures again after a revision, revising further is
    pointless — route to a human instead of spinning."""
    basis = f"{plan_json}|{'|'.join(sorted(reasons))}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def decide(vector: VerificationVector) -> VerificationDecision:
    """The online confidence policy. Hard requirements gate an answer; a genuine
    ambiguity in the data routes to a human; anything short of the requirements
    abstains rather than guesses."""
    hard_ok = (
        vector.plan_valid
        and vector.columns_exist
        and vector.execution_ok
        and vector.result_schema_valid
        and vector.provenance_present
        and vector.policy_ok
    )
    if not hard_ok:
        return VerificationDecision.ABSTAIN
    if vector.ambiguous:
        return VerificationDecision.REVIEW
    return VerificationDecision.ANSWER


def result_schema_valid(
    plan: AnalysisPlan, result: dict[str, object], artifacts: Sequence[ArtifactRef]
) -> bool:
    """Shape-dispatched replacement for the old blanket `"value" in result`
    check. Scalar answer kinds are unchanged; a TABLE answer must name a
    `table_ref` that was actually collected as a sandbox artifact, with a
    non-negative row count and a non-empty column list."""
    if plan.answer_kind is AnswerKind.TABLE:
        table_ref = result.get("table_ref")
        if not isinstance(table_ref, str) or not table_ref:
            return False
        if not any(a.name == table_ref for a in artifacts):
            return False
        row_count = result.get("row_count")
        columns = result.get("columns")
        return (
            isinstance(row_count, int)
            and row_count >= 0
            and isinstance(columns, list)
            and bool(columns)
        )
    return "value" in result and result.get("value") is not None


# --- Anti-fabrication guard --------------------------------------------------
#
# Splits a column name on underscores and camelCase boundaries so "OrderID",
# "order_id", and "orderId" all yield a last token of "id" — but "AmountPaid"
# yields "paid", not "id", avoiding a false hit on a real monetary column that
# merely ends in similar letters.
_TOKEN_SPLIT = re.compile(r"[_\s]+|(?<=[a-z0-9])(?=[A-Z])")

_IDENTIFIER_ROLE_HINTS = ("identifier", "id ", " id", "primary key", "row id")
_MONETARY_ROLE_HINTS = ("monetary", "amount", "revenue", "price", "cost", "sales", "quantity")


def _last_token(name: str) -> str:
    tokens = [t for t in _TOKEN_SPLIT.split(name) if t]
    return tokens[-1].lower() if tokens else ""


def check_column_semantics(
    plan: AnalysisPlan, profile: Sequence[ColumnView], row_count: int | None
) -> tuple[bool, bool, str]:
    """Structural guard against summing/averaging an identifier column (the
    `sum(OrderID)` fabrication this guard was written to close). Reads only
    column names and the profiler's own `distinct_count`/row_count stats —
    never a prompt, never a cell value.

    Returns `(contradiction, uncertain, reason)`:
      - `contradiction=True`  -> the plan's own `column_role` already concedes
        this is an identifier while aggregating it as a quantity; hard abstain.
      - `uncertain=True`      -> the column looks identifier-shaped and the
        plan gives no convincing defense; route to human review rather than
        silently answering OR blanket-rejecting (a legitimate edge case may
        exist that only a human can confirm).
      - both False            -> no signal; the guard has nothing to add.
    """
    if plan.operation not in MONETARY_AGGREGATE_OPS:
        return False, False, ""
    col = plan.target_column
    if not col:
        return False, False, ""

    name_looks_like_id = _last_token(col) == "id"

    value_looks_like_id = False
    if row_count and row_count > 0:
        match = next((c for c in profile if c.name == col), None)
        if match is not None and match.distinct_count is not None:
            value_looks_like_id = match.distinct_count >= row_count * 0.98

    if not (name_looks_like_id or value_looks_like_id):
        return False, False, ""

    role = plan.column_role.lower()
    role_says_identifier = any(h in role for h in _IDENTIFIER_ROLE_HINTS)
    role_says_monetary = any(h in role for h in _MONETARY_ROLE_HINTS)

    if role_says_identifier:
        return (
            True,
            False,
            f"the plan's own column_role calls {col!r} an identifier, but "
            f"{plan.operation.value} aggregates it as a quantity",
        )
    if role_says_monetary:
        # The plan explicitly defends this as monetary despite looking like an
        # id. A real edge case may exist; don't hardcode either verdict.
        return False, True, f"{col!r} is identifier-shaped but the plan claims it is monetary"
    return False, True, f"{col!r} looks like an identifier and the plan gives no column_role defending it"


# --- Plausibility assertions -------------------------------------------------
#
# Deterministic bounds checks against stats the storage-layer profiler already
# computed at upload time (packages/storage/.../profiler.py) — never a cell
# value, so this stays host-side only, same as the anti-fabrication guard. A
# violation is direct evidence the program is wrong: these are logically
# impossible outcomes (a count bigger than the dataset, a mean outside the
# column's own observed range), not a judgment call needing a gold answer.


def _is_finite_number(value: object) -> bool:
    # bool is an int subclass but never NaN/Inf, so math.isfinite(bool) is
    # trivially True — no special-casing needed to avoid a false violation.
    return isinstance(value, int | float) and math.isfinite(value)


def check_plausibility(
    plan: AnalysisPlan,
    result: dict[str, object],
    profile: Sequence[ColumnView],
    row_count: int | None,
) -> list[str]:
    """Returns violation descriptions; empty means every applicable check
    passed. A check with no stat to compare against (e.g. row_count unknown
    on the eval-harness path) is skipped, not counted as a pass — silence
    here is "no evidence either way," not "verified plausible."""
    violations: list[str] = []
    value = result.get("value")

    def by_name(name: str | None) -> ColumnView | None:
        return next((c for c in profile if c.name == name), None) if name else None

    if plan.operation is Operation.COUNT and isinstance(value, int) and row_count is not None:
        if value > row_count:
            violations.append(f"count {value} exceeds the dataset's row_count {row_count}")

    if plan.operation is Operation.COUNT_DISTINCT and isinstance(value, int):
        col = by_name(plan.target_column)
        if col is not None and col.distinct_count is not None and value > col.distinct_count:
            violations.append(
                f"count_distinct {value} exceeds the profiled distinct_count "
                f"{col.distinct_count} for {plan.target_column!r}"
            )

    if plan.operation is Operation.MEAN and isinstance(value, int | float) and not isinstance(value, bool):
        col = by_name(plan.target_column)
        if col is not None and col.min_value is not None and col.max_value is not None:
            try:
                lo, hi = float(col.min_value), float(col.max_value)
            except ValueError:
                lo = hi = None
            if lo is not None and hi is not None:
                slack = max(abs(lo), abs(hi), 1.0) * 1e-9
                if not (lo - slack <= float(value) <= hi + slack):
                    violations.append(
                        f"mean {value} falls outside {plan.target_column!r}'s "
                        f"observed range [{lo}, {hi}]"
                    )

    if plan.answer_kind is AnswerKind.TABLE:
        table_row_count = result.get("row_count")
        group_col = by_name(plan.group_column)
        if (
            isinstance(table_row_count, int)
            and group_col is not None
            and group_col.distinct_count is not None
            and table_row_count > group_col.distinct_count
        ):
            violations.append(
                f"table has {table_row_count} rows, more than the profiled "
                f"distinct_count {group_col.distinct_count} of group column "
                f"{plan.group_column!r}"
            )
        rows = result.get("value")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    for cell_key, cell_value in row.items():
                        if isinstance(cell_value, int | float) and not _is_finite_number(cell_value):
                            violations.append(f"table cell {cell_key!r} is not finite ({cell_value!r})")

    if isinstance(value, int | float) and not _is_finite_number(value):
        violations.append(f"value is not finite ({value!r})")

    return violations
