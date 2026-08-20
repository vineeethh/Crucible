"""Reference for seed-05: number of orders placed in March 2024."""

from _common import dataset_path_from_argv, emit, load_rows

count = sum(
    1
    for r in load_rows(dataset_path_from_argv())
    if r["order_date"].year == 2024 and r["order_date"].month == 3
)
emit("seed-05-march-order-count", "integer_scalar", count, "calendar month match on ISO order_date")
