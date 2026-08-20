"""Reference for seed-04: mean unit_price over Furniture order lines.

Unweighted mean of unit_price per row (not weighted by quantity).
"""

from _common import dataset_path_from_argv, emit, load_rows

prices = [
    r["unit_price"] for r in load_rows(dataset_path_from_argv()) if r["category"] == "Furniture"
]
emit(
    "seed-04-avg-unit-price-furniture",
    "numeric_scalar",
    round(sum(prices) / len(prices), 4),
    f"n={len(prices)} furniture rows; unweighted row mean",
)
