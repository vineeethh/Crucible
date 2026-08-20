"""Organization budget: read the monthly position, set the limit (owner-only).

Admission enforcement lives in CreateRun (a run is refused *before* spending);
this router is the visibility and control surface.
"""

from __future__ import annotations

from fastapi import APIRouter

from crucible.application import GetBudgetStatus, SetBudget
from crucible_api.dependencies import (
    AuditDep,
    BudgetRepoDep,
    PrincipalDep,
    RequestIdDep,
)
from crucible_api.schemas import BudgetOut, SetBudgetIn

router = APIRouter(prefix="/v1/budget", tags=["budget"])


@router.get("", response_model=BudgetOut)
async def budget_status(principal: PrincipalDep, budgets: BudgetRepoDep) -> BudgetOut:
    status = await GetBudgetStatus(budgets=budgets)(principal)
    return BudgetOut(
        monthly_limit_usd=status.monthly_limit_usd,
        month_spend_usd=status.month_spend_usd,
        remaining_usd=status.remaining_usd,
    )


@router.put("", response_model=BudgetOut)
async def set_budget(
    body: SetBudgetIn,
    principal: PrincipalDep,
    budgets: BudgetRepoDep,
    audit: AuditDep,
    request_id: RequestIdDep,
) -> BudgetOut:
    status = await SetBudget(budgets=budgets, audit=audit)(
        principal, monthly_limit_usd=body.monthly_limit_usd, request_id=request_id
    )
    return BudgetOut(
        monthly_limit_usd=status.monthly_limit_usd,
        month_spend_usd=status.month_spend_usd,
        remaining_usd=status.remaining_usd,
    )
