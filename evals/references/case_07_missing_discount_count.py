"""Reference for seed-07: how many order rows have a missing discount value.

Missing = empty cell in the raw CSV, before the discount->0 canonicalization.
"""

from _common import dataset_path_from_argv, emit, load_rows

count = sum(1 for r in load_rows(dataset_path_from_argv()) if r["discount_raw"] == "")
emit(
    "seed-07-missing-discount-count",
    "integer_scalar",
    count,
    "counts raw empty discount cells; tests missing-value handling, not the 0-default",
)
