"""Reference for seed-02: region with highest net sales in Q2 2024.

Q2 2024 = 2024-04-01..2024-06-30 inclusive. Rows with unknown region are
excluded from region grouping. Answer canonicalization: trim + lowercase.
"""

from datetime import date

from _common import dataset_path_from_argv, emit, load_rows, net

Q2_START, Q2_END = date(2024, 4, 1), date(2024, 6, 30)

totals = {}
for r in load_rows(dataset_path_from_argv()):
    if r["region"] is None:
        continue
    if Q2_START <= r["order_date"] <= Q2_END:
        totals[r["region"]] = totals.get(r["region"], 0.0) + net(r)

ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
top_region, top_value = ranked[0]
margin = top_value - ranked[1][1] if len(ranked) > 1 else top_value
emit(
    "seed-02-top-region-q2",
    "categorical_scalar",
    top_region.strip().lower(),
    f"totals={ {k: round(v, 2) for k, v in ranked} }; winning margin={round(margin, 2)} (no tie)",
)
