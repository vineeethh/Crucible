"""Dataset profiling job.

Uploaded bytes are untrusted (threat model T2). This job:

  1. re-computes the SHA-256 and compares it with the client's declaration —
     a mismatch is a terminal `invalid`, never a silent acceptance;
  2. parses and profiles inside resource limits (row/column caps guard against
     decompression bombs);
  3. marks the version `ready` (immutable from then on) or `invalid` with a
     stable reason.

A parse failure is a normal outcome, not an exception: the version records why.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from crucible.db import SqlDatasetRepository
from crucible.domain import DatasetVersionStatus
from crucible.storage import ProfileFailure, profile_bytes

logger = logging.getLogger("crucible.worker.datasets")


async def profile_dataset_version(ctx: dict[str, Any], version_id: str) -> dict[str, str]:
    factory: async_sessionmaker[Any] = ctx["session_factory"]
    storage = ctx["storage"]
    vid = uuid.UUID(version_id)

    async with factory() as session:
        repo = SqlDatasetRepository(session)
        version = await repo.get_version_unscoped(vid)
        if version is None:
            logger.warning("profile: version %s not found", version_id)
            return {"result": "not_found"}
        if version.status is not DatasetVersionStatus.PENDING_PROFILE:
            # Re-delivery of a job we already handled: profiling is idempotent
            # because a version leaves PENDING_PROFILE exactly once.
            return {"result": "skipped", "status": version.status.value}

        try:
            data = await asyncio.to_thread(storage.get_bytes, version.object_key)
        except Exception as exc:
            await repo.mark_version_invalid(
                version_id=vid,
                reason="storage_unavailable",
                detail=f"Could not read uploaded object: {type(exc).__name__}",
            )
            await session.commit()
            return {"result": "invalid", "reason": "storage_unavailable"}

        actual_sha = hashlib.sha256(data).hexdigest()
        if actual_sha != version.content_sha256:
            # The client declared a digest that the stored bytes do not match.
            await repo.mark_version_invalid(
                version_id=vid,
                reason="content_hash_mismatch",
                detail=(
                    "The uploaded bytes do not match the declared SHA-256. "
                    f"declared={version.content_sha256} actual={actual_sha}"
                ),
            )
            await session.commit()
            logger.warning("profile: hash mismatch for version %s", version_id)
            return {"result": "invalid", "reason": "content_hash_mismatch"}

        outcome = await asyncio.to_thread(profile_bytes, data, content_type=version.content_type)
        if isinstance(outcome, ProfileFailure):
            await repo.mark_version_invalid(
                version_id=vid, reason=outcome.reason, detail=outcome.detail
            )
            await session.commit()
            return {"result": "invalid", "reason": outcome.reason}

        await repo.mark_version_ready(version_id=vid, profile=outcome)
        await session.commit()
        logger.info(
            "profile: version %s ready rows=%s cols=%s",
            version_id,
            outcome.row_count,
            outcome.column_count,
        )
        return {"result": "ready", "schema_hash": outcome.schema_hash}
