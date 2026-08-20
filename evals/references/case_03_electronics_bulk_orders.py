"""Reference for seed-03: count of Electronics orders with quantity >= 3."""

from _common import dataset_path_from_argv, emit, load_rows

rows = load_rows(dataset_path_from_argv())
count = sum(1 for r in rows if r["category"] == "Electronics" and r["quantity"] >= 3)
emit(
    "seed-03-electronics-bulk-orders",
    "integer_scalar",
    count,
    "category exact-match 'Electronics'; quantity >= 3; unknown-region rows included",
)
