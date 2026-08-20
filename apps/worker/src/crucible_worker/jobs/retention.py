"""Data-retention job (master plan Phase 10).

Runs daily. Deletes terminal runs and their evidence (and old cache entries)
older than the platform window, honouring per-tenant `retention_days` overrides.
System-level: no principal, no single tenant. Audit events and datasets are out
of scope by design (compliance evidence and user assets, respectively).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from crucible.application import ApplyRetention
from crucible.db import SqlIdentityRepository, SqlRetentionRepository

logger = logging.getLogger("crucible.worker.retention")


async def apply_retention(ctx: dict[str, Any]) -> dict[str, int]:
    factory: async_sessionmaker[Any] = ctx["session_factory"]
    default_days: int = ctx["retention_days"]
    async with factory() as session:
        command = ApplyRetention(
            retention=SqlRetentionRepository(session),
            identity=SqlIdentityRepository(session),
            default_days=default_days,
        )
        outcome = await command()
        await session.commit()
    logger.info(
        "apply_retention: deleted runs=%s cache_entries=%s (default window %sd)",
        outcome.runs,
        outcome.cache_entries,
        default_days,
    )
    return {"runs": outcome.runs, "cache_entries": outcome.cache_entries}
