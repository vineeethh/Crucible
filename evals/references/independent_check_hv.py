"""Independent second calculation for high-value cases seed-01 and seed-02.

Deliberately implemented differently from the primary references (no shared
_common import, different parsing and accumulation strategy) per the Phase 0
ground-truth rule: high-value cases get a second independently written
calculation.
"""

import json
import sys
from pathlib import Path

path = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else Path(__file__).resolve().parent.parent / "fixtures" / "retail_sales_v1.csv"
)

lines = path.read_text(encoding="utf-8").strip().splitlines()
header = lines[0].split(",")
idx = {name: i for i, name in enumerate(header)}

total = 0.0
q2_by_region = {}
for line in lines[1:]:
    cells = line.split(",")  # fixture has no quoted/embedded commas by design
    qty = int(cells[idx["quantity"]])
    price = float(cells[idx["unit_price"]])
    disc_cell = cells[idx["discount"]].strip()
    disc = float(disc_cell) if disc_cell else 0.0
    line_net = qty * price * (1 - disc)
    total += line_net

    y, m, _d = cells[idx["order_date"]].split("-")
    region = cells[idx["region"]].strip()
    if region and y == "2024" and m in ("04", "05", "06"):
        q2_by_region[region] = q2_by_region.get(region, 0.0) + line_net

top_q2 = max(q2_by_region.items(), key=lambda kv: kv[1])
print(
    json.dumps(
        {
            "seed-01 independent total_net_revenue": round(total, 2),
            "seed-02 independent q2_by_region": {k: round(v, 2) for k, v in q2_by_region.items()},
            "seed-02 independent top_region": top_q2[0].lower(),
        }
    )
)
