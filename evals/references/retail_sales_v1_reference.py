"""Trusted reference calculator for the retail_sales_v1 suite.

Computes every gold answer with the SAME semantics the agent's code generator
emits (packages/agent/src/crucible/agent/models/codegen.py), so the suite is
grounded in an independent, executable oracle rather than hand arithmetic:

  sum / mean     -> polars ignores nulls
  count          -> df.height
  count_distinct -> Series.n_unique() (polars counts null as one distinct value)
  missing_count  -> is_null() OR cast-to-str == ''
  max/min_by_group -> group_by().agg(sum(target) or len()).sort(...).row(0)

`group_margins` reports the top-two gap for every grouped case: codegen sets
`ambiguous: True` on a tie, which routes the run to human review instead of an
answer. A grouped case is only a valid `exact_value` gold when its margin is
non-zero.

Two quantities are computed under `_unusable` but deliberately excluded from the
suite, because this fixture's one empty `region` cell makes them indefensible as
golds rather than merely hard:

  distinct_region      n_unique() counts null as a distinct value -> 5, where a
                       reader would reasonably defend 4.
  min_region_unit_price  the smallest region group IS the null group, so the
                       answer is the degenerate string "None".

Both are honest properties of the agent's own semantics, not bugs — they are
excluded because a gold has to be defensible on inspection, not because the
computation is wrong.

Run:  uv run python evals/references/retail_sales_v1_reference.py
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "retail_sales_v1.csv"


def compute() -> dict[str, object]:
    df = pl.read_csv(FIXTURE, infer_schema_length=10000)

    def group_top(group: str, target: str | None, descending: bool) -> str:
        agg = pl.col(target).sum() if target else pl.len()
        g = df.group_by(group).agg(agg.alias("m")).sort("m", descending=descending)
        return str(g.row(0)[0])

    def group_margin(group: str, target: str | None, descending: bool) -> float:
        """Gap between the top two groups; 0.0 means a tie (-> ambiguous)."""
        agg = pl.col(target).sum() if target else pl.len()
        g = df.group_by(group).agg(agg.alias("m")).sort("m", descending=descending)
        if g.height < 2:
            return float("inf")
        return abs(float(g.row(0)[1]) - float(g.row(1)[1]))

    def missing(col: str) -> int:
        s = df[col]
        return int((s.is_null() | (s.cast(pl.Utf8, strict=False) == "")).sum())

    return {
        "sum_quantity": int(df["quantity"].sum()),
        "sum_unit_price": round(float(df["unit_price"].sum()), 4),
        "mean_quantity": round(float(df["quantity"].mean()), 4),
        "mean_unit_price": round(float(df["unit_price"].mean()), 4),
        "mean_discount": round(float(df["discount"].mean()), 4),
        "row_count": int(df.height),
        "distinct_category": int(df["category"].n_unique()),
        "distinct_product": int(df["product"].n_unique()),
        "distinct_customer": int(df["customer_id"].n_unique()),
        "missing_discount": missing("discount"),
        "missing_region": missing("region"),
        "max_region_unit_price": group_top("region", "unit_price", descending=True),
        "max_category_quantity": group_top("category", "quantity", descending=True),
        "max_product_quantity": group_top("product", "quantity", descending=True),
        "min_category_quantity": group_top("category", "quantity", descending=False),
        "min_category_unit_price": group_top("category", "unit_price", descending=False),
        "top_customer_count": group_top("customer_id", None, descending=True),
        "group_margins": {
            "max_region_unit_price": group_margin("region", "unit_price", descending=True),
            "max_category_quantity": group_margin("category", "quantity", descending=True),
            "max_product_quantity": group_margin("product", "quantity", descending=True),
            "min_category_quantity": group_margin("category", "quantity", descending=False),
            "min_category_unit_price": group_margin("category", "unit_price", descending=False),
            "top_customer_count": group_margin("customer_id", None, descending=True),
        },
        # Computed but deliberately NOT used as suite golds — see module docstring.
        "_unusable": {
            # n_unique() counts the one empty region cell as a distinct value, so
            # this returns 5 where a reader would defend 4. Contestable gold.
            "distinct_region": int(df["region"].n_unique()),
            # The minimum-by-region group IS the null region, so the answer is the
            # degenerate string "None". Not a defensible gold.
            "min_region_unit_price": group_top("region", "unit_price", descending=False),
        },
    }


if __name__ == "__main__":
    print(json.dumps(compute(), indent=2))
