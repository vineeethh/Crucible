"""Crucible load & soak harness (master plan Phase 9).

A small asyncio + httpx load generator with explicit pass/fail thresholds, so
"does it hold up under load" is a measured, gated answer — not a vibe. Two uses:

- `python -m tests.load --url ... --token ...` against a running API (staging
  soak, or a local uvicorn) — see `__main__`;
- `tests/integration/test_load_smoke.py`, a short in-CI smoke that reuses the
  same `run_load` against the live compose stack.

The harness never fabricates a passing number: a request that errors or times
out counts against the error budget, and latency percentiles are computed from
the observed samples (nearest-rank), not smoothed.
"""

from tests.load.harness import LoadResult, LoadThresholds, Scenario, run_load

__all__ = ["LoadResult", "LoadThresholds", "Scenario", "run_load"]
