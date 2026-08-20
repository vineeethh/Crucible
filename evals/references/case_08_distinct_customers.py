"""Reference for seed-08: number of distinct customer_id values."""

from _common import dataset_path_from_argv, emit, load_rows

customers = {r["customer_id"] for r in load_rows(dataset_path_from_argv())}
emit(
    "seed-08-distinct-customers",
    "integer_scalar",
    len(customers),
    "set cardinality of trimmed customer_id; repeat buyers counted once",
)
