"""SQLAlchemy implementations of the application repository ports.

Tenant scoping is structural: every read of a tenant-owned table filters on
`organization_id`, which callers must pass explicitly. The only unscoped read
is `get_run_unscoped`, used by the worker (which holds no principal) and never
reachable from a request path.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from crucible.application.ports import (
    AgentAttemptRecord,
    ApiKeyRecord,
    AuditEntry,
    CacheEntryRecord,
    CacheStats,
    DatasetRecord,
    DatasetVersionRecord,
    MembershipRecord,
    OrganizationRecord,
    ReviewQueueItem,
    ReviewRecord,
    RunEventRecord,
    RunRecord,
    RunTelemetryRow,
    ScoreInput,
    ScoreRecord,
    UserRecord,
)
from crucible.db import models as m
from crucible.domain import (
    TERMINAL_RUN_STATES,
    DatasetProfile,
    DatasetStatus,
    DatasetVersionStatus,
    Permission,
    Role,
    RunEventType,
    RunStatus,
    can_transition,
    new_id,
)


def _now() -> datetime:
    return datetime.now(UTC)


class SqlIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert_user(
        self, *, subject: str, email: str | None, display_name: str | None
    ) -> UserRecord:
        row = (
            await self._s.execute(select(m.User).where(m.User.subject == subject))
        ).scalar_one_or_none()
        if row is None:
            row = m.User(id=new_id(), subject=subject, email=email, display_name=display_name)
            self._s.add(row)
            await self._s.flush()
        else:
            # Profile fields follow the identity provider; the subject never changes.
            row.email = email or row.email
            row.display_name = display_name or row.display_name
        return UserRecord(
            id=row.id, subject=row.subject, email=row.email, display_name=row.display_name
        )

    async def organization_status(self, organization_id: uuid.UUID) -> str | None:
        row = await self._s.get(m.Organization, organization_id)
        return None if row is None else row.status

    async def organization_retention_days(self, organization_id: uuid.UUID) -> int | None:
        row = await self._s.get(m.Organization, organization_id)
        return None if row is None else row.retention_days

    async def set_organization_status(self, *, organization_id: uuid.UUID, status: str) -> bool:
        row = await self._s.get(m.Organization, organization_id)
        if row is None:
            return False
        row.status = status
        await self._s.flush()
        return True

    async def set_organization_retention(
        self, *, organization_id: uuid.UUID, retention_days: int | None
    ) -> bool:
        row = await self._s.get(m.Organization, organization_id)
        if row is None:
            return False
        row.retention_days = retention_days
        await self._s.flush()
        return True

    async def list_organizations(self) -> list[OrganizationRecord]:
        rows = (
            await self._s.execute(select(m.Organization).order_by(m.Organization.created_at))
        ).scalars()
        return [
            OrganizationRecord(
                id=o.id,
                slug=o.slug,
                name=o.name,
                status=o.status,
                retention_days=o.retention_days,
                created_at=o.created_at,
            )
            for o in rows
        ]

    async def memberships_for_user(self, user_id: uuid.UUID) -> list[MembershipRecord]:
        stmt = (
            select(m.Membership, m.Organization)
            .join(m.Organization, m.Organization.id == m.Membership.organization_id)
            .where(m.Membership.user_id == user_id)
            .order_by(m.Organization.slug)
        )
        rows = (await self._s.execute(stmt)).all()
        return [
            MembershipRecord(
                organization_id=mem.organization_id,
                organization_slug=org.slug,
                organization_name=org.name,
                user_id=mem.user_id,
                role=Role(mem.role),
            )
            for mem, org in rows
        ]

    async def membership(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> MembershipRecord | None:
        found = [
            mem
            for mem in await self.memberships_for_user(user_id)
            if mem.organization_id == organization_id
        ]
        return found[0] if found else None

    async def api_key_by_prefix(self, prefix: str) -> ApiKeyRecord | None:
        row = (
            await self._s.execute(select(m.ApiKey).where(m.ApiKey.prefix == prefix))
        ).scalar_one_or_none()
        return None if row is None else self._api_key(row)

    async def touch_api_key(self, key_id: uuid.UUID) -> None:
        await self._s.execute(
            update(m.ApiKey).where(m.ApiKey.id == key_id).values(last_used_at=_now())
        )

    async def create_api_key(
        self,
        *,
        organization_id: uuid.UUID,
        created_by: uuid.UUID | None,
        name: str,
        prefix: str,
        secret_hash: str,
        role: Role,
        scopes: tuple[Permission, ...] | None,
        expires_at: datetime | None,
    ) -> ApiKeyRecord:
        row = m.ApiKey(
            id=new_id(),
            organization_id=organization_id,
            created_by_user_id=created_by,
            name=name,
            prefix=prefix,
            secret_hash=secret_hash,
            role=role.value,
            scopes=None if scopes is None else [s.value for s in scopes],
            expires_at=expires_at,
        )
        self._s.add(row)
        await self._s.flush()
        return self._api_key(row)

    async def list_api_keys(self, organization_id: uuid.UUID) -> list[ApiKeyRecord]:
        rows = (
            await self._s.execute(
                select(m.ApiKey)
                .where(m.ApiKey.organization_id == organization_id)
                .order_by(m.ApiKey.created_at.desc())
            )
        ).scalars()
        return [self._api_key(r) for r in rows]

    async def revoke_api_key(self, *, organization_id: uuid.UUID, key_id: uuid.UUID) -> bool:
        # Scoped by organization: revoking another tenant's key matches no rows
        # and reports "not found" rather than succeeding.
        revoked = (
            await self._s.execute(
                update(m.ApiKey)
                .where(
                    m.ApiKey.id == key_id,
                    m.ApiKey.organization_id == organization_id,
                    m.ApiKey.revoked_at.is_(None),
                )
                .values(revoked_at=_now())
                .returning(m.ApiKey.id)
            )
        ).scalar_one_or_none()
        return revoked is not None

    @staticmethod
    def _api_key(row: m.ApiKey) -> ApiKeyRecord:
        return ApiKeyRecord(
            id=row.id,
            organization_id=row.organization_id,
            name=row.name,
            prefix=row.prefix,
            secret_hash=row.secret_hash,
            role=Role(row.role),
            scopes=None if row.scopes is None else tuple(Permission(s) for s in row.scopes),
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
        )


class SqlDatasetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create_dataset(self, *, organization_id: uuid.UUID, name: str) -> DatasetRecord:
        row = m.Dataset(
            id=new_id(),
            organization_id=organization_id,
            name=name,
            status=DatasetStatus.ACTIVE.value,
        )
        self._s.add(row)
        await self._s.flush()
        return self._dataset(row)

    async def dataset_by_name(
        self, *, organization_id: uuid.UUID, name: str
    ) -> DatasetRecord | None:
        row = (
            await self._s.execute(
                select(m.Dataset).where(
                    m.Dataset.organization_id == organization_id,
                    m.Dataset.name == name,
                    m.Dataset.status == DatasetStatus.ACTIVE.value,
                )
            )
        ).scalar_one_or_none()
        return None if row is None else self._dataset(row)

    async def get_dataset(
        self, *, organization_id: uuid.UUID, dataset_id: uuid.UUID
    ) -> DatasetRecord | None:
        row = (
            await self._s.execute(
                select(m.Dataset).where(
                    m.Dataset.id == dataset_id,
                    m.Dataset.organization_id == organization_id,
                )
            )
        ).scalar_one_or_none()
        return None if row is None else self._dataset(row)

    async def list_datasets(self, organization_id: uuid.UUID) -> list[DatasetRecord]:
        rows = (
            await self._s.execute(
                select(m.Dataset)
                .where(
                    m.Dataset.organization_id == organization_id,
                    m.Dataset.status == DatasetStatus.ACTIVE.value,
                )
                .order_by(m.Dataset.created_at.desc())
            )
        ).scalars()
        return [self._dataset(r) for r in rows]

    async def create_version(
        self,
        *,
        organization_id: uuid.UUID,
        dataset_id: uuid.UUID,
        version_id: uuid.UUID,
        object_key: str,
        content_type: str,
        declared_size_bytes: int,
        filename: str,
    ) -> DatasetVersionRecord:
        next_no = (
            await self._s.execute(
                select(func.coalesce(func.max(m.DatasetVersion.version_no), 0) + 1).where(
                    m.DatasetVersion.dataset_id == dataset_id
                )
            )
        ).scalar_one()
        row = m.DatasetVersion(
            id=version_id,
            dataset_id=dataset_id,
            organization_id=organization_id,
            version_no=int(next_no),
            status=DatasetVersionStatus.AWAITING_UPLOAD.value,
            object_key=object_key,
            original_filename=filename[:255],
            content_type=content_type,
            declared_size_bytes=declared_size_bytes,
        )
        self._s.add(row)
        await self._s.flush()
        return self._version(row)

    async def get_version(
        self, *, organization_id: uuid.UUID, version_id: uuid.UUID
    ) -> DatasetVersionRecord | None:
        row = (
            await self._s.execute(
                select(m.DatasetVersion).where(
                    m.DatasetVersion.id == version_id,
                    m.DatasetVersion.organization_id == organization_id,
                )
            )
        ).scalar_one_or_none()
        return None if row is None else self._version(row)

    async def get_version_unscoped(self, version_id: uuid.UUID) -> DatasetVersionRecord | None:
        """Worker-only: the profiling job has a version ID and no principal."""
        row = (
            await self._s.execute(select(m.DatasetVersion).where(m.DatasetVersion.id == version_id))
        ).scalar_one_or_none()
        return None if row is None else self._version(row)

    async def list_versions(
        self, *, organization_id: uuid.UUID, dataset_id: uuid.UUID
    ) -> list[DatasetVersionRecord]:
        rows = (
            await self._s.execute(
                select(m.DatasetVersion)
                .where(
                    m.DatasetVersion.dataset_id == dataset_id,
                    m.DatasetVersion.organization_id == organization_id,
                )
                .order_by(m.DatasetVersion.version_no.desc())
            )
        ).scalars()
        return [self._version(r) for r in rows]

    async def version_by_content_hash(
        self, *, dataset_id: uuid.UUID, content_sha256: str
    ) -> DatasetVersionRecord | None:
        row = (
            await self._s.execute(
                select(m.DatasetVersion).where(
                    m.DatasetVersion.dataset_id == dataset_id,
                    m.DatasetVersion.content_sha256 == content_sha256,
                )
            )
        ).scalar_one_or_none()
        return None if row is None else self._version(row)

    async def mark_version_uploaded(
        self, *, version_id: uuid.UUID, size_bytes: int, content_sha256: str
    ) -> DatasetVersionRecord:
        row = await self._require(version_id)
        row.size_bytes = size_bytes
        row.content_sha256 = content_sha256
        row.status = DatasetVersionStatus.PENDING_PROFILE.value
        await self._s.flush()
        return self._version(row)

    async def mark_version_ready(
        self, *, version_id: uuid.UUID, profile: DatasetProfile
    ) -> DatasetVersionRecord:
        row = await self._require(version_id)
        row.profile = profile.to_dict()
        row.schema_hash = profile.schema_hash
        row.row_count = profile.row_count
        row.column_count = profile.column_count
        row.status = DatasetVersionStatus.READY.value
        await self._s.flush()
        return self._version(row)

    async def mark_version_invalid(
        self, *, version_id: uuid.UUID, reason: str, detail: str
    ) -> DatasetVersionRecord:
        row = await self._require(version_id)
        row.status = DatasetVersionStatus.INVALID.value
        row.invalid_reason = reason[:64]
        row.invalid_detail = detail[:2000]
        await self._s.flush()
        return self._version(row)

    async def delete_version(self, version_id: uuid.UUID) -> None:
        """Only ever used for a not-yet-ready duplicate upload; a READY version
        is immutable evidence and is never deleted here."""
        await self._s.execute(
            delete(m.DatasetVersion).where(
                m.DatasetVersion.id == version_id,
                m.DatasetVersion.status != DatasetVersionStatus.READY.value,
            )
        )

    async def _require(self, version_id: uuid.UUID) -> m.DatasetVersion:
        row = (
            await self._s.execute(select(m.DatasetVersion).where(m.DatasetVersion.id == version_id))
        ).scalar_one()
        return row

    @staticmethod
    def _dataset(row: m.Dataset) -> DatasetRecord:
        return DatasetRecord(
            id=row.id,
            organization_id=row.organization_id,
            name=row.name,
            created_at=row.created_at,
        )

    @staticmethod
    def _version(row: m.DatasetVersion) -> DatasetVersionRecord:
        return DatasetVersionRecord(
            id=row.id,
            dataset_id=row.dataset_id,
            organization_id=row.organization_id,
            version_no=row.version_no,
            status=DatasetVersionStatus(row.status),
            object_key=row.object_key,
            content_type=row.content_type,
            declared_size_bytes=row.declared_size_bytes,
            size_bytes=row.size_bytes,
            content_sha256=row.content_sha256,
            schema_hash=row.schema_hash,
            row_count=row.row_count,
            column_count=row.column_count,
            profile=row.profile,
            invalid_reason=row.invalid_reason,
            created_at=row.created_at,
        )


class SqlRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create_run(
        self,
        *,
        organization_id: uuid.UUID,
        dataset_version_id: uuid.UUID,
        question: str,
        config_manifest: dict[str, Any],
        idempotency_key: str | None,
        request_hash: str | None,
        created_by: uuid.UUID | None,
    ) -> RunRecord:
        row = m.AgentRun(
            id=new_id(),
            organization_id=organization_id,
            dataset_version_id=dataset_version_id,
            created_by_user_id=created_by,
            question=question,
            status=RunStatus.QUEUED.value,
            config_manifest=config_manifest,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        self._s.add(row)
        await self._s.flush()
        return self._run(row)

    async def get_run(self, *, organization_id: uuid.UUID, run_id: uuid.UUID) -> RunRecord | None:
        row = (
            await self._s.execute(
                select(m.AgentRun).where(
                    m.AgentRun.id == run_id,
                    m.AgentRun.organization_id == organization_id,
                )
            )
        ).scalar_one_or_none()
        return None if row is None else self._run(row)

    async def get_run_unscoped(self, run_id: uuid.UUID) -> RunRecord | None:
        row = (
            await self._s.execute(select(m.AgentRun).where(m.AgentRun.id == run_id))
        ).scalar_one_or_none()
        return None if row is None else self._run(row)

    async def list_runs(
        self, *, organization_id: uuid.UUID, limit: int, offset: int
    ) -> list[RunRecord]:
        rows = (
            await self._s.execute(
                select(m.AgentRun)
                .where(m.AgentRun.organization_id == organization_id)
                .order_by(m.AgentRun.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return [self._run(r) for r in rows]

    async def run_by_idempotency_key(
        self, *, organization_id: uuid.UUID, idempotency_key: str
    ) -> RunRecord | None:
        row = (
            await self._s.execute(
                select(m.AgentRun).where(
                    m.AgentRun.organization_id == organization_id,
                    m.AgentRun.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        return None if row is None else self._run(row)

    async def transition(
        self,
        *,
        run_id: uuid.UUID,
        expected: RunStatus,
        target: RunStatus,
        terminal_detail: str | None = None,
        failure_category: str | None = None,
    ) -> RunRecord | None:
        if not can_transition(expected, target):
            raise ValueError(f"illegal run transition {expected.value} -> {target.value}")

        values: dict[str, Any] = {"status": target.value, "updated_at": _now()}
        if terminal_detail is not None:
            values["terminal_detail"] = terminal_detail
        if failure_category is not None:
            values["failure_category"] = failure_category

        # Compare-and-set: the UPDATE only matches while the run is still in the
        # expected state, so two workers cannot both drive it forward.
        result = await self._s.execute(
            update(m.AgentRun)
            .where(m.AgentRun.id == run_id, m.AgentRun.status == expected.value)
            .values(**values)
            .returning(m.AgentRun)
        )
        row = result.scalar_one_or_none()
        return None if row is None else self._run(row)

    async def request_cancel(self, run_id: uuid.UUID) -> None:
        await self._s.execute(
            update(m.AgentRun)
            .where(m.AgentRun.id == run_id, m.AgentRun.cancel_requested_at.is_(None))
            .values(cancel_requested_at=_now())
        )

    async def set_result(
        self,
        *,
        run_id: uuid.UUID,
        answer: dict[str, Any] | None,
        verification: dict[str, Any] | None,
    ) -> None:
        await self._s.execute(
            update(m.AgentRun)
            .where(m.AgentRun.id == run_id)
            .values(answer=answer, verification=verification, updated_at=_now())
        )

    async def is_cancel_requested(self, run_id: uuid.UUID) -> bool:
        value = (
            await self._s.execute(
                select(m.AgentRun.cancel_requested_at).where(m.AgentRun.id == run_id)
            )
        ).scalar_one_or_none()
        return value is not None

    async def append_event(
        self, *, run_id: uuid.UUID, event_type: RunEventType, payload: dict[str, Any]
    ) -> RunEventRecord:
        next_no = (
            await self._s.execute(
                select(func.coalesce(func.max(m.RunEvent.sequence_no), 0) + 1).where(
                    m.RunEvent.run_id == run_id
                )
            )
        ).scalar_one()
        row = m.RunEvent(
            id=new_id(),
            run_id=run_id,
            sequence_no=int(next_no),
            event_type=event_type.value,
            payload=payload,
        )
        self._s.add(row)
        await self._s.flush()
        return RunEventRecord(
            run_id=row.run_id,
            sequence_no=row.sequence_no,
            event_type=RunEventType(row.event_type),
            payload=row.payload,
            created_at=row.created_at,
        )

    async def list_events(
        self, *, run_id: uuid.UUID, after_sequence: int = 0
    ) -> list[RunEventRecord]:
        rows = (
            await self._s.execute(
                select(m.RunEvent)
                .where(m.RunEvent.run_id == run_id, m.RunEvent.sequence_no > after_sequence)
                .order_by(m.RunEvent.sequence_no)
            )
        ).scalars()
        return [
            RunEventRecord(
                run_id=r.run_id,
                sequence_no=r.sequence_no,
                event_type=RunEventType(r.event_type),
                payload=r.payload,
                created_at=r.created_at,
            )
            for r in rows
        ]

    @staticmethod
    def _run(row: m.AgentRun) -> RunRecord:
        return RunRecord(
            id=row.id,
            organization_id=row.organization_id,
            dataset_version_id=row.dataset_version_id,
            question=row.question,
            status=RunStatus(row.status),
            config_manifest=row.config_manifest,
            idempotency_key=row.idempotency_key,
            request_hash=row.request_hash,
            terminal_detail=row.terminal_detail,
            failure_category=row.failure_category,
            cancel_requested_at=row.cancel_requested_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
            answer=row.answer,
            verification=row.verification,
        )


class SqlAgentStore:
    """Agent attempts (append-only evidence) and resume checkpoints (upserted)."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def append_attempt(
        self,
        *,
        run_id: uuid.UUID,
        organization_id: uuid.UUID,
        kind: str,
        sequence_no: int,
        payload: dict[str, Any],
        model_provider: str | None = None,
        model_id: str | None = None,
        exit_class: str | None = None,
        failure_category: str | None = None,
        duration_ms: int | None = None,
        cost_usd: float | None = None,
        source_sha256: str | None = None,
    ) -> None:
        next_no = (
            await self._s.execute(
                select(func.coalesce(func.max(m.AgentAttempt.attempt_no), 0) + 1).where(
                    m.AgentAttempt.run_id == run_id
                )
            )
        ).scalar_one()
        self._s.add(
            m.AgentAttempt(
                id=new_id(),
                run_id=run_id,
                organization_id=organization_id,
                attempt_no=int(next_no),
                kind=kind,
                sequence_no=sequence_no,
                payload=payload,
                model_provider=model_provider,
                model_id=model_id,
                exit_class=exit_class,
                failure_category=failure_category,
                duration_ms=duration_ms,
                cost_usd=cost_usd,
                source_sha256=source_sha256,
            )
        )
        await self._s.flush()

    async def list_attempts(self, run_id: uuid.UUID) -> list[AgentAttemptRecord]:
        rows = (
            await self._s.execute(
                select(m.AgentAttempt)
                .where(m.AgentAttempt.run_id == run_id)
                .order_by(m.AgentAttempt.attempt_no)
            )
        ).scalars()
        return [
            AgentAttemptRecord(
                run_id=r.run_id,
                attempt_no=r.attempt_no,
                kind=r.kind,
                sequence_no=r.sequence_no,
                payload=r.payload,
                model_provider=r.model_provider,
                model_id=r.model_id,
                exit_class=r.exit_class,
                failure_category=r.failure_category,
                duration_ms=r.duration_ms,
                cost_usd=r.cost_usd,
                source_sha256=r.source_sha256,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def save_checkpoint(self, *, run_id: uuid.UUID, node: str, state: dict[str, Any]) -> None:
        row = (
            await self._s.execute(
                select(m.AgentCheckpoint).where(m.AgentCheckpoint.run_id == run_id)
            )
        ).scalar_one_or_none()
        if row is None:
            self._s.add(m.AgentCheckpoint(run_id=run_id, node=node, state=state))
        else:
            row.node = node
            row.state = state
        await self._s.flush()

    async def load_checkpoint(self, run_id: uuid.UUID) -> tuple[str, dict[str, Any]] | None:
        row = (
            await self._s.execute(
                select(m.AgentCheckpoint).where(m.AgentCheckpoint.run_id == run_id)
            )
        ).scalar_one_or_none()
        return None if row is None else (row.node, row.state)


class SqlScoreStore:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add_score(self, *, organization_id: uuid.UUID, score: ScoreInput) -> None:
        self._s.add(
            m.Score(
                id=new_id(),
                organization_id=organization_id,
                definition_key=score.definition_key,
                score_type=score.score_type,
                source=score.source,
                target_type=score.target_type,
                target_id=score.target_id,
                value_num=score.value_num,
                value_bool=score.value_bool,
                value_categorical=score.value_categorical,
                value_text=score.value_text,
                evaluator_version=score.evaluator_version,
                created_by_user_id=score.created_by,
            )
        )
        await self._s.flush()

    async def list_scores(
        self, *, organization_id: uuid.UUID, target_type: str, target_id: str
    ) -> list[ScoreRecord]:
        rows = (
            await self._s.execute(
                select(m.Score)
                .where(
                    m.Score.organization_id == organization_id,
                    m.Score.target_type == target_type,
                    m.Score.target_id == target_id,
                )
                .order_by(m.Score.created_at)
            )
        ).scalars()
        return [
            ScoreRecord(
                definition_key=r.definition_key,
                score_type=r.score_type,
                source=r.source,
                target_type=r.target_type,
                target_id=r.target_id,
                evaluator_version=r.evaluator_version,
                value_num=r.value_num,
                value_bool=r.value_bool,
                value_categorical=r.value_categorical,
                value_text=r.value_text,
                created_at=r.created_at,
            )
            for r in rows
        ]


class SqlReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def list_queue(
        self, *, organization_id: uuid.UUID, limit: int = 50
    ) -> list[ReviewQueueItem]:
        stmt = (
            select(m.AgentRun, m.HumanReview.status)
            .select_from(m.AgentRun)
            .outerjoin(m.HumanReview, m.HumanReview.run_id == m.AgentRun.id)
            .where(
                m.AgentRun.organization_id == organization_id,
                m.AgentRun.status == RunStatus.WAITING_REVIEW.value,
            )
            .order_by(m.AgentRun.created_at)
            .limit(limit)
        )
        rows = (await self._s.execute(stmt)).all()
        return [
            ReviewQueueItem(
                run_id=run.id,
                question=run.question,
                created_at=run.created_at,
                review_status=status,
                verification=run.verification,
            )
            for run, status in rows
        ]

    async def get_review(
        self, *, organization_id: uuid.UUID, run_id: uuid.UUID
    ) -> ReviewRecord | None:
        row = (
            await self._s.execute(
                select(m.HumanReview).where(
                    m.HumanReview.run_id == run_id,
                    m.HumanReview.organization_id == organization_id,
                )
            )
        ).scalar_one_or_none()
        return None if row is None else self._review(row)

    async def claim(
        self,
        *,
        organization_id: uuid.UUID,
        run_id: uuid.UUID,
        reviewer: uuid.UUID,
        rubric_version: str,
        ttl_seconds: int,
    ) -> ReviewRecord | None:
        """Claim a run for review. Returns the claimed review, or None if another
        reviewer holds an unexpired claim. One row per run (unique run_id)."""
        now = _now()
        expires = now + timedelta(seconds=ttl_seconds)
        existing = (
            await self._s.execute(
                select(m.HumanReview).where(m.HumanReview.run_id == run_id).with_for_update()
            )
        ).scalar_one_or_none()

        if existing is None:
            row = m.HumanReview(
                id=new_id(),
                organization_id=organization_id,
                run_id=run_id,
                status="claimed",
                rubric_version=rubric_version,
                claimed_by=reviewer,
                claimed_at=now,
                claim_expires_at=expires,
                lock_version=0,
            )
            self._s.add(row)
            await self._s.flush()
            return self._review(row)

        if existing.status == "submitted":
            return None
        held = (
            existing.status == "claimed"
            and existing.claim_expires_at is not None
            and existing.claim_expires_at > now
            and existing.claimed_by != reviewer
        )
        if held:
            return None
        existing.status = "claimed"
        existing.claimed_by = reviewer
        existing.claimed_at = now
        existing.claim_expires_at = expires
        existing.lock_version += 1
        await self._s.flush()
        return self._review(existing)

    async def submit(
        self,
        *,
        organization_id: uuid.UUID,
        run_id: uuid.UUID,
        reviewer: uuid.UUID,
        decision: str,
    ) -> ReviewRecord | None:
        row = (
            await self._s.execute(
                select(m.HumanReview)
                .where(
                    m.HumanReview.run_id == run_id,
                    m.HumanReview.organization_id == organization_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None or row.status != "claimed" or row.claimed_by != reviewer:
            return None
        row.status = "submitted"
        row.decision = decision
        row.submitted_by = reviewer
        row.submitted_at = _now()
        row.lock_version += 1
        await self._s.flush()
        return self._review(row)

    @staticmethod
    def _review(row: m.HumanReview) -> ReviewRecord:
        return ReviewRecord(
            id=row.id,
            organization_id=row.organization_id,
            run_id=row.run_id,
            status=row.status,
            rubric_version=row.rubric_version,
            claimed_by=row.claimed_by,
            claim_expires_at=row.claim_expires_at,
            decision=row.decision,
            lock_version=row.lock_version,
        )


class SqlMetricsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def run_telemetry(
        self, *, organization_id: uuid.UUID, limit: int = 200
    ) -> list[RunTelemetryRow]:
        runs = list(
            (
                await self._s.execute(
                    select(m.AgentRun)
                    .where(m.AgentRun.organization_id == organization_id)
                    .order_by(m.AgentRun.created_at.desc())
                    .limit(limit)
                )
            ).scalars()
        )
        if not runs:
            return []
        run_ids = [r.id for r in runs]
        attempts = (
            await self._s.execute(select(m.AgentAttempt).where(m.AgentAttempt.run_id.in_(run_ids)))
        ).scalars()
        terminal_events = (
            await self._s.execute(
                select(m.RunEvent.run_id)
                .where(m.RunEvent.run_id.in_(run_ids), m.RunEvent.event_type == "terminal")
                .distinct()
            )
        ).scalars()

        has_terminal = set(terminal_events)
        by_run: dict[uuid.UUID, dict[str, Any]] = {
            rid: {"cost": 0.0, "latency": 0, "executes": 0, "model": False} for rid in run_ids
        }
        for a in attempts:
            agg = by_run[a.run_id]
            agg["cost"] += a.cost_usd or 0.0
            if a.kind == "execute":
                agg["executes"] += 1
                agg["latency"] += a.duration_ms or 0
            if a.kind in ("plan", "code"):
                agg["model"] = True

        rows: list[RunTelemetryRow] = []
        for run in runs:
            agg = by_run[run.id]
            terminal = RunStatus(run.status) in TERMINAL_RUN_STATES
            reached_model = bool(agg["model"])
            trace_complete = (
                bool(run.config_manifest)
                and (run.id in has_terminal if terminal else True)
                and (agg["model"] if reached_model else True)
            )
            rows.append(
                RunTelemetryRow(
                    run_id=run.id,
                    status=run.status,
                    failure_category=run.failure_category,
                    cost_usd=round(float(agg["cost"]), 6),
                    latency_ms=int(agg["latency"]),
                    attempt_count=int(agg["executes"]),
                    trace_complete=trace_complete,
                )
            )
        return rows

    async def cache_stats(self, *, organization_id: uuid.UUID) -> CacheStats:
        rows = (
            await self._s.execute(
                select(m.AgentAttempt.payload).where(
                    m.AgentAttempt.organization_id == organization_id,
                    m.AgentAttempt.kind == "cache",
                )
            )
        ).scalars()
        counts = {"hit": 0, "miss": 0, "false_hit": 0, "store": 0}
        for payload in rows:
            outcome = str(payload.get("outcome", ""))
            if outcome in counts:
                counts[outcome] += 1
        return CacheStats(
            hits=counts["hit"],
            misses=counts["miss"],
            false_hits=counts["false_hit"],
            stores=counts["store"],
        )


class SqlBudgetRepository:
    """The budget ledger. Entries are append-only; the partial unique index on
    (run_id, kind) makes reserve/settle idempotent under job re-delivery."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_limit(self, organization_id: uuid.UUID) -> float | None:
        row = await self._s.get(m.Budget, organization_id)
        return None if row is None else float(row.monthly_limit_usd)

    async def set_limit(self, *, organization_id: uuid.UUID, monthly_limit_usd: float) -> None:
        row = await self._s.get(m.Budget, organization_id)
        if row is None:
            self._s.add(
                m.Budget(organization_id=organization_id, monthly_limit_usd=monthly_limit_usd)
            )
        else:
            row.monthly_limit_usd = monthly_limit_usd
        await self._s.flush()

    async def month_spend(self, organization_id: uuid.UUID) -> float:
        now = _now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        total = (
            await self._s.execute(
                select(func.coalesce(func.sum(m.BudgetEntry.amount_usd), 0)).where(
                    m.BudgetEntry.organization_id == organization_id,
                    m.BudgetEntry.created_at >= month_start,
                )
            )
        ).scalar_one()
        return round(float(total), 6)

    async def add_entry(
        self,
        *,
        organization_id: uuid.UUID,
        run_id: uuid.UUID | None,
        kind: str,
        amount_usd: float,
        detail: str | None = None,
    ) -> bool:
        if run_id is not None:
            exists = (
                await self._s.execute(
                    select(m.BudgetEntry.id).where(
                        m.BudgetEntry.run_id == run_id, m.BudgetEntry.kind == kind
                    )
                )
            ).scalar_one_or_none()
            if exists is not None:
                return False
        self._s.add(
            m.BudgetEntry(
                id=new_id(),
                organization_id=organization_id,
                run_id=run_id,
                kind=kind,
                amount_usd=amount_usd,
                detail=detail,
            )
        )
        await self._s.flush()
        return True

    async def reserve_amount(self, run_id: uuid.UUID) -> float | None:
        amount = (
            await self._s.execute(
                select(m.BudgetEntry.amount_usd).where(
                    m.BudgetEntry.run_id == run_id, m.BudgetEntry.kind == "reserve"
                )
            )
        ).scalar_one_or_none()
        return None if amount is None else float(amount)


class SqlCacheStore:
    """Exact answer cache rows. Every query filters on organization_id — the
    org inside the cache key is defense in depth, not the only control."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def lookup(
        self, *, organization_id: uuid.UUID, cache_key: str
    ) -> CacheEntryRecord | None:
        row = (
            await self._s.execute(
                select(m.AnswerCacheEntry).where(
                    m.AnswerCacheEntry.organization_id == organization_id,
                    m.AnswerCacheEntry.cache_key == cache_key,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return CacheEntryRecord(
            cache_key=row.cache_key,
            dataset_version_id=row.dataset_version_id,
            dataset_sha256=row.dataset_sha256,
            config_signature=row.config_signature,
            answer=row.answer,
            verification=row.verification,
        )

    async def store(
        self,
        *,
        organization_id: uuid.UUID,
        cache_key: str,
        dataset_version_id: uuid.UUID,
        dataset_sha256: str,
        question_sha256: str,
        config_signature: str,
        answer: dict[str, Any],
        verification: dict[str, Any] | None,
    ) -> None:
        existing = (
            await self._s.execute(
                select(m.AnswerCacheEntry.id).where(
                    m.AnswerCacheEntry.organization_id == organization_id,
                    m.AnswerCacheEntry.cache_key == cache_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return  # first write wins; identical inputs produce identical answers
        self._s.add(
            m.AnswerCacheEntry(
                id=new_id(),
                organization_id=organization_id,
                cache_key=cache_key,
                dataset_version_id=dataset_version_id,
                dataset_sha256=dataset_sha256,
                question_sha256=question_sha256,
                config_signature=config_signature,
                answer=answer,
                verification=verification,
            )
        )
        await self._s.flush()

    async def record_hit(self, *, organization_id: uuid.UUID, cache_key: str) -> None:
        await self._s.execute(
            update(m.AnswerCacheEntry)
            .where(
                m.AnswerCacheEntry.organization_id == organization_id,
                m.AnswerCacheEntry.cache_key == cache_key,
            )
            .values(hit_count=m.AnswerCacheEntry.hit_count + 1, last_hit_at=_now())
        )

    async def invalidate(self, *, organization_id: uuid.UUID, cache_key: str) -> None:
        await self._s.execute(
            delete(m.AnswerCacheEntry).where(
                m.AnswerCacheEntry.organization_id == organization_id,
                m.AnswerCacheEntry.cache_key == cache_key,
            )
        )


class SqlRetentionRepository:
    """Data-minimization + erasure (Phase 10).

    Runs carry evidence in five child tables (RESTRICT FKs, so children go
    first) plus `scores` rows keyed by `target_id`. Deletion happens inside one
    transaction the caller commits, so a partial delete is impossible.
    """

    # FK-safe order: children of agent_runs before the runs themselves.
    _RUN_CHILD_DELETES = (
        "DELETE FROM scores WHERE target_type = 'run' AND target_id = ANY(:ids)",
        "DELETE FROM budget_entries WHERE run_id = ANY(:rids)",
        "DELETE FROM human_reviews WHERE run_id = ANY(:rids)",
        "DELETE FROM agent_attempts WHERE run_id = ANY(:rids)",
        "DELETE FROM agent_checkpoints WHERE run_id = ANY(:rids)",
        "DELETE FROM run_events WHERE run_id = ANY(:rids)",
    )

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def _expired_run_ids(
        self, cutoff: datetime, organization_id: uuid.UUID | None
    ) -> list[uuid.UUID]:
        # Only terminal runs are eligible; an in-flight run is never reaped.
        stmt = select(m.AgentRun.id).where(
            m.AgentRun.created_at < cutoff,
            m.AgentRun.status.in_([s.value for s in TERMINAL_RUN_STATES]),
        )
        if organization_id is not None:
            stmt = stmt.where(m.AgentRun.organization_id == organization_id)
        return list((await self._s.execute(stmt)).scalars())

    async def count_expired_runs(
        self, *, cutoff: datetime, organization_id: uuid.UUID | None = None
    ) -> int:
        return len(await self._expired_run_ids(cutoff, organization_id))

    async def _delete_runs(self, run_ids: list[uuid.UUID]) -> int:
        if not run_ids:
            return 0
        str_ids = [str(r) for r in run_ids]
        await self._s.execute(text(self._RUN_CHILD_DELETES[0]), {"ids": str_ids})
        for stmt in self._RUN_CHILD_DELETES[1:]:
            await self._s.execute(text(stmt), {"rids": run_ids})
        await self._s.execute(
            text("DELETE FROM agent_runs WHERE id = ANY(:rids)"), {"rids": run_ids}
        )
        await self._s.flush()
        return len(run_ids)  # every selected run is deleted

    async def delete_expired_runs(
        self, *, cutoff: datetime, organization_id: uuid.UUID | None = None
    ) -> int:
        run_ids = await self._expired_run_ids(cutoff, organization_id)
        return await self._delete_runs(run_ids)

    async def delete_expired_cache(
        self, *, cutoff: datetime, organization_id: uuid.UUID | None = None
    ) -> int:
        # Static SQL with bound parameters (no string interpolation). The two
        # shapes differ only by an optional tenant filter.
        params: dict[str, Any] = {"cutoff": cutoff}
        if organization_id is not None:
            params["org"] = organization_id
            count_sql = text(
                "SELECT count(*) FROM answer_cache "
                "WHERE created_at < :cutoff AND organization_id = :org"
            )
            delete_sql = text(
                "DELETE FROM answer_cache WHERE created_at < :cutoff AND organization_id = :org"
            )
        else:
            count_sql = text("SELECT count(*) FROM answer_cache WHERE created_at < :cutoff")
            delete_sql = text("DELETE FROM answer_cache WHERE created_at < :cutoff")
        n = int((await self._s.execute(count_sql, params)).scalar_one())
        await self._s.execute(delete_sql, params)
        await self._s.flush()
        return n

    async def describe_organization(self, organization_id: uuid.UUID) -> dict[str, int]:
        """Counts of a tenant's data — the dry-run answer for an erasure request."""
        tables = [
            ("runs", "agent_runs"),
            ("datasets", "datasets"),
            ("dataset_versions", "dataset_versions"),
            ("api_keys", "api_keys"),
            ("memberships", "memberships"),
            ("scores", "scores"),
            ("answer_cache", "answer_cache"),
            ("budget_entries", "budget_entries"),
            ("audit_events", "audit_events"),
        ]
        counts: dict[str, int] = {}
        for label, table in tables:
            # `table` is a SQL identifier, which cannot be a bound parameter, and
            # it comes only from the hardcoded allowlist above — never from user
            # input. The org filter IS bound. Safe by construction.
            # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
            query = text(f"SELECT count(*) FROM {table} WHERE organization_id = :org")
            n = (await self._s.execute(query, {"org": organization_id})).scalar_one()
            counts[label] = int(n)
        return counts

    async def purge_organization(self, organization_id: uuid.UUID) -> dict[str, int]:
        """Right-to-erasure: delete ALL of one tenant's data, then the org.
        Users are global (subject-based) and are left intact; the audit trail
        for this org is included in the erasure."""
        before = await self.describe_organization(organization_id)
        run_ids = list(
            (
                await self._s.execute(
                    select(m.AgentRun.id).where(m.AgentRun.organization_id == organization_id)
                )
            ).scalars()
        )
        await self._delete_runs(run_ids)
        # Remaining tenant-owned rows, FK-safe: versions before datasets.
        for stmt in (
            "DELETE FROM answer_cache WHERE organization_id = :org",
            "DELETE FROM budget_entries WHERE organization_id = :org",
            "DELETE FROM budgets WHERE organization_id = :org",
            "DELETE FROM scores WHERE organization_id = :org",
            "DELETE FROM dataset_versions WHERE organization_id = :org",
            "DELETE FROM datasets WHERE organization_id = :org",
            "DELETE FROM api_keys WHERE organization_id = :org",
            "DELETE FROM memberships WHERE organization_id = :org",
            "DELETE FROM audit_events WHERE organization_id = :org",
            "DELETE FROM organizations WHERE id = :org",
        ):
            await self._s.execute(text(stmt), {"org": organization_id})
        await self._s.flush()
        return before


class SqlAuditSink:
    """Append-only audit log. There is deliberately no update or delete method."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def record(self, entry: AuditEntry) -> None:
        self._s.add(
            m.AuditEvent(
                id=new_id(),
                organization_id=entry.organization_id,
                actor_type=entry.actor_type.value,
                actor_id=entry.actor_id,
                action=entry.action.value,
                result=entry.result.value,
                target_type=entry.target_type,
                target_id=entry.target_id,
                request_id=entry.request_id,
                event_metadata=entry.metadata,
            )
        )
        await self._s.flush()
