"""Data retention and erasure (master plan Phase 10).

These are *system* operations — they have no tenant principal (the retention job
runs platform-wide; erasure is a support/admin action against one tenant), so
they are invoked by the worker cron and the admin CLI, never from a request
path. Every operation supports a dry run so an operator sees exactly what would
be deleted before anything is.

Retention deletes terminal runs and their evidence (and, optionally, old cache
entries) older than a window. Audit events and datasets are deliberately out of
scope: the audit trail is compliance evidence, and datasets are user assets
governed by explicit deletion / full erasure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from crucible.application.ports import IdentityRepository, RetentionRepository

DEFAULT_RETENTION_DAYS = 90


@dataclass(frozen=True, slots=True)
class RetentionOutcome:
    cutoff: datetime
    dry_run: bool
    runs: int = 0
    cache_entries: int = 0
    per_org: dict[str, int] = field(default_factory=dict)


class ApplyRetention:
    """Delete data older than the retention window, platform-wide.

    The window is the platform default unless a tenant sets its own
    `retention_days`; a per-tenant override is applied only to that tenant.
    """

    def __init__(
        self,
        *,
        retention: RetentionRepository,
        identity: IdentityRepository,
        default_days: int = DEFAULT_RETENTION_DAYS,
    ) -> None:
        self._retention = retention
        self._identity = identity
        self._default_days = default_days

    async def __call__(
        self, *, dry_run: bool = False, now: datetime | None = None
    ) -> RetentionOutcome:
        now = now or datetime.now(UTC)
        default_cutoff = now - timedelta(days=self._default_days)
        total_runs = 0
        total_cache = 0
        per_org: dict[str, int] = {}

        # One pass per tenant, each with its own cutoff (override or default).
        # At beta scale the org count is tiny; this stays simple and correct.
        for org in await self._identity.list_organizations():
            days = org.retention_days if org.retention_days is not None else self._default_days
            cutoff = now - timedelta(days=days)
            if dry_run:
                n = await self._retention.count_expired_runs(cutoff=cutoff, organization_id=org.id)
                if n:
                    per_org[org.slug] = n
                total_runs += n
            else:
                total_runs += await self._retention.delete_expired_runs(
                    cutoff=cutoff, organization_id=org.id
                )
                total_cache += await self._retention.delete_expired_cache(
                    cutoff=cutoff, organization_id=org.id
                )

        return RetentionOutcome(
            cutoff=default_cutoff,
            dry_run=dry_run,
            runs=total_runs,
            cache_entries=total_cache,
            per_org=per_org,
        )
