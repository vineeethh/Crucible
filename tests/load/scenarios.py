"""Standard request mixes for the load harness.

`read_mix` is safe for a soak against any environment: it only reads. `run_mix`
adds run creation (a write + a queue enqueue) and is what the queue-saturation
game day uses to push the worker.
"""

from __future__ import annotations

import httpx

from tests.load.harness import Scenario


def read_mix(*, auth: dict[str, str]) -> list[Scenario]:
    async def healthz(c: httpx.AsyncClient) -> httpx.Response:
        return await c.get("/healthz")

    async def readyz(c: httpx.AsyncClient) -> httpx.Response:
        return await c.get("/readyz")

    async def list_runs(c: httpx.AsyncClient) -> httpx.Response:
        return await c.get("/v1/runs?limit=20", headers=auth)

    async def reliability(c: httpx.AsyncClient) -> httpx.Response:
        return await c.get("/v1/metrics/reliability", headers=auth)

    return [
        Scenario("healthz", 3, healthz),
        Scenario("readyz", 1, readyz),
        Scenario("list_runs", 4, list_runs),
        Scenario("reliability", 2, reliability),
    ]


def run_mix(*, auth: dict[str, str], dataset_version_id: str) -> list[Scenario]:
    """A write-heavy mix: create runs (enqueue jobs) alongside reads. Used to
    saturate the queue in the queue-loss game day."""

    async def create_run(c: httpx.AsyncClient) -> httpx.Response:
        return await c.post(
            "/v1/runs",
            headers=auth,
            json={
                "dataset_version_id": dataset_version_id,
                "question": "What is the total amount?",
            },
        )

    async def list_runs(c: httpx.AsyncClient) -> httpx.Response:
        return await c.get("/v1/runs?limit=20", headers=auth)

    return [
        Scenario("create_run", 5, create_run),
        Scenario("list_runs", 2, list_runs),
    ]
