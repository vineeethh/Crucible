"""Trusted reference calculator for the retail_orders_2024_v1 suite.

Computes every gold answer with the SAME semantics the agent's code generator
emits (packages/agent/src/crucible/agent/models/codegen.py), so the suite is
grounded in an executable oracle rather than hand arithmetic:

  sum / mean       -> polars ignores nulls
  count            -> df.height
  count_distinct   -> Series.n_unique() (polars counts null as one distinct value)
  missing_count    -> is_null() OR cast-to-str == ''
  max/min_by_group -> group_by().agg(sum(target) or len()).sort(...).row(0)

`group_margins` reports the top-two gap for every grouped case: codegen sets
`ambiguous: True` on a tie, which routes the run to human review instead of an
answer. A grouped case is only a valid `exact_value` gold when its margin is
non-zero, so every grouped gold below is margin-checked before it is used.

Grouped answers are compared as TEXT. codegen emits the raw group key
(`'value': top[0]`), and every group column in this fixture is Int64, so the
agent returns e.g. `2`; the scorer's `_canonical` applies `str()` to both sides,
so the suite writes `expected: "2"`.

## Quantities this fixture makes available but the suite deliberately EXCLUDES

`sum_quantity` and `mean_quantity` are computed here for completeness but are
NOT used as golds. Four rows carry data-entry outliers (Quantity 100/150/250/500
against a legitimate 1-12 range), so both figures are dominated by values a
reader would reject on sight. They are honest under the agent's semantics and
indefensible as a reviewable gold — the same standard that excluded two
`retail_sales_v1` quantities in Stage B. See `_unusable`.

Run:  uv run python evals/references/retail_orders_2024_v1_reference.py
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "retail_orders_2024_v1.csv"

# Legitimate Quantity range observed in the fixture; anything above is a
# data-entry outlier, not a bulk order (see the manifest's anomaly block).
_QUANTITY_SANE_MAX = 12


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

    golds: dict[str, object] = {
        # -- scalars -------------------------------------------------------
        "row_count": int(df.height),
        "sum_unit_price": round(float(df["UnitPrice"].sum()), 4),
        "sum_shipping_days": int(df["ShippingDays"].sum()),
        "mean_unit_price": round(float(df["UnitPrice"].mean()), 4),
        "mean_rating": round(float(df["Rating"].mean()), 4),
        "mean_customer_age": round(float(df["CustomerAge"].mean()), 4),
        "mean_discount_pct": round(float(df["DiscountPct"].mean()), 4),
        # -- distinct ------------------------------------------------------
        "distinct_order_id": int(df["OrderID"].n_unique()),
        "distinct_product": int(df["ProductCode"].n_unique()),
        "distinct_sales_rep": int(df["SalesRepID"].n_unique()),
        "distinct_region": int(df["RegionCode"].n_unique()),
        "distinct_month": int(df["Month"].n_unique()),
        # -- missing -------------------------------------------------------
        "missing_quantity": missing("Quantity"),
        "missing_unit_price": missing("UnitPrice"),
        "missing_rating": missing("Rating"),
        "missing_order_id": missing("OrderID"),  # expected 0: report 0, never invent
        # DEDUPE gold: exact-duplicate row count (df.height - df.unique().height),
        # same computation codegen.py's dedupe template runs in the sandbox.
        "duplicate_row_count": int(df.height - df.unique().height),
        # -- grouped -------------------------------------------------------
        "max_region_unit_price": group_top("RegionCode", "UnitPrice", descending=True),
        "min_region_unit_price": group_top("RegionCode", "UnitPrice", descending=False),
        "max_category_unit_price": group_top("CategoryCode", "UnitPrice", descending=True),
        "max_sales_rep_unit_price": group_top("SalesRepID", "UnitPrice", descending=True),
        "max_product_unit_price": group_top("ProductCode", "UnitPrice", descending=True),
        "max_month_unit_price": group_top("Month", "UnitPrice", descending=True),
        "max_region_row_count": group_top("RegionCode", None, descending=True),
        # Full per-group breakdown (GROUP_AGGREGATE -> TABLE), not one winner.
        # Same polars semantics (group_by/sum/sort) the coder's generated
        # program uses; key order (group column, then 'value') matches what
        # codegen.py's group_aggregate template emits.
        "revenue_by_region": (
            df.group_by("RegionCode")
            .agg(pl.col("UnitPrice").sum().round(2).alias("value"))
            .sort("RegionCode")
            .to_dicts()
        ),
        # RANK_TOP_N golds: same group_by/sum/round(2)/sort(desc)/head(n) as
        # codegen.py's rank_top_n template.
        "top5_products_by_unit_price": (
            df.group_by("ProductCode")
            .agg(pl.col("UnitPrice").sum().round(2).alias("value"))
            .sort("value", descending=True)
            .head(5)
            .to_dicts()
        ),
        "top3_reps_by_unit_price": (
            df.group_by("SalesRepID")
            .agg(pl.col("UnitPrice").sum().round(2).alias("value"))
            .sort("value", descending=True)
            .head(3)
            .to_dicts()
        ),
    }

    golds["group_margins"] = {
        "max_region_unit_price": group_margin("RegionCode", "UnitPrice", True),
        "min_region_unit_price": group_margin("RegionCode", "UnitPrice", False),
        "max_category_unit_price": group_margin("CategoryCode", "UnitPrice", True),
        "max_sales_rep_unit_price": group_margin("SalesRepID", "UnitPrice", True),
        "max_product_unit_price": group_margin("ProductCode", "UnitPrice", True),
        "max_month_unit_price": group_margin("Month", "UnitPrice", True),
        "max_region_row_count": group_margin("RegionCode", None, True),
    }

    # Computed, recorded, and deliberately NOT used as golds.
    outliers = df.filter(pl.col("Quantity") > _QUANTITY_SANE_MAX)
    golds["_unusable"] = {
        "sum_quantity": int(df["Quantity"].sum()),
        "mean_quantity": round(float(df["Quantity"].mean()), 4),
        "reason": (
            f"{outliers.height} rows carry Quantity outliers "
            f"({sorted(outliers['Quantity'].to_list())}) against a legitimate 1-"
            f"{_QUANTITY_SANE_MAX} range; both aggregates are dominated by them and "
            "are not defensible as a reviewable gold."
        ),
    }

    # Anomaly facts asserted by the manifest, verified here so the two cannot drift.
    golds["_anomalies"] = {
        "exact_duplicate_rows": int(df.height - df.unique().height),
        "quantity_outlier_rows": int(outliers.height),
        "negative_shipping_days_rows": int(df.filter(pl.col("ShippingDays") < 0).height),
    }
    return golds


def main() -> int:
    golds = compute()
    margins = golds["group_margins"]
    assert isinstance(margins, dict)
    failed = [k for k, v in margins.items() if float(v) == 0.0]
    for key, value in golds.items():
        print(json.dumps({key: value}))
    if failed:
        print(json.dumps({"ERROR": "tied groups cannot be exact_value golds", "cases": failed}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
