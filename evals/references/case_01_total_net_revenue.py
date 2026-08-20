"""Reference for seed-01: total net revenue across all orders.

Includes rows with unknown region (ungrouped total). Missing discount = 0.
"""

from _common import dataset_path_from_argv, emit, load_rows, net

rows = load_rows(dataset_path_from_argv())
total = sum(net(r) for r in rows)
emit(
    "seed-01-total-net-revenue",
    "numeric_scalar",
    round(total, 2),
    f"sum over {len(rows)} rows; missing discount treated as 0",
)
