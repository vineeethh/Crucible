"""Human review use cases (master plan §11, §8.2 HumanReview).

A reviewer claims a run from the queue (optimistic, one reviewer per run),
applies a versioned rubric, and submits a decision. Submitting records the
rubric scores as typed human observations and resumes the agent graph
(approve → synthesize, reject → abstain) via the Phase 4 review-resolution job.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from crucible.application.ports import (
    AuditEntry,
    AuditSink,
    JobQueue,
    ReviewQueueItem,
    ReviewRecord,
    ReviewRepository,
    RunRepository,
    ScoreInput,
    ScoreStore,
)
from crucible.domain import (
    AuditAction,
    AuditResult,
    Conflict,
    NotFound,
    Permission,
    PermissionDenied,
    Principal,
    ReviewDecision,
    RunStatus,
    ScoreSource,
    ScoreType,
)

REVIEW_RUBRIC_VERSION = "review-rubric@1"
CLAIM_TTL_SECONDS = 900  # a claim the reviewer must submit within, else it lapses
_RUBRIC_DIMENSIONS = ("groundedness", "provenance", "usefulness", "uncertainty")


def _require(principal: Principal, permission: Permission) -> None:
    if not principal.can(permission):
        raise PermissionDenied()


@dataclass(frozen=True, slots=True)
class RubricGrades:
    groundedness: int
    provenance: int
    usefulness: int
    uncertainty: int

    def as_map(self) -> dict[str, int]:
        return {d: int(getattr(self, d)) for d in _RUBRIC_DIMENSIONS}


class ListReviewQueue:
    def __init__(self, *, reviews: ReviewRepository) -> None:
        self._reviews = reviews

    async def __call__(self, principal: Principal, *, limit: int = 50) -> list[ReviewQueueItem]:
        _require(principal, Permission.REVIEW_SUBMIT)
        return await self._reviews.list_queue(
            organization_id=principal.organization_id, limit=max(1, min(limit, 200))
        )


class ClaimReview:
    def __init__(self, *, reviews: ReviewRepository, runs: RunRepository, audit: AuditSink) -> None:
        self._reviews = reviews
        self._runs = runs
        self._audit = audit

    async def __call__(
        self, principal: Principal, run_id: uuid.UUID, *, request_id: str = ""
    ) -> ReviewRecord:
        _require(principal, Permission.REVIEW_SUBMIT)
        run = await self._runs.get_run(organization_id=principal.organization_id, run_id=run_id)
        if run is None:
            raise NotFound("Run")
        if run.status is not RunStatus.WAITING_REVIEW:
            raise Conflict(
                f"Run is '{run.status.value}', not awaiting review.", code="run-not-in-review"
            )
        review = await self._reviews.claim(
            organization_id=principal.organization_id,
            run_id=run_id,
            reviewer=principal.actor_id,
            rubric_version=REVIEW_RUBRIC_VERSION,
            ttl_seconds=CLAIM_TTL_SECONDS,
        )
        if review is None:
            raise Conflict(
                "This run is already claimed by another reviewer.", code="review-claimed"
            )
        return review


class SubmitReview:
    def __init__(
        self,
        *,
        reviews: ReviewRepository,
        scores: ScoreStore,
        queue: JobQueue,
        audit: AuditSink,
    ) -> None:
        self._reviews = reviews
        self._scores = scores
        self._queue = queue
        self._audit = audit

    async def __call__(
        self,
        principal: Principal,
        run_id: uuid.UUID,
        *,
        decision: ReviewDecision,
        grades: RubricGrades,
        request_id: str = "",
    ) -> ReviewRecord:
        _require(principal, Permission.REVIEW_SUBMIT)
        review = await self._reviews.submit(
            organization_id=principal.organization_id,
            run_id=run_id,
            reviewer=principal.actor_id,
            decision=decision.value,
        )
        if review is None:
            raise Conflict("No review is claimed by you for this run.", code="review-not-claimed")

        # Record the rubric grades as typed human observations (never a gate).
        for dimension, grade in grades.as_map().items():
            await self._scores.add_score(
                organization_id=principal.organization_id,
                score=ScoreInput(
                    definition_key=f"rubric.{dimension}",
                    score_type=ScoreType.CATEGORICAL.value,
                    source=ScoreSource.HUMAN.value,
                    target_type="run",
                    target_id=str(run_id),
                    evaluator_version=REVIEW_RUBRIC_VERSION,
                    value_num=float(grade),
                    value_categorical=str(grade),
                    created_by=principal.user_id,
                ),
            )

        # Resume the agent graph asynchronously (Phase 4 review resolution).
        await self._queue.enqueue(
            "resolve_run_review", str(run_id), decision is ReviewDecision.APPROVE
        )
        await self._audit.record(
            AuditEntry(
                organization_id=principal.organization_id,
                actor_type=principal.actor_type,
                actor_id=principal.actor_id,
                action=AuditAction.RUN_REVIEW_SUBMITTED,
                result=AuditResult.ALLOWED,
                target_type="run",
                target_id=str(run_id),
                request_id=request_id,
                metadata={"decision": decision.value, "rubric": REVIEW_RUBRIC_VERSION},
            )
        )
        return review
