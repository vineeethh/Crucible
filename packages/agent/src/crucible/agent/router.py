"""Static two-tier model router (master plan Phase 8).

The router is a *declared policy*, not a learned one: which tier serves each
role, when the planner escalates, and whether provider errors fall back are all
written down here, versioned, and recorded in the run manifest — so a routing
change is a config change you can diff, evaluate (see
`crucible.evaluation.efficiency`), and roll back by flipping a setting.

Decisions are pure functions of the call inputs (determinism is tested), and
the gateway holds no per-run mutable state, so one instance is safe to share
across concurrent runs. Escalation evidence travels in `ModelUsage`
(escalated/route_reason, with tokens and cost that INCLUDE the burned primary
call), which the nodes persist per attempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from crucible.agent.ports import ModelGateway, ModelUsage
from crucible.agent.schemas import AnalysisPlan, GeneratedCode
from crucible.agent.state import ColumnView

ROUTER_POLICY_VERSION = "two-tier@1"


@dataclass(frozen=True, slots=True)
class RouterPolicy:
    """The declared escalation/fallback policy.

    - The planner runs on tier 1 and escalates to tier 2 when the cheap plan
      abstains or reports low confidence (the only quality signal a plan has).
    - Coder/repair run on tier 1: generated code is validated by execution and
      verification downstream, so there is no pre-execution signal to escalate
      on — a bad program surfaces as a repairable failure, not a silent loss.
    - Any provider error on the primary falls back to the secondary when
      `fallback_on_error` is set; the failure reason is recorded.
    """

    policy_version: str = ROUTER_POLICY_VERSION
    confidence_threshold: float = 0.8
    escalate_on_abstain: bool = True
    fallback_on_error: bool = True

    def manifest(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "confidence_threshold": self.confidence_threshold,
            "escalate_on_abstain": self.escalate_on_abstain,
            "fallback_on_error": self.fallback_on_error,
        }


def _merge_usage(
    primary: ModelUsage | None, serving: ModelUsage, *, reason: str | None
) -> ModelUsage:
    """Usage attributed to the serving model, with the burned primary call's
    tokens and cost folded in. If either cost is unknown, the sum is unknown —
    never a partial number presented as a total."""
    if primary is None:
        return serving
    if primary.cost_usd is None or serving.cost_usd is None:
        combined_cost = None
    else:
        combined_cost = round(primary.cost_usd + serving.cost_usd, 8)
    return ModelUsage(
        provider=serving.provider,
        model_id=serving.model_id,
        tokens_in=primary.tokens_in + serving.tokens_in,
        tokens_out=primary.tokens_out + serving.tokens_out,
        cost_usd=combined_cost,
        escalated=True,
        route_reason=reason,
    )


class TieredModelGateway:
    """Routes plan/code/repair across a cheap primary and a capable secondary
    gateway according to a `RouterPolicy`. Implements `ModelGateway`."""

    def __init__(
        self, *, primary: ModelGateway, secondary: ModelGateway, policy: RouterPolicy
    ) -> None:
        self._primary = primary
        self._secondary = secondary
        self._policy = policy

    def manifest(self) -> dict[str, dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for role, config in self._secondary.manifest().items():
            merged[role] = {**config, "router_tier": "secondary"}
        for role, config in self._primary.manifest().items():
            merged[role] = {**config, "router_tier": "primary"}
        merged["router"] = self._policy.manifest()
        return merged

    # -------------------------------------------------------------------- plan
    async def plan(
        self, *, question: str, profile: list[ColumnView]
    ) -> tuple[AnalysisPlan, ModelUsage]:
        try:
            plan, usage = await self._primary.plan(question=question, profile=profile)
        except Exception:
            if not self._policy.fallback_on_error:
                raise
            plan, fallback_usage = await self._secondary.plan(question=question, profile=profile)
            return plan, ModelUsage(
                provider=fallback_usage.provider,
                model_id=fallback_usage.model_id,
                tokens_in=fallback_usage.tokens_in,
                tokens_out=fallback_usage.tokens_out,
                cost_usd=fallback_usage.cost_usd,
                escalated=True,
                route_reason="primary_error",
            )

        reason: str | None = None
        if plan.is_abstain and self._policy.escalate_on_abstain:
            reason = "primary_abstain"
        elif not plan.is_abstain and plan.confidence < self._policy.confidence_threshold:
            reason = "low_confidence"
        if reason is None:
            return plan, usage

        escalated_plan, secondary_usage = await self._secondary.plan(
            question=question, profile=profile
        )
        return escalated_plan, _merge_usage(usage, secondary_usage, reason=reason)

    # -------------------------------------------------------------------- code
    async def code(
        self, *, plan: AnalysisPlan, profile: list[ColumnView]
    ) -> tuple[GeneratedCode, ModelUsage]:
        try:
            return await self._primary.code(plan=plan, profile=profile)
        except Exception:
            if not self._policy.fallback_on_error:
                raise
            code, usage = await self._secondary.code(plan=plan, profile=profile)
            return code, ModelUsage(
                provider=usage.provider,
                model_id=usage.model_id,
                tokens_in=usage.tokens_in,
                tokens_out=usage.tokens_out,
                cost_usd=usage.cost_usd,
                escalated=True,
                route_reason="primary_error",
            )

    # ------------------------------------------------------------------ repair
    async def repair(
        self,
        *,
        plan: AnalysisPlan,
        profile: list[ColumnView],
        prior_code: str,
        error: str,
    ) -> tuple[GeneratedCode, ModelUsage]:
        try:
            return await self._primary.repair(
                plan=plan, profile=profile, prior_code=prior_code, error=error
            )
        except Exception:
            if not self._policy.fallback_on_error:
                raise
            code, usage = await self._secondary.repair(
                plan=plan, profile=profile, prior_code=prior_code, error=error
            )
            return code, ModelUsage(
                provider=usage.provider,
                model_id=usage.model_id,
                tokens_in=usage.tokens_in,
                tokens_out=usage.tokens_out,
                cost_usd=usage.cost_usd,
                escalated=True,
                route_reason="primary_error",
            )
