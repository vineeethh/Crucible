"""Model registry pricing and the two-tier router's declared policy."""

import asyncio

import pytest

from crucible.agent import (
    AnalysisPlan,
    FakeLiteModel,
    FakeModel,
    ModelUsage,
    RouterPolicy,
    TieredModelGateway,
)
from crucible.agent.models import registry
from crucible.agent.schemas import AnswerKind, GeneratedCode, Operation
from crucible.agent.state import ColumnView

PROFILE = [ColumnView(name="region", dtype="str"), ColumnView(name="amount", dtype="float64")]


# ------------------------------------------------------------------- registry


def test_cost_is_declared_price_times_tokens() -> None:
    cost = registry.compute_cost(registry.FAKE_TEMPLATE_ID, tokens_in=1000, tokens_out=100)
    assert cost == pytest.approx((1000 * 0.50 + 100 * 2.00) / 1_000_000)


def test_unknown_model_cost_is_none_not_zero() -> None:
    assert registry.compute_cost("mystery-model", tokens_in=1000, tokens_out=1000) is None


def test_tier1_is_cheaper_than_tier2_for_the_same_tokens() -> None:
    lite = registry.compute_cost(registry.FAKE_LITE_ID, tokens_in=500, tokens_out=500)
    full = registry.compute_cost(registry.FAKE_TEMPLATE_ID, tokens_in=500, tokens_out=500)
    assert lite is not None and full is not None and lite < full


def test_fake_models_declare_synthetic_prices() -> None:
    spec = registry.get(registry.FAKE_LITE_ID)
    assert spec is not None and spec.synthetic_price and spec.tier == 1


# ------------------------------------------------------------------ fake lite


def test_lite_plans_simple_aggregates_itself() -> None:
    async def scenario() -> None:
        plan, usage = await FakeLiteModel().plan(
            question="What is the total amount?", profile=PROFILE
        )
        assert plan.operation is Operation.SUM
        assert usage.model_id == registry.FAKE_LITE_ID
        assert usage.cost_usd is not None and usage.cost_usd > 0

    asyncio.run(scenario())


def test_lite_abstains_beyond_its_scope() -> None:
    async def scenario() -> None:
        plan, _ = await FakeLiteModel().plan(
            question="Which region had the highest amount?", profile=PROFILE
        )
        assert plan.is_abstain
        assert "beyond tier-1 scope" in plan.rationale

    asyncio.run(scenario())


# --------------------------------------------------------------------- router


def _tiered(policy: RouterPolicy | None = None) -> TieredModelGateway:
    return TieredModelGateway(
        primary=FakeLiteModel(), secondary=FakeModel(), policy=policy or RouterPolicy()
    )


def test_easy_question_served_by_tier1_without_escalation() -> None:
    async def scenario() -> None:
        plan, usage = await _tiered().plan(question="What is the total amount?", profile=PROFILE)
        assert plan.operation is Operation.SUM
        assert usage.model_id == registry.FAKE_LITE_ID
        assert not usage.escalated

    asyncio.run(scenario())


def test_hard_question_escalates_to_tier2_and_charges_both_calls() -> None:
    async def scenario() -> None:
        gateway = _tiered()
        plan, usage = await gateway.plan(
            question="Which region had the highest amount?", profile=PROFILE
        )
        # Tier 2 rescued the plan; the burned tier-1 call is included in the bill.
        assert plan.operation is Operation.MAX_BY_GROUP
        assert usage.model_id == registry.FAKE_TEMPLATE_ID
        assert usage.escalated and usage.route_reason == "primary_abstain"

        _, lite_usage = await FakeLiteModel().plan(
            question="Which region had the highest amount?", profile=PROFILE
        )
        assert usage.cost_usd is not None and lite_usage.cost_usd is not None
        assert usage.cost_usd > lite_usage.cost_usd
        assert usage.tokens_in > lite_usage.tokens_in

    asyncio.run(scenario())


def test_low_confidence_plan_escalates() -> None:
    async def scenario() -> None:
        class Hesitant(FakeModel):
            MODEL_ID = registry.FAKE_LITE_ID

            def _plan_from_question(self, question: str, profile: list[ColumnView]) -> AnalysisPlan:
                plan = super()._plan_from_question(question, profile)
                return plan.model_copy(update={"confidence": 0.3})

        gateway = TieredModelGateway(
            primary=Hesitant(), secondary=FakeModel(), policy=RouterPolicy()
        )
        _, usage = await gateway.plan(question="What is the total amount?", profile=PROFILE)
        assert usage.escalated and usage.route_reason == "low_confidence"

    asyncio.run(scenario())


def test_router_decisions_are_deterministic() -> None:
    async def scenario() -> None:
        gateway = _tiered()
        first = await gateway.plan(question="Which region had the highest amount?", profile=PROFILE)
        second = await gateway.plan(
            question="Which region had the highest amount?", profile=PROFILE
        )
        assert first[0] == second[0]
        assert first[1] == second[1]  # identical usage, cost, and route reason

    asyncio.run(scenario())


def test_primary_error_falls_back_to_secondary() -> None:
    async def scenario() -> None:
        class Exploding(FakeModel):
            async def plan(self, *, question, profile):  # type: ignore[no-untyped-def]
                raise RuntimeError("provider 500")

        gateway = TieredModelGateway(
            primary=Exploding(), secondary=FakeModel(), policy=RouterPolicy()
        )
        plan, usage = await gateway.plan(question="What is the total amount?", profile=PROFILE)
        assert plan.operation is Operation.SUM
        assert usage.escalated and usage.route_reason == "primary_error"

    asyncio.run(scenario())


def test_fallback_disabled_raises() -> None:
    async def scenario() -> None:
        class Exploding(FakeModel):
            async def plan(self, *, question, profile):  # type: ignore[no-untyped-def]
                raise RuntimeError("provider 500")

        gateway = TieredModelGateway(
            primary=Exploding(), secondary=FakeModel(), policy=RouterPolicy(fallback_on_error=False)
        )
        with pytest.raises(RuntimeError):
            await gateway.plan(question="What is the total amount?", profile=PROFILE)

    asyncio.run(scenario())


def test_code_runs_on_tier1_without_quality_escalation() -> None:
    async def scenario() -> None:
        gateway = _tiered()
        plan = AnalysisPlan(
            operation=Operation.SUM,
            answer_kind=AnswerKind.NUMERIC_SCALAR,
            target_column="amount",
            referenced_columns=["amount"],
        )
        code, usage = await gateway.code(plan=plan, profile=PROFILE)
        assert isinstance(code, GeneratedCode)
        assert usage.model_id == registry.FAKE_LITE_ID
        assert not usage.escalated

    asyncio.run(scenario())


def test_manifest_records_policy_and_tiers() -> None:
    manifest = _tiered().manifest()
    assert manifest["router"]["policy_version"] == "two-tier@1"
    assert manifest["planner"]["router_tier"] == "primary"
    assert manifest["planner"]["model_id"] == registry.FAKE_LITE_ID


def test_usage_merge_with_unknown_cost_stays_unknown() -> None:
    from crucible.agent.router import _merge_usage

    primary = ModelUsage(provider="x", model_id="a", tokens_in=10, tokens_out=5, cost_usd=None)
    serving = ModelUsage(provider="x", model_id="b", tokens_in=20, tokens_out=9, cost_usd=0.5)
    merged = _merge_usage(primary, serving, reason="low_confidence")
    assert merged.cost_usd is None  # never a partial sum presented as a total
    assert merged.tokens_in == 30 and merged.tokens_out == 14
