"""In-process load smoke (master plan Phase 9).

Drives the real ASGI app under concurrency with the load harness and gates on
the error budget + latency. This is the short, deterministic version of the
soak that `python -m tests.load` runs against a real URL; it needs the live
compose stack (real DB/Redis/MinIO) because it exercises readyz and authed
reads. Marked `load` so the default lanes skip it.
"""

from __future__ import annotations

import httpx
import pytest

from crucible_api.main import create_app
from crucible_api.settings import ApiSettings
from tests.load.harness import LoadThresholds, run_load
from tests.load.scenarios import read_mix
from tests.support.stack import Tenant, requires_stack

pytestmark = [pytest.mark.integration, pytest.mark.load, requires_stack]


def test_read_mix_holds_under_concurrency(settings: ApiSettings, alice: Tenant) -> None:
    import asyncio

    app = create_app(settings=settings)
    auth = {"Authorization": f"Bearer {alice.token}"}
    # Generous in-process bounds: the point is to catch error-budget blowups and
    # gross latency regressions under concurrency, not to benchmark the host
    # (which may be running the whole test suite concurrently). The strict gate
    # is the zero error budget; the latency ceiling is a coarse guard.
    thresholds = LoadThresholds(max_error_rate=0.0, max_p95_ms=2500.0, max_p99_ms=4000.0)

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://loadtest") as client,
        ):
            result = await run_load(
                client,
                read_mix(auth=auth),
                concurrency=12,
                duration_s=2.5,
                warmup_rounds=3,  # pay cold-start (pools, query plans) before measuring
            )
        return result

    result = asyncio.run(scenario())

    assert result.total > 0, "no requests were issued"
    ok, reasons = result.gate(thresholds)
    assert ok, f"{result.summary()} :: {reasons}"
    # Every read must have been authorized and served (no 401/403/5xx).
    assert set(result.status_counts).issubset({200}), result.status_counts
