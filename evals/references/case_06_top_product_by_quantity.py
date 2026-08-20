"""Reference for seed-06: product with the largest total units sold.

Grouping by product name; unknown-region rows included (ungrouped by region).
Answer canonicalization: trim + lowercase.
"""

from _common import dataset_path_from_argv, emit, load_rows

totals = {}
for r in load_rows(dataset_path_from_argv()):
    totals[r["product"]] = totals.get(r["product"], 0) + r["quantity"]

ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
top_product, top_qty = ranked[0]
margin = top_qty - ranked[1][1] if len(ranked) > 1 else top_qty
emit(
    "seed-06-top-product-by-quantity",
    "categorical_scalar",
    top_product.strip().lower(),
    f"top={top_product}:{top_qty}; runner-up={ranked[1][0]}:{ranked[1][1]}; margin={margin} (no tie)",
)
