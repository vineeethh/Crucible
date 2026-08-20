"""arq queue adapter implementing the JobQueue port."""

from __future__ import annotations

from typing import Any

from arq.connections import ArqRedis

from crucible.domain import DependencyUnavailable


class ArqJobQueue:
    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def enqueue(self, job: str, *args: Any) -> str:
        try:
            handle = await self._pool.enqueue_job(job, *args)
        except Exception as exc:
            raise DependencyUnavailable(
                "The job queue is unavailable; the request was not accepted."
            ) from exc
        if handle is None:
            raise DependencyUnavailable("The job queue rejected the request.")
        return str(handle.job_id)
