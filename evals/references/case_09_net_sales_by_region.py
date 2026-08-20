"""Reference for seed-09: net sales per region (full period), table answer.

Rows with unknown region are excluded. Comparison is order-insensitive on
region key; money compared with per-case abs_tol.
"""

from _common import dataset_path_from_argv, emit, load_rows, net

totals = {}
for r in load_rows(dataset_path_from_argv()):
    if r["region"] is None:
        continue
    totals[r["region"]] = totals.get(r["region"], 0.0) + net(r)

table = sorted(
    ({"region": k.strip().lower(), "net_sales": round(v, 2)} for k, v in totals.items()),
    key=lambda row: row["region"],
)
emit(
    "seed-09-net-sales-by-region",
    "table",
    table,
    "order-insensitive result set keyed by region; unknown-region rows excluded",
)
