"""Load / soak CLI (master plan Phase 9).

    # 60s read soak against staging, gated on latency + error budget:
    python -m tests.load --url https://staging.example --token "$KEY" \
        --duration 60 --concurrency 25 --max-p95-ms 750

Exit code is non-zero when the run breaches a threshold, so CI/soak jobs gate on
it. A soak is just a long duration with a modest concurrency; the same harness
serves both.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx

from tests.load.harness import LoadThresholds, run_load
from tests.load.scenarios import read_mix


async def _main(args: argparse.Namespace) -> int:
    auth = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    thresholds = LoadThresholds(
        max_error_rate=args.max_error_rate,
        max_p95_ms=args.max_p95_ms,
        max_p99_ms=args.max_p99_ms,
        min_throughput_rps=args.min_rps,
    )
    limits = httpx.Limits(max_connections=args.concurrency * 2)
    timeout = httpx.Timeout(args.timeout)
    async with httpx.AsyncClient(base_url=args.url, limits=limits, timeout=timeout) as client:
        result = await run_load(
            client,
            read_mix(auth=auth),
            concurrency=args.concurrency,
            duration_s=args.duration,
            warmup_rounds=args.warmup_rounds,
        )
    print(result.summary())
    ok, reasons = result.gate(thresholds)
    for reason in reasons:
        print(f"  THRESHOLD BREACH: {reason}")
    print("LOAD PASSED" if ok else "LOAD FAILED")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tests.load")
    p.add_argument("--url", required=True, help="API base URL")
    p.add_argument("--token", default="", help="Bearer API key for authenticated routes")
    p.add_argument("--duration", type=float, default=30.0)
    p.add_argument("--concurrency", type=int, default=20)
    p.add_argument("--warmup-rounds", type=int, default=1)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--max-error-rate", type=float, default=0.01)
    p.add_argument("--max-p95-ms", type=float, default=750.0)
    p.add_argument("--max-p99-ms", type=float, default=1500.0)
    p.add_argument("--min-rps", type=float, default=0.0)
    return asyncio.run(_main(p.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
