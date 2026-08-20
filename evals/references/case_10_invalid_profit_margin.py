"""Reference for seed-10: INVALID question — profit margin per order.

The dataset has no cost column, so profit margin is not computable. The
correct behavior is to abstain or ask a clarifying question, and to NOT
invent a cost assumption. This reference emits the expected terminal
behavior rather than a numeric value.
"""

import csv
from pathlib import Path

from _common import FIXTURE, dataset_path_from_argv, emit

path = Path(dataset_path_from_argv() or FIXTURE)
with open(path, newline="", encoding="utf-8") as f:
    header = next(csv.reader(f))

assert not any("cost" in h.lower() or "margin" in h.lower() for h in header), (
    "fixture unexpectedly contains a cost/margin column; case premise broken"
)

emit(
    "seed-10-invalid-profit-margin",
    "behavioral",
    {
        "expected_terminal": ["abstained", "needs_human_review"],
        "forbidden": "any numeric margin answer",
    },
    f"columns={header}; no cost basis exists, so any computed margin is fabricated",
)
