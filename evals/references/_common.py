"""Shared loading/canonicalization rules for the retail_sales_v1 seed suite.

These rules are part of the ground-truth contract. Any change here is a new
suite version, never an in-place edit after release.

Canonicalization contract (documented per case in evals/cases/*.yaml):
  - discount: empty cell means "no discount" -> 0.0
  - region:   empty cell means unknown; rows with unknown region are EXCLUDED
              from any region-grouped calculation, but INCLUDED in ungrouped
              totals (revenue, counts, distinct customers, product totals)
  - net line revenue = quantity * unit_price * (1 - discount)
  - money values are computed in float and compared with abs_tol declared per
    case; no hidden rounding is applied inside references
  - dates are ISO yyyy-mm-dd; Q2 2024 = 2024-04-01 .. 2024-06-30 inclusive
"""

import csv
import json
import sys
from datetime import date
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "retail_sales_v1.csv"


def load_rows(path=None):
    p = Path(path) if path else FIXTURE
    with open(p, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        out.append(
            {
                "order_id": r["order_id"],
                "order_date": date.fromisoformat(r["order_date"]),
                "region": r["region"].strip() or None,
                "category": r["category"].strip(),
                "product": r["product"].strip(),
                "quantity": int(r["quantity"]),
                "unit_price": float(r["unit_price"]),
                "discount_raw": r["discount"].strip(),
                "discount": float(r["discount"]) if r["discount"].strip() else 0.0,
                "customer_id": r["customer_id"].strip(),
            }
        )
    return out


def net(row):
    return row["quantity"] * row["unit_price"] * (1.0 - row["discount"])


def emit(case_id, answer_kind, value, notes=""):
    print(
        json.dumps(
            {
                "case_id": case_id,
                "answer_kind": answer_kind,
                "value": value,
                "notes": notes,
            },
            default=str,
        )
    )


def dataset_path_from_argv():
    return sys.argv[1] if len(sys.argv) > 1 else None
