"""Budget management (Phase 8).

Setting the monthly limit is an owner-level operation (ORG_MANAGE) and is
audited: a budget change alters what the platform will refuse to run, so it is
evidence, not preference. Reading the position needs only run visibility.
"""

from __future__ import annotations

from crucible.application.ports import (
    AuditEntry,
    AuditSink,
    BudgetRepository,
    BudgetStatus,
)
from crucible.domain import (
    AuditAction,
    AuditResult,
    Permission,
    PermissionDenied,
    Principal,
    ValidationFailed,
)


def _require(principal: Principal, permission: Permission) -> None:
    if not principal.can(permission):
        raise PermissionDenied()


class SetBudget:
    def __init__(self, *, budgets: BudgetRepository, audit: AuditSink) -> None:
        self._budgets = budgets
        self._audit = audit

    async def __call__(
        self, principal: Principal, *, monthly_limit_usd: float, request_id: str = ""
    ) -> BudgetStatus:
        _require(principal, Permission.ORG_MANAGE)
        if monthly_limit_usd < 0:
            raise ValidationFailed("monthly_limit_usd must be >= 0")
        org = principal.organization_id
        await self._budgets.set_limit(organization_id=org, monthly_limit_usd=monthly_limit_usd)
        await self._audit.record(
            AuditEntry(
                organization_id=org,
                actor_type=principal.actor_type,
                actor_id=principal.actor_id,
                action=AuditAction.BUDGET_SET,
                result=AuditResult.ALLOWED,
                target_type="organization",
                target_id=str(org),
                request_id=request_id,
                metadata={"monthly_limit_usd": monthly_limit_usd},
            )
        )
        spend = await self._budgets.month_spend(org)
        return BudgetStatus(monthly_limit_usd=monthly_limit_usd, month_spend_usd=spend)


class GetBudgetStatus:
    def __init__(self, *, budgets: BudgetRepository) -> None:
        self._budgets = budgets

    async def __call__(self, principal: Principal) -> BudgetStatus:
        _require(principal, Permission.RUN_READ)
        org = principal.organization_id
        limit = await self._budgets.get_limit(org)
        spend = await self._budgets.month_spend(org)
        return BudgetStatus(monthly_limit_usd=limit, month_spend_usd=spend)
