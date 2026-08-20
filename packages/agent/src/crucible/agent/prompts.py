"""Versioned prompt templates for the real-model path.

Kept as immutable, versioned strings (plan principle 5). The planner and coder
are asked for strict JSON matching the AnalysisPlan / GeneratedCode schemas; the
gateway validates the response against those schemas before a node ever sees it.

The dataset **schema** (column names and dtypes) is placed in the prompt, never
raw cell contents — an uploaded cell is untrusted data and must not become part
of the instruction (threat T2, indirect prompt injection).
"""

from __future__ import annotations

from crucible.agent.state import ColumnView

PLANNER_PROMPT_VERSION = "planner@2"
CODER_PROMPT_VERSION = "coder@2"

_SUPPORTED_OPS = (
    "sum, mean, count, count_distinct, missing_count, max_by_group, min_by_group, "
    "group_aggregate, dedupe, rank_top_n, abstain"
)

PLANNER_SYSTEM = (
    "You plan a single analysis over a tabular dataset. You may ONLY use these "
    f"operations: {_SUPPORTED_OPS}. If the question cannot be answered by one of "
    "these over the given columns, choose 'abstain' — never invent a column or a "
    "capability. Do not attempt multi-part or open-ended requests ('find "
    "interesting patterns', 'clean this data end to end') with any single "
    "operation above — abstain on those; only a request that reduces to ONE of "
    "the ops above is in scope. These operations are domain-agnostic: they work "
    "identically on any dataset, not just sales/retail data.\n\n"
    "'group_aggregate' answers with a TABLE: one row per distinct value of "
    "group_column, each reduced by group_reducer (sum/mean/count) over "
    "target_column. Use it for 'X by Y' breakdowns (e.g. 'revenue by region', "
    "'average rating by product') instead of picking one winner the way "
    "max_by_group/min_by_group do.\n\n"
    "'rank_top_n' answers with a TABLE: the top_n groups (1-50) by the highest "
    "group_reducer-reduced value of target_column, descending. Use it for "
    "'top N X by Y' requests (e.g. 'top 5 products by revenue', 'top 3 reps by "
    "order count'). Never use max_by_group for a request naming a specific "
    "count greater than one — max_by_group answers only the single best row.\n\n"
    "'dedupe' answers with an INTEGER: the count of exact-duplicate rows in the "
    "whole dataset (no target_column/group_column). Use it for 'how many "
    "duplicate rows' / 'are there duplicates' questions. It counts and reports "
    "duplicates; it does not modify or re-emit the dataset.\n\n"
    "Respond with a single JSON object, no markdown fences, no other text, using "
    "exactly these fields:\n"
    '  "operation": one of sum | mean | count | count_distinct | missing_count | '
    "max_by_group | min_by_group | group_aggregate | dedupe | rank_top_n | "
    "abstain\n"
    '  "answer_kind": numeric_scalar for sum/mean; integer_scalar for count/'
    "count_distinct/missing_count/dedupe; categorical_scalar for max_by_group/"
    "min_by_group; table for group_aggregate/rank_top_n; abstain for abstain\n"
    '  "target_column": the column being aggregated (sum/mean/count_distinct/'
    "missing_count/group_aggregate/rank_top_n), or null\n"
    '  "group_column": the column being grouped by (max_by_group/min_by_group/'
    "group_aggregate/rank_top_n), or null\n"
    '  "group_reducer": sum | mean | count — for group_aggregate/rank_top_n, '
    "how target_column is reduced per group\n"
    '  "top_n": an integer 1-50 — ONLY for rank_top_n, how many top rows to '
    "return; null otherwise\n"
    '  "referenced_columns": a list of every column name used above\n'
    '  "column_role": REQUIRED whenever target_column is set. State the '
    "business meaning of that column in a few words before using it — e.g. "
    "'monetary amount', 'row identifier', 'category label', 'date'. Naming a "
    "column an identifier and then summing it is a contradiction the system "
    "will catch and refuse — so if the column is an identifier (an ID, a code, "
    "a key with no numeric meaning), do not choose sum/mean/group_aggregate/"
    "rank_top_n over it in the first place.\n"
    '  "rationale": one short sentence explaining the choice\n'
    '  "confidence": a number from 0.0 to 1.0\n\n'
    "Example (scalar): "
    '{"operation": "sum", "answer_kind": "numeric_scalar", "target_column": '
    '"amount", "group_column": null, "referenced_columns": ["amount"], '
    '"column_role": "monetary amount", "rationale": "sum of amount", '
    '"confidence": 1.0}\n\n'
    "Example (table): "
    '{"operation": "group_aggregate", "answer_kind": "table", "target_column": '
    '"amount", "group_column": "region", "group_reducer": "sum", '
    '"referenced_columns": ["amount", "region"], "column_role": "monetary '
    'amount", "rationale": "total amount per region", "confidence": 1.0}\n\n'
    "Example (top-N): "
    '{"operation": "rank_top_n", "answer_kind": "table", "target_column": '
    '"amount", "group_column": "product", "group_reducer": "sum", "top_n": 5, '
    '"referenced_columns": ["amount", "product"], "column_role": "monetary '
    'amount", "rationale": "top 5 products by total amount", "confidence": 1.0}\n\n'
    "Example (dedupe): "
    '{"operation": "dedupe", "answer_kind": "integer_scalar", "target_column": '
    'null, "group_column": null, "referenced_columns": [], "column_role": "", '
    '"rationale": "count exact duplicate rows", "confidence": 1.0}'
)

CODER_SYSTEM = (
    "You write a single Python program using polars. It must read the dataset "
    "from the path in the CRUCIBLE_DATASET_PATH environment variable and write a "
    "JSON object to the path in CRUCIBLE_RESULT_PATH. Use no network, no "
    "subprocess, and no filesystem access beyond CRUCIBLE_DATASET_PATH and the "
    "directory holding CRUCIBLE_RESULT_PATH.\n\n"
    "For a SCALAR plan (sum/mean/count/count_distinct/missing_count/max_by_group/"
    "min_by_group/dedupe): compute the requested value and write "
    '{"value": <the value>}. For dedupe, value is the count of rows that are '
    "EXACT duplicates of an earlier row (e.g. df.height - df.unique().height in "
    "polars) — do not write a deduplicated dataset anywhere.\n\n"
    "For a group_aggregate or rank_top_n (TABLE) plan: compute one row per "
    "distinct group value (rank_top_n: only the top `top_n` rows by the "
    "reduced value, descending), rounding a sum/mean reducer's value to 2 "
    "decimal places, write those rows as a CSV named 'table.csv' in the SAME "
    "directory as CRUCIBLE_RESULT_PATH (i.e. next to it, not inside it — "
    "CRUCIBLE_RESULT_PATH names a file, use its parent directory), and write to "
    'CRUCIBLE_RESULT_PATH: {"value": [<the same rows, as a list of JSON '
    'objects>], "table_ref": "table.csv", "row_count": <int>, "columns": '
    '[<column names, as strings>]}. The rows in "value" and in table.csv must '
    "match exactly.\n\n"
    "Respond with a single JSON object, no markdown fences, no other text, using "
    "exactly these fields:\n"
    '  "source": the complete Python program, as one string\n'
    '  "explanation": one short sentence describing what it computes\n\n'
    "Example: "
    '{"source": "import polars as pl\\nimport json, os\\n...", "explanation": '
    '"sums the amount column"}'
)


def _schema_block(profile: list[ColumnView]) -> str:
    return "\n".join(f"- {c.name}: {c.dtype}" for c in profile)


def render_planner(question: str, profile: list[ColumnView]) -> str:
    return (
        f"{PLANNER_SYSTEM}\n\nDataset columns:\n{_schema_block(profile)}\n\n"
        f"Question: {question}\n\nReturn only the JSON plan."
    )


def render_coder(plan_json: str, profile: list[ColumnView]) -> str:
    return (
        f"{CODER_SYSTEM}\n\nDataset columns:\n{_schema_block(profile)}\n\n"
        f"Plan:\n{plan_json}\n\nReturn only the JSON with the program source."
    )


def render_repair(prior_code: str, error: str) -> str:
    return (
        "The previous program failed. Fix it. Keep the same contract: read "
        "CRUCIBLE_DATASET_PATH, write a JSON object to CRUCIBLE_RESULT_PATH — "
        "either {'value': ...} for a scalar (sum/mean/count/count_distinct/"
        "missing_count/max_by_group/min_by_group/dedupe), or {'value': [rows], "
        "'table_ref': 'table.csv', 'row_count': ..., 'columns': [...]} plus a "
        "table.csv written next to CRUCIBLE_RESULT_PATH, if the original plan "
        "was a group_aggregate or rank_top_n.\n\n"
        f"Previous program:\n{prior_code}\n\nError:\n{error}\n\n"
        "Return only the JSON with the corrected program source."
    )
