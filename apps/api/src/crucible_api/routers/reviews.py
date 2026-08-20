"""Human-review queue: claim (optimistic), apply a versioned rubric, submit."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from crucible.application import (
    ClaimReview,
    ListReviewQueue,
    RubricGrades,
    SubmitReview,
)
from crucible.domain import ReviewDecision
from crucible_api.dependencies import (
    AuditDep,
    PrincipalDep,
    RequestIdDep,
    ReviewRepoDep,
    RunRepoDep,
    ScoreStoreDep,
)
from crucible_api.queue import ArqJobQueue
from crucible_api.schemas import ReviewOut, ReviewQueueItemOut, SubmitReviewIn

router = APIRouter(prefix="/v1/reviews", tags=["reviews"])


@router.get("", response_model=list[ReviewQueueItemOut])
async def queue(
    principal: PrincipalDep, reviews: ReviewRepoDep, limit: int = 50
) -> list[ReviewQueueItemOut]:
    items = await ListReviewQueue(reviews=reviews)(principal, limit=limit)
    return [
        ReviewQueueItemOut(
            run_id=i.run_id,
            question=i.question,
            created_at=i.created_at,
            review_status=i.review_status,
            verification=i.verification,
        )
        for i in items
    ]


@router.post("/{run_id}/claim", response_model=ReviewOut)
async def claim(
    run_id: uuid.UUID,
    principal: PrincipalDep,
    reviews: ReviewRepoDep,
    runs: RunRepoDep,
    audit: AuditDep,
    request_id: RequestIdDep,
) -> ReviewOut:
    record = await ClaimReview(reviews=reviews, runs=runs, audit=audit)(
        principal, run_id, request_id=request_id
    )
    return ReviewOut(
        run_id=record.run_id,
        status=record.status,
        rubric_version=record.rubric_version,
        decision=record.decision,
    )


@router.post("/{run_id}/submit", response_model=ReviewOut)
async def submit(
    run_id: uuid.UUID,
    body: SubmitReviewIn,
    request: Request,
    principal: PrincipalDep,
    reviews: ReviewRepoDep,
    scores: ScoreStoreDep,
    audit: AuditDep,
    request_id: RequestIdDep,
) -> ReviewOut:
    record = await SubmitReview(
        reviews=reviews,
        scores=scores,
        queue=ArqJobQueue(request.app.state.queue_pool),
        audit=audit,
    )(
        principal,
        run_id,
        decision=ReviewDecision(body.decision),
        grades=RubricGrades(
            groundedness=body.grades.groundedness,
            provenance=body.grades.provenance,
            usefulness=body.grades.usefulness,
            uncertainty=body.grades.uncertainty,
        ),
        request_id=request_id,
    )
    return ReviewOut(
        run_id=record.run_id,
        status=record.status,
        rubric_version=record.rubric_version,
        decision=record.decision,
    )
