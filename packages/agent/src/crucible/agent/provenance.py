"""Synthesis: turn a verified structured result into an answer with provenance.

Template-based, not model-generated: the answer text is derived mechanically
from the verified result, so it *cannot* add facts beyond what was computed
(master plan §8.2 Synthesize + OutputGuard). This is the honesty guarantee — the
prose never says more than the number.
"""

from __future__ import annotations

from crucible.agent.schemas import AnalysisPlan, Answer, AnswerKind, Operation, Provenance

MAX_TEXT = 2000


def build_answer(
    *,
    plan: AnalysisPlan,
    result: dict[str, object],
    provenance: Provenance,
) -> Answer:
    value = result.get("value")
    columns = ", ".join(provenance.columns_used) or "the dataset"
    op = plan.operation.value.replace("_", " ")
    table_ref: str | None = None
    row_count: int | None = None

    if plan.answer_kind is AnswerKind.TABLE:
        # Template-only, same as every other branch: composed from row/column
        # COUNTS the sandbox reported, never from the table's actual rows —
        # this node never reads the artifact's content.
        raw_ref = result.get("table_ref")
        table_ref = raw_ref if isinstance(raw_ref, str) else None
        raw_count = result.get("row_count")
        row_count = raw_count if isinstance(raw_count, int) else None
        table_columns = result.get("columns")
        col_list = ", ".join(str(c) for c in table_columns) if isinstance(table_columns, list) else columns
        if plan.operation is Operation.RANK_TOP_N:
            text = f"Top {plan.top_n} by {columns}, {row_count} rows across columns: {col_list}."
        else:
            text = f"Grouped by {columns}, producing {row_count} rows across columns: {col_list}."
    elif plan.operation is Operation.DEDUPE:
        text = f"There are {value} exact-duplicate rows in the dataset."
    elif plan.answer_kind in (AnswerKind.NUMERIC_SCALAR, AnswerKind.INTEGER_SCALAR):
        text = f"The {op} over {columns} is {value}."
    elif plan.answer_kind is AnswerKind.CATEGORICAL_SCALAR:
        metric = result.get("metric")
        text = f"By {op}, the answer is {value} ({provenance.columns_used[0] if provenance.columns_used else 'group'}"
        text += f" with metric {metric})." if metric is not None else ")."
    else:
        text = f"Result: {value}."

    limitations = (
        "Computed by executing generated code against this dataset version; "
        "correctness is established for the computation performed, not verified "
        "against an independent gold answer."
    )
    if result.get("ambiguous"):
        limitations = "The top groups tie, so this answer is not unambiguous. " + limitations

    return Answer(
        answer_kind=plan.answer_kind,
        value=value,
        text=text[:MAX_TEXT],
        provenance=provenance,
        limitations=limitations,
        table_ref=table_ref,
        row_count=row_count,
    )


def output_guard(answer: Answer) -> tuple[bool, str | None]:
    """Final safety/schema check on the synthesized answer. Strip/reject unsafe
    output; never invent a replacement (master plan §8.2 OutputGuard)."""
    if not answer.text or len(answer.text) > MAX_TEXT:
        return False, "answer text missing or too long"
    if answer.answer_kind is AnswerKind.TABLE:
        if not answer.table_ref:
            return False, "table answer has no table_ref"
        if answer.row_count is None:
            return False, "table answer has no row_count"
        return True, None
    if answer.value is None and answer.answer_kind is not AnswerKind.ABSTAIN:
        return False, "answer has no value"
    if not answer.provenance.columns_used and answer.answer_kind in (
        AnswerKind.NUMERIC_SCALAR,
        AnswerKind.CATEGORICAL_SCALAR,
    ):
        # A scalar over columns must name the columns it used.
        return False, "answer lacks column provenance"
    return True, None
